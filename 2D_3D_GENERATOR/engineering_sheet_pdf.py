from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
import math
import re
import struct
import zlib


MM_TO_PT = 72.0 / 25.4
A4_LANDSCAPE_MM = (297.0, 210.0)
A3_LANDSCAPE_MM = (420.0, 297.0)
DEFAULT_CONFIG_FILE = "title_block_values.txt"
DEFAULT_PDF_DIR = "pdf_output"


DEFAULT_TITLE_BLOCK_VALUES = """# Engineering sheet title block values.
# Edit the values on the right side. Blank date uses today's date.

drawing_number = PMS-WA-ARCO-003
project = SCAFFOLDING WORKS
drawing_title = SCAFFOLD GENERAL ARRANGEMENT
client = 
location = 
company = 
scale = NTS
revision = 0
date = 
drawn_by = 
reviewed_by = 
approved_by = 

# Logos can be local files in the project root or image URLs.
# PNG, JPG, and JPEG are supported. Local root files are tried before URLs.
nlng_logo = nlng_logo.png
nlng_logo_url = 
company_logo = company_logo.png
company_logo_url = 

# PDF output folder, relative to the project root unless absolute.
pdf_output_dir = pdf_output
"""


def ensure_title_block_template(path: Path) -> None:
    if not path.exists():
        path.write_text(DEFAULT_TITLE_BLOCK_VALUES, encoding="utf-8")


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def load_title_block_values(path: Path) -> dict[str, str]:
    ensure_title_block_template(path)
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        values[_key(key)] = value.strip().strip('"').strip("'")
    return values


