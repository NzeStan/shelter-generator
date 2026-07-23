

def _resolve_css_vars(html):
    """Inline CSS custom properties - xhtml2pdf does not support var() syntax."""
    subs = {
        'var(--navy)':       '#0A2342',
        'var(--navy-mid)':   '#1B4B82',
        'var(--navy-light)': '#2C5F8A',
        'var(--gold)':       '#C8951A',
        'var(--gold-light)': '#F0C040',
        'var(--bg-row)':     '#EBF2FA',
        'var(--bg-hdr)':     '#D0E4F5',
        'var(--border)':     '#94AFC8',
        'var(--text)':       '#1A1A2E',
        'var(--muted)':      '#4A5568',
        'var(--white)':      '#FFFFFF',
        'var(--pass-bg)':    '#D4EDDA',
        'var(--pass-fg)':    '#155724',
        'var(--fail-bg)':    '#F8D7DA',
        'var(--fail-fg)':    '#721C24',
    }
    for var, val in subs.items():
        html = html.replace(var, val)
    return html


def _try_system_browser(html_path, pdf_path):
    """Use Chrome or Edge already installed on this machine - no extra downloads needed."""
    import subprocess, os
    candidates = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        os.path.expandvars(r'%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe'),
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ]
    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.run([
                    exe, '--headless', '--disable-gpu', '--no-sandbox',
                    '--disable-software-rasterizer',
                    f'--print-to-pdf={pdf_path}',
                    '--no-pdf-header-footer',
                    f'file:///{html_path.resolve().as_posix()}',
                ], capture_output=True, timeout=30)
                if pdf_path.exists():
                    label = 'Chrome' if 'chrome' in exe.lower() else 'Edge'
                    print(f"  PDF   ->  {pdf_path}  [via system {label}]")
                    return True
            except Exception:
                continue
    return False



"""
A-Frame Scaffold Report Generator
Usage:  python generate_report.py
Output: output/<DOC_NO>_Report.html and .pdf when a PDF engine is available
"""
import argparse
import os
import re
import sys
import base64
import subprocess
from pathlib import Path
from datetime import datetime

ROOT     = Path(__file__).parent
INPUTS   = ROOT / 'inputs'
LOGO_DIR = ROOT / 'logo'
IMG_DIR  = ROOT / 'images'
TMPL_DIR = ROOT / 'templates'
OUT_DIR  = ROOT / 'output'
PROJECT_ROOT = ROOT.parent
RENDERER_DIR = PROJECT_ROOT / '3D Renderer'
DRAWING_DIR  = PROJECT_ROOT / '2D_3D_GENERATOR'

sys.path.insert(0, str(ROOT))
from parsers.staad_parser import StaadParser
from parsers.wind_calc    import WindCalculator

# -- Project info --------------------------------------------------------------

DEFAULTS = {
    'DOCUMENT_NO':       'PMS-WA-ARCO-XXX',
    'SCAFFOLD_DRAWING_NO': '',
    'REVISION':          '0',
    'LOCATION':          'TRAIN X',
    'AREA':              'X',
    'SCAFFOLD_TYPE':     'A Frame',
    'RISK_LEVEL':        'Medium',       # High / Medium / Low
    'PERMIT_NO':         '',
    'ERMT_NO':           '',
    # Optional cover-page callouts — shown once under Brief Description (after the tie
    # display if the project has ties). Leave blank to omit entirely.
    'NOTE':              '',
    'WARNING':           '',
    'DESIGNED_BY_ID':    '',
    'DESIGNED_BY_NAME':  '',
    'VERIFIED_BY_ID':    '',
    'VERIFIED_BY_NAME':  '',
    'CHECKED_BY_ID':     '',
    'CHECKED_BY_NAME':   '',
    'REVIEWED_BY_ID':    '',
    'REVIEWED_BY_NAME':  '',
    'APPROVED_BY_ID':    '',
    'APPROVED_BY_NAME':  '',
    'EQUIPMENT_TAG':     '',
    'WORK_ORDER':        '',
    'PURPOSE':           'maintenance activities',
    'STRUCTURE_ABOVE_GROUND_M': '',
    'WIND_CALC_HEIGHT_M': '',
    'DOC_LIFE':          '3 Years',
    'PREPARED_BY_NAME':  '',   # falls back to DESIGNED_BY_NAME if blank
    'AUTO_RENDER_3D_MODEL': 'yes',
    'AUTO_ENGINEERING_DRAWINGS': 'yes',
    'ENGINEERING_DRAWING_FORMAT': 'standard',
    # Show the large 3D Isometric View as the last page of the PDF (default: yes)
    'SHOW_3D_ISOMETRIC_PAGE': 'yes',
    # Page 2 — Reaction on Parent Structure (Ties), only relevant if the A-frame is tied.
    'SHOW_TIE_REACTIONS': 'no',
    'TIE_DISPLAY': 'sum',
    'TIE_FORCE_FX': '',
    'TIE_FORCE_FZ': '',
}

REPORT_OUTLINE = [
    ("general-note", "General Note, Material Properties & Modelling Philosophy"),
    ("load-cases", "Load Cases"),
    ("wind-calc", "Wind Load Calculation"),
    ("load-combs", "Load Combinations"),
    ("uc-summary", "Utilization Ratio Summary"),
    ("connection-check", "Connection Stability Check"),
    ("deflection-check", "Deflection Check Results"),
    ("conclusion", "Conclusion, Recommendations & Installation Notes"),
]

