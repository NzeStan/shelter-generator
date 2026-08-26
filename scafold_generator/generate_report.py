

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
General Scaffold Report Generator
Usage:  python generate_report.py
Output: output/<DOC_NO>_Report.html and .pdf when a PDF engine is available
"""
import argparse
import os
import re
import sys
import base64
import json
import math
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
    'SCAFFOLD_TYPE':     'Independent',
    'LOAD_INTENSITY_KN_M2': '',   # optional override — kN/m²; auto-detected from STAAD LL if blank
    'CATEGORY_1_ASSURANCE_NOTE': '',
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
    'EQUIPMENT_NAME':    '',
    'LINE_NUMBER':       '',
    'WORK_ORDER':        '',
    'PURPOSE':           'maintenance activities',
    'STRUCTURE_ABOVE_GROUND_M': '',
    'WIND_CALC_HEIGHT_M': '',
    'DOC_LIFE':          '3 Years',
    'PREPARED_BY_NAME':  '',   # falls back to DESIGNED_BY_NAME if blank
    'AUTO_RENDER_3D_MODEL': 'yes',
    'AUTO_ENGINEERING_DRAWINGS': 'yes',
    'ENGINEERING_DRAWING_FORMAT': 'standard',
    'COUNTERWEIGHT_ENABLED': 'no',
    'COUNTERWEIGHT_ZONE_NODES': '',
    'COUNTERWEIGHT_PIVOT_NODES': '',
    'COUNTERWEIGHT_SAFETY_FACTOR': '4',
}

REPORT_OUTLINE = [
    ("load-summary", "Load Summary"),
    ("general-note", "General Note, Material Properties & Modelling Philosophy"),
    ("load-cases", "Load Cases"),
    ("wind-calc", "Wind Load Calculation"),
    ("load-combs", "Load Combinations"),
    ("uc-summary", "Utilization Ratio Summary"),
    ("connection-check", "Connection Stability Check"),
    ("deflection-check", "Deflection Check Results"),
    ("conclusion", "Conclusion, Recommendations & Installation Notes"),
    ("app-e", "Appendix E - Counterweight Design Calculation"),
    ("references-standards", "References & Standards"),
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
    ap = argparse.ArgumentParser(description="Generate a scaffold design report.")
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


def _project_value(project, *keys):
    for key in keys:
        value = project.get(key, "")
        if str(value).strip():
            return str(value).strip()
    return ""


def _is_hanging_scaffold(scaffold_type):
    return "HANGING" in str(scaffold_type or "").upper()


LOAD_CLASS_INTENSITIES = {
    "1": 0.75,
    "2": 1.50,
    "3": 2.00,
    "4": 3.00,
    "5": 4.50,
    "6": 6.00,
}


def _extract_first_float(value):
    m = re.search(r'[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?', str(value or ""))
    return float(m.group(0)) if m else None


def _normalise_load_class(value):
    m = re.search(r'\b(?:CLASS\s*)?([1-6])\b', str(value or "").upper())
    return m.group(1) if m else ""


def _project_load_intensity(project):
    # Primary key: LOAD_INTENSITY_KN_M2; also accept legacy aliases for backward compatibility
    raw = _project_value(
        project,
        "LOAD_INTENSITY_KN_M2",
        "SERVICE_LOAD_KN_M2",
        "SAFE_WORKING_LOAD_KN_M2",
        "SAFE_WORKING_LOAD",
        "SWL",
    )
    value = _extract_first_float(raw)
    if value is not None:
        return value, "project_info"

    load_class = _normalise_load_class(_project_value(project, "LOAD_CLASS", "SERVICE_LOAD_CLASS"))
    if load_class and load_class in LOAD_CLASS_INTENSITIES:
        return LOAD_CLASS_INTENSITIES[load_class], f"class {load_class}"

    return None, ""


def _format_load_value(value):
    if value is None:
        return ""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _indefinite_article(text):
    clean = str(text or "").strip()
    return "an" if clean[:1].lower() in {"a", "e", "i", "o", "u"} else "a"


def _minimum_plan_bay_spacing(structural):
    nodes = (structural.get("geometry", {}) or {}).get("nodes", {})
    spacings = []
    for idx in (0, 2):
        vals = sorted(set(round(coord[idx], 3) for coord in nodes.values()))
        spacings.extend(
            round(vals[i + 1] - vals[i], 3)
            for i in range(len(vals) - 1)
            if vals[i + 1] - vals[i] > 0.05
        )
    return min(spacings) if spacings else 0.0


def _default_platform_tributary_width(structural):
    bay_spacing = _minimum_plan_bay_spacing(structural)
    if bay_spacing:
        return round(bay_spacing / 2.0, 3), f"{bay_spacing:.3f} / 2 = {bay_spacing / 2.0:.3f}"
    return 1.0, "1.000"


def _fmt_width(value):
    return f"{float(value):.3f}"


def _load_class_for_intensity(intensity):
    """Return BS EN 12811-1 class string for the given intensity, or '' if unmatched."""
    for cls, cls_int in LOAD_CLASS_INTENSITIES.items():
        if abs(float(intensity or 0.0) - cls_int) < 0.026:
            return cls
    return ""


def _format_member_ids(member_ids):
    ids = sorted(set(int(mid) for mid in member_ids if mid))
    if not ids:
        return "STAAD LL members"
    if len(ids) == 1:
        return f"Member {ids[0]}"
    return "Members " + ", ".join(str(mid) for mid in ids)


def _live_member_geometry(member_id, structural):
    members = structural.get("members", {})
    nodes = (structural.get("geometry", {}) or {}).get("nodes", {})
    member = members.get(member_id)
    if not member:
        return None

    p1 = nodes.get(member.get("j1"))
    p2 = nodes.get(member.get("j2"))
    if not p1 or not p2:
        return None

    dx = abs(p2[0] - p1[0])
    dz = abs(p2[2] - p1[2])
    if dx >= dz:
        axis = "X"
        perp_idx = 2
    else:
        axis = "Z"
        perp_idx = 0

    return {
        "axis": axis,
        "y_mid": round((p1[1] + p2[1]) / 2.0, 3),
        # Rounded to 1cm (not 1mm) so members meant to sit at the same design position
        # collapse into the same bucket even when STAAD node coordinates carry sub-mm
        # noise (e.g. 4.00001 instead of 4.0) — avoids splitting one Edge/Interior role
        # into several near-identical tributary-width rows purely from float noise.
        "perp_coord": round((p1[perp_idx] + p2[perp_idx]) / 2.0, 2),
    }


def _assign_tributary_widths(member_entries):
    groups = {}
    for entry in member_entries:
        geom = entry.get("geometry")
        if not geom:
            continue
        key = (entry["load_case"], geom["axis"], geom["y_mid"])
        groups.setdefault(key, set()).add(geom["perp_coord"])

    for entry in member_entries:
        geom = entry.get("geometry")
        if not geom:
            continue

        coords = sorted(groups.get((entry["load_case"], geom["axis"], geom["y_mid"]), []))
        if len(coords) < 2 or geom["perp_coord"] not in coords:
            continue

        idx = coords.index(geom["perp_coord"])
        if idx == 0:
            # Round the bay itself first so two edges that display as the same bay width
            # (e.g. both "1.667") always halve to the same tributary width — otherwise
            # sub-millimetre noise in the underlying node coordinates (STAAD geometry is
            # rarely exact) can round the half up at one edge and down at the other.
            bay = round(coords[1] - coords[0], 3)
            tw = round(bay / 2.0, 3)
            entry["member_role"] = "Edge"
            entry["tributary_width_m"] = tw
            entry["tributary_width_display"] = f"{_fmt_width(bay)} / 2 = {_fmt_width(tw)}"
        elif idx == len(coords) - 1:
            bay = round(coords[-1] - coords[-2], 3)
            tw = round(bay / 2.0, 3)
            entry["member_role"] = "Edge"
            entry["tributary_width_m"] = tw
            entry["tributary_width_display"] = f"{_fmt_width(bay)} / 2 = {_fmt_width(tw)}"
        else:
            left_half = round((coords[idx] - coords[idx - 1]) / 2.0, 3)
            right_half = round((coords[idx + 1] - coords[idx]) / 2.0, 3)
            tw = round(left_half + right_half, 3)
            entry["member_role"] = "Interior"
            entry["tributary_width_m"] = tw
            entry["tributary_width_display"] = (
                f"({_fmt_width(left_half)} + {_fmt_width(right_half)}) = {_fmt_width(tw)}"
            )


def _platform_live_workings(project, structural):
    loads = structural.get("loads", {})
    udls = loads.get("platform_live_udls_kn_m") or []
    if not udls and loads.get("platform_live_udl_kn_m"):
        udls = [loads["platform_live_udl_kn_m"]]

    project_intensity, intensity_source = _project_load_intensity(project)
    configured_tw = _optional_float(_project_value(project, "TRIBUTARY_WIDTH_M", "LIVE_LOAD_TRIBUTARY_WIDTH_M"))
    inferred_tw, inferred_tw_display = _default_platform_tributary_width(structural)

    member_entries = []
    for load in loads.get("platform_live_member_loads", []):
        member_ids = load.get("members") or []
        if not member_ids:
            member_entries.append({
                "load_case": load.get("load_case"),
                "title": load.get("title") or "LL",
                "member_id": None,
                "line_load_kn_m": abs(float(load.get("value", 0.0))),
                "geometry": None,
            })
            continue

        for member_id in member_ids:
            member_entries.append({
                "load_case": load.get("load_case"),
                "title": load.get("title") or "LL",
                "member_id": int(member_id),
                "line_load_kn_m": abs(float(load.get("value", 0.0))),
                "geometry": _live_member_geometry(int(member_id), structural),
            })

    _assign_tributary_widths(member_entries)

    grouped = {}
    for entry in member_entries:
        line_load = entry["line_load_kn_m"]
        tributary_width = entry.get("tributary_width_m")
        tw_display = entry.get("tributary_width_display")
        geom = entry.get("geometry") or {}
        y_mid = round(geom.get("y_mid", 0.0), 3) if geom else 0.0

        if not tributary_width:
            if project_intensity:
                tributary_width = configured_tw if configured_tw and configured_tw > 0 else round(line_load / project_intensity, 3)
                tw_display = _fmt_width(tributary_width)
            elif configured_tw and configured_tw > 0:
                tributary_width = configured_tw
                tw_display = _fmt_width(tributary_width)
            else:
                tributary_width = inferred_tw
                tw_display = inferred_tw_display

        intensity = project_intensity or (line_load / tributary_width if tributary_width else line_load)
        matched_class = _load_class_for_intensity(intensity)
        if matched_class:
            # Snap to the exact BS EN 12811-1 class intensity instead of displaying a noisy
            # back-calculated value (e.g. 1.499/1.501 instead of 1.5) for what is a single
            # design intensity, and let members sharing a role collapse into one table row
            # instead of one row per member.
            intensity = LOAD_CLASS_INTENSITIES[matched_class]
            if tributary_width:
                line_load = round(intensity * tributary_width, 3)
        role = entry.get("member_role") or "Loaded"
        # Group purely by platform level / load case / role - members STAAD applies
        # ONE uniform UDL to (e.g. "3493 TO 3523 UNI GY -1.829") must collapse into a
        # single row, even when their individually-computed tributary widths differ
        # by a millimetre or two (real, tiny bay-spacing noise in the STAAD geometry,
        # not a different design condition). Keying on the exact width/intensity/load
        # split one applied UDL into several near-duplicate rows. The governing
        # (largest) tributary width found in the group is kept as the single,
        # conservative representative value shown on that row.
        key = (y_mid, entry.get("load_case"), entry.get("title") or "LL", role)
        candidate = {
            "y_mid": y_mid,
            "load_case": entry.get("load_case"),
            "title": entry.get("title") or "LL",
            "member_role": role,
            "load_intensity_kn_m2": round(float(intensity), 3),
            "tributary_width_m": round(float(tributary_width), 3) if tributary_width else 0.0,
            "tributary_width_display": tw_display,
            "line_load_kn_m": round(float(line_load), 3),
            "load_class": matched_class,
            "intensity_source": intensity_source or "STAAD LL / tributary width",
        }
        existing = grouped.get(key)
        if existing is None or candidate["tributary_width_m"] > existing["tributary_width_m"]:
            grouped[key] = candidate

    all_rows = []
    live_case_count = len(loads.get("platform_live_cases") or [])
    for row in grouped.values():
        member_display = row["member_role"]
        if live_case_count > 1 and row.get("load_case"):
            member_display = f"LC {row['load_case']}: {member_display}"
        row["member_display"] = member_display
        row["working"] = (
            f"{_format_load_value(row['load_intensity_kn_m2'])} × "
            f"{_fmt_width(row['tributary_width_m'])} = {_format_load_value(row['line_load_kn_m'])}"
        )
        all_rows.append(row)

    all_rows.sort(key=lambda item: (
        item.get("y_mid") or 0,
        item.get("load_case") or 0,
        item.get("line_load_kn_m") or 0,
        item.get("tributary_width_m") or 0,
        item.get("member_display") or "",
    ))

    if not all_rows:
        for udl in udls:
            line_load = abs(float(udl))
            if project_intensity:
                tributary_width = configured_tw if configured_tw and configured_tw > 0 else round(line_load / project_intensity, 3)
                intensity = project_intensity
                tw_display = _fmt_width(tributary_width)
            else:
                if configured_tw and configured_tw > 0:
                    tributary_width = configured_tw
                    tw_display = _fmt_width(tributary_width)
                else:
                    tributary_width = inferred_tw
                    tw_display = inferred_tw_display
                intensity = line_load / tributary_width if tributary_width else line_load

            all_rows.append({
                "y_mid": 0.0,
                "member_display": "STAAD LL members",
                "member_role": "Loaded",
                "load_intensity_kn_m2": round(intensity, 3),
                "tributary_width_m": round(tributary_width, 3),
                "tributary_width_display": tw_display,
                "line_load_kn_m": round(line_load, 3),
                "load_class": _load_class_for_intensity(intensity),
                "intensity_source": intensity_source or "STAAD LL / tributary width",
                "working": (
                    f"{_format_load_value(intensity)} × "
                    f"{_fmt_width(tributary_width)} = {_format_load_value(line_load)}"
                ),
            })

    if not all_rows and project_intensity:
        tributary_width = configured_tw if configured_tw and configured_tw > 0 else inferred_tw
        line_load = project_intensity * tributary_width
        all_rows.append({
            "y_mid": 0.0,
            "member_display": "Platform support members",
            "member_role": "Loaded",
            "load_intensity_kn_m2": round(project_intensity, 3),
            "tributary_width_m": tributary_width,
            "tributary_width_display": _fmt_width(tributary_width),
            "line_load_kn_m": round(line_load, 3),
            "load_class": _normalise_load_class(project.get("LOAD_CLASS", "")),
            "intensity_source": intensity_source,
            "working": (
                f"{_format_load_value(project_intensity)} × "
                f"{_format_load_value(tributary_width)} = {_format_load_value(line_load)}"
            ),
        })

    # Group rows into platforms by Y elevation
    platform_levels: dict = {}
    for row in all_rows:
        y = row.pop("y_mid", 0.0)
        y_key = round(float(y or 0.0), 2)
        platform_levels.setdefault(y_key, []).append(row)

    platforms = []
    for y_key in sorted(platform_levels.keys()):
        p_rows = platform_levels[y_key]
        p_intensity = max(r["load_intensity_kn_m2"] for r in p_rows)
        cls = _load_class_for_intensity(p_intensity)
        platforms.append({
            "elevation_m": y_key,
            "load_intensity_kn_m2": round(p_intensity, 3),
            "load_class": cls,
            "platform_label": "",
            "rows": p_rows,
        })

    if len(platforms) > 1:
        for i, p in enumerate(platforms, 1):
            p["platform_label"] = f"Platform {i}  —  Elev. {_format_number(p['elevation_m'])} m"

    # Collapse platforms with identical loading patterns into a single displayed table.
    # Signature = load intensity + sorted set of (role, trib_width, line_load) rows.
    seen_sigs: dict = {}
    for p in platforms:
        sig = (
            round(p["load_intensity_kn_m2"], 3),
            tuple(sorted(
                (r["member_role"], round(r["tributary_width_m"], 3), round(r["line_load_kn_m"], 3))
                for r in p["rows"]
            )),
        )
        p["also_applies_at"] = []
        if sig not in seen_sigs:
            seen_sigs[sig] = p
            p["skip"] = False
        else:
            representative = seen_sigs[sig]
            label = p["platform_label"] or f"Elev. {_format_number(p['elevation_m'])} m"
            representative["also_applies_at"].append(label)
            p["skip"] = True

    swl = max((p["load_intensity_kn_m2"] for p in platforms), default=project_intensity or 0.0)
    return platforms, round(swl, 3)


def _parse_node_list(value):
    return list(dict.fromkeys(int(node) for node in re.findall(r'\d+', str(value or ''))))


def _point_on_plan_segment(point, start, end, tolerance=1e-5):
    px, pz = point
    ax, az = start
    bx, bz = end
    cross = (px - ax) * (bz - az) - (pz - az) * (bx - ax)
    if abs(cross) > tolerance:
        return False
    return (
        min(ax, bx) - tolerance <= px <= max(ax, bx) + tolerance
        and min(az, bz) - tolerance <= pz <= max(az, bz) + tolerance
    )


def _point_in_plan_polygon(point, polygon):
    for index, start in enumerate(polygon):
        if _point_on_plan_segment(point, start, polygon[(index + 1) % len(polygon)]):
            return True

    px, pz = point
    inside = False
    for index, (ax, az) in enumerate(polygon):
        bx, bz = polygon[(index + 1) % len(polygon)]
        crosses = (az > pz) != (bz > pz)
        if crosses and px < (bx - ax) * (pz - az) / (bz - az) + ax:
            inside = not inside
    return inside


def _plan_polygon_area_centroid(polygon):
    twice_area = 0.0
    centroid_x = 0.0
    centroid_z = 0.0
    for index, (x1, z1) in enumerate(polygon):
        x2, z2 = polygon[(index + 1) % len(polygon)]
        cross = x1 * z2 - x2 * z1
        twice_area += cross
        centroid_x += (x1 + x2) * cross
        centroid_z += (z1 + z2) * cross

    if abs(twice_area) < 1e-8:
        return 0.0, None
    return abs(twice_area) / 2.0, (centroid_x / (3.0 * twice_area), centroid_z / (3.0 * twice_area))


def _counterweight_grid_distribution(structural, polygon, zone_elevation, zone_area, counterweight_kn):
    nodes = (structural.get('geometry') or {}).get('nodes', {})
    members = structural.get('members') or {}
    candidates = {'X': [], 'Z': []}
    elevation_tolerance = 0.003

    for member_id, member in members.items():
        first = nodes.get(member.get('j1'))
        second = nodes.get(member.get('j2'))
        if not first or not second:
            continue
        if abs(first[1] - zone_elevation) > elevation_tolerance or abs(second[1] - zone_elevation) > elevation_tolerance:
            continue
        if not _point_in_plan_polygon((first[0], first[2]), polygon):
            continue
        if not _point_in_plan_polygon((second[0], second[2]), polygon):
            continue

        dx = second[0] - first[0]
        dz = second[2] - first[2]
        if abs(dx) < 1e-6 and abs(dz) < 1e-6:
            continue
        if abs(dx) > 1e-6 and abs(dz) > 1e-6:
            continue

        axis = 'X' if abs(dx) > abs(dz) else 'Z'
        perpendicular = round((first[2] + second[2]) / 2.0, 5) if axis == 'X' else round((first[0] + second[0]) / 2.0, 5)
        candidates[axis].append({
            'member_id': int(member_id),
            'perpendicular': perpendicular,
            'length_m': float(member.get('length_mm', 0.0)) / 1000.0,
        })

    pressure = counterweight_kn / zone_area if zone_area else 0.0
    evaluated = []
    for axis, members_on_axis in candidates.items():
        line_coords = sorted({entry['perpendicular'] for entry in members_on_axis})
        if len(line_coords) < 2:
            continue

        for entry in members_on_axis:
            index = line_coords.index(entry['perpendicular'])
            if index == 0:
                bay = line_coords[1] - line_coords[0]
                tributary_width = bay / 2.0
                width_display = f"{_fmt_width(bay)} / 2 = {_fmt_width(tributary_width)}"
                role = 'Edge'
            elif index == len(line_coords) - 1:
                bay = line_coords[-1] - line_coords[-2]
                tributary_width = bay / 2.0
                width_display = f"{_fmt_width(bay)} / 2 = {_fmt_width(tributary_width)}"
                role = 'Edge'
            else:
                left_half = (line_coords[index] - line_coords[index - 1]) / 2.0
                right_half = (line_coords[index + 1] - line_coords[index]) / 2.0
                tributary_width = left_half + right_half
                width_display = f"({_fmt_width(left_half)} + {_fmt_width(right_half)}) = {_fmt_width(tributary_width)}"
                role = 'Interior'

            entry['tributary_width_m'] = tributary_width
            entry['tributary_width_display'] = width_display
            entry['member_role'] = role
            entry['line_load_kn_m'] = pressure * tributary_width

        distributed_area = sum(entry['length_m'] * entry['tributary_width_m'] for entry in members_on_axis)
        evaluated.append({
            'axis': axis,
            'line_count': len(line_coords),
            'members': members_on_axis,
            'distributed_area_m2': distributed_area,
            'area_error': abs(distributed_area - zone_area),
        })

    accepted = [
        item for item in evaluated
        if zone_area and item['area_error'] <= max(0.02, zone_area * 0.02)
    ]
    if not accepted:
        return None

    # Use the denser complete grid so each proposed line load remains traceable.
    selected = max(accepted, key=lambda item: (item['line_count'], item['axis'] == 'X'))
    grouped = {}
    for entry in selected['members']:
        key = (
            entry['member_role'],
            round(entry['tributary_width_m'], 5),
            entry['tributary_width_display'],
            round(entry['line_load_kn_m'], 5),
        )
        row = grouped.setdefault(key, {
            'member_role': entry['member_role'],
            'member_ids': [],
            'tributary_width_m': round(entry['tributary_width_m'], 3),
            'tributary_width_display': entry['tributary_width_display'],
            'line_load_kn_m': round(entry['line_load_kn_m'], 3),
        })
        row['member_ids'].append(entry['member_id'])

    rows = []
    for row in grouped.values():
        row['member_ids'].sort()
        row['member_display'] = _format_member_ids(row['member_ids'])
        rows.append(row)
    rows.sort(key=lambda row: (row['tributary_width_m'], row['member_display']))

    return {
        'axis': selected['axis'],
        'line_count': selected['line_count'],
        'distributed_area_m2': round(selected['distributed_area_m2'], 3),
        'rows': rows,
        'total_distributed_kn': round(sum(
            entry['line_load_kn_m'] * entry['length_m'] for entry in selected['members']
        ), 3),
    }


def _float_project_setting(value, default=0.0):
    match = re.search(r'[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?', str(value or ''))
    return float(match.group(0)) if match else default


def _counterweight_axis_value(point, axis):
    return point[0] if axis == 'X' else point[2]


def _counterweight_pivot_info(project, nodes, centroid):
    pivot_nodes = _parse_node_list(project.get('COUNTERWEIGHT_PIVOT_NODES'))
    missing = [node for node in pivot_nodes if node not in nodes]
    if len(pivot_nodes) < 2:
        return None, 'COUNTERWEIGHT_PIVOT_NODES requires at least two nodes defining the overturning pivot line.'
    if missing:
        return None, 'Pivot node(s) not found in STAAD geometry: ' + ', '.join(map(str, missing)) + '.'

    pivot_points = [nodes[node] for node in pivot_nodes]
    x_range = max(point[0] for point in pivot_points) - min(point[0] for point in pivot_points)
    z_range = max(point[2] for point in pivot_points) - min(point[2] for point in pivot_points)
    if x_range <= 0.003 and z_range <= 0.003:
        return None, 'COUNTERWEIGHT_PIVOT_NODES must define a line, not a single point.'

    pivot_axis = 'Z' if x_range <= z_range else 'X'
    normal_axis = 'X' if pivot_axis == 'Z' else 'Z'
    pivot_normal = sum(_counterweight_axis_value(point, normal_axis) for point in pivot_points) / len(pivot_points)
    pivot_start = min(_counterweight_axis_value(point, pivot_axis) for point in pivot_points)
    pivot_end = max(_counterweight_axis_value(point, pivot_axis) for point in pivot_points)
    centroid_normal = centroid[0] if normal_axis == 'X' else centroid[1]
    cw_lever = abs(pivot_normal - centroid_normal)
    if cw_lever <= 0.001:
        return None, 'Counterweight zone centroid is on the pivot line; no useful counterweight lever arm is available.'

    return {
        'pivot_nodes': pivot_nodes,
        'pivot_axis': pivot_axis,
        'normal_axis': normal_axis,
        'pivot_normal_m': pivot_normal,
        'pivot_start_m': pivot_start,
        'pivot_end_m': pivot_end,
        'cw_centroid_normal_m': centroid_normal,
        'cw_lever_m': cw_lever,
    }, None


def _analysis_line_label(index):
    """Spreadsheet-style label: 0->A, 1->B, ..., 25->Z, 26->AA, 27->AB, ..."""
    label = ''
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _counterweight_line_diagram_svg(row, lever):
    """One labelled free-body sketch per analysis line, in the style of the reference
    calculation: a CW block, a beam, the pivot, and the actual node reactions with their
    distances marked directly on the sketch — no values baked into the CW block itself."""
    terms = sorted(row.get('terms') or [], key=lambda t: -t['arm_m'])

    beam_y = 130
    cw_x = 130
    pivot_x = 560
    max_arm = max((t['arm_m'] for t in terms), default=lever) or lever or 1.0
    span = pivot_x - cw_x - 50

    arrows = []
    for term in terms:
        x = pivot_x - (term['arm_m'] / max_arm) * span
        arrows.append(
            f'<line x1="{x:.1f}" y1="{beam_y-40}" x2="{x:.1f}" y2="{beam_y}" stroke="#9b1c1c" '
            f'stroke-width="2.5" marker-end="url(#cw-arrow)"></line>'
            f'<text x="{x:.1f}" y="{beam_y-46}" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="#9b1c1c">{term["uplift_kn"]:.3f} kN</text>'
            f'<text x="{x:.1f}" y="{beam_y+32}" text-anchor="middle" font-size="9.5" fill="#0f2b46">'
            f'{term["arm_m"]:.2f} m</text>'
        )

    return f"""
