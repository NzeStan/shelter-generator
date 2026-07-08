"""
generate_scaffold_grid_dxf.py
Professional gridline-based scaffold drawing generator.

Outputs four DXF files in dxf_output/:
  scaffold_grid_plans.dxf  -- plan view at each structural level, tiled
  scaffold_grid_front.dxf  -- front elevation (X-Y) with gridlines
  scaffold_grid_side.dxf   -- side elevation (Z-Y) with gridlines
  scaffold_grid_3d.dxf     -- isometric 3D with grid-origin marker

Also outputs four A4 landscape engineering-sheet PDFs in pdf_output/.

Gridline convention:
  X axis  ->  lettered columns  A, B, C ...
  Z axis  ->  numbered rows     1, 2, 3 ...
  Y axis  ->  levels            L1, L2, L3 ...

Usage:
  py generate_scaffold_grid_dxf.py [staad_file.txt]
  (Falls back to staad_input.txt then embedded sample data.)
"""

from __future__ import annotations
from collections import defaultdict
import math, os, sys
import re
from pathlib import Path

from engineering_sheet_pdf import export_engineering_sheet_pdfs

os.environ.setdefault("XDG_CACHE_HOME", str((Path.cwd() / ".ezdxf_cache").resolve()))
try:
    import ezdxf
    from ezdxf import units
    from ezdxf.enums import TextEntityAlignment
except ImportError:
    ezdxf = units = TextEntityAlignment = None

# ── constants ─────────────────────────────────────────────────────────────────
SCALE        = 1000
GAP          = 0.06
BR           = 0.12
TH           = 0.09
TH_SM        = 0.07
ARROW_SZ     = 0.06
DIM_CHAIN    = 0.38
DIM_TOTAL    = 0.62
BUBBLE_OFF   = 0.92
DIM_TEXT_OFF = 0.17
PLANS_PER_ROW = 3
OUTPUT_DIR   = Path("dxf_output")
DEFAULT_INPUT = Path("staad_input.txt")

PIPE_COLOR = 1
DIM_COLOR = 5
BUBBLE_COLOR = 1
TIE_COLOR = 6

LAYER_COLOR  = {
    "PIPES": PIPE_COLOR,
    "GRIDLINE": DIM_COLOR,
    "DIMENSION": DIM_COLOR,
    "BUBBLE": BUBBLE_COLOR,
    "TIE": TIE_COLOR,
}

NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")