def parse_project_info(path):
    info = dict(DEFAULTS)
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if ':' in line and not line.startswith('#'):
                    k, _, v = line.partition(':')
                    info[k.strip()] = v.strip()
    except FileNotFoundError:
        print(f"  [WARN] {path} not found - using defaults")

    if not info['SCAFFOLD_DRAWING_NO']:
        info['SCAFFOLD_DRAWING_NO'] = info['DOCUMENT_NO']
    if not info['PREPARED_BY_NAME']:
        info['PREPARED_BY_NAME'] = info['DESIGNED_BY_NAME']
    return info


def _optional_float(value):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_number(value):
    if value is None:
        return ''
    return f"{float(value):g}"


def _cover_callout_font_pt(*texts):
    """Font size (pt) for the cover-page NOTE/WARNING callouts, scaled down by combined
    text length. Computed server-side (not via browser JS) since the cover page's fixed
    height must never push content onto page 2 regardless of which PDF engine renders it —
    a print-time reflow can wrap text differently than an on-screen measurement would."""
    total_chars = sum(len(t or '') for t in texts)
    if total_chars <= 150:
        return 8.5
    if total_chars <= 300:
        return 7.5
    if total_chars <= 500:
        return 6.8
    if total_chars <= 800:
        return 6.2
    return 6.0


# -- Logo / image loading ------------------------------------------------------

def load_logo(name):
    """Return {'src': '...'} - URL takes priority over PNG."""
    url_file = LOGO_DIR / 'logo_url.txt'
    if url_file.exists():
        for line in url_file.read_text().splitlines():
            if line.strip().upper().startswith(f'{name.upper()}_URL:'):
                url = line.split(':', 1)[1].strip()
                if url:
                    return {'src': url}

    for ext in ('.png', '.jpg', '.jpeg'):
        png = LOGO_DIR / f'{name.lower()}_logo{ext}'
        if png.exists():
            b64  = base64.b64encode(png.read_bytes()).decode()
            mime = 'image/jpeg' if ext != '.png' else 'image/png'
            return {'src': f'data:{mime};base64,{b64}'}
    return None


def load_image(name):
    """Return base64 data URI or None (triggers placeholder in template)."""
    for ext in ('.png', '.jpg', '.jpeg'):
        p = IMG_DIR / f'{name}{ext}'
        if p.exists():
            b64  = base64.b64encode(p.read_bytes()).decode()
            mime = 'image/jpeg' if ext != '.png' else 'image/png'
            return f'data:{mime};base64,{b64}'
    return None


def find_image_file(name):
    for ext in ('.png', '.jpg', '.jpeg'):
        p = IMG_DIR / f'{name}{ext}'
        if p.exists():
            return p
    return None


def parse_args():
    ap = argparse.ArgumentParser(description="Generate the A-frame scaffold report.")
    ap.add_argument(
        "--drawing-format",
        choices=("standard", "grid", "none"),
        help="Engineering drawing format to generate and append. Overrides project_info.txt.",
    )
    ap.add_argument(
        "--skip-3d-render",
        action="store_true",
        help="Use the existing images/3d_model image instead of calling the 3D renderer.",
    )
    ap.add_argument(
        "--skip-engineering-drawings",
        action="store_true",
        help="Do not generate or append the four engineering drawing PDFs.",
    )
    return ap.parse_args()


def _bool_setting(value, default=True):
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "yes", "y", "true", "on"}


def _indefinite_article(text):
    clean = str(text or "").strip()
    return "an" if clean[:1].lower() in {"a", "e", "i", "o", "u"} else "a"


def _brief_description(project, structural, structure_above_ground):
    purpose = str(project.get("PURPOSE") or "the intended work activity").strip()
    scaffold_type = str(project.get("SCAFFOLD_TYPE") or "A Frame").strip()
    article = _indefinite_article(scaffold_type)
    location_text = str(project.get("LOCATION") or "").strip()

    equipment_bits = []
    if str(project.get("EQUIPMENT_NAME") or "").strip():
        equipment_bits.append(str(project["EQUIPMENT_NAME"]).strip())
    if str(project.get("EQUIPMENT_TAG") or "").strip():
        equipment_bits.append(f"equipment tag {str(project['EQUIPMENT_TAG']).strip()}")
    equipment_text = ""
    if equipment_bits:
        equipment_text = " of the " + ", ".join(equipment_bits)

    work_order = str(project.get("WORK_ORDER") or "").strip()
    work_order_text = f" under work order {work_order}" if work_order else ""
    location_sentence = f" at {location_text}" if location_text else ""
    height_sentence = f" The structure is {structure_above_ground}m above ground level." if structure_above_ground else ""

    has_ties = bool(structural.get('supports', {}).get('tie_nodes'))

    components = ["standards", "ledgers", "transoms", "bracing", "ladder beam"]
    if has_ties:
        components.append("support/tie arrangements")
    component_text = ", ".join(components[:-1]) + ", and " + components[-1]

    return (
        f"This document describes the structural design of {article} {scaffold_type} scaffold required for "
        f"{purpose}{equipment_text}{work_order_text}{location_sentence}. "
        f"The scaffold envelope is {structural['dimension_display']} (length x width x height) and "
        f"is configured with {component_text} as indicated on the approved drawing.{height_sentence}"
    )