def _value(values: dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        found = values.get(_key(key), "")
        if found.strip():
            return found.strip()
    return default


def _safe_filename(text: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text.strip())
    clean = re.sub(r"\s+", "-", clean)
    clean = re.sub(r"-{2,}", "-", clean).strip("-.")
    return clean or "drawing"


def _pdf_escape(text: str) -> str:
    safe = []
    for char in str(text):
        code = ord(char)
        if char == "\\":
            safe.append("\\\\")
        elif char == "(":
            safe.append("\\(")
        elif char == ")":
            safe.append("\\)")
        elif char in "\r\n\t":
            safe.append(" ")
        elif 32 <= code <= 126:
            safe.append(char)
        else:
            safe.append("?")
    return "".join(safe)


def _num(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def _pt(value_mm: float) -> float:
    return value_mm * MM_TO_PT


class PdfCanvas:
    def __init__(self, width_mm: float, height_mm: float):
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.commands: list[str] = []
        self.images: list[dict[str, object]] = []

    def line(
        self,
        p1: tuple[float, float],
        p2: tuple[float, float],
        color=(0.0, 0.0, 0.0),
        width: float = 0.2,
        dashed: bool = False,
    ) -> None:
        self._stroke_style(color, width, dashed)
        self.commands.append(
            f"{_num(_pt(p1[0]))} {_num(_pt(p1[1]))} m "
            f"{_num(_pt(p2[0]))} {_num(_pt(p2[1]))} l S\n"
        )
        if dashed:
            self.commands.append("[] 0 d\n")

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        color=(0.0, 0.0, 0.0),
        width: float = 0.2,
    ) -> None:
        self._stroke_style(color, width, False)
        self.commands.append(
            f"{_num(_pt(x))} {_num(_pt(y))} {_num(_pt(w))} {_num(_pt(h))} re S\n"
        )

    def circle(
        self,
        center: tuple[float, float],
        radius: float,
        color=(0.0, 0.0, 0.0),
        width: float = 0.2,
    ) -> None:
        cx, cy = center
        k = 0.5522847498
        r = radius
        self._stroke_style(color, width, False)
        points = [
            (cx + r, cy),
            (cx + r, cy + k * r, cx + k * r, cy + r, cx, cy + r),
            (cx - k * r, cy + r, cx - r, cy + k * r, cx - r, cy),
            (cx - r, cy - k * r, cx - k * r, cy - r, cx, cy - r),
            (cx + k * r, cy - r, cx + r, cy - k * r, cx + r, cy),
        ]
        self.commands.append(f"{_num(_pt(points[0][0]))} {_num(_pt(points[0][1]))} m\n")
        for item in points[1:]:
            x1, y1, x2, y2, x3, y3 = item
            self.commands.append(
                f"{_num(_pt(x1))} {_num(_pt(y1))} "
                f"{_num(_pt(x2))} {_num(_pt(y2))} "
                f"{_num(_pt(x3))} {_num(_pt(y3))} c\n"
            )
        self.commands.append("S\n")

    def text(
        self,
        text: str,
        x: float,
        y: float,
        size: float = 2.5,
        font: str = "F1",
        color=(0.0, 0.0, 0.0),
        align: str = "left",
        rotation: float = 0.0,
    ) -> None:
        text = str(text)
        width = _text_width_mm(text, size, font == "F2")
        if align == "center":
            x -= width / 2.0
        elif align == "right":
            x -= width

        angle = math.radians(rotation)
        a = math.cos(angle)
        b = math.sin(angle)
        c = -math.sin(angle)
        d = math.cos(angle)
        e = _pt(x)
        f = _pt(y)
        r, g, bl = color
        self.commands.append(
            "BT "
            f"{_num(r)} {_num(g)} {_num(bl)} rg "
            f"/{font} {_num(_pt(size))} Tf "
            f"{_num(a)} {_num(b)} {_num(c)} {_num(d)} {_num(e)} {_num(f)} Tm "
            f"({_pdf_escape(text)}) Tj ET\n"
        )

    def fit_text(
        self,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        label: bool = False,
        bold: bool = False,
        align: str = "left",
    ) -> None:
        text = str(text)
        max_size = 1.7 if label else min(3.2, h * 0.45)
        min_size = 1.0 if label else 1.25
        font = "F2" if bold else "F1"
        size = max_size
        if text:
            estimated = _text_width_mm(text, size, bold)
            if estimated > w:
                size = max(min_size, size * w / max(estimated, 0.01))
        drawn = text
        while drawn and _text_width_mm(drawn, size, bold) > w and size <= min_size + 0.01:
            drawn = drawn[:-2].rstrip() + "."
        baseline = y + (h - size) / 2.0 - 0.15
        tx = x
        if align == "center":
            tx = x + w / 2.0
        elif align == "right":
            tx = x + w
        self.text(drawn, tx, baseline, size=size, font=font, align=align)

    def image(self, image: dict[str, object], x: float, y: float, w: float, h: float) -> None:
        name = f"Im{len(self.images) + 1}"
        image = dict(image)
        image["name"] = name
        self.images.append(image)
        iw = float(image["width"])
        ih = float(image["height"])
        scale = min(w / iw, h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        draw_x = x + (w - draw_w) / 2.0
        draw_y = y + (h - draw_h) / 2.0
        self.commands.append(
            "q "
            f"{_num(_pt(draw_w))} 0 0 {_num(_pt(draw_h))} "
            f"{_num(_pt(draw_x))} {_num(_pt(draw_y))} cm "
            f"/{name} Do Q\n"
        )

    def _stroke_style(self, color, width: float, dashed: bool) -> None:
        r, g, b = color
        self.commands.append(f"{_num(r)} {_num(g)} {_num(b)} RG {_num(_pt(width))} w\n")
        if dashed:
            self.commands.append(f"[{_num(_pt(2.2))} {_num(_pt(1.4))}] 0 d\n")


def _text_width_mm(text: str, size: float, bold: bool = False) -> float:
    factor = 0.56 if bold else 0.52
    wide = sum(1.3 if char in "MW@#%" else 1.0 for char in str(text))
    return wide * size * factor


def _field(
    pdf: PdfCanvas,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    bold_value: bool = False,
    align: str = "left",
) -> None:
    pdf.rect(x, y, w, h, width=0.18)
    pdf.fit_text(label.upper(), x + 1.4, y + h - 3.0, w - 2.8, 2.4, label=True)
    pdf.fit_text(value, x + 1.4, y + 0.7, w - 2.8, h - 3.6, bold=bold_value, align=align)


def _layer_color(layer: str, explicit=None):
    if explicit == 1:
        return (0.85, 0.0, 0.0)
    if explicit == 5:
        return (0.0, 0.18, 0.75)
    if explicit == 6:
        return (0.85, 0.0, 0.85)
    if explicit == 8:
        return (0.45, 0.45, 0.45)
    layer = str(layer).upper()
    if layer in {"PIPES", "PIPE_ENDS", "FRAME"}:
        return (0.0, 0.18, 0.75)
    if layer in {"DIMENSION", "LEVEL_GUIDE", "LEVEL_TEXT", "GRIDLINE", "BUBBLE"}:
        return (0.80, 0.0, 0.0)
    return (0.0, 0.0, 0.0)


def _line_width(layer: str) -> float:
    layer = str(layer).upper()
    if layer in {"PIPES", "PIPE_ENDS", "FRAME"}:
        return 0.25
    if layer in {"GRIDLINE", "LEVEL_GUIDE"}:
        return 0.13
    return 0.16


def _read_jpeg_size(data: bytes) -> tuple[int, int, str] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker in {0xD8, 0xD9}:
            continue
        if i + 2 > len(data):
            break
        length = int.from_bytes(data[i : i + 2], "big")
        if length < 2 or i + length > len(data):
            break
        if marker in sof_markers and length >= 8:
            precision_at = i + 2
            height = int.from_bytes(data[precision_at + 1 : precision_at + 3], "big")
            width = int.from_bytes(data[precision_at + 3 : precision_at + 5], "big")
            components = data[precision_at + 5]
            color_space = "DeviceGray" if components == 1 else "DeviceCMYK" if components == 4 else "DeviceRGB"
            return width, height, color_space
        i += length
    return None


def _png_channels(color_type: int) -> int | None:
    return {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)


def _unfilter_png(raw: bytes, width: int, height: int, channels: int, bit_depth: int) -> bytes | None:
    if bit_depth != 8:
        return None
    stride = width * channels
    rows = []
    pos = 0
    prev = bytearray(stride)
    for _ in range(height):
        if pos >= len(raw):
            return None
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + stride])
        pos += stride
        if len(row) != stride:
            return None
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            upper_left = prev[i - channels] if i >= channels else 0
            if filter_type == 1:
                row[i] = (row[i] + left) & 0xFF
            elif filter_type == 2:
                row[i] = (row[i] + up) & 0xFF
            elif filter_type == 3:
                row[i] = (row[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                p = left + up - upper_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - upper_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else upper_left
                row[i] = (row[i] + predictor) & 0xFF
            elif filter_type != 0:
                return None
        rows.append(bytes(row))
        prev = row
    return b"".join(rows)


def _read_png_image(data: bytes) -> dict[str, object] | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    width = height = bit_depth = color_type = None
    palette: list[tuple[int, int, int]] = []
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_data = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
        elif chunk_type == b"PLTE":
            palette = [tuple(chunk_data[i:i + 3]) for i in range(0, len(chunk_data), 3)]
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type is None:
        return None
    channels = _png_channels(color_type)
    if channels is None:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    pixels = _unfilter_png(raw, width, height, channels, bit_depth)
    if pixels is None:
        return None

    if color_type == 0:
        out = pixels
        color_space = "DeviceGray"
    elif color_type == 2:
        out = pixels
        color_space = "DeviceRGB"
    elif color_type == 3:
        if not palette:
            return None
        rgb = bytearray()
        for idx in pixels:
            if idx >= len(palette):
                return None
            rgb.extend(palette[idx])
        out = bytes(rgb)
        color_space = "DeviceRGB"
    elif color_type == 4:
        gray = bytearray()
        for i in range(0, len(pixels), 2):
            value = pixels[i]
            alpha = pixels[i + 1]
            gray.append((value * alpha + 255 * (255 - alpha)) // 255)
        out = bytes(gray)
        color_space = "DeviceGray"
    elif color_type == 6:
        rgb = bytearray()
        for i in range(0, len(pixels), 4):
            alpha = pixels[i + 3]
            rgb.extend((pixels[i + c] * alpha + 255 * (255 - alpha)) // 255 for c in range(3))
        out = bytes(rgb)
        color_space = "DeviceRGB"
    else:
        return None
    compressed = zlib.compress(out)
    return {
        "data": compressed,
        "width": width,
        "height": height,
        "color_space": color_space,
        "filter": "FlateDecode",
    }


def _read_source_bytes(source: str, root_dir: Path) -> bytes | None:
    source = source.strip()
    if not source:
        return None
    if re.match(r"https?://", source, flags=re.IGNORECASE):
        try:
            request = Request(source, headers={"User-Agent": "scaffold-pdf-generator/1.0"})
            with urlopen(request, timeout=20) as response:
                return response.read()
        except Exception:
            return None
    path = Path(source)
    if not path.is_absolute():
        path = root_dir / path
    try:
        return path.read_bytes() if path.exists() else None
    except OSError:
        return None


def _load_image_from_source(source: str, root_dir: Path) -> dict[str, object] | None:
    data = _read_source_bytes(source, root_dir)
    if not data:
        return None
    png = _read_png_image(data)
    if png is not None:
        return png
    jpeg = _read_jpeg_size(data)
    if jpeg is not None:
        width, height, color_space = jpeg
        return {
            "data": data,
            "width": width,
            "height": height,
            "color_space": color_space,
            "filter": "DCTDecode",
        }
    return None


def _logo_source(values: dict[str, str], prefix: str, root_dir: Path) -> str:
    local = _value(values, f"{prefix}_logo", f"{prefix}_image", prefix)
    local_path = Path(local) if local else None
    if local_path and not local_path.is_absolute():
        local_path = root_dir / local_path
    if local_path and local_path.exists():
        return local
    defaults = {
        "nlng": ["nlng_logo.png", "nlng_logo.jpg", "nlng_logo.jpeg"],
        "company": ["company_logo.png", "company_logo.jpeg", "company_logo.jpg"],
    }
    for name in defaults.get(prefix, []):
        if (root_dir / name).exists():
            return name
    url = _value(values, f"{prefix}_logo_url", f"{prefix}_url")
    if url:
        return url
    if local:
        return local
    return ""


def _draw_title_block(
    pdf: PdfCanvas,
    values: dict[str, str],
    view_title: str,
    drawing_no: str,
    sheet_index: int,
    sheet_count: int,
    root_dir: Path,
) -> None:
    tb_x, tb_y, tb_h = 8.0, 8.0, 38.0
    tb_w = pdf.width_mm - 16.0          # 8 mm margin each side
    f = tb_w / 281.0                     # scale factor relative to A4 baseline (281 mm)
    paper_size = "A3" if pdf.width_mm > 350 else "A4"

    left_w = 126.0 * f
    mid_w = 84.0 * f
    right_w = tb_w - left_w - mid_w
    mid_x = tb_x + left_w
    right_x = mid_x + mid_w

    # scaled sub-widths inside the middle column (A4 baseline: 28, 35, 21, 56, 63)
    m28 = 28.0 * f
    m35 = 35.0 * f
    m21 = mid_w - m28 - m35             # absorb rounding so sub-widths sum to mid_w exactly
    m56 = m28 * 2
    m63 = m28 + m35

    title = _value(values, "drawing_title", "title", default="SCAFFOLD GENERAL ARRANGEMENT")
    full_title = f"{title} - {view_title.upper()}" if title.upper() not in view_title.upper() else view_title.upper()
    sheet_date = _value(values, "date", default=date.today().strftime("%d-%b-%Y")).upper()

    pdf.rect(tb_x, tb_y, tb_w, tb_h, width=0.25)
    _field(pdf, tb_x, tb_y + 25.0, left_w, 13.0, "Project", _value(values, "project", default="SCAFFOLDING WORKS"), True)
    _field(pdf, tb_x, tb_y + 12.0, left_w, 13.0, "Drawing Title", full_title, True)
    _field(pdf, tb_x, tb_y, left_w / 2, 12.0, "Client", _value(values, "client"))
    _field(pdf, tb_x + left_w / 2, tb_y, left_w / 2, 12.0, "Location", _value(values, "location"))

    _field(pdf, mid_x, tb_y + 25.0, mid_w, 13.0, "Drawing No.", drawing_no, True)
    _field(pdf, mid_x, tb_y + 13.0, m28, 12.0, "Scale", _value(values, "scale", default="NTS"), True, "center")
    _field(pdf, mid_x + m28, tb_y + 13.0, m35, 12.0, "Date", sheet_date, True, "center")
    _field(pdf, mid_x + m63, tb_y + 13.0, m21, 12.0, "Rev", _value(values, "revision", "rev", default="0"), True, "center")
    _field(pdf, mid_x, tb_y, m28, 13.0, "Drawn", _value(values, "drawn_by", "drawn"), False, "center")
    _field(pdf, mid_x + m28, tb_y, m28, 13.0, "Reviewed", _value(values, "reviewed_by", "Reviewed"), False, "center")
    _field(pdf, mid_x + m56, tb_y, mid_w - m56, 13.0, "Approved", _value(values, "approved_by", "approved"), False, "center")

    pdf.rect(right_x, tb_y + 18.0, right_w / 2, 20.0, width=0.18)
    pdf.rect(right_x + right_w / 2, tb_y + 18.0, right_w / 2, 20.0, width=0.18)
    nlng = _load_image_from_source(_logo_source(values, "nlng", root_dir), root_dir)
    company_logo = _load_image_from_source(_logo_source(values, "company", root_dir), root_dir)
    if nlng:
        pdf.image(nlng, right_x + 1.0, tb_y + 19.0, right_w / 2 - 2.0, 18.0)
    else:
        pdf.fit_text("NLNG LOGO", right_x + 1.0, tb_y + 25.0, right_w / 2 - 2.0, 6.0, bold=True, align="center")
    if company_logo:
        pdf.image(company_logo, right_x + right_w / 2 + 1.0, tb_y + 19.0, right_w / 2 - 2.0, 18.0)
    else:
        pdf.fit_text("COMPANY LOGO", right_x + right_w / 2 + 1.0, tb_y + 25.0, right_w / 2 - 2.0, 6.0, bold=True, align="center")

    _field(pdf, right_x, tb_y + 8.0, right_w, 10.0, "Company", _value(values, "company", "contractor"), False, "center")
    _field(pdf, right_x, tb_y, right_w / 2, 8.0, "Sheet", f"{sheet_index} OF {sheet_count}", True, "center")
    _field(pdf, right_x + right_w / 2, tb_y, right_w / 2, 8.0, "Size", paper_size, True, "center")


def _canvas_bounds(canvas) -> tuple[float, float, float, float]:
    if hasattr(canvas, "bounds"):
        xmin, ymin, xmax, ymax = canvas.bounds()
        if xmax > xmin and ymax > ymin:
            return xmin, ymin, xmax, ymax
    return 0.0, 0.0, 1.0, 1.0


def _draw_view_canvas(pdf: PdfCanvas, canvas, x: float, y: float, w: float, h: float) -> None:
    pdf.rect(x, y, w, h, color=(0.55, 0.55, 0.55), width=0.12)
    xmin, ymin, xmax, ymax = _canvas_bounds(canvas)
    bw = max(xmax - xmin, 0.001)
    bh = max(ymax - ymin, 0.001)
    pad = 1.5
    scale = min((w - 2 * pad) / bw, (h - 2 * pad) / bh)
    ox = x + (w - bw * scale) / 2.0 - xmin * scale
    oy = y + (h - bh * scale) / 2.0 - ymin * scale

    def tx(pt):
        return (ox + pt[0] * scale, oy + pt[1] * scale)

    for entity in getattr(canvas, "entities", []):
        kind = entity[0]
        if kind == "LINE":
            _, p1, p2, layer, color, ltype = entity
            pdf.line(tx(p1), tx(p2), color=_layer_color(layer, color), width=_line_width(layer), dashed=ltype == "DASHED")
        elif kind == "CIRCLE":
            _, center, radius, layer, color = entity
            pdf.circle(tx(center), max(radius * scale, 0.40), color=_layer_color(layer, color), width=_line_width(layer))
        elif kind == "TEXT":
            _, text, point, height, rotation, layer, color, align = entity
            px, py = tx(point)
            size = max(1.0, min(height * scale, 5.5))
            pdf.text(text, px, py - size * 0.35, size=size, color=_layer_color(layer, color), align=align, rotation=rotation)


def _write_pdf(path: Path, pdf: PdfCanvas) -> None:
    width_pt = _pt(pdf.width_mm)
    height_pt = _pt(pdf.height_mm)
    content = "".join(pdf.commands).encode("latin-1", errors="replace")

    objects: list[bytes] = []

    def add_object(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    add_object(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add_object(b"")
    add_object(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    image_object_numbers: list[tuple[str, int]] = []
    for image in pdf.images:
        data = image["data"]
        if not isinstance(data, bytes):
            continue
        color_space = image.get("color_space", "DeviceRGB")
        image_filter = image.get("filter", "DCTDecode")
        image_dict = (
            f"<< /Type /XObject /Subtype /Image /Width {int(image['width'])} "
            f"/Height {int(image['height'])} /ColorSpace /{color_space} "
            f"/BitsPerComponent 8 /Filter /{image_filter} /Length {len(data)} >>\n"
        ).encode("ascii")
        obj_no = add_object(image_dict + b"stream\n" + data + b"\nendstream")
        image_object_numbers.append((str(image["name"]), obj_no))

    xobjects = " ".join(f"/{name} {obj_no} 0 R" for name, obj_no in image_object_numbers)
    resources = f"<< /Font << /F1 5 0 R /F2 6 0 R >> /XObject << {xobjects} >> >>"
    page = (
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(width_pt)} {_num(height_pt)}] "
        f"/Resources {resources} /Contents 4 0 R >>"
    ).encode("ascii")
    objects[2] = page

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{i} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_at = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(output))


def export_engineering_sheet_pdfs(
    views,
    root_dir: Path | str | None = None,
    config_file: str | Path = DEFAULT_CONFIG_FILE,
    output_dir: str | Path | None = None,
) -> list[Path]:
    root = Path(root_dir) if root_dir is not None else Path.cwd()
    config_path = Path(config_file)
    if not config_path.is_absolute():
        config_path = root / config_path
    values = load_title_block_values(config_path)

    folder = output_dir or _value(values, "pdf_output_dir", default=DEFAULT_PDF_DIR)
    outdir = Path(folder)
    if not outdir.is_absolute():
        outdir = root / outdir
    outdir.mkdir(exist_ok=True)

    drawing_number = _value(values, "drawing_number", "drawing_no", "drawing_num", default="SCAFFOLD-DWG-001")
    exported: list[Path] = []
    view_list = list(views)
    for index, view in enumerate(view_list, start=1):
        canvas = view["canvas"]
        view_title = view["title"]
        suffix = _safe_filename(view["suffix"]).upper()
        drawing_no = f"{drawing_number}-{suffix}"
        pw, ph = A3_LANDSCAPE_MM                              # 420 × 297 mm
        margin = 8.0
        title_h = 38.0
        view_y = title_h + margin + 5.0                       # 51 mm from bottom
        view_h = ph - view_y - margin - 7.0                   # ~232 mm tall
        view_w = pw - (margin + 4.0) * 2                      # ~396 mm wide
        cx = pw / 2.0
        pdf = PdfCanvas(pw, ph)
        pdf.rect(margin, margin, pw - 2 * margin, ph - 2 * margin, width=0.25)
        pdf.rect(margin + 2.0, margin + 2.0, pw - 2 * margin - 4.0, ph - 2 * margin - 4.0,
                 color=(0.55, 0.55, 0.55), width=0.10)
        _draw_view_canvas(pdf, canvas, margin + 4.0, view_y, view_w, view_h)
        pdf.text(view_title.upper(), cx, view_y - 3.8, size=2.6, font="F2", align="center")
        _draw_title_block(pdf, values, view_title, drawing_no, index, len(view_list), root)
        path = outdir / f"{_safe_filename(drawing_no)}.pdf"
        _write_pdf(path, pdf)
        exported.append(path)
    return exported