# ── embedded sample ───────────────────────────────────────────────────────────
DATA = r"""
JOINT COORDINATES
1 0 0 0; 2 1.28 0 0; 3 2.72001 0 0; 4 4.00001 0 0; 5 4.00001 0 2;
6 4.00001 0 4.00001; 7 2.72001 0 4.00001; 8 1.28 0 4.00001; 9 0 0 4.00001;
10 0 0 2; 11 1.28 0 2; 12 2.72001 0 2; 13 0 0.300001 0; 14 1.28 0.300001 0;
15 2.72001 0.300001 0; 16 4.00001 0.300001 0; 17 4.00001 0.300001 2;
18 4.00001 0.300001 4.00001; 19 2.72001 0.300001 4.00001;
20 1.28 0.300001 4.00001; 21 0 0.300001 4.00001; 22 0 0.300001 2;
23 1.28 0.300001 2; 24 2.72001 0.300001 2; 25 0 1.24468 0; 26 1.28 1.24468 0;
27 2.72001 1.24468 0; 28 4.00001 1.24468 0; 29 0 2.42554 0; 30 1.28 2.42554 0;
31 2.72001 2.42554 0; 32 4.00001 2.42554 0; 33 0 3.60639 0; 34 1.28 3.60639 0;
35 2.72001 3.60639 0; 36 4.00001 3.60639 0; 37 4.00001 1.24468 4.00001;
38 2.72001 1.24468 4.00001; 39 1.28 1.24468 4.00001; 40 0 1.24468 4.00001;
41 4.00001 2.42554 4.00001; 42 2.72001 2.42554 4.00001;
43 1.28 2.42554 4.00001; 44 0 2.42554 4.00001; 45 4.00001 3.60639 4.00001;
46 2.72001 3.60639 4.00001; 47 1.28 3.60639 4.00001; 48 0 3.60639 4.00001;
49 4.00001 4.00001 4.00001; 50 2.72001 4.00001 4.00001;
51 1.28 4.00001 4.00001; 52 0 4.00001 4.00001; 53 0 3.21277 0;
54 1.28 3.21277 0; 55 2.72001 3.21277 0; 56 4.00001 3.21277 0;
57 4.00001 1.24468 2; 58 0 1.24468 2; 59 4.00001 2.42554 2; 60 0 2.42554 2;
61 4.00001 3.8032 2; 62 2.72001 3.8032 2; 63 1.28 3.8032 2; 64 0 3.8032 2;
65 0 3.40958 2; 66 1.28 3.40958 2; 67 2.72001 3.40958 2; 68 4.00001 3.40958 2;
69 0 0.851064 0; 70 1.28 0.851064 0; 71 2.72001 0.851064 0;
72 4.00001 0.851064 0; 73 4.00001 0.851064 2; 74 4.00001 0.851064 4.00001;
75 2.72001 0.851064 4.00001; 76 1.28 0.851064 4.00001; 77 0 0.851064 4.00001;
78 0 0.851064 2; 79 1.28 0.851064 2; 80 2.72001 0.851064 2;
81 0.400001 1.24468 0; 82 0.400001 1.24468 4.00001; 83 0.400001 1.24468 2;
84 1.28 1.24468 0.500001; 85 2.72001 1.24468 0.500001;
86 4.00001 1.24468 0.500001; 87 0.400001 1.24468 0.500001;
88 3.60001 1.24468 4.00001; 89 3.60001 1.24468 2; 90 3.60001 1.24468 0.500001;
91 2.72001 1.24468 3.50001; 92 1.28 1.24468 3.50001;
93 0.400001 1.24468 3.50001; 94 3.60001 1.24468 3.50001;
95 0.400001 0.851064 2; 96 1.28 0.851064 0.500001;
97 2.72001 0.851064 0.500001; 98 0.400001 0.851064 0.500001;
99 3.60001 0.851064 2; 100 3.60001 0.851064 0.500001;
101 2.72001 0.851064 3.50001; 102 1.28 0.851064 3.50001;
103 0.400001 0.851064 3.50001; 104 3.60001 0.851064 3.50001;
105 2.72001 2.81916 4.00001; 106 1.28 2.81916 4.00001;
107 2.72001 3.97071 3.70232; 108 1.28 3.97071 3.70232;
109 2.72001 3.77391 1.70232; 110 1.28 3.77391 1.70232;
111 2.72001 3.94142 3.40464; 112 1.28 3.94142 3.40464;
113 2.72001 3.74461 1.40464; 114 1.28 3.74461 1.40464;
115 2.72001 3.91213 3.10696; 116 1.28 3.91213 3.10696;
117 2.72001 3.71532 1.10695; 118 1.28 3.71532 1.10695;
119 2.72001 3.88284 2.80927; 120 1.28 3.88284 2.80927;
121 2.72001 3.68603 0.80927; 122 1.28 3.68603 0.80927;
123 2.72001 3.85354 2.51159; 124 1.28 3.85354 2.51159;
125 2.72001 3.65673 0.511587; 126 1.28 3.65673 0.511587;
127 2.72001 3.82425 2.21391; 128 1.28 3.82425 2.21391;
129 2.72001 3.62744 0.213904; 130 1.28 3.62744 0.213904; 131 1.28 3.32299 0;
132 2.72001 3.32299 0; 133 2.72001 3.7166 4.00001; 134 1.28 3.7166 4.00001;
135 2.72001 3.5198 2; 136 1.28 3.5198 2; 137 2.72001 3.68731 3.70232;
138 1.28 3.68731 3.70232; 139 2.72001 3.4905 1.70232; 140 1.28 3.4905 1.70232;
141 2.72001 3.65802 3.40464; 142 1.28 3.65802 3.40464;
143 2.72001 3.46121 1.40464; 144 1.28 3.46121 1.40464;
145 2.72001 3.62872 3.10696; 146 1.28 3.62872 3.10696;
147 2.72001 3.43192 1.10695; 148 1.28 3.43192 1.10695;
149 2.72001 3.59943 2.80927; 150 1.28 3.59943 2.80927;
151 2.72001 3.40262 0.80927; 152 1.28 3.40262 0.80927;
153 2.72001 3.57014 2.51159; 154 1.28 3.57014 2.51159;
155 2.72001 3.37333 0.511587; 156 1.28 3.37333 0.511587;
157 2.72001 3.54085 2.21391; 158 1.28 3.54085 2.21391;
159 2.72001 3.34404 0.213904; 160 1.28 3.34404 0.213904; 161 2.72001 0 5.50001;
162 1.28 0 5.50001; 163 2.72001 0.457448 4.00001; 164 1.28 0.457448 4.00001;
167 2.72001 0 5.00001; 168 1.28 0 5.00001; 171 2.72001 0.300001 5.50001;
172 1.28 0.300001 5.50001; 173 2.72001 0.300001 5.00001;
174 1.28 0.300001 5.00001; 175 2.72001 0.536171 5.00001;
176 1.28 0.536171 5.00001; 177 2.72001 0.536171 4.50001;
178 1.28 0.536171 4.50001; 179 2.72001 0.772342 4.50001;
180 1.28 0.772342 4.50001; 181 2.72001 0.772342 4.00001;
182 1.28 0.772342 4.00001; 183 2.72001 0 4.50001; 184 1.28 0 4.50001;
185 2.72001 0.693619 5.50001; 186 1.28 0.693619 5.50001;
187 2.72001 1.08723 5.50001; 188 1.28 1.08723 5.50001;
189 2.72001 1.6383 4.00001; 190 1.28 1.6383 4.00001;
MEMBER INCIDENCES
18 1 13; 19 2 14; 20 3 15; 21 4 16; 22 5 17; 23 6 18; 24 7 19; 25 8 20;
26 9 21; 27 10 22; 28 11 23; 29 12 24; 30 13 14; 31 14 15; 32 15 16; 33 16 17;
34 17 18; 35 18 19; 36 19 20; 37 20 21; 38 21 22; 39 22 13; 40 22 23; 41 23 24;
42 24 17; 43 24 19; 44 24 15; 45 20 23; 46 23 14; 47 13 69; 48 14 70; 49 15 71;
50 16 72; 51 25 81; 52 26 27; 53 27 28; 54 25 29; 55 26 30; 56 27 31; 57 28 32;
58 29 30; 59 30 31; 60 31 32; 61 29 53; 62 30 54; 63 31 55; 64 32 56; 65 33 34;
66 34 35; 67 35 36; 68 18 74; 69 19 163; 70 20 164; 71 21 77; 72 37 88;
74 39 82; 75 37 41; 76 38 189; 77 39 190; 78 40 44; 79 41 42; 81 43 44;
82 41 45; 83 42 105; 84 43 106; 85 44 48; 86 45 46; 87 46 47; 88 47 48;
89 45 49; 90 46 133; 91 47 134; 92 48 52; 93 49 50; 94 50 51; 95 51 52;
96 49 61; 97 50 107; 98 51 108; 99 52 64; 100 53 33; 101 54 131; 102 55 132;
103 56 36; 104 53 54; 105 54 55; 106 55 56; 107 53 65; 110 56 68; 111 17 73;
112 22 78; 113 28 86; 114 57 37; 115 40 58; 116 58 25; 117 32 59; 118 59 41;
119 44 60; 120 60 29; 121 60 58; 122 59 57; 123 61 36; 124 62 109; 125 63 110;
126 64 33; 127 65 48; 130 68 45; 131 64 65; 132 65 60; 133 63 136; 134 62 135;
135 61 68; 136 68 59; 137 64 63; 138 65 66; 139 66 67; 140 63 62; 141 67 68;
142 62 61; 143 69 25; 144 70 26; 145 71 27; 146 72 28; 147 73 57; 148 74 37;
149 75 38; 150 76 39; 151 77 40; 152 78 58; 153 69 70; 154 70 71; 155 71 72;
156 72 73; 157 73 74; 158 74 75; 159 75 76; 160 76 77; 161 77 78; 162 78 69;
163 78 95; 164 79 80; 165 80 99; 166 80 101; 167 80 97; 168 76 102; 169 79 96;
170 79 23; 171 80 24; 172 81 26; 173 82 40; 174 58 83; 175 82 93; 176 83 87;
177 26 84; 178 27 85; 179 86 57; 180 87 81; 181 84 85; 182 85 90; 183 87 84;
184 88 38; 185 57 89; 186 90 86; 187 89 94; 188 90 89; 189 38 91; 190 39 92;
191 93 83; 192 94 88; 193 92 93; 194 94 91; 195 95 79; 196 83 95; 197 96 70;
198 84 96; 199 97 71; 200 85 97; 201 87 98; 202 99 73; 203 89 99; 204 90 100;
205 101 75; 206 91 101; 207 102 79; 208 92 102; 209 93 103; 210 94 104;
211 105 46; 212 106 47; 213 105 106; 214 46 106; 215 43 48; 216 43 40;
218 46 41; 219 41 38; 220 38 6; 221 40 8; 222 65 29; 223 29 58; 224 58 1;
225 48 60; 226 60 40; 227 40 10; 228 56 59; 229 59 28; 230 28 17; 231 68 41;
232 41 57; 233 57 18; 234 54 29; 235 29 26; 236 26 1; 237 56 31; 238 31 28;
239 28 3; 344 163 181; 345 7 163; 346 164 182; 347 8 164; 348 161 171;
349 162 172; 354 167 173; 355 168 174; 360 172 171; 362 171 173; 364 172 174;
365 174 173; 366 173 175; 367 174 176; 368 176 175; 369 175 177; 370 176 178;
371 178 177; 372 177 179; 373 178 180; 374 180 179; 375 181 75; 376 179 181;
377 182 76; 378 180 182; 380 177 183; 382 178 184; 383 171 185; 384 172 186;
385 185 187; 386 186 188; 387 189 42; 388 190 43; 389 189 187; 390 38 185;
391 190 188; 392 39 186;
"""