def _connection_class(max_axial):
    axial = abs(float(max_axial or 0.0))
    if axial <= 10.0:
        return {"class": "Class A", "capacity": 10.0, "status": "PASS", "message": "Class A right-angle couplers are adequate."}
    if axial <= 15.0:
        return {"class": "Class B", "capacity": 15.0, "status": "PASS", "message": "Class B right-angle couplers are required."}
    return {"class": "Review required", "capacity": 15.0, "status": "FAIL", "message": "Applied axial load exceeds the Class B slipping resistance in Table C.1."}


def _normalise_drawing_format(value):
    raw = (value or "standard").strip().lower().replace("_", "-")
    aliases = {
        "generate-scaffold-dxf": "standard",
        "generate-scaffold-grid-dxf": "grid",
        "normal": "standard",
        "plain": "standard",
        "off": "none",
        "no": "none",
    }
    return aliases.get(raw, raw if raw in {"standard", "grid", "none"} else "standard")


def _venv_python(project_dir):
    win_py = project_dir / ".venv" / "Scripts" / "python.exe"
    nix_py = project_dir / ".venv" / "bin" / "python"
    if win_py.exists():
        return win_py
    if nix_py.exists():
        return nix_py
    return Path(sys.executable)


def _console_safe(text):
    encoding = sys.stdout.encoding or "utf-8"
    return str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")


def _print_tail(label, text, max_lines=8):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return
    print(f"  {_console_safe(label)}:")
    for line in lines[-max_lines:]:
        print(f"    {_console_safe(line)}")


def _run_command(label, command, cwd, timeout=300):
    try:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        print(f"  [WARN] {label} failed to start: {exc}")
        return False

    if result.returncode != 0:
        print(f"  [WARN] {label} failed with exit code {result.returncode}")
        _print_tail("stdout", result.stdout)
        _print_tail("stderr", result.stderr)
        return False

    _print_tail(label, result.stdout, max_lines=4)
    return True


def auto_render_3d_model(std_path):
    renderer = RENDERER_DIR / "scaffold_renderer.py"
    if not renderer.exists():
        print(f"  [WARN] 3D renderer not found: {renderer}")
        return None

    output_path = IMG_DIR / "3d_model.png"
    command = [
        _venv_python(RENDERER_DIR),
        renderer,
        std_path.resolve(),
        "--output",
        output_path.resolve(),
        "--no-jpg",
    ]

    # A-Frame scaffolds have no working platforms, so the renderer is never given a
    # --platforms file here (unlike scafold_generator) — this also avoids picking up a
    # stale platforms.txt left behind in the shared 3D Renderer dir by a scaffold job.
    print("  3D Render : generating images/3d_model.png from STAAD command")
    if _run_command("3D renderer", command, RENDERER_DIR, timeout=420) and output_path.exists():
        return output_path
    return None


def _read_key_value_file(path):
    values = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            values[key.strip().lower()] = value.strip()
    except FileNotFoundError:
        pass
    return values


def _safe_filename(text):
    safe = re.sub(r'[<>:"/\\|?*]+', "-", str(text or "").strip())
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    return safe or "scaffold"