<svg viewBox="0 0 700 200" width="100%" height="170" role="img" aria-label="Counter weight Analysis {row.get('label','')} diagram" style="border:1px solid #9bb8d6; background:#fff; margin:4px 0 6px;">
  <defs>
    <marker id="cw-arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L8,4 L0,8 z" fill="#0f2b46"></path>
    </marker>
  </defs>
  <line x1="70" y1="{beam_y}" x2="{pivot_x+60}" y2="{beam_y}" stroke="#0f2b46" stroke-width="6" stroke-linecap="round"></line>
  <rect x="{cw_x-40}" y="{beam_y-64}" width="80" height="64" fill="#5f8fc4" stroke="#0f2b46" stroke-width="3"></rect>
  <text x="{cw_x}" y="{beam_y-72}" text-anchor="middle" font-size="15" font-weight="700" fill="#0f2b46">CW</text>
  <polygon points="{pivot_x:.0f},{beam_y} {pivot_x-14:.0f},{beam_y+26} {pivot_x+14:.0f},{beam_y+26}" fill="#fff" stroke="#0f2b46" stroke-width="3"></polygon>
  {''.join(arrows)}
  <line x1="{cw_x}" y1="{beam_y+52}" x2="{pivot_x:.0f}" y2="{beam_y+52}" stroke="#0f2b46" stroke-width="1.5" marker-start="url(#cw-arrow)" marker-end="url(#cw-arrow)"></line>
  <text x="{(cw_x+pivot_x)/2:.0f}" y="{beam_y+68}" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0f2b46">{lever:.3f} m</text>