# ── input loading ─────────────────────────────────────────────────────────────
def load_input():
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        return p.read_text(encoding="utf-8"), str(p)
    if DEFAULT_INPUT.exists():
        return DEFAULT_INPUT.read_text(encoding="utf-8"), str(DEFAULT_INPUT)
    return DATA, "embedded sample data"


# ── STAAD parser ──────────────────────────────────────────────────────────────
def parse_staad(text):
    joints, members = {}, {}
    jblock = mblock = ""
    in_j = in_m = False
    STOP = {"MEMBER PROPERTY", "ELEMENT", "SUPPORT", "LOAD", "DEFINE", "CONSTANT"}
    for line in text.splitlines():
        u = line.upper().strip()
        if "JOINT COORDINATES" in u:
            in_j, in_m = True, False; continue
        if "MEMBER INCIDENCES" in u:
            in_m, in_j = True, False; continue
        if any(k in u for k in STOP):
            in_j = in_m = False
        if in_j:  jblock += " " + line
        elif in_m: mblock += " " + line

    toks = jblock.replace(";", " ").split(); i = 0
    while i < len(toks):
        try:
            jid = int(toks[i]); x, y, z = float(toks[i+1]), float(toks[i+2]), float(toks[i+3])
            joints[jid] = (x, y, z); i += 4
        except (ValueError, IndexError): i += 1

    toks = mblock.replace(";", " ").split(); i = 0
    while i < len(toks):
        try:
            mid = int(toks[i]); a, b = int(toks[i+1]), int(toks[i+2])
            members[mid] = (a, b); i += 3
        except (ValueError, IndexError): i += 1

    return joints, members, parse_supports(text)


def _is_int_token(token):
    try:
        int(float(token))
        return True
    except ValueError:
        return False


def _as_int(token):
    return int(float(token))


def expand_id_tokens(tokens):
    ids = []
    i = 0
    while i < len(tokens):
        token = tokens[i].upper()
        if not _is_int_token(token):
            i += 1
            continue
        start = _as_int(token)
        if i + 2 < len(tokens) and tokens[i + 1].upper() == "TO" and _is_int_token(tokens[i + 2]):
            end = _as_int(tokens[i + 2])
            step = 1 if end >= start else -1
            ids.extend(range(start, end + step, step))
            i += 3
        else:
            ids.append(start)
            i += 1
    return ids


def join_staad_continuation_lines(text):
    return re.sub(r"\s+-\s*\n\s*", " ", text)


def parse_supports(text):
    text = join_staad_continuation_lines(text)
    support_keywords = {
        "FIXED", "PINNED", "ENFORCED", "SPRING", "ELASTIC", "INCLINED",
        "MULTILINEAR", "COMPRESSION", "TENSION", "BUT", "FX", "FY", "FZ",
        "MX", "MY", "MZ", "KFX", "KFY", "KFZ", "KMX", "KMY", "KMZ",
    }
    stop_headers = {
        "LOAD", "MEMBER", "ELEMENT", "DEFINE", "CONSTANT", "PERFORM",
        "PARAMETER", "CHECK", "FINISH", "UNIT", "JOINT", "START", "END",
    }
    supports = {}
    in_supports = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("SUPPORTS"):
            in_supports = True
            line = line[len("SUPPORTS"):].strip()
            if not line:
                continue
            upper = line.upper()
        elif in_supports and any(upper.startswith(header) for header in stop_headers):
            break
        if not in_supports:
            continue

        line = line.replace(";", " ")
        tokens = line.split()
        if not tokens:
            continue

        split_at = len(tokens)
        for i, token in enumerate(tokens):
            if token.upper() in support_keywords:
                split_at = i
                break
        ids = expand_id_tokens(tokens[:split_at])
        spec = " ".join(tokens[split_at:]).strip()
        if ids and spec:
            for joint_id in ids:
                supports[joint_id] = spec
    return supports


def tie_joints_from_supports(joints, supports, tol=0.003):
    if not supports or not joints:
        return []
    ties = []
    for jid, spec in sorted(supports.items()):
        if jid not in joints:
            continue
        upper = spec.upper()
        released = set()
        if " BUT " in f" {upper} ":
            released = set(upper.split("BUT", 1)[1].split())
        if "FY" in released:
            ties.append(jid)
    return ties