def _latest_pdf_for_suffix(outdir, suffix):
    matches = [p for p in outdir.glob(f"*-{suffix}.pdf") if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def collect_engineering_drawings():
    values = _read_key_value_file(DRAWING_DIR / "title_block_values.txt")
    drawing_no = values.get("drawing_number", "scaffold")
    out_folder = Path(values.get("pdf_output_dir", "pdf_output"))
    outdir = out_folder if out_folder.is_absolute() else DRAWING_DIR / out_folder
    drawing_base = _safe_filename(drawing_no)

    items = [
        {"anchor": "drawing-front-view", "title": "Engineering Drawing - Front View", "suffix": "FRONT-VIEW"},
        {"anchor": "drawing-side-view",  "title": "Engineering Drawing - Side View",  "suffix": "SIDE-VIEW"},
        {"anchor": "drawing-plan-view",  "title": "Engineering Drawing - Plan View",  "suffix": "PLAN-VIEW"},
        {"anchor": "drawing-3d-view",    "title": "Engineering Drawing - 3D View",    "suffix": "3D-VIEW"},
    ]

    found = []
    for item in items:
        expected = outdir / f"{drawing_base}-{item['suffix']}.pdf"
        path = expected if expected.exists() else _latest_pdf_for_suffix(outdir, item["suffix"])
        if path and path.exists():
            entry = dict(item)
            entry["path"] = path
            entry["pdf_name"] = path.name
            found.append(entry)
        else:
            print(f"  [WARN] Missing engineering drawing PDF: {expected}")
    return found


def _update_title_block_values(project):
    tbv_path = DRAWING_DIR / "title_block_values.txt"
    try:
        lines = tbv_path.read_text(encoding='utf-8').splitlines() if tbv_path.exists() else []
        overrides = {
            'drawing_number': (project.get('DOCUMENT_NO') or '').strip(),
            'drawing_title':  (project.get('DOCUMENT_NO') or '').strip(),
            'reviewed_by':    (project.get('REVIEWED_BY_NAME') or '').strip(),
            'approved_by':    (project.get('APPROVED_BY_NAME') or '').strip(),
        }
        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#') or '=' not in stripped:
                new_lines.append(line)
                continue
            key = stripped.partition('=')[0].strip()
            if key in overrides:
                new_lines.append(f"{key} = {overrides[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        for key, val in overrides.items():
            if key not in updated_keys:
                new_lines.append(f"{key} = {val}")
        tbv_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    except Exception as exc:
        print(f"  [WARN] Could not update title_block_values.txt: {exc}")


def generate_engineering_drawings(std_path, drawing_format):
    scripts = {
        "standard": "generate_scaffold_dxf.py",
        "grid": "generate_scaffold_grid_dxf.py",
    }
    script_name = scripts.get(drawing_format)
    if not script_name:
        return []

    script = DRAWING_DIR / script_name
    if not script.exists():
        print(f"  [WARN] Drawing generator not found: {script}")
        return []

    print(f"  Drawings  : generating {drawing_format} PDFs from STAAD command")
    command = [_venv_python(DRAWING_DIR), script, std_path.resolve()]
    if not _run_command("drawing generator", command, DRAWING_DIR, timeout=240):
        return []
    drawings = collect_engineering_drawings()
    print(f"  Drawings  : {len(drawings)}/4 PDFs ready")
    return drawings


def _load_pdf_tools():
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import ArrayObject, NameObject, FloatObject, NullObject
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter
        from PyPDF2.generic import ArrayObject, NameObject, FloatObject, NullObject
    return PdfReader, PdfWriter, ArrayObject, NameObject, FloatObject, NullObject


def _pdf_anchor_name(target):
    if target is None:
        return None
    return str(target).lstrip("/")


def _pdf_dest_value(value, FloatObject, NullObject):
    return NullObject() if value is None else FloatObject(float(value))


def _pdf_destination(writer, page_num, ArrayObject, NameObject, FloatObject, NullObject, source=None):
    page_ref = writer._pages.get_object()["/Kids"][page_num]
    dest_type = str(getattr(source, "typ", "/Fit") or "/Fit")
    if dest_type == "/XYZ":
        return ArrayObject([
            page_ref,
            NameObject("/XYZ"),
            _pdf_dest_value(getattr(source, "left", None), FloatObject, NullObject),
            _pdf_dest_value(getattr(source, "top", None), FloatObject, NullObject),
            _pdf_dest_value(getattr(source, "zoom", None), FloatObject, NullObject),
        ])
    return ArrayObject([page_ref, NameObject(dest_type)])


def _direct_pdf_link_targets(writer, destinations, ArrayObject, NameObject):
    fixed = 0

    for page in writer.pages:
        for annot_ref in page.get("/Annots", []):
            annot = annot_ref.get_object()
            action = annot.get("/A")

            if action and str(action.get("/S", "/GoTo")) == "/GoTo":
                key = _pdf_anchor_name(action.get("/D"))
                if key in destinations:
                    action[NameObject("/D")] = ArrayObject(list(destinations[key]))
                    fixed += 1
                continue

            key = _pdf_anchor_name(annot.get("/Dest"))
            if key in destinations:
                annot[NameObject("/Dest")] = ArrayObject(list(destinations[key]))
                fixed += 1

    return fixed


def repair_pdf_links(report_pdf):
    try:
        PdfReader, PdfWriter, ArrayObject, NameObject, FloatObject, NullObject = _load_pdf_tools()
    except ImportError:
        return False

    tmp_pdf = report_pdf.with_name(f"{report_pdf.stem}_tmp_links.pdf")
    try:
        reader = PdfReader(str(report_pdf), strict=False)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        page_targets = {}
        destinations = {}
        for name, dest in getattr(reader, "named_destinations", {}).items():
            page_num = reader.get_destination_page_number(dest)
            if page_num is None:
                continue
            writer.add_named_destination(str(name), page_num)
            key = str(name).lstrip("/")
            page_targets[key] = page_num
            destinations[key] = _pdf_destination(
                writer, page_num, ArrayObject, NameObject, FloatObject, NullObject, dest
            )

        for anchor, title in REPORT_OUTLINE:
            page_num = page_targets.get(anchor)
            if page_num is not None:
                writer.add_outline_item(title, page_num)

        fixed = _direct_pdf_link_targets(writer, destinations, ArrayObject, NameObject)
        with open(tmp_pdf, "wb") as fout:
            writer.write(fout)
        tmp_pdf.replace(report_pdf)
        print(f"  PDF   ->  repaired {fixed} internal links")
        return True
    except Exception as exc:
        print(f"  [WARN] Could not repair PDF links: {exc}")
        try:
            tmp_pdf.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _load_pdf_page_font(size, bold=False):
    from PIL import ImageFont

    names = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def create_landscape_image_pdf(image_path, output_pdf, title):
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError:
        print("  [WARN] Install Pillow to append the large 3D model page: pip install Pillow")
        return False

    page_w, page_h = 1754, 1240  # A4 landscape at 150 dpi
    margin = 70
    header_h = 110
    navy = (9, 43, 74)
    gold = (205, 157, 37)
    border = (126, 160, 196)

    canvas = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, page_w, header_h], fill=navy)
    draw.rectangle([0, header_h - 10, page_w, header_h], fill=gold)

    title_font = _load_pdf_page_font(38, bold=True)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_box[2] - title_box[0]
    title_h = title_box[3] - title_box[1]
    draw.text(((page_w - title_w) / 2, (header_h - title_h) / 2 - 4), title, fill="white", font=title_font)

    with Image.open(image_path) as src:
        src = ImageOps.exif_transpose(src)
        if src.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", src.size, "white")
            bg.paste(src, mask=src.split()[-1])
            src = bg
        else:
            src = src.convert("RGB")

        area_w = page_w - (2 * margin)
        area_h = page_h - header_h - (2 * margin)
        resample = getattr(Image, "Resampling", Image).LANCZOS
        fitted = ImageOps.contain(src, (area_w, area_h), resample)
        x = margin + (area_w - fitted.width) // 2
        y = header_h + margin + (area_h - fitted.height) // 2
        draw.rectangle([margin, header_h + margin, page_w - margin, page_h - margin], outline=border, width=3)
        canvas.paste(fitted, (x, y))

    canvas.save(output_pdf, "PDF", resolution=150.0)
    return True