</svg>
"""


def _counterweight_snapshot_path(project):
    doc = str(project.get('DOCUMENT_NO') or 'project').replace('/', '_').strip() or 'project'
    return OUT_DIR / f'{doc}_counterweight_snapshot.json'


def _save_counterweight_snapshot(project, result):
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        _counterweight_snapshot_path(project).write_text(
            json.dumps(result, indent=2), encoding='utf-8'
        )
    except OSError:
        pass


def _load_counterweight_snapshot(project):
    path = _counterweight_snapshot_path(project)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _dl_already_has_counterweight_loads():
    """True once the DL (LOADTYPE Dead) primary case in staad_command.txt already carries
    explicit MEMBER LOAD lines beyond self-weight — the signal that the resolved counterweight
    has been applied and this run is for final-report presentation only. From this point the
    counterweight design must not be recomputed, no matter what the reactions now show."""
    path = INPUTS / 'staad_command.txt'
    if not path.exists():
        return False
    text = path.read_text(encoding='utf-8', errors='ignore')
    match = re.search(r'^LOAD\s+\d+\s+LOADTYPE\s+Dead\b.*$', text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return False
    next_load = re.search(r'^LOAD\s+\d+\b', text[match.end():], re.IGNORECASE | re.MULTILINE)
    block = text[match.end():match.end() + next_load.start()] if next_load else text[match.end():]
    return bool(re.search(r'^\s*MEMBER LOAD\b', block, re.IGNORECASE | re.MULTILINE))


def _counterweight_design(project, structural):
    result = {
        'enabled': _bool_setting(project.get('COUNTERWEIGHT_ENABLED'), False),
        'valid': False,
        'has_demand': False,
        'errors': [],
        'zone_nodes': [],
        'pivot_nodes': [],
        'analysis_line_rows': [],
        'distribution_rows': [],
        'recommended_staad_lines': [],
        'diagrams': [],
    }
    if not result['enabled']:
        return result

    if _dl_already_has_counterweight_loads():
        snapshot = _load_counterweight_snapshot(project)
        if snapshot:
            snapshot['message'] = (
                'Counterweight already applied to DL for this run — this is the design snapshot '
                'from the run that established it; not recomputed.'
            )
            return snapshot
        # DL already carries applied member loads but no snapshot exists yet (e.g. first-ever
        # run on this project with the counterweight pre-applied). Compute once now — the save
        # at the end of this function freezes it for every run after this one.

    zone_nodes = _parse_node_list(project.get('COUNTERWEIGHT_ZONE_NODES'))
    nodes = (structural.get('geometry') or {}).get('nodes', {})
    missing_nodes = [node for node in zone_nodes if node not in nodes]
    if len(zone_nodes) < 3:
        result['errors'].append('COUNTERWEIGHT_ZONE_NODES requires at least three ordered nodes.')
        return result
    if missing_nodes:
        result['errors'].append('Zone node(s) not found in STAAD geometry: ' + ', '.join(map(str, missing_nodes)) + '.')
        return result

    elevations = [nodes[node][1] for node in zone_nodes]
    if max(elevations) - min(elevations) > 0.003:
        result['errors'].append('Counterweight zone nodes must lie on one horizontal platform elevation.')
        return result

    polygon = [(nodes[node][0], nodes[node][2]) for node in zone_nodes]
    area, centroid = _plan_polygon_area_centroid(polygon)
    if not centroid or area <= 0.001:
        result['errors'].append('Counterweight zone nodes do not form a valid plan area.')
        return result

    result.update({
        'valid': True,
        'zone_nodes': zone_nodes,
        'zone_area_m2': round(area, 3),
        'zone_elevation_m': round(sum(elevations) / len(elevations), 3),
        'centroid_x_m': round(centroid[0], 3),
        'centroid_z_m': round(centroid[1], 3),
    })

    pivot_info, pivot_error = _counterweight_pivot_info(project, nodes, centroid)
    if pivot_error:
        result['errors'].append(pivot_error)
        return result

    base_rows = (structural.get('base_support_reactions') or {}).get('rows') or []
    base_nodes = (structural.get('supports') or {}).get('base_nodes') or []
    support_points = [nodes[node] for node in base_nodes if node in nodes]
    if not base_rows or len(support_points) < 2:
        result['errors'].append('STAAD base support reactions are required before counterweight demand can be calculated.')
        return result

    load_combinations = structural.get('load_combinations') or []
    base_by_load = {
        row['load_case']: {
            item['node']: float(item.get('fy', 0.0))
            for item in row.get('reactions', [])
        }
        for row in base_rows
    }

    safety_factor = _float_project_setting(project.get('COUNTERWEIGHT_SAFETY_FACTOR'), 4.0)
    if safety_factor <= 0.0:
        safety_factor = 4.0

    normal_axis = pivot_info['normal_axis']
    pivot_axis = pivot_info['pivot_axis']
    pivot_normal = pivot_info['pivot_normal_m']
    cw_lever = pivot_info['cw_lever_m']

    line_peaks = {}
    combo_summaries = []
    current_min = None
    current_governing = None
    for combo in load_combinations:
        title = str(combo.get('title') or '')
        if 'ULS' not in title.upper():
            continue
        combo_reactions = base_by_load.get(combo['number']) or {}
        if not combo_reactions:
            continue

        line_map = {}
        for node in sorted(base_nodes):
            if node not in combo_reactions or node not in nodes:
                continue
            fy = combo_reactions[node]
            if current_min is None or fy < current_min:
                current_min = fy
                current_governing = {
                    'load_case': combo['number'],
                    'title': title,
                    'node': node,
                    'fy': fy,
                }

            uplift = max(0.0, -fy)
            if uplift <= 0.005:
                continue
            normal_value = _counterweight_axis_value(nodes[node], normal_axis)
            moment_arm = abs(pivot_normal - normal_value)
            if moment_arm <= 0.001:
                continue
            line_coordinate = round(_counterweight_axis_value(nodes[node], pivot_axis), 3)
            line = line_map.setdefault(line_coordinate, {
                'axis_coordinate_m': line_coordinate,
                'moment_knm': 0.0,
                'nodes': [],
                'terms': [],
            })
            line['moment_knm'] += uplift * moment_arm
            line['nodes'].append(node)
            line['terms'].append({
                'node': node,
                'uplift_kn': uplift,
                'arm_m': moment_arm,
            })

        line_results = []
        for line in line_map.values():
            raw_cw = line['moment_knm'] / cw_lever
            line_result = {
                'axis_coordinate_m': line['axis_coordinate_m'],
                'line_label': f"{pivot_axis} = {_format_load_value(line['axis_coordinate_m'])} m",
                'governing_load_case': combo['number'],
                'governing_title': title,
                'critical_nodes': sorted(set(line['nodes'])),
                'terms': line['terms'],
                'terms_sum_kn': line['moment_knm'],
                'raw_cw_kn': raw_cw,
            }
            line_results.append(line_result)
            previous = line_peaks.get(line['axis_coordinate_m'])
            if not previous or raw_cw > previous['raw_cw_kn']:
                line_peaks[line['axis_coordinate_m']] = line_result

        combo_summaries.append({
            'load_case': combo['number'],
            'title': title,
            'line_results': line_results,
        })

    if not combo_summaries:
        result['errors'].append('No ULS combinations produced uplift at the base supports — counterweight demand could not be assessed.')
        return result

    # One-shot envelope: for each analysis line, take its worst (peak) demand across ALL ULS
    # combinations (every wind direction, not just whichever combo has the largest total), then
    # sum those peaks. The counterweight's restoring effect (CW x lever) is purely geometric and
    # applies equally regardless of load direction, so sizing to the worst case per line in a
    # single pass covers every combination at once — matching the PDF's one-shot hand calculation
    # instead of resolving one governing combo, rerunning, and finding another one behind it.
    analysis_lines = sorted(line_peaks.values(), key=lambda row: row['axis_coordinate_m'])
    raw_sum_kn = sum(row['raw_cw_kn'] for row in analysis_lines)

    if not analysis_lines or raw_sum_kn <= 0.001:
        # No uplift left in this STAAD run — this is expected once the resolved counterweight
        # has been applied to DL and the model rerun. The design calculation itself must not be
        # recomputed from this (now-stabilised) state, since there is no more uplift left to
        # derive it from. Re-display the snapshot captured the last time real uplift was found,
        # so the report keeps showing the calculation that the adopted counterweight is based on.
        snapshot = _load_counterweight_snapshot(project)
        if snapshot:
            snapshot['message'] = (
                'Counterweight resolved — the current STAAD run (with the adopted counterweight applied to '
                'DL) shows no residual uplift at any base node. The calculation below is the design snapshot '
                'from the run that established the adopted counterweight.'
            )
            return snapshot
        result.update({
            'valid': True,
            'has_demand': False,
            'message': 'No counterweight demand found — base reactions show no uplift under any ULS combination.',
        })
        return result

    total_kn = raw_sum_kn * safety_factor

    # Round the total up to a practical kentledge figure (nearest 0.5 t), the way the PDF adopts a
    # round practical tonnage rather than an odd decimal.
    design_tonnes = math.ceil((total_kn / 9.81) * 2) / 2
    design_kn = design_tonnes * 9.81

    distribution = _counterweight_grid_distribution(
        structural,
        polygon,
        result['zone_elevation_m'],
        area,
        design_kn,
    )
    if not distribution:
        result['errors'].append('No complete horizontal member grid was found within the counterweight zone for a reliable UDL proposal.')
        return result

    labelled_lines = [
        {
            **row,
            'label': _analysis_line_label(i),
            'terms': [
                {
                    'node': term['node'],
                    'uplift_kn': round(term['uplift_kn'], 3),
                    'arm_m': round(term['arm_m'], 3),
                }
                for term in row['terms']
            ],
            'terms_sum_kn': round(row['terms_sum_kn'], 3),
            'raw_cw_kn': round(row['raw_cw_kn'], 3),
        }
        for i, row in enumerate(analysis_lines)
    ]

    max_anchor_tension_kn = abs(min(current_min or 0.0, 0.0))

    result.update({
        'has_demand': True,
        'safety_factor': round(safety_factor, 3),
        'max_anchor_tension_kn': round(max_anchor_tension_kn, 3),
        'current_governing_load_case': current_governing['load_case'] if current_governing else '',
        'current_governing_title': current_governing['title'] if current_governing else '',
        'current_governing_node': current_governing['node'] if current_governing else '',
        'current_min_fy_kn': round(current_min or 0.0, 3),
        'raw_sum_kn': round(raw_sum_kn, 3),
        'required_design_kn': round(total_kn, 3),
        'total_kn': round(total_kn, 3),
        'minimum_counterweight_kn': round(design_kn, 3),
        'minimum_counterweight_tonnes': round(design_tonnes, 3),
        'pressure_kn_m2': round(design_kn / area, 3),
        'cw_lever_m': round(cw_lever, 3),
        'pivot_nodes': pivot_info['pivot_nodes'],
        'pivot_axis': pivot_axis,
        'normal_axis': normal_axis,
        'pivot_normal_m': round(pivot_normal, 3),
        'pivot_start_m': round(pivot_info['pivot_start_m'], 3),
        'pivot_end_m': round(pivot_info['pivot_end_m'], 3),
        'cw_centroid_normal_m': round(pivot_info['cw_centroid_normal_m'], 3),
        'analysis_line_rows': labelled_lines,
        'distribution_axis': distribution['axis'],
        'distribution_rows': distribution['rows'],
        'distributed_area_m2': distribution['distributed_area_m2'],
        'total_distributed_kn': distribution['total_distributed_kn'],
        'recommended_staad_lines': [
            'MEMBER LOAD',
            *[
                f"{' '.join(str(member) for member in row['member_ids'])} UNI GY -{row['line_load_kn_m']:.3f}"
                for row in distribution['rows']
            ],
        ],
    })
    result['diagrams'] = [
        {'label': row['label'], 'svg': _counterweight_line_diagram_svg(row, cw_lever)}
        for row in labelled_lines
    ]
    _save_counterweight_snapshot(project, result)
    return result


def _brief_description(project, structural, structure_above_ground):
    purpose = str(project.get("PURPOSE") or "the intended work activity").strip()
    scaffold_type = str(project.get("SCAFFOLD_TYPE") or "").strip()
    location_text = str(project.get("LOCATION") or "").strip()

    equipment_bits = []
    if str(project.get("EQUIPMENT_NAME") or "").strip():
        equipment_bits.append(str(project["EQUIPMENT_NAME"]).strip())
    equipment_tag = str(project.get("EQUIPMENT_TAG") or "").strip()
    line_number = str(project.get("LINE_NUMBER") or "").strip()
    if equipment_tag:
        equipment_bits.append(f"equipment tag {equipment_tag}")
    elif line_number:
        equipment_bits.append(f"line number {line_number}")
    equipment_text = ""
    if equipment_bits:
        equipment_text = " of the " + ", ".join(equipment_bits)

    work_order = str(project.get("WORK_ORDER") or "").strip()
    work_order_text = f" under work order {work_order}" if work_order else ""
    location_sentence = f" at {location_text}" if location_text else ""
    height_sentence = f" The structure is {structure_above_ground}m above ground level." if structure_above_ground else ""

    has_platforms = any(
        c.get('category') == 'platform_live'
        for c in structural.get('load_cases', [])
    )
    has_ties = bool(structural.get('supports', {}).get('tie_nodes'))

    components = ["standards", "ledgers", "transoms", "bracing"]
    if has_platforms:
        components.append("platforms")
    if has_ties:
        components.append("support/tie arrangements")

    if len(components) > 1:
        component_text = ", ".join(components[:-1]) + ", and " + components[-1]
    else:
        component_text = components[0]

    if scaffold_type:
        article = _indefinite_article(scaffold_type)
        opening = f"This document describes the structural design of {article} {scaffold_type} scaffold required for "
    else:
        opening = "This document describes the structural design of a scaffold required for "

    return (
        f"{opening}"
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


def _detect_platform_quads(structural):
    """Detect boarded platform rectangles from LL GY transoms.

    Each loaded transom defines the full strip it supports.  Z-spanning transoms
    at different X positions that share the same Z-range form one front/back
    strip.  X-spanning transoms at different Z positions sharing the same X-range
    form a side strip.  The bounding rectangle of each group becomes a quad.
    """
    import math
    load_cases = structural.get('load_cases', [])
    members    = structural.get('members', {})
    nodes      = structural.get('geometry', {}).get('nodes', {})

    ll_member_ids = set()
    for case in load_cases:
        if case.get('category') == 'platform_live':
            for udl in case.get('member_udls', []):
                if udl.get('direction', '').upper() == 'Y':
                    for mid in udl.get('members', []):
                        ll_member_ids.add(int(mid))

    if not ll_member_ids:
        return []

    # Classify each horizontal LL member by Y-level and span direction
    y_z_strips = {}   # ylevel -> {(z_min, z_max): [x_pos, ...]}  Z-spanning transoms
    y_x_strips = {}   # ylevel -> {(x_min, x_max): [z_pos, ...]}  X-spanning transoms

    for mid in ll_member_ids:
        mem = members.get(mid)
        if not mem:
            continue
        j1, j2 = mem.get('j1'), mem.get('j2')
        c1, c2 = nodes.get(j1), nodes.get(j2)
        if not c1 or not c2:
            continue
        y1, y2 = round(c1[1], 1), round(c2[1], 1)
        if abs(y1 - y2) > 0.1:
            continue
        ylevel = round((y1 + y2) / 2, 1)
        x1, z1, x2, z2 = c1[0], c1[2], c2[0], c2[2]
        dx, dz = abs(x2 - x1), abs(z2 - z1)

        if dz > dx:  # Z-spanning transom
            key = (round(min(z1, z2), 2), round(max(z1, z2), 2))
            y_z_strips.setdefault(ylevel, {}).setdefault(key, []).append(round((x1 + x2) / 2, 2))
        elif dx > dz:  # X-spanning transom
            key = (round(min(x1, x2), 2), round(max(x1, x2), 2))
            y_x_strips.setdefault(ylevel, {}).setdefault(key, []).append(round((z1 + z2) / 2, 2))

    quads = []
    for ylevel in set(y_z_strips) | set(y_x_strips):
        # Node lookup: rounded (x, z) → node id
        node_xz = {}
        for nid, coord in nodes.items():
            if abs(coord[1] - ylevel) < 0.15:
                node_xz[(round(coord[0], 1), round(coord[2], 1))] = nid

        # Z-spanning groups → front/back strips
        for (z_min, z_max), x_positions in (y_z_strips.get(ylevel) or {}).items():
            x0, x1_ = round(min(x_positions), 1), round(max(x_positions), 1)
            z0, z1_ = round(z_min, 1), round(z_max, 1)
            ns = [node_xz.get((x0, z0)), node_xz.get((x1_, z0)),
                  node_xz.get((x1_, z1_)), node_xz.get((x0, z1_))]
            if all(n is not None for n in ns) and len(set(ns)) == 4:
                quads.append(ns)

        # X-spanning groups → side strips
        for (x_min, x_max), z_positions in (y_x_strips.get(ylevel) or {}).items():
            z0, z1_ = round(min(z_positions), 1), round(max(z_positions), 1)
            x0, x1_ = round(x_min, 1), round(x_max, 1)
            ns = [node_xz.get((x0, z0)), node_xz.get((x1_, z0)),
                  node_xz.get((x1_, z1_)), node_xz.get((x0, z1_))]
            if all(n is not None for n in ns) and len(set(ns)) == 4:
                quads.append(ns)

    # Sort each quad's nodes CCW by angle from centroid
    ordered = []
    for quad in quads:
        xz = [nodes[n] for n in quad]
        cx = sum(c[0] for c in xz) / 4
        cz = sum(c[2] for c in xz) / 4
        angles = [math.atan2(c[2] - cz, c[0] - cx) for c in xz]
        ordered.append([n for _, n in sorted(zip(angles, quad))])

    return ordered


def _write_platforms_txt(structural):
    quads = _detect_platform_quads(structural)
    platforms_path = RENDERER_DIR / "platforms.txt"
    if not quads:
        print("  Platforms : no LL quads detected; keeping existing platforms.txt")
        return
    try:
        lines = ["#BOARDED_PLATFORMS:"] + [','.join(str(n) for n in q) for q in quads]
        platforms_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f"  Platforms : auto-detected {len(quads)} quad(s) -> platforms.txt")
    except Exception as exc:
        print(f"  [WARN] Could not write platforms.txt: {exc}")


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

    platforms = RENDERER_DIR / "platforms.txt"
    try:
        has_platforms = platforms.exists() and platforms.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        has_platforms = False
    if has_platforms:
        command.extend(["--platforms", platforms.resolve()])

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
    _run_command("drawing generator", command, DRAWING_DIR, timeout=240)
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


def make_install_notes(structural, project=None):
    project = project or {}
    g  = structural['geometry']
    s  = structural['supports']
    W, D, H = g['width'], g['depth'], g['height']
    kicker  = g['kicker_lift']
    mids    = g['mid_lifts']
    tie_h   = s.get('tie_heights', [H])
    tie_n   = s.get('tie_nodes', [])
    scaffold_type = str(project.get('SCAFFOLD_TYPE', 'scaffold')).strip()
    scaffold_key = scaffold_type.upper()
    purpose = str(project.get('PURPOSE', 'the approved task')).strip() or 'the approved task'
    hanging = _is_hanging_scaffold(scaffold_type)
    cantilever = 'CANTILEVER' in scaffold_key
    birdcage = 'BIRDCAGE' in scaffold_key
    tower = 'TOWER' in scaffold_key
    composite = 'COMPOSITE' in scaffold_key
    scaffold_config_text = f"the {scaffold_type} scaffold" if scaffold_type else "the scaffold"

    notes = [
        "The scaffold working drawings and purpose of the scaffold must be reviewed and "
        "discussed by all personnel involved prior to execution.",
        f"Confirm that {scaffold_config_text} configuration matches the approved drawing "
        f"and is suitable for {purpose}.",
        "The work vicinity must be barricaded and appropriate signage placed at all access points.",
        "All scaffolders must wear complete PPE in accordance with NLNG work-at-height regulations.",
        "A valid work permit must be obtained, discussed, and signed before erection commences.",
        "Scaffold erection must be carried out in strict accordance with NASC guidance and site "
        "safety procedures.",
    ]

    if hanging:
        notes += [
            "Verify all suspension points, support steelwork, clamps, anchors, and hangers against "
            "the approved drawing before any scaffold load is applied.",
            f"Assemble the hanging scaffold support frame and platform zone to the approximate "
            f"overall envelope of {W:.1f}m x {D:.1f}m x {H:.1f}m shown on the drawing.",
            "Install hangers, ledgers, transoms, platform boards, guardrails, toe boards, and "
            "bracing progressively from the secured suspension/support points.",
            "Do not load the platform until all suspension connections and secondary restraints "
            "have been inspected and signed off.",
        ]
    elif cantilever:
        notes += [
            "Install and secure cantilever support members, needles, anchors, ties, and back-span "
            "restraints exactly as shown on the approved drawing before building the working platform.",
            f"Build the scaffold frame to the approved envelope of {W:.1f}m x {D:.1f}m x {H:.1f}m, "
            "checking level, plumb, and cantilever projection at each lift.",
            "Install bracing, ledgers, transoms, platform boards, guardrails, and toe boards "
            "progressively, maintaining all specified ties and restraints.",
        ]
    else:
        if composite:
            notes.append(
                "Set out each scaffold zone shown on the composite drawing and confirm interface "
                "points between the combined scaffold types before erection proceeds."
            )
        elif birdcage:
            notes.append(
                "Set out the birdcage grid, base plates, standards, and bay spacing in both plan "
                "directions in accordance with the approved working drawing."
            )
        elif tower:
            notes.append(
                "Set out and level the tower scaffold base plates/outriggers as required by the "
                "approved working drawing before erecting the first lift."
            )
        else:
            notes.append(
                "Set out and level the scaffold base plates and sole boards in accordance with "
                "the approved working drawing."
            )

        notes += [
            f"Confirm the scaffold footprint/envelope is approximately {W:.1f}m x {D:.1f}m x {H:.1f}m "
            "or as otherwise dimensioned on the approved drawing.",
            f"Erect scaffold tube standards (48.3 x 3.6 mm), ledgers, and transoms progressively "
            f"from the base, checking plumb and level in both axes before proceeding to the next lift.",
            f"Install the lower horizontal ledgers and transoms at the kicker lift height "
            f"({kicker:.3f}m) to form the first stable frame.",
        ]

    for ml in mids:
        notes.append(
            f"Install mid-level horizontal ledgers and transoms at {ml:.1f}m height in "
            f"accordance with the working drawing."
        )

    notes += [
        "Install all plan, face, and longitudinal bracing shown on the approved drawing to provide "
        "sway resistance in both principal directions.",
        "Install platform boards, guardrails, mid-rails, toe boards, access arrangements, and any "
        "handrail load-resisting members required by the design.",
        "Tighten and torque-check all load-bearing couplers and support connections before the "
        "scaffold is released for inspection.",
    ]

    if tie_n:
        tie_str = ' and '.join(f'{h:.1f}m' for h in tie_h)
        notes.append(
            f"Gravlock or box-tie the scaffold structure to the existing structure at all "
            f"indicated tie points at {tie_str} height as shown on the working drawing."
        )

    notes += [
        "The scaffold structure must be inspected and tagged by a competent advance scaffold "
        "inspector after erection and before use.",
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

    print("=== Scaffold Report Generator ===\n")

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
        _write_platforms_txt(structural)
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
        'load_platform_live', 'load_handrail_x', 'load_handrail_z',
        'load_wind_x', 'load_wind_z',
        'load_counterweight',
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
    hl   = structural.get('handrail_loads', {})
    geom = structural['geometry']
    plan_length = max(geom['width'], geom['depth'])
    plan_width = min(geom['width'], geom['depth'])
    structural['dimension_display'] = (
        f"{_format_number(plan_length)}m x {_format_number(plan_width)}m x {_format_number(geom['height'])}m"
    )
    platform_live_workings, swl_kn_m2 = _platform_live_workings(project, structural)
    structural['platform_live_workings'] = platform_live_workings
    structural['swl_kn_m2'] = swl_kn_m2
    structural['swl_display'] = _format_load_value(swl_kn_m2)
    structural['swl_load_class'] = _load_class_for_intensity(swl_kn_m2)
    structural['brief_description'] = _brief_description(
        project,
        structural,
        _format_number(structure_above_ground),
    )
    show_assurance_note = _bool_setting(
        _project_value(project, 'CATEGORY_1_ASSURANCE_NOTE', 'SHOW_CATEGORY_1_NOTE', 'ASSURANCE_NOTE'),
        False
    )
    # Signature table: a role row only appears when it has a name, and the ID
    # column only appears at all when at least one of the rows actually being
    # shown has an ID to display.
    signatory_rows = [
        (role, pid, name)
        for role, pid, name in (
            ('DESIGNED BY', project.get('DESIGNED_BY_ID'), project.get('DESIGNED_BY_NAME')),
            ('VERIFIED BY', project.get('VERIFIED_BY_ID'), project.get('VERIFIED_BY_NAME')),
            ('CHECKED BY',  project.get('CHECKED_BY_ID'),  project.get('CHECKED_BY_NAME')),
            ('REVIEWED BY', project.get('REVIEWED_BY_ID'), project.get('REVIEWED_BY_NAME')),
            ('REVIEWED & APPROVED BY', project.get('APPROVED_BY_ID'), project.get('APPROVED_BY_NAME')),
        )
        if str(name or '').strip()
    ]
    has_any_signatory_id = any(str(pid or '').strip() for _, pid, _ in signatory_rows)
    # Frictional resistance only means something when the model actually has a
    # KFX/KFZ spring base support ("FIXED BUT MX MY MZ KFX ... KFZ ..."); when
    # every support is a plain, fully-fixed support (no friction spring defined),
    # the calc would just be showing the parser's meaningless fallback default -
    # so hide it regardless of SCAFFOLD_TYPE.
    show_frictional_resistance = bool(structural.get('supports', {}).get('base_nodes'))
    has_scaffold_type = bool(str(project.get('SCAFFOLD_TYPE') or '').strip())
    has_handrail = bool(hl.get('has_x') or hl.get('has_z'))
    has_ties = bool(structural.get('supports', {}).get('tie_nodes'))
    has_wind = bool(wl.get('has_wind'))
    show_tie_reactions = _bool_setting(project.get('SHOW_TIE_REACTIONS'), False)

    # Cover page tie force display — sum (default) or worst single node
    sr = structural.get('support_reactions', {})
    worst_tie     = sr.get('worst_individual_tie')
    net_governing = sr.get('net_global', {}).get('governing')
    tie_display_mode = (project.get('TIE_DISPLAY') or 'sum').strip().lower()
    if tie_display_mode not in ('sum', 'worst'):
        tie_display_mode = 'sum'
    # Legacy scalar variables kept so template fallback still works
    if tie_display_mode == 'worst' and worst_tie:
        tie_sum_fx = worst_tie['max_fx']
        tie_sum_fz = worst_tie['max_fz']
    elif net_governing:
        tie_sum_fx = net_governing['total_x']
        tie_sum_fz = net_governing['total_z']
    else:
        tie_sum_fx = worst_tie['max_fx'] if worst_tie else None
        tie_sum_fz = worst_tie['max_fz'] if worst_tie else None

    # STAAD-output source tags: TIE_FORCE_FX/FZ/FY are a manual design override (per the
    # project_info.txt comment), so once set the cover-page value no longer represents a
    # direct STAAD .out reading and must not be tagged as such.
    tie_fx_from_out = _optional_float(project.get('TIE_FORCE_FX')) is None
    tie_fz_from_out = _optional_float(project.get('TIE_FORCE_FZ')) is None
    tie_fy_from_out = _optional_float(project.get('TIE_FORCE_FY')) is None

    if _optional_float(project.get('TIE_FORCE_FX')) is not None:
        tie_sum_fx = _optional_float(project.get('TIE_FORCE_FX'))
    if _optional_float(project.get('TIE_FORCE_FZ')) is not None:
        tie_sum_fz = _optional_float(project.get('TIE_FORCE_FZ'))

    is_hanging = 'HANGING' in str(project.get('SCAFFOLD_TYPE') or '').upper()
    # A plain FIXED support (as opposed to "FIXED BUT ...") always carries a vertical (FY)
    # reaction, so the Total Vertical Load display applies whenever the STAAD model has one
    # — not just for Hanging scaffolds.
    has_fixed_supports = bool(structural.get('supports', {}).get('fixed_nodes'))
    tie_sum_fy = None
    if is_hanging or has_fixed_supports:
        fy_governing = sr.get('net_fy_at_fixed', {}).get('governing')
        if fy_governing:
            tie_sum_fy = fy_governing['total_y']
    if _optional_float(project.get('TIE_FORCE_FY')) is not None:
        tie_sum_fy = _optional_float(project.get('TIE_FORCE_FY'))

    # -- Deflection L: look up member length from STAAD geometry -----------------
    members_dict = structural.get('members', {})
    d = structural['displacements']

    def _span_from_node_auto(node_id, fallback_mm):
        """Longest member connected to the critical-displacement node."""
        if node_id:
            lengths = [m['length_mm'] for m in members_dict.values()
                       if m.get('j1') == node_id or m.get('j2') == node_id]
            if lengths:
                return max(lengths)
        return fallback_mm

    def _member_length_mm(member_key, fallback_mm):
        try:
            mid = int(project.get(member_key, 0) or 0)
            if mid and mid in members_dict:
                return members_dict[mid]['length_mm']
        except (ValueError, TypeError):
            pass
        return fallback_mm

    vert_span_mm  = _member_length_mm('MAX_VERT_MEMBER',
                        _span_from_node_auto(d.get('max_vertical_node'),  geom['width'] * 1000))
    horiz_span_mm = _member_length_mm('MAX_HORIZ_MEMBER',
                        _span_from_node_auto(d.get('max_horizontal_node'), geom['depth'] * 1000))
    vert_allow    = round(vert_span_mm  / 100, 1)
    horiz_allow   = round(horiz_span_mm / 200, 1)

    # Member details for report display
    def _member_info(member_key, auto_node=None):
        try:
            mid = int(project.get(member_key, 0) or 0)
            if mid and mid in members_dict:
                return {'id': mid, 'length_mm': members_dict[mid]['length_mm']}
        except:
            pass
        if auto_node:
            connected = [(mid, m['length_mm']) for mid, m in members_dict.items()
                         if m.get('j1') == auto_node or m.get('j2') == auto_node]
            if connected:
                best_mid, best_len = max(connected, key=lambda x: x[1])
                return {'id': best_mid, 'length_mm': best_len}
        return None

    vert_member_info  = _member_info('MAX_VERT_MEMBER',  d.get('max_vertical_node'))
    horiz_member_info = _member_info('MAX_HORIZ_MEMBER', d.get('max_horizontal_node'))

    total_horiz_x = round(wl.get('total_x', 0.0) + (hl.get('total_x', 0.0) if has_handrail else 0.0), 3)
    total_horiz_z = round(wl.get('total_z', 0.0) + (hl.get('total_z', 0.0) if has_handrail else 0.0), 3)
    vertical_live_rows = ld.get('platform_live_case_totals', [])
    vertical_live_total = round(max((row.get('total_y', 0.0) for row in vertical_live_rows), default=0.0), 3)
    counterweight = _counterweight_design(project, structural)
    if counterweight.get('enabled'):
        if counterweight.get('valid') and not counterweight.get('errors') and counterweight.get('has_demand'):
            if counterweight.get('message'):
                print(f"  Counterweight: {counterweight['message']}")
            print(f"  Counterweight Load Calculation — {len(counterweight['analysis_line_rows'])} analysis line(s):")
            for row in counterweight['analysis_line_rows']:
                terms_str = ' + '.join(f"{t['uplift_kn']:.3f}x{t['arm_m']:.2f}" for t in row['terms'])
                print(
                    f"    Analysis {row['label']} ({row['line_label']}, LC {row['governing_load_case']}): "
                    f"{terms_str} = {row['terms_sum_kn']:.3f}"
                )
                print(f"      CW = {row['terms_sum_kn']:.3f} / {counterweight['cw_lever_m']:.3f} = {row['raw_cw_kn']:.3f} kN")
            line_sum = ' + '.join(f"{row['raw_cw_kn']:.3f}" for row in counterweight['analysis_line_rows'])
            print(f"    Sum counter weight {', '.join(row['label'] for row in counterweight['analysis_line_rows'])} = {line_sum} = {counterweight['raw_sum_kn']:.3f} kN")
            print(f"    Use factor of safety of {counterweight['safety_factor']:g}")
            print(f"    Total counterweight = {counterweight['raw_sum_kn']:.3f} x {counterweight['safety_factor']:g} = {counterweight['total_kn']:.3f} kN")
            print(f"    Use counterweight of {counterweight['minimum_counterweight_tonnes']:.3f} tonnes ({counterweight['minimum_counterweight_kn']:.3f} kN)")
            if counterweight.get('recommended_staad_lines'):
                print("  Resolved into member loads — add under the DL load case (LOAD 1) for the final rerun:")
                for line in counterweight['recommended_staad_lines']:
                    print(f"    {line}")
        elif counterweight.get('valid') and not counterweight.get('errors'):
            print("  Counterweight: no demand found — base reactions show no uplift under any ULS combination.")
        elif counterweight.get('errors'):
            print("  [WARN] Counterweight: " + ' '.join(counterweight['errors']))

    net_global_reaction_summary = (
        structural.get('support_reactions', {})
        .get('net_global', {})
        .get('governing')
    )

    # -- Connection stability: max axial in HORIZONTAL members only (coupler slipping) --
    cc = structural['code_check']
    def _float(val, fallback):
        try: return float(val) if val else fallback
        except: return fallback

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

    # Prefer the real per-member, per-load-case axial force (from a STAAD 'PRINT MEMBER
    # FORCES' table) over the STAAD steel code-check block: the code-check axial is tied
    # to whichever load case governs that member's bending/combined-stress UC ratio, not
    # necessarily the load case with the largest raw axial force - which is what actually
    # matters for a coupler slipping check. Falls back to the code-check block's axial for
    # projects that don't have a member-forces table.
    member_forces = structural.get('member_forces') or {}
    combos = structural.get('load_combinations', [])

    def _combo_basis(combo):
        """ULS if the combo title says so, else SLS; falls back to inspecting the load
        factors (ULS combos here are always 1.5x, SLS combos always 1.0x) for projects
        whose combo titles don't carry an explicit ULS/SLS prefix."""
        title = str(combo.get('title', '')).strip().upper()
        if title.startswith('ULS'):
            return 'ULS'
        if title.startswith('SLS'):
            return 'SLS'
        factors = combo.get('factors', [])
        if factors and all(abs(abs(f) - 1.0) < 0.01 for _, f in factors):
            return 'SLS'
        return 'ULS'

    uls_lc_numbers = {c['number'] for c in combos if _combo_basis(c) == 'ULS'}
    sls_lc_numbers = {c['number'] for c in combos if _combo_basis(c) == 'SLS'}

    def _peak_axial(per_load, lc_numbers):
        """(abs_axial, signed_axial, load_case) of the largest-magnitude axial among
        the given load cases, or None if none apply."""
        candidates = [(abs(v), v, lc) for lc, v in per_load.items() if lc in lc_numbers]
        return max(candidates, key=lambda t: t[0]) if candidates else None

    axial_source = 'member_forces' if member_forces and uls_lc_numbers else 'code_check'

    if axial_source == 'member_forces':
        uls_rows = []
        for mid, per_load in member_forces.items():
            if not _is_horizontal(mid):
                continue
            peak = _peak_axial(per_load, uls_lc_numbers)
            if peak is None:
                continue
            abs_v, signed_v, lc = peak
            uls_rows.append({'member': mid, 'axial': round(abs_v, 3), 'type': 'C' if signed_v < 0 else 'T', 'lc': lc})
        uls_rows.sort(key=lambda r: r['axial'], reverse=True)

        if uls_rows:
            best = uls_rows[0]
            auto_axial, auto_axial_member, auto_axial_type = best['axial'], best['member'], best['type']
            top_axial_members = uls_rows[:30]
        else:
            axial_source = 'code_check'  # no horizontal members had member-forces data

    if axial_source == 'code_check':
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
        top_axial_members = sorted(horiz_members if horiz_members else cc.get('members', []),
                                   key=lambda m: m['axial'], reverse=True)[:30]

    # Check ULS first; if the coupler class fails under ULS, fall back to SLS (unfactored,
    # gamma=1.0 — see Load Combinations legend). This is a fallback verification basis, not
    # a substitute UC check — the Status/Clause/UC Ratio columns are ULS-specific and are
    # not shown for the SLS view.
    connection_basis = 'ULS'
    max_axial        = auto_axial
    max_axial_member = str(auto_axial_member or '')
    max_axial_type   = auto_axial_type
    connection_class = _connection_class(max_axial)

    if connection_class['status'] == 'FAIL':
        connection_basis = 'SLS'
        if axial_source == 'member_forces':
            # Look up the SAME governing member's real SLS-combo axial directly - exact,
            # no unfactoring needed.
            peak = _peak_axial(member_forces.get(auto_axial_member, {}), sls_lc_numbers)
            if peak is not None:
                abs_v, signed_v, lc = peak
                max_axial, max_axial_type = round(abs_v, 3), 'C' if signed_v < 0 else 'T'

            sls_rows = []
            for row in top_axial_members:
                peak = _peak_axial(member_forces.get(row['member'], {}), sls_lc_numbers)
                if peak is not None:
                    abs_v, signed_v, lc = peak
                    sls_rows.append({'member': row['member'], 'axial': round(abs_v, 3),
                                      'type': 'C' if signed_v < 0 else 'T', 'lc': lc})
                else:
                    sls_rows.append({**row, 'axial': round(row['axial'] / 1.5, 3)})
            sls_rows.sort(key=lambda r: r['axial'], reverse=True)
            top_axial_members = sls_rows
        else:
            # Legacy path (no member-forces table): SLS force = ULS force / 1.5, since
            # every ULS combo here is the same SLS combo at 1.5x - an exact unfactoring.
            max_axial = round(auto_axial / 1.5, 3)
            top_axial_members = [
                {**m, 'axial': round(m['axial'] / 1.5, 3)}
                for m in top_axial_members
            ]
        connection_class = _connection_class(max_axial)

    # -- Deflection values (auto from .out file; project_info keys are optional overrides) --
    max_vert_mm   = _float(project.get('MAX_VERT_DISP_MM'),  d['max_vertical_mm'])
    max_vert_lc   = project.get('MAX_VERT_DISP_LC',  '')  or str(d['max_vertical_lc'])
    max_horiz_mm  = _float(project.get('MAX_HORIZ_DISP_MM'), d['max_horizontal_mm'])
    max_horiz_lc  = project.get('MAX_HORIZ_DISP_LC', '')  or str(d['max_horizontal_lc'])

    install_notes = make_install_notes(structural, project)
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
        vertical_live_total = vertical_live_total,
        counterweight = counterweight,
        net_global_reaction_summary = net_global_reaction_summary,
        has_handrail = has_handrail,
        has_ties = has_ties,
        has_wind = has_wind,
        has_scaffold_type = has_scaffold_type,
        show_assurance_note = show_assurance_note,
        signatory_rows = signatory_rows,
        has_any_signatory_id = has_any_signatory_id,
        show_frictional_resistance = show_frictional_resistance,
        show_tie_reactions = show_tie_reactions,
        tie_sum_fx        = tie_sum_fx,
        tie_sum_fz        = tie_sum_fz,
        tie_sum_fy        = tie_sum_fy,
        tie_fx_from_out   = tie_fx_from_out,
        tie_fz_from_out   = tie_fz_from_out,
        tie_fy_from_out   = tie_fy_from_out,
        is_hanging        = is_hanging,
        has_fixed_supports = has_fixed_supports,
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
        axial_source      = axial_source,
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