# ── Canvas ────────────────────────────────────────────────────────────────────
class Canvas:
    def __init__(self): self.entities = []

    def line(self, p0, p1, layer="PIPES", ltype=None, color=None):
        self.entities.append(("LINE", tuple(p0), tuple(p1), layer, color, ltype))

    def circle(self, center, radius, layer="BUBBLE", color=None):
        self.entities.append(("CIRCLE", tuple(center), radius, layer, color))

    def text(self, txt, pos, height=TH, rotation=0.0, layer="DIMENSION", color=None, align="left"):
        self.entities.append(("TEXT", str(txt), tuple(pos), height, rotation, layer, color, align))

    def bounds(self):
        pts = []
        for e in self.entities:
            if e[0] == "LINE": pts += [e[1], e[2]]
            elif e[0] == "CIRCLE": cx,cy=e[1]; r=e[2]; pts+=[(cx-r,cy-r),(cx+r,cy+r)]
            elif e[0] == "TEXT": pts.append(e[2])
        if not pts: return (0,0,1,1)
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        return (min(xs),min(ys),max(xs),max(ys))


# ── DXF save ──────────────────────────────────────────────────────────────────
def _lc(layer, explicit=None):
    return explicit if explicit is not None else LAYER_COLOR.get(layer, 5)


def _ta(align):
    if TextEntityAlignment is None: return None
    return {"center": TextEntityAlignment.MIDDLE_CENTER,
            "right":  TextEntityAlignment.MIDDLE_RIGHT}.get(align, TextEntityAlignment.LEFT)


def _add_text(layout, txt, pt, h, rot, layer, color, align):
    a = _ta(align)
    att = {"layer": layer, "color": color, "height": h, "rotation": rot}
    if a is None or align == "left":
        layout.add_text(txt, dxfattribs={**att, "insert": pt})
    else:
        layout.add_text(txt, dxfattribs={**att, "insert": pt,
                                          "halign": 1 if align == "center" else 2,
                                          "valign": 2, "align_point": pt})


def save_dxf(canvas, path):
    if ezdxf is None:
        _save_plain(canvas, path); return
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    for name, color in LAYER_COLOR.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    try:
        if "DASHED" not in doc.linetypes:
            doc.linetypes.add("DASHED", [0.6, 0.4, -0.2])
    except Exception:
        pass

    msp = doc.modelspace()
    xmin,ymin,xmax,ymax = canvas.bounds()
    cx=(xmin+xmax)/2; cy=(ymin+ymax)/2
    def tx(pt): return ((pt[0]-cx)*SCALE, (pt[1]-cy)*SCALE, 0.0)

    for e in canvas.entities:
        if e[0] == "LINE":
            _,p0,p1,layer,color,ltype = e
            att = {"layer": layer, "color": _lc(layer, color)}
            if ltype == "DASHED": att["linetype"] = "DASHED"
            msp.add_line(tx(p0), tx(p1), dxfattribs=att)
        elif e[0] == "CIRCLE":
            _,cen,r,layer,color = e
            msp.add_circle(tx(cen), r*SCALE, dxfattribs={"layer":layer,"color":_lc(layer,color)})
        elif e[0] == "TEXT":
            _,txt,pos,h,rot,layer,color,align = e
            _add_text(msp, txt, tx(pos), h*SCALE, rot, layer, _lc(layer,color), align)

    h = max((ymax-ymin)*SCALE, 1000.0)
    doc.set_modelspace_vport(height=h+200, center=(0,0))
    doc.saveas(path)


def _save_plain(canvas, path):
    xmin,ymin,xmax,ymax = canvas.bounds()
    cx=(xmin+xmax)/2; cy=(ymin+ymax)/2
    def tx(pt): return ((pt[0]-cx)*SCALE, (pt[1]-cy)*SCALE)
    def n(v): return f"{v:.4f}".rstrip("0").rstrip(".")
    out = [
        "0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n"
        "9\n$INSUNITS\n70\n4\n0\nENDSEC\n"
        "0\nSECTION\n2\nTABLES\n"
        "0\nTABLE\n2\nLTYPE\n70\n2\n"
        "0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid\n72\n65\n73\n0\n40\n0\n"
        "0\nLTYPE\n2\nDASHED\n70\n0\n3\nDashed\n72\n65\n73\n2\n40\n240\n49\n120\n74\n0\n49\n-120\n74\n0\n"
        "0\nENDTAB\n"
        "0\nTABLE\n2\nLAYER\n70\n5\n"
        f"0\nLAYER\n2\nPIPES\n70\n0\n62\n{PIPE_COLOR}\n6\nCONTINUOUS\n"
        f"0\nLAYER\n2\nGRIDLINE\n70\n0\n62\n{DIM_COLOR}\n6\nDASHED\n"
        f"0\nLAYER\n2\nDIMENSION\n70\n0\n62\n{DIM_COLOR}\n6\nCONTINUOUS\n"
        f"0\nLAYER\n2\nBUBBLE\n70\n0\n62\n{BUBBLE_COLOR}\n6\nCONTINUOUS\n"
        f"0\nLAYER\n2\nTIE\n70\n0\n62\n{TIE_COLOR}\n6\nCONTINUOUS\n"
        "0\nENDTAB\n0\nENDSEC\n"
        "0\nSECTION\n2\nENTITIES\n"
    ]
    for e in canvas.entities:
        if e[0] == "LINE":
            _,p0,p1,layer,color,ltype = e
            t0=tx(p0); t1=tx(p1); lt="DASHED" if ltype=="DASHED" else "CONTINUOUS"
            out.append(f"0\nLINE\n8\n{layer}\n6\n{lt}\n"
                       f"10\n{n(t0[0])}\n20\n{n(t0[1])}\n30\n0\n"
                       f"11\n{n(t1[0])}\n21\n{n(t1[1])}\n31\n0")
        elif e[0] == "CIRCLE":
            _,cen,r,layer,color = e; tc=tx(cen)
            out.append(f"0\nCIRCLE\n8\n{layer}\n10\n{n(tc[0])}\n20\n{n(tc[1])}\n30\n0\n40\n{n(r*SCALE)}")
        elif e[0] == "TEXT":
            _,txt,pos,h,rot,layer,color,align = e; tp=tx(pos)
            out.append(f"0\nTEXT\n8\n{layer}\n10\n{n(tp[0])}\n20\n{n(tp[1])}\n30\n0\n40\n{n(h*SCALE)}\n1\n{txt}\n50\n{n(rot)}")
    out.append("0\nENDSEC\n0\nEOF")
    path.write_text("\n".join(out)+"\n", encoding="ascii")


# ── grid analysis ─────────────────────────────────────────────────────────────
def grid_vals(joints, axis, tol=0.012):
    raw = sorted(p[axis] for p in joints.values())
    merged = []
    for v in raw:
        if not merged or abs(v - merged[-1]) > tol:
            merged.append(round(v, 3))
    return merged