def append_engineering_drawings(report_pdf, drawings, model_image_path=None):
    valid = [d for d in drawings if Path(d.get("path", "")).exists()]
    if not valid:
        return False

    try:
        PdfReader, PdfWriter, ArrayObject, NameObject, FloatObject, NullObject = _load_pdf_tools()
    except ImportError:
        print("  [WARN] Install pypdf to append drawing PDFs automatically: pip install pypdf")
        return False

    tmp_pdf = report_pdf.with_name(f"{report_pdf.stem}_tmp_with_drawings.pdf")
    model_page_pdf = report_pdf.with_name(f"{report_pdf.stem}_tmp_3d_model_page.pdf")
    model_appended = False
    try:
        writer = PdfWriter()
        base_reader = PdfReader(str(report_pdf), strict=False)
        for page in base_reader.pages:
            writer.add_page(page)

        page_targets = {}
        destinations = {}
        for name, dest in getattr(base_reader, "named_destinations", {}).items():
            if str(name).lstrip("/").startswith("drawing-"):
                continue
            page_num = base_reader.get_destination_page_number(dest)
            if page_num is None:
                continue
            writer.add_named_destination(str(name), page_num)
            key = str(name).lstrip("/")
            page_targets[key] = page_num
            destinations[key] = _pdf_destination(
                writer, page_num, ArrayObject, NameObject, FloatObject, NullObject, dest
            )

        for anchor, title in REPORT_OUTLINE:
            page_num = page_targets.get(anchor)
            if page_num is not None:
                writer.add_outline_item(title, page_num)

        for drawing in valid:
            start_page = len(writer.pages)
            reader = PdfReader(str(drawing["path"]), strict=False)
            for page in reader.pages:
                writer.add_page(page)
            writer.add_named_destination(f"/{drawing['anchor']}", start_page)
            writer.add_outline_item(drawing["title"], start_page)
            page_targets[drawing["anchor"]] = start_page
            destinations[drawing["anchor"]] = _pdf_destination(
                writer, start_page, ArrayObject, NameObject, FloatObject, NullObject
            )

        if model_image_path and Path(model_image_path).exists():
            if create_landscape_image_pdf(model_image_path, model_page_pdf, "3D Isometric View"):
                start_page = len(writer.pages)
                model_reader = PdfReader(str(model_page_pdf), strict=False)
                for page in model_reader.pages:
                    writer.add_page(page)
                writer.add_named_destination("/large-3d-model", start_page)
                writer.add_outline_item("3D Isometric View - Large", start_page)
                model_appended = True

        fixed = _direct_pdf_link_targets(writer, destinations, ArrayObject, NameObject)

        with open(tmp_pdf, "wb") as fout:
            writer.write(fout)
        tmp_pdf.replace(report_pdf)
        try:
            model_page_pdf.unlink(missing_ok=True)
        except Exception:
            pass
        model_msg = "; appended large 3D model page" if model_appended else ""
        print(f"  PDF   ->  appended {len(valid)} engineering drawing PDFs{model_msg}; repaired {fixed} internal links")
        return True
    except Exception as exc:
        print(f"  [WARN] Could not append engineering drawings: {exc}")
        try:
            tmp_pdf.unlink(missing_ok=True)
            model_page_pdf.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# -- Installation note generator -----------------------------------------------


def make_install_notes(structural):
    g  = structural['geometry']
    s  = structural['supports']
    W, D, H = g['width'], g['depth'], g['height']
    kicker  = g['kicker_lift']
    mids    = g['mid_lifts']
    tie_h   = s.get('tie_heights', [H])
    tie_n   = s.get('tie_nodes', [])

    notes = [
        "The scaffold working drawings and purpose of the scaffold must be reviewed and "
        "discussed by all personnel involved prior to execution.",
        "The work vicinity must be barricaded and appropriate signage placed at all access points.",
        "All scaffolders must wear complete PPE in accordance with NLNG work-at-height regulations.",
        "A valid work permit must be obtained, discussed, and signed before erection commences.",
        "Scaffold erection must be carried out in strict accordance with NASC guidance and site "
        "safety procedures.",
        f"Lay out and level the four base plates at the standard positions, ensuring a plan "
        f"footprint of {W:.1f}m x {D:.1f}m in accordance with the approved working drawing.",
        f"Erect the four scaffold tube standards (48.3 x 3.6 mm) vertically on the base plates "
        f"and secure with base collars. Check plumb in both axes before proceeding.",
        f"Install the lower horizontal ledgers and transoms at the kicker lift height "
        f"({kicker:.3f}m) to tie the four standards together and form the rigid base frame.",
    ]

    for ml in mids:
        notes.append(
            f"Install mid-level horizontal ledgers and transoms at {ml:.1f}m height in "
            f"accordance with the working drawing."
        )

    notes += [
        "Fix all vertical bracing members diagonally across the face panels of the A-frame "
        "structure using right-angle couplers to provide sway resistance in both X and Z axes "
        "as shown on the working drawing.",
        f"Install the {W*1000:.0f}mm ladder beam horizontally across the top of the standards "
        f"at {H:.1f}m height, connecting to both standards with right-angle double couplers. "
        f"Ensure the beam is level before fully tightening all couplers.",
        "Rig the chain hoist to the ladder beam at the designated hoist point shown on the "
        "working drawing. Confirm the hoist is rated for a minimum safe working load equal to "
        "or greater than the design SWL.",
        "The chain hoist attachment point and all coupler connections at ladder beam level shall "
        "be inspected and torque-checked by a competent person before any lifting operation "
        "commences.",
    ]

    if tie_n:
        tie_str = ' and '.join(f'{h:.1f}m' for h in tie_h)
        notes.append(
            f"Gravlock or box-tie the scaffold structure to the existing structure at all "
            f"indicated tie points at {tie_str} height as shown on the working drawing."
        )

    notes += [
        "The scaffold structure must be inspected and tagged by a competent advance scaffold "
        "inspector after erection and before any lift is performed.",
        "The safe working load (SWL) stated on the design report must not be exceeded at any "
        "time during operations.",
        "All modifications made after erection must be carried out by a competent scaffold team "
        "with the approval of the scaffold engineer. End-user or third-party modification "
        "of this scaffold structure is strictly prohibited.",
        "For dismantling, perform the erection steps in reverse order.",
    ]
    return notes


# -- Main ----------------------------------------------------------------------