def major_grid_vals(joints, members, axis, tol=0.012):
    all_vals = grid_vals(joints, axis, tol)
    if len(all_vals) <= 2:
        return all_vals

    min_y = min(p[1] for p in joints.values())
    max_y = max(p[1] for p in joints.values())
    height = max(max_y - min_y, tol)
    vertical_lines = defaultdict(list)
    for a, b in members.values():
        pa, pb = joints[a], joints[b]
        if abs(pa[0] - pb[0]) < tol and abs(pa[2] - pb[2]) < tol and abs(pa[1] - pb[1]) > tol:
            key = (round(pa[0], 3), round(pa[2], 3))
            vertical_lines[key].extend([pa[1], pb[1]])

    score = defaultdict(float)
    for (x, z), ys in vertical_lines.items():
        span = max(ys) - min(ys)
        coord = x if axis == 0 else z
        score[round(coord, 3)] = max(score[round(coord, 3)], span)

    keep = {all_vals[0], all_vals[-1]}
    for value in all_vals[1:-1]:
        if score.get(round(value, 3), 0.0) >= height * 0.45:
            keep.add(value)
    return sorted(keep)


def structural_levels(joints, members, tol=0.003):
    lvls = set()
    for _, (a, b) in members.items():
        ya, yb = joints[a][1], joints[b][1]
        if abs(ya - yb) < tol:
            lvls.add(round((ya+yb)/2, 3))
    return sorted(lvls)


def drawing_levels(joints, members):
    levels = structural_levels(joints, members)
    return levels or sorted({round(p[1], 3) for p in joints.values()})


def col_label(i):
    return chr(65+i) if i < 26 else chr(64+i//26)+chr(65+i%26)

def row_label(i):
    return str(i+1)

def fmt_mm(v):
    mm = v * 1000
    return str(int(round(mm))) if abs(mm-round(mm)) < 0.5 else f"{mm:.1f}"


def format_refs(items, single_word, plural_word):
    values = list(items)
    if not values:
        return ""
    word = single_word if len(values) == 1 else plural_word
    if len(values) == 1:
        return f"{word} {values[0]}"
    if len(values) == 2:
        return f"{word} {values[0]} & {values[1]}"
    return f"{word} {', '.join(values[:-1])} & {values[-1]}"


def format_level_refs(level_refs):
    return format_refs([f"{idx + 1}" for idx, _ in level_refs], "LEVEL", "LEVELS")


def line_key(p0, p1, precision=3):
    a = (round(p0[0], precision), round(p0[1], precision))
    b = (round(p1[0], precision), round(p1[1], precision))
    return tuple(sorted((a, b)))


def plan_signature(joints, members, y_level, tol=0.003):
    lines = set()
    for a, b in members.values():
        pa, pb = joints[a], joints[b]
        if abs(pa[1] - y_level) < tol and abs(pb[1] - y_level) < tol:
            p0, p1 = (pa[0], pa[2]), (pb[0], pb[2])
            if abs(p0[0] - p1[0]) > tol or abs(p0[1] - p1[1]) > tol:
                lines.add(line_key(p0, p1))
    return tuple(sorted(lines))


def grouped_plan_levels(joints, members, y_levels):
    groups = []
    seen = {}
    for idx, y_level in enumerate(y_levels):
        signature = plan_signature(joints, members, y_level)
        if not signature:
            continue
        if signature in seen:
            groups[seen[signature]]["levels"].append((idx, y_level))
        else:
            seen[signature] = len(groups)
            groups.append({"signature": signature, "levels": [(idx, y_level)]})
    return groups


def grid_range_label(labels):
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]}-{labels[-1]}"


def elevation_signature(joints, members, fixed_axis, fixed_value, h_axis, tol=0.003):
    lines = set()
    for a, b in members.values():
        pa, pb = joints[a], joints[b]
        if abs(pa[fixed_axis] - fixed_value) > tol or abs(pb[fixed_axis] - fixed_value) > tol:
            continue
        p0, p1 = (pa[h_axis], pa[1]), (pb[h_axis], pb[1])
        if abs(p0[0] - p1[0]) > tol or abs(p0[1] - p1[1]) > tol:
            lines.add(line_key(p0, p1))
    return tuple(sorted(lines))


def grouped_gridline_views(joints, members, fixed_axis, fixed_values, h_axis, labels):
    groups = []
    seen = {}
    for idx, fixed_value in enumerate(fixed_values):
        signature = elevation_signature(joints, members, fixed_axis, fixed_value, h_axis)
        if not signature:
            continue
        ref = (idx, fixed_value, labels[idx])
        if signature in seen:
            groups[seen[signature]]["refs"].append(ref)
        else:
            seen[signature] = len(groups)
            groups.append({"signature": signature, "refs": [ref]})
    return groups


# ── drawing primitives ────────────────────────────────────────────────────────
def arrow(canvas, tip, angle):
    for d in (math.radians(150), math.radians(-150)):
        end = (tip[0]+ARROW_SZ*math.cos(angle+d), tip[1]+ARROW_SZ*math.sin(angle+d))
        canvas.line(tip, end, layer="DIMENSION", color=DIM_COLOR)


def dim_h(canvas, x0, x1, y_line, y_struct):
    if abs(x1-x0) < 1e-6: return
    sign = math.copysign(1, y_line-y_struct)
    ys = y_struct + sign*GAP
    canvas.line((x0,ys),(x0,y_line),layer="DIMENSION", color=DIM_COLOR)
    canvas.line((x1,ys),(x1,y_line),layer="DIMENSION", color=DIM_COLOR)
    canvas.line((x0,y_line),(x1,y_line),layer="DIMENSION", color=DIM_COLOR)
    arrow(canvas,(x0,y_line),0.0); arrow(canvas,(x1,y_line),math.pi)
    canvas.text(fmt_mm(abs(x1-x0)),((x0+x1)/2, y_line+sign*DIM_TEXT_OFF),TH_SM,layer="DIMENSION",color=DIM_COLOR,align="center")