def main():
    from jinja2 import Environment, FileSystemLoader

    args = parse_args()
    OUT_DIR.mkdir(exist_ok=True)

    print("=== A-Frame Scaffold Report Generator ===\n")

    # -- 1. Project info -------------------------------------------------------
    project = parse_project_info(INPUTS / 'project_info.txt')
    print(f"  Project : {project['DOCUMENT_NO']}")

    structure_above_ground = _optional_float(project.get('STRUCTURE_ABOVE_GROUND_M'))
    if project.get('STRUCTURE_ABOVE_GROUND_M', '').strip() and structure_above_ground is None:
        print("  [WARN] STRUCTURE_ABOVE_GROUND_M is not numeric; cover sentence skipped")

    # -- 2. STAAD parsing ------------------------------------------------------
    std_path = INPUTS / 'staad_command.txt'
    out_path = INPUTS / 'staad_output.txt'

    for p in (std_path, out_path):
        if not p.exists():
            print(f"  [ERROR] Missing: {p}")
            print("  Copy your STAAD .std/.out file contents into inputs/")
            sys.exit(1)

    print("  Parsing STAAD files ...")
    parser     = StaadParser(str(std_path), str(out_path))
    structural = parser.parse()
    g          = structural['geometry']

    drawing_format = _normalise_drawing_format(
        args.drawing_format or project.get("ENGINEERING_DRAWING_FORMAT")
    )

    if not args.skip_3d_render and _bool_setting(project.get("AUTO_RENDER_3D_MODEL"), True):
        auto_render_3d_model(std_path)

    engineering_drawings = []
    if (
        not args.skip_engineering_drawings
        and _bool_setting(project.get("AUTO_ENGINEERING_DRAWINGS"), True)
        and drawing_format != "none"
    ):
        _update_title_block_values(project)
        engineering_drawings = generate_engineering_drawings(std_path, drawing_format)
    print(f"  Scaffold  : {g['width']:.1f}m W x {g['depth']:.1f}m D x {g['height']:.1f}m H")

    # -- 3. Wind calculation ---------------------------------------------------
    wind_height_override = _optional_float(project.get('WIND_CALC_HEIGHT_M'))
    if project.get('WIND_CALC_HEIGHT_M', '').strip() and wind_height_override is None:
        print("  [WARN] WIND_CALC_HEIGHT_M is not numeric; falling back to STAAD height")
    wind_height = wind_height_override if wind_height_override is not None else g['height']
    print(f"  Wind calc : z = {_format_number(wind_height)}m ...")
    wind = WindCalculator(wind_height).calculate()
    wind['z_default'] = g['height']
    print(f"             qp = {wind['qp_nm2']:.2f} N/m2  |  UDL = {wind['wind_udl']:.6f} kN/m")

    # -- 4. Logos & images -----------------------------------------------------
    nlng_logo    = load_logo('nlng')
    company_logo = load_logo('company')
    site_photo = load_image('site_photo')   # no placeholder if missing - intentional
    images = {k: load_image(k) for k in [
        '3d_model', 'plan_view', 'elev_x', 'elev_z',
        'load_chain_hoist', 'load_impact_x', 'load_impact_z',
        'load_wind_x', 'load_wind_z',
        'connection_table',
        'deflection_vertical', 'deflection_vertical_table',
        'deflection_horizontal', 'deflection_horizontal_table',
        'uc_diagram',
    ]}
    loaded = sum(1 for v in images.values() if v)
    print(f"  Images    : {loaded}/{len(images)} found")

    # -- 5. Derived values -----------------------------------------------------
    wl   = structural['wind_loads']
    ld   = structural['loads']
    geom = structural['geometry']
    plan_length = max(geom['width'], geom['depth'])
    plan_width  = min(geom['width'], geom['depth'])
    structural['dimension_display'] = (
        f"{_format_number(plan_length)}m x {_format_number(plan_width)}m x {_format_number(geom['height'])}m"
    )
    structural['brief_description'] = _brief_description(
        project,
        structural,
        _format_number(structure_above_ground),
    )

    # -- Deflection L: look up member length from STAAD geometry -----------------
    members_dict = structural.get('members', {})

    def _member_length_mm(member_key, fallback_mm):
        try:
            mid = int(project.get(member_key, 0) or 0)
            if mid and mid in members_dict:
                return members_dict[mid]['length_mm']
        except (ValueError, TypeError):
            pass
        return fallback_mm

    vert_span_mm  = _member_length_mm('MAX_VERT_MEMBER',  geom['width'] * 1000)
    horiz_span_mm = _member_length_mm('MAX_HORIZ_MEMBER', geom['depth'] * 1000)
    vert_allow    = round(vert_span_mm  / 100, 1)
    horiz_allow   = round(horiz_span_mm / 200, 1)

    # Member details for report display
    def _member_info(member_key):
        try:
            mid = int(project.get(member_key, 0) or 0)
            if mid and mid in members_dict:
                return {'id': mid, 'length_mm': members_dict[mid]['length_mm']}
        except:
            pass
        return None

    vert_member_info  = _member_info('MAX_VERT_MEMBER')
    horiz_member_info = _member_info('MAX_HORIZ_MEMBER')

    total_horiz_x = round(wl['total_x'] + ld['impact_fx'], 3)
    total_horiz_z = round(wl['total_z'] + ld['impact_fz'], 3)

    # -- Ties: cover page shows a Total Horizontal Load (FX/FZ) block only when the
    # A-frame is actually tied to a parent structure. A-frame is never a hanging type,
    # so there is no FY / suspension-tie concept here.
    has_ties = bool(structural.get('supports', {}).get('tie_nodes'))
    has_wind = bool(wl.get('has_wind'))
    show_tie_reactions = _bool_setting(project.get('SHOW_TIE_REACTIONS'), False)

    sr = structural.get('support_reactions', {})
    worst_tie     = sr.get('worst_individual_tie')
    net_governing = sr.get('net_global', {}).get('governing')
    tie_display_mode = (project.get('TIE_DISPLAY') or 'sum').strip().lower()
    if tie_display_mode not in ('sum', 'worst'):
        tie_display_mode = 'sum'
    if tie_display_mode == 'worst' and worst_tie:
        tie_sum_fx = worst_tie['max_fx']
        tie_sum_fz = worst_tie['max_fz']
    elif net_governing:
        tie_sum_fx = net_governing['total_x']
        tie_sum_fz = net_governing['total_z']
    else:
        tie_sum_fx = worst_tie['max_fx'] if worst_tie else None
        tie_sum_fz = worst_tie['max_fz'] if worst_tie else None

    if _optional_float(project.get('TIE_FORCE_FX')) is not None:
        tie_sum_fx = _optional_float(project.get('TIE_FORCE_FX'))
    if _optional_float(project.get('TIE_FORCE_FZ')) is not None:
        tie_sum_fz = _optional_float(project.get('TIE_FORCE_FZ'))

    # -- Connection stability: max axial in HORIZONTAL members only (coupler slipping) --
    cc = structural['code_check']
    nodes_coord = structural.get('geometry', {}).get('nodes', {})

    def _is_horizontal(member_id):
        """True when member runs primarily in X-Z plane (ledger/transom), not Y (standard)."""
        m = members_dict.get(member_id)
        if not m:
            return True
        n1, n2 = nodes_coord.get(m['j1']), nodes_coord.get(m['j2'])
        if not n1 or not n2:
            return True
        dy = abs(n2[1] - n1[1])
        dx, dz = abs(n2[0] - n1[0]), abs(n2[2] - n1[2])
        return (dx * dx + dz * dz) > dy * dy

    horiz_members = [m for m in cc.get('members', []) if _is_horizontal(m['member'])]
    if horiz_members:
        best_horiz = max(horiz_members, key=lambda m: m['axial'])
        auto_axial        = best_horiz['axial']
        auto_axial_member = best_horiz['member']
        auto_axial_type   = best_horiz.get('type', 'C')
    else:
        auto_axial        = cc['max_axial']
        auto_axial_member = cc['max_axial_member']
        auto_axial_type   = cc['max_axial_type']

    # Check ULS first; if the coupler class fails under ULS, fall back to SLS (unfactored,
    # gamma=1.0 — see Load Combinations legend). SLS force = ULS force / 1.5, since every
    # ULS combo here is the same SLS combo at 1.5x, so this is an exact unfactoring, not an
    # approximation. The Status/Clause/UC Ratio columns are ULS-specific and are not shown
    # for the SLS view.
    connection_basis = 'ULS'
    max_axial        = auto_axial
    max_axial_member = str(auto_axial_member or '')
    max_axial_type   = auto_axial_type
    connection_class = _connection_class(max_axial)

    # Top 30 horizontal members by axial force for the connection check table
    top_axial_members = sorted(horiz_members if horiz_members else cc.get('members', []),
                               key=lambda m: m['axial'], reverse=True)[:30]

    if connection_class['status'] == 'FAIL':
        connection_basis = 'SLS'
        max_axial = round(auto_axial / 1.5, 3)
        connection_class = _connection_class(max_axial)
        top_axial_members = [
            {**m, 'axial': round(m['axial'] / 1.5, 3)}
            for m in top_axial_members
        ]

    # -- Deflection values (auto from .out file; project_info keys are optional overrides) --
    def _float(val, fallback):
        try: return float(val) if val else fallback
        except: return fallback

    d = structural['displacements']
    max_vert_mm   = _float(project.get('MAX_VERT_DISP_MM'),  d['max_vertical_mm'])
    max_vert_lc   = project.get('MAX_VERT_DISP_LC',  '')  or str(d['max_vertical_lc'])
    max_horiz_mm  = _float(project.get('MAX_HORIZ_DISP_MM'), d['max_horizontal_mm'])
    max_horiz_lc  = project.get('MAX_HORIZ_DISP_LC', '')  or str(d['max_horizontal_lc'])

    install_notes = make_install_notes(structural)
    date_gen = datetime.now().strftime('%d-%b-%Y')

    # -- 6. Render template ----------------------------------------------------
    env = Environment(loader=FileSystemLoader(str(TMPL_DIR)))
    env.globals.update({
        'round': round,
        'abs':   abs,
    })

    cover_callout_font_pt = _cover_callout_font_pt(project.get('NOTE'), project.get('WARNING'))

    template = env.get_template('report.html')
    html = template.render(
        project       = project,
        structural    = structural,
        wind          = wind,
        nlng_logo     = nlng_logo,
        company_logo  = company_logo,
        images        = images,
        vert_allow    = vert_allow,
        horiz_allow   = horiz_allow,
        total_horiz_x = total_horiz_x,
        total_horiz_z = total_horiz_z,
        cover_callout_font_pt = cover_callout_font_pt,
        has_ties = has_ties,
        has_wind = has_wind,
        show_tie_reactions = show_tie_reactions,
        tie_sum_fx        = tie_sum_fx,
        tie_sum_fz        = tie_sum_fz,
        tie_display_mode  = tie_display_mode,
        worst_tie         = worst_tie,
        net_governing     = net_governing,
        install_notes = install_notes,
        date_gen      = date_gen,
        max_axial        = max_axial,
        max_axial_member = max_axial_member,
        max_axial_type   = max_axial_type,
        connection_class  = connection_class,
        connection_basis  = connection_basis,
        top_axial_members = top_axial_members,
        max_vert_mm      = max_vert_mm,
        max_vert_lc      = max_vert_lc,
        max_horiz_mm     = max_horiz_mm,
        max_horiz_lc     = max_horiz_lc,
        vert_span_mm      = vert_span_mm,
        vert_member_info  = vert_member_info,
        horiz_span_mm     = horiz_span_mm,
        horiz_member_info = horiz_member_info,
        site_photo       = site_photo,
        engineering_drawings = engineering_drawings,
        drawing_format   = drawing_format,
        structure_above_ground_m = _format_number(structure_above_ground),
    )

    # -- 7. Save HTML ----------------------------------------------------------
    doc = project['DOCUMENT_NO'].replace('/', '_')
    html_path = OUT_DIR / f'{doc}_Report.html'
    html_path.write_text(html, encoding='utf-8')
    print(f"\n  HTML  ->  {html_path}")

    # -- 8. PDF generation - 3 engines in order -------------------------------
    pdf_path = OUT_DIR / f'{doc}_Report.pdf'
    _ok = False

    # Engine 1: Playwright (if chromium was previously downloaded)
    if not _ok:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                br   = pw.chromium.launch()
                page = br.new_page()
                page.goto(f'file:///{html_path.resolve().as_posix()}')
                page.wait_for_load_state('networkidle')
                page.pdf(path=str(pdf_path), format='A4',
                         print_background=True,
                         display_header_footer=False,
                         margin={'top':'0mm','bottom':'0mm',
                                 'left':'0mm','right':'0mm'})
                br.close()
            print(f"  PDF   ->  {pdf_path}  [via Playwright]")
            _ok = True
        except Exception:
            pass

    # Engine 2: System Chrome / Edge (no install needed)
    if not _ok:
        _ok = _try_system_browser(html_path, pdf_path)

    # Engine 3: xhtml2pdf (pip install xhtml2pdf - pure Python, no binary)
    if not _ok:
        try:
            from xhtml2pdf import pisa
            resolved = _resolve_css_vars(html_path.read_text(encoding='utf-8'))
            with open(pdf_path, 'wb') as fout:
                pisa.CreatePDF(resolved, dest=fout)
            print(f"  PDF   ->  {pdf_path}  [via xhtml2pdf]")
            _ok = True
        except ImportError:
            pass
        except Exception as e:
            print(f"  [WARN] xhtml2pdf error: {e}")

    if not _ok:
        print("\n  HTML saved. To get a PDF, choose one:")
        print("  A) pip install xhtml2pdf        (pure Python, no extra downloads)")
        print("  B) playwright install chromium   (best quality, one-time ~150 MB)")
        print("  C) Open HTML in Chrome/Edge -> Ctrl+P -> Save as PDF")
    else:
        show_3d_iso = _bool_setting(project.get("SHOW_3D_ISOMETRIC_PAGE"), True)
        model_img = find_image_file('3d_model') if show_3d_iso else None
        if engineering_drawings or model_img:
            append_engineering_drawings(pdf_path, engineering_drawings, model_img)
        else:
            repair_pdf_links(pdf_path)

    print("\nDone.\n")


if __name__ == '__main__':
    main()