def dim_v(canvas, y0, y1, x_line, x_struct):
    if abs(y1-y0) < 1e-6: return
    sign = math.copysign(1, x_line-x_struct)
    xs = x_struct + sign*GAP
    canvas.line((xs,y0),(x_line,y0),layer="DIMENSION", color=DIM_COLOR)
    canvas.line((xs,y1),(x_line,y1),layer="DIMENSION", color=DIM_COLOR)
    canvas.line((x_line,y0),(x_line,y1),layer="DIMENSION", color=DIM_COLOR)
    arrow(canvas,(x_line,y0),math.pi/2); arrow(canvas,(x_line,y1),-math.pi/2)
    canvas.text(fmt_mm(abs(y1-y0)),(x_line+sign*DIM_TEXT_OFF,(y0+y1)/2),TH_SM,rotation=90,layer="DIMENSION",color=DIM_COLOR,align="center")


def bubble(canvas, cx, cy, label):
    canvas.circle((cx,cy), BR, layer="BUBBLE", color=BUBBLE_COLOR)
    canvas.text(label, (cx,cy), TH, layer="BUBBLE", color=BUBBLE_COLOR, align="center")


def title_block_text(canvas, centre_x, base_y, lines):
    for i, text in enumerate(lines):
        y = base_y - i * 0.16
        canvas.text(text, (centre_x, y), TH_SM, layer="DIMENSION", color=PIPE_COLOR, align="center")


# ── plan view at one level ────────────────────────────────────────────────────
def draw_plan(canvas, joints, members, xs, zs, level_refs, ox, oz, tol=0.003):
    xmin,xmax = xs[0],xs[-1]
    zmin,zmax = zs[0],zs[-1]
    y_level = level_refs[0][1]

    # members at this level
    for _, (a,b) in members.items():
        ya,yb = joints[a][1],joints[b][1]
        if abs(ya-y_level)<tol and abs(yb-y_level)<tol:
            canvas.line((ox+joints[a][0], oz+joints[a][2]),
                        (ox+joints[b][0], oz+joints[b][2]), layer="PIPES", color=PIPE_COLOR)

    # top bubbles — X gridlines (A, B, C...)
    bub_top = oz+zmax+0.44
    for i,xi in enumerate(xs):
        bubble(canvas, ox+xi, bub_top, col_label(i))

    # left bubbles — Z gridlines (1, 2, 3...)
    bub_left = ox+xmin-0.44
    for i,zi in enumerate(zs):
        bubble(canvas, bub_left, oz+zi, row_label(i))

    # horizontal dim chain (above structure, inside bubble line)
    dh_y = oz+zmax+0.22
    for i in range(len(xs)-1):
        dim_h(canvas, ox+xs[i], ox+xs[i+1], dh_y, oz+zmax)
    # vertical dim chain (left of structure)
    dv_x = ox+xmin-0.22
    for i in range(len(zs)-1):
        dim_v(canvas, oz+zs[i], oz+zs[i+1], dv_x, ox+xmin)
    centre_x = ox+(xmin+xmax)/2
    title_block_text(
        canvas,
        centre_x,
        oz+zmin-0.45,
        ["PLAN VIEW TYPICAL FOR", format_level_refs(level_refs)],
    )


# ── elevation (generic) ───────────────────────────────────────────────────────
def draw_elevation(canvas, joints, members, h_axis, h_vals, h_labels, y_levels, level_labels, ox=0.0, oy=0.0):
    hmin,hmax = h_vals[0],h_vals[-1]
    ymin,ymax = y_levels[0],y_levels[-1]

    # all members (deduplicated)
    done = set()
    for _, (a,b) in members.items():
        h0,h1 = joints[a][h_axis],joints[b][h_axis]
        v0,v1 = joints[a][1],     joints[b][1]
        key = tuple(sorted(((round(h0,4),round(v0,4)),(round(h1,4),round(v1,4)))))
        if key in done: continue
        done.add(key)
        canvas.line((ox+h0,oy+v0),(ox+h1,oy+v1),layer="PIPES")

    # vertical gridlines
    for hv in h_vals:
        canvas.line((ox+hv,oy+ymin),(ox+hv,oy+ymax),layer="GRIDLINE",ltype="DASHED")

    # horizontal level lines
    for yv in y_levels:
        canvas.line((ox+hmin,oy+yv),(ox+hmax,oy+yv),layer="GRIDLINE",ltype="DASHED")

    # top bubbles for h_vals
    bub_top = oy+ymax+BUBBLE_OFF
    for i,hv in enumerate(h_vals):
        bubble(canvas, ox+hv, bub_top, h_labels[i])

    # left level labels
    for i,yv in enumerate(y_levels):
        canvas.text(level_labels[i], (ox+hmin-0.18,oy+yv), TH_SM,
                    layer="DIMENSION", align="right")

    # bottom dim chain (h spacing)
    dh_y = oy+ymin-DIM_CHAIN
    for i in range(len(h_vals)-1):
        dim_h(canvas, ox+h_vals[i], ox+h_vals[i+1], dh_y, oy+ymin)
    if len(h_vals) >= 2:
        dim_h(canvas, ox+h_vals[0], ox+h_vals[-1], oy+ymin-DIM_TOTAL, oy+ymin)

    # right dim chain (level spacing)
    dv_x = ox+hmax+DIM_CHAIN
    for i in range(len(y_levels)-1):
        dim_v(canvas, oy+y_levels[i], oy+y_levels[i+1], dv_x, ox+hmax)
    if len(y_levels) >= 2:
        dim_v(canvas, oy+y_levels[0], oy+y_levels[-1], ox+hmax+DIM_TOTAL, ox+hmax)


# ── isometric ─────────────────────────────────────────────────────────────────
def draw_gridline_elevation(
    canvas,
    joints,
    members,
    fixed_axis,
    fixed_value,
    h_axis,
    h_vals,
    h_labels,
    y_levels,
    title_lines,
    ox=0.0,
    oy=0.0,
    tol=0.003,
):
    hmin,hmax = h_vals[0],h_vals[-1]
    ymin,ymax = min(y_levels),max(y_levels)
    done = set()
    for _, (a,b) in members.items():
        pa,pb = joints[a],joints[b]
        if abs(pa[fixed_axis]-fixed_value) > tol or abs(pb[fixed_axis]-fixed_value) > tol:
            continue
        p0 = (pa[h_axis], pa[1])
        p1 = (pb[h_axis], pb[1])
        if abs(p0[0]-p1[0]) < tol and abs(p0[1]-p1[1]) < tol:
            continue
        key = line_key(p0, p1, precision=4)
        if key in done:
            continue
        done.add(key)
        canvas.line((ox+p0[0],oy+p0[1]),(ox+p1[0],oy+p1[1]),layer="PIPES",color=PIPE_COLOR)

    bub_top = oy+ymax+0.34
    for i,hv in enumerate(h_vals):
        bubble(canvas, ox+hv, bub_top, h_labels[i])

    dh_y = oy+ymax+0.18
    for i in range(len(h_vals)-1):
        dim_h(canvas, ox+h_vals[i], ox+h_vals[i+1], dh_y, oy+ymax)

    dv_x = ox+hmin-0.34
    for i in range(len(y_levels)-1):
        dim_v(canvas, oy+y_levels[i], oy+y_levels[i+1], dv_x, ox+hmin)

    centre_x = ox+(hmin+hmax)/2
    title_block_text(canvas, centre_x, oy+ymin-0.56, title_lines)


def draw_gridline_group(
    canvas,
    joints,
    members,
    group,
    fixed_axis,
    h_axis,
    h_vals,
    h_labels,
    y_levels,
    view_name,
    range_label,
    ox=0.0,
    oy=0.0,
):
    fixed_value = group["refs"][0][1]
    refs = [ref[2] for ref in group["refs"]]
    title_lines = [
        f"{view_name} VIEW TYPICAL FOR",
        f"GRID LINE {', '.join(refs)} ({range_label})",
    ]
    draw_gridline_elevation(
        canvas,
        joints,
        members,
        fixed_axis,
        fixed_value,
        h_axis,
        h_vals,
        h_labels,
        y_levels,
        title_lines,
        ox,
        oy,
    )


def iso(pt):
    ang = math.radians(30.0)
    return ((pt[0]-pt[2])*math.cos(ang), pt[1]+(pt[0]+pt[2])*math.sin(ang))


def iso_bounds(joints):
    pts = [iso(pt) for pt in joints.values()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def draw_iso_dim(canvas, p0, p1, text, offset=(0.0, 0.0)):
    u0,v0 = iso(p0)
    u1,v1 = iso(p1)
    u0 += offset[0]; v0 += offset[1]
    u1 += offset[0]; v1 += offset[1]
    canvas.line((u0,v0),(u1,v1),layer="DIMENSION",color=DIM_COLOR)
    angle = math.atan2(v1-v0, u1-u0)
    arrow(canvas, (u0,v0), angle)
    arrow(canvas, (u1,v1), angle+math.pi)
    nx, ny = -math.sin(angle), math.cos(angle)
    label_pt = ((u0+u1)/2 + nx*DIM_TEXT_OFF, (v0+v1)/2 + ny*DIM_TEXT_OFF)
    canvas.text(text, label_pt, TH_SM, rotation=math.degrees(angle),
                layer="DIMENSION", color=DIM_COLOR, align="center")


def draw_iso_grid_labels(canvas, joints, xs, zs, y_levels):
    base_y = min(y_levels)
    xmin_i, ymin_i, xmax_i, ymax_i = iso_bounds(joints)
    x_label_z = zs[-1]
    for i, x in enumerate(xs):
        u,v = iso((x, base_y, x_label_z))
        bubble(canvas, u, v-0.28, col_label(i))

    z_label_x = xs[0]
    for i, z in enumerate(zs):
        u,v = iso((z_label_x, base_y, z))
        bubble(canvas, u-0.25, v-0.20, row_label(i))

    for i in range(len(xs)-1):
        draw_iso_dim(canvas, (xs[i], base_y, x_label_z), (xs[i+1], base_y, x_label_z),
                     fmt_mm(xs[i+1]-xs[i]), offset=(0.0, -0.14))
    for i in range(len(zs)-1):
        draw_iso_dim(canvas, (z_label_x, base_y, zs[i]), (z_label_x, base_y, zs[i+1]),
                     fmt_mm(zs[i+1]-zs[i]), offset=(-0.13, -0.12))

    label_anchor = (xs[-1], base_y, zs[-1])
    for i, y in enumerate(y_levels):
        start = iso((label_anchor[0], y, label_anchor[2]))
        end = (xmax_i + 0.80, start[1] + 0.22)
        canvas.line(start, end, layer="DIMENSION", color=DIM_COLOR)
        canvas.text(f"LEVEL {i+1}", (end[0]+0.12, end[1]+0.02), TH_SM,
                    rotation=18, layer="DIMENSION", color=DIM_COLOR)

    for i in range(len(y_levels)-1):
        p0 = (xs[0], y_levels[i], zs[0])
        p1 = (xs[0], y_levels[i+1], zs[0])
        draw_iso_dim(canvas, p0, p1, fmt_mm(y_levels[i+1]-y_levels[i]), offset=(-0.55, 0.0))


def draw_tie_callout(canvas, joints, tie_joints):
    if not tie_joints:
        return
    tie_points = [iso(joints[jid]) for jid in tie_joints if jid in joints]
    if not tie_points:
        return
    _, ymin_i, xmax_i, ymax_i = iso_bounds(joints)
    for pt in tie_points:
        canvas.circle(pt, BR * 0.72, layer="TIE", color=TIE_COLOR)

    leader_x = xmax_i + 0.55
    text_x = leader_x + 0.35
    label_y = min(max(v for _, v in tie_points) + 0.18, ymax_i + 0.35)
    label_y = max(label_y, ymin_i + 0.75)
    for pt in tie_points:
        elbow = (leader_x, pt[1])
        canvas.line(pt, elbow, layer="TIE", color=TIE_COLOR)
        canvas.line(elbow, (leader_x, label_y), layer="TIE", color=TIE_COLOR)
    canvas.line((leader_x, label_y), (text_x - 0.08, label_y), layer="TIE", color=TIE_COLOR)
    lines = [
        "Tie points to",
        "existing structures",
        "at indicated points.",
    ]
    for i, line in enumerate(lines):
        canvas.text(line, (text_x, label_y-i*0.13), TH_SM, layer="TIE", color=TIE_COLOR)


# ── view makers ───────────────────────────────────────────────────────────────
def make_plans(joints, members, xs, zs, y_levels, outdir):
    canvas = Canvas()
    xspan = xs[-1]-xs[0]; zspan = zs[-1]-zs[0]
    cell_w = xspan + 1.25
    cell_h = zspan + 1.45
    groups = grouped_plan_levels(joints, members, y_levels)
    # all plan levels in one horizontal row for better visibility
    for k, group in enumerate(groups):
        ox = k * (cell_w + 0.60)
        oz = 0.0
        draw_plan(canvas, joints, members, xs, zs, group["levels"], ox, oz)
    path = outdir / "scaffold_grid_plans.dxf"
    save_dxf(canvas, path)
    return {"dxf_path": path, "canvas": canvas, "title": "Plan View", "suffix": "PLAN-VIEW"}


def make_front(joints, members, xs, y_levels, outdir):
    canvas = Canvas()
    zs = major_grid_vals(joints, members, 2)
    x_labels = [col_label(i) for i in range(len(xs))]
    z_labels = [row_label(i) for i in range(len(zs))]
    groups = grouped_gridline_views(joints, members, 0, xs, 2, x_labels)
    width = zs[-1] - zs[0] + 1.1
    height = y_levels[-1] - y_levels[0] + 1.35
    # all grid-line groups in one horizontal row
    for k, group in enumerate(groups):
        ox = k * (width + 1.0)
        oy = 0.0
        draw_gridline_group(
            canvas, joints, members, group, 0, 2, zs, z_labels, y_levels,
            "FRONT", grid_range_label(z_labels), ox, oy,
        )
    path = outdir / "scaffold_grid_front.dxf"
    save_dxf(canvas, path)
    return {"dxf_path": path, "canvas": canvas, "title": "Front View", "suffix": "FRONT-VIEW"}


def make_side(joints, members, zs, y_levels, outdir):
    canvas = Canvas()
    xs = major_grid_vals(joints, members, 0)
    x_labels = [col_label(i) for i in range(len(xs))]
    z_labels = [row_label(i) for i in range(len(zs))]
    groups = grouped_gridline_views(joints, members, 2, zs, 0, z_labels)
    width = xs[-1] - xs[0] + 1.1
    height = y_levels[-1] - y_levels[0] + 1.35
    # all grid-line groups in one horizontal row
    for k, group in enumerate(groups):
        ox = k * (width + 1.0)
        oy = 0.0
        draw_gridline_group(
            canvas, joints, members, group, 2, 0, xs, x_labels, y_levels,
            "SIDE", grid_range_label(x_labels), ox, oy,
        )
    path = outdir / "scaffold_grid_side.dxf"
    save_dxf(canvas, path)
    return {"dxf_path": path, "canvas": canvas, "title": "Side View", "suffix": "SIDE-VIEW"}


def make_3d(joints, members, xs, zs, y_levels, tie_joints, outdir):
    canvas = Canvas()
    done = set()
    for _, (a,b) in members.items():
        u0,v0 = iso(joints[a]); u1,v1 = iso(joints[b])
        if abs(u0-u1)<1e-5 and abs(v0-v1)<1e-5: continue
        key = tuple(sorted(((round(u0,4),round(v0,4)),(round(u1,4),round(v1,4)))))
        if key in done: continue
        done.add(key); canvas.line((u0,v0),(u1,v1),layer="PIPES",color=PIPE_COLOR)

    draw_tie_callout(canvas, joints, tie_joints)

    """
    # grid-origin marker at corner (A=xs[0], row 1=zs[0]), base level Y=0
    base_y = min(joints[j][1] for j in joints)
    ou,ov = iso((xs[0], base_y, zs[0]))
    bubble(canvas, ou, ov-BR-0.08, "A1")

    # axis arrows showing grid reading direction
    AX = min((xs[-1]-xs[0])*0.20, 0.80)
    # X direction arrow (A→B)
    xt = iso((xs[0]+AX, base_y, zs[0]))
    canvas.line((ou,ov), xt, layer="DIMENSION")
    ang_x = math.atan2(xt[1]-ov, xt[0]-ou)
    arrow(canvas, xt, ang_x+math.pi)
    canvas.text(col_label(1) if len(xs)>1 else "B",
                (xt[0]+0.05, xt[1]+0.04), TH_SM, layer="DIMENSION")

    # Z direction arrow (1→2)
    zt = iso((xs[0], base_y, zs[0]+AX))
    canvas.line((ou,ov), zt, layer="DIMENSION")
    ang_z = math.atan2(zt[1]-ov, zt[0]-ou)
    arrow(canvas, zt, ang_z+math.pi)
    canvas.text(row_label(1) if len(zs)>1 else "2",
                (zt[0]-0.20, zt[1]+0.04), TH_SM, layer="DIMENSION")
    """

    path = outdir / "scaffold_grid_3d.dxf"
    save_dxf(canvas, path)
    return {"dxf_path": path, "canvas": canvas, "title": "3D View", "suffix": "3D-VIEW"}


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    data, source = load_input()
    joints, members, supports = parse_staad(data)
    if not joints:
        print("ERROR: no joints parsed. Check your input file.")
        sys.exit(1)

    xs      = major_grid_vals(joints, members, 0)
    zs      = major_grid_vals(joints, members, 2)
    y_lvls  = drawing_levels(joints, members)
    tie_joints = tie_joints_from_supports(joints, supports)

    OUTPUT_DIR.mkdir(exist_ok=True)

    views = [
        make_front(joints, members, xs, y_lvls,      OUTPUT_DIR),
        make_side (joints, members, zs, y_lvls,      OUTPUT_DIR),
        make_plans(joints, members, xs, zs, y_lvls, OUTPUT_DIR),
        make_3d   (joints, members, xs, zs, y_lvls, tie_joints, OUTPUT_DIR),
    ]
    pdf_paths = export_engineering_sheet_pdfs(views, root_dir=Path.cwd())

    print(f"Input   : {source}")
    print(f"Joints  : {len(joints)}    Members : {len(members)}")
    print(f"X grid  : {len(xs)} lines  ({col_label(0)} to {col_label(len(xs)-1)})")
    print(f"Z grid  : {len(zs)} lines  ({row_label(0)} to {row_label(len(zs)-1)})")
    print(f"Levels  : {len(y_lvls)}")
    print(f"Supports: {len(supports)}    Tie callout joints: {', '.join(map(str, tie_joints)) if tie_joints else 'none'}")
    print()
    print("DXF output:")
    for p in [view["dxf_path"] for view in views]:
        print(p)
    print()
    print("PDF output:")
    for p in pdf_paths:
        print(p)


if __name__ == "__main__":
    main()
