from __future__ import annotations

import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from engineering_sheet_pdf import export_engineering_sheet_pdfs

os.environ.setdefault("XDG_CACHE_HOME", str((Path.cwd() / ".ezdxf_cache").resolve()))

try:
    import ezdxf
    from ezdxf import units
    from ezdxf.enums import TextEntityAlignment
except ImportError:
    ezdxf = None
    units = None
    TextEntityAlignment = None


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
239 28 3; 240 107 111; 241 108 112; 242 109 113; 243 110 114; 244 111 115;
245 112 116; 246 113 117; 247 114 118; 248 115 119; 249 116 120; 250 117 121;
251 118 122; 252 119 123; 253 120 124; 254 121 125; 255 122 126; 256 123 127;
257 124 128; 258 125 129; 259 126 130; 260 127 62; 261 128 63; 262 129 35;
263 130 34; 264 131 34; 265 132 35; 266 133 50; 267 134 51; 268 135 67;
269 136 66; 270 107 137; 271 108 138; 272 109 139; 273 110 140; 274 111 141;
275 112 142; 276 113 143; 277 114 144; 278 115 145; 279 116 146; 280 117 147;
281 118 148; 282 119 149; 283 120 150; 284 121 151; 285 122 152; 286 123 153;
287 124 154; 288 125 155; 289 126 156; 290 127 157; 291 128 158; 292 129 159;
293 130 160; 294 133 137; 295 134 138; 296 135 139; 297 136 140; 298 137 141;
299 138 142; 300 139 143; 301 140 144; 302 141 145; 303 142 146; 304 143 147;
305 144 148; 306 145 149; 307 146 150; 308 147 151; 309 148 152; 310 149 153;
311 150 154; 312 151 155; 313 152 156; 314 153 157; 315 154 158; 316 155 159;
317 156 160; 318 157 135; 319 158 136; 320 159 132; 321 160 131; 322 33 54;
323 54 35; 324 35 56; 325 61 67; 326 67 63; 327 63 65; 328 52 47; 329 47 50;
330 50 45; 331 14 79; 332 79 20; 333 71 24; 334 24 75; 335 80 17; 336 80 23;
337 23 78; 338 33 65; 339 65 52; 340 56 61; 341 61 45; 344 163 181; 345 7 163;
346 164 182; 347 8 164; 348 161 171; 349 162 172; 354 167 173; 355 168 174;
360 172 171; 362 171 173; 364 172 174; 365 174 173; 366 173 175; 367 174 176;
368 176 175; 369 175 177; 370 176 178; 371 178 177; 372 177 179; 373 178 180;
374 180 179; 375 181 75; 376 179 181; 377 182 76; 378 180 182; 380 177 183;
382 178 184; 383 171 185; 384 172 186; 385 185 187; 386 186 188; 387 189 42;
388 190 43; 389 189 187; 390 38 185; 391 190 188; 392 39 186;
"""


SCALE = 1000.0
DEFAULT_INPUT_FILE = Path("staad_input.txt")
OUTPUT_DIR = Path("dxf_output")
DIM_TEXT_OFFSET = 0.17


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
SECTION_STOP_RE = re.compile(
    r"^\s*(?:"
    r"MEMBER\s+(?!INCIDENCES\b)|ELEMENT\b|DEFINE\b|CONSTANTS?\b|SUPPORTS\b|"
    r"LOAD\b|PERFORM\b|PARAMETER\b|CHECK\b|FINISH\b|UNIT\b|START\b|END\b"
    r")",
    flags=re.IGNORECASE,
)


def read_staad_section(data: str, start: int) -> str:
    lines = []
    for line in data[start:].splitlines():
        if SECTION_STOP_RE.match(line):
            break
        lines.append(line)
    return "\n".join(lines)


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
        if not _is_int_token(tokens[i]):
            i += 1
            continue
        start = _as_int(tokens[i])
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

        tokens = line.replace(";", " ").split()
        split_at = len(tokens)
        for i, token in enumerate(tokens):
            if token.upper() in support_keywords:
                split_at = i
                break
        spec = " ".join(tokens[split_at:]).strip()
        if spec:
            for joint_id in expand_id_tokens(tokens[:split_at]):
                supports[joint_id] = spec
    return supports


def tie_joints_from_supports(joints, supports, tol=0.003):
    if not supports or not joints:
        return []
    ties = []
    for joint_id, spec in sorted(supports.items()):
        if joint_id not in joints:
            continue
        upper = spec.upper()
        released = set()
        if " BUT " in f" {upper} ":
            released = set(upper.split("BUT", 1)[1].split())
        if "FY" in released:
            ties.append(joint_id)
    return ties


def parse_staad(data: str):
    joint_match = re.search(r"\bJOINT\s+COORDINATES\b", data, flags=re.IGNORECASE)
    member_match = re.search(r"\bMEMBER\s+INCIDENCES\b", data, flags=re.IGNORECASE)
    if not joint_match or not member_match or member_match.start() <= joint_match.end():
        raise ValueError("Input must contain JOINT COORDINATES and MEMBER INCIDENCES sections.")

    joint_block = data[joint_match.end() : member_match.start()]
    member_block = read_staad_section(data, member_match.end())

    joints = {}
    for statement in re.split(r";|\n", joint_block):
        nums = re.findall(NUMBER, statement)
        if len(nums) < 4:
            continue
        jid = int(float(nums[0]))
        joints[jid] = (float(nums[1]), float(nums[2]), float(nums[3]))

    members = {}
    for statement in re.split(r";|\n", member_block):
        nums = re.findall(NUMBER, statement)
        if len(nums) < 3:
            continue
        mid = int(float(nums[0]))
        members[mid] = (int(float(nums[1])), int(float(nums[2])))

    if not joints:
        raise ValueError("No joints were parsed from the JOINT COORDINATES section.")
    if not members:
        raise ValueError("No members were parsed from the MEMBER INCIDENCES section.")

    missing = sorted({jid for pair in members.values() for jid in pair if jid not in joints})
    if missing:
        shown = ", ".join(str(j) for j in missing[:20])
        more = "..." if len(missing) > 20 else ""
        raise ValueError(f"Member incidences reference missing joints: {shown}{more}")
    return joints, members


def load_staad_text() -> tuple[str, str]:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        return path.read_text(encoding="utf-8"), str(path)
    if DEFAULT_INPUT_FILE.exists():
        return DEFAULT_INPUT_FILE.read_text(encoding="utf-8"), str(DEFAULT_INPUT_FILE)
    return DATA, "embedded sample data"


def fmt(value: float, precision: int = 3) -> str:
    clean = round(value, precision)
    if precision == 0:
        return str(int(clean))
    text = f"{clean:.{precision}f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def fmt_mm(source_value: float) -> str:
    mm_value = source_value * SCALE
    if abs(mm_value - round(mm_value)) < 0.05:
        return str(int(round(mm_value)))
    return fmt(mm_value, 1)


def fmt_m(source_value: float) -> str:
    return fmt(source_value, 3)


def dxf_num(value: float) -> str:
    if isinstance(value, int):
        return str(value)
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def key_pt(pt, precision: int = 5):
    return tuple(round(v, precision) for v in pt)


class Canvas:
    def __init__(self):
        self.entities: list[tuple] = []

    def line(self, p1, p2, layer="PIPES", color=None, ltype=None):
        self.entities.append(("LINE", tuple(p1), tuple(p2), layer, color, ltype))

    def circle(self, center, radius, layer="PIPE_ENDS", color=None):
        self.entities.append(("CIRCLE", tuple(center), radius, layer, color))

    def text(
        self,
        text,
        point,
        height=0.10,
        rotation=0.0,
        layer="TEXT",
        color=None,
        align="left",
    ):
        safe = str(text).replace("\n", " ")
        self.entities.append(("TEXT", safe, tuple(point), height, rotation, layer, color, align))

    def bounds(self):
        points = []
        for entity in self.entities:
            if entity[0] == "LINE":
                points.extend([entity[1], entity[2]])
            elif entity[0] == "CIRCLE":
                _, center, radius, *_ = entity
                points.extend(
                    [
                        (center[0] - radius, center[1] - radius),
                        (center[0] + radius, center[1] + radius),
                    ]
                )
            elif entity[0] == "TEXT":
                _, text, point, height, rotation, *_ = entity
                width = max(len(text) * height * 0.55, height)
                points.extend([point, (point[0] + width, point[1] + height)])
        if not points:
            return (-1.0, -1.0, 1.0, 1.0)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (min(xs), min(ys), max(xs), max(ys))


class DXFWriter:
    def __init__(self, canvas: Canvas, scale: float = SCALE):
        self.canvas = canvas
        self.scale = scale
        xmin, ymin, xmax, ymax = canvas.bounds()
        self.source_center = ((xmin + xmax) / 2, (ymin + ymax) / 2)
        self.extmin = self.transform((xmin, ymin))
        self.extmax = self.transform((xmax, ymax))
        self.margin = 500.0

    def transform(self, pt):
        return (
            (pt[0] - self.source_center[0]) * self.scale,
            (pt[1] - self.source_center[1]) * self.scale,
        )

    def _pairs(self, out: list[str], *pairs):
        for code, value in pairs:
            out.append(str(code))
            if isinstance(value, float):
                out.append(dxf_num(value))
            else:
                out.append(str(value))

    def _common(self, out: list[str], layer, paper_space=False, color=None, ltype=None):
        if paper_space:
            self._pairs(out, (67, 1))
        self._pairs(out, (8, layer))
        if color is not None:
            self._pairs(out, (62, color))
        if ltype is not None:
            self._pairs(out, (6, ltype))

    def _write_line(self, out, p1, p2, layer, color, ltype, paper_space=False):
        p1 = self.transform(p1)
        p2 = self.transform(p2)
        self._pairs(out, (0, "LINE"))
        self._common(out, layer, paper_space, color, ltype)
        self._pairs(
            out,
            (10, p1[0]),
            (20, p1[1]),
            (30, 0.0),
            (11, p2[0]),
            (21, p2[1]),
            (31, 0.0),
        )

    def _write_circle(self, out, center, radius, layer, color, paper_space=False):
        center = self.transform(center)
        self._pairs(out, (0, "CIRCLE"))
        self._common(out, layer, paper_space, color)
        self._pairs(out, (10, center[0]), (20, center[1]), (30, 0.0), (40, radius * self.scale))

    def _write_text(self, out, text, point, height, rotation, layer, color, align, paper_space=False):
        point = self.transform(point)
        height = height * self.scale
        self._pairs(out, (0, "TEXT"))
        self._common(out, layer, paper_space, color)
        self._pairs(
            out,
            (10, point[0]),
            (20, point[1]),
            (30, 0.0),
            (40, height),
            (1, text),
            (50, rotation),
            (7, "STANDARD"),
        )
        if align == "center":
            self._pairs(out, (72, 1), (73, 2), (11, point[0]), (21, point[1]), (31, 0.0))
        elif align == "right":
            self._pairs(out, (72, 2), (73, 2), (11, point[0]), (21, point[1]), (31, 0.0))

    def _write_entities(self, paper_space=False):
        out = []
        for entity in self.canvas.entities:
            if entity[0] == "LINE":
                _, p1, p2, layer, color, ltype = entity
                self._write_line(out, p1, p2, layer, color, ltype, paper_space)
            elif entity[0] == "CIRCLE":
                _, center, radius, layer, color = entity
                self._write_circle(out, center, radius, layer, color, paper_space)
            elif entity[0] == "TEXT":
                _, text, point, height, rotation, layer, color, align = entity
                self._write_text(out, text, point, height, rotation, layer, color, align, paper_space)
        return out

    def _header(self):
        minx, miny = self.extmin
        maxx, maxy = self.extmax
        width = max(maxx - minx, 1000.0)
        height = max(maxy - miny, 1000.0)
        view_height = height + self.margin * 2
        aspect = max((width + self.margin * 2) / view_height, 0.1)
        limmin = (minx - self.margin, miny - self.margin)
        limmax = (maxx + self.margin, maxy + self.margin)
        out = []
        self._pairs(
            out,
            (0, "SECTION"),
            (2, "HEADER"),
            (9, "$ACADVER"),
            (1, "AC1009"),
            (9, "$INSUNITS"),
            (70, 4),
            (9, "$MEASUREMENT"),
            (70, 1),
            (9, "$LUNITS"),
            (70, 2),
            (9, "$LUPREC"),
            (70, 1),
            (9, "$TILEMODE"),
            (70, 1),
            (9, "$EXTMIN"),
            (10, minx),
            (20, miny),
            (30, 0.0),
            (9, "$EXTMAX"),
            (10, maxx),
            (20, maxy),
            (30, 0.0),
            (9, "$PEXTMIN"),
            (10, minx),
            (20, miny),
            (30, 0.0),
            (9, "$PEXTMAX"),
            (10, maxx),
            (20, maxy),
            (30, 0.0),
            (9, "$LIMMIN"),
            (10, limmin[0]),
            (20, limmin[1]),
            (9, "$LIMMAX"),
            (10, limmax[0]),
            (20, limmax[1]),
            (9, "$PLIMMIN"),
            (10, limmin[0]),
            (20, limmin[1]),
            (9, "$PLIMMAX"),
            (10, limmax[0]),
            (20, limmax[1]),
            (0, "ENDSEC"),
        )
        return out, view_height, aspect

    def _tables(self, view_height, aspect):
        out = []
        self._pairs(out, (0, "SECTION"), (2, "TABLES"))
        self._pairs(out, (0, "TABLE"), (2, "VPORT"), (70, 1))
        self._pairs(
            out,
            (0, "VPORT"),
            (2, "*ACTIVE"),
            (70, 0),
            (10, 0.0),
            (20, 0.0),
            (11, 1.0),
            (21, 1.0),
            (12, 0.0),
            (22, 0.0),
            (40, view_height),
            (41, aspect),
            (42, 50.0),
            (43, 0.0),
            (44, 0.0),
            (50, 0.0),
            (51, 0.0),
            (71, 0),
            (72, 100),
            (73, 1),
            (74, 3),
            (75, 0),
            (76, 0),
            (77, 0),
            (78, 0),
        )
        self._pairs(out, (0, "ENDTAB"))

        self._pairs(out, (0, "TABLE"), (2, "LTYPE"), (70, 2))
        self._pairs(
            out,
            (0, "LTYPE"),
            (2, "CONTINUOUS"),
            (70, 0),
            (3, "Solid line"),
            (72, 65),
            (73, 0),
            (40, 0.0),
            (0, "LTYPE"),
            (2, "DASHED"),
            (70, 0),
            (3, "Dashed"),
            (72, 65),
            (73, 2),
            (40, 240.0),
            (49, 120.0),
            (74, 0),
            (49, -120.0),
            (74, 0),
            (0, "ENDTAB"),
        )

        layers = [
            ("PIPES",       5, "CONTINUOUS"),  # Blue  — structure
            ("PIPE_ENDS",   5, "CONTINUOUS"),  # Blue  — structure
            ("DIMENSION",   1, "CONTINUOUS"),  # Red   — dimensions
            ("LEVEL_GUIDE", 1, "DASHED"),      # Red   — level guides
            ("LEVEL_TEXT",  1, "CONTINUOUS"),  # Red   — dimension text
            ("FRAME",       5, "CONTINUOUS"),  # Blue  — border
        ]
        self._pairs(out, (0, "TABLE"), (2, "LAYER"), (70, len(layers)))
        for name, color, ltype in layers:
            self._pairs(out, (0, "LAYER"), (2, name), (70, 0), (62, color), (6, ltype))
        self._pairs(out, (0, "ENDTAB"))

        self._pairs(out, (0, "TABLE"), (2, "STYLE"), (70, 1))
        self._pairs(
            out,
            (0, "STYLE"),
            (2, "STANDARD"),
            (70, 0),
            (40, 0.0),
            (41, 1.0),
            (50, 0.0),
            (71, 0),
            (42, 100.0),
            (3, "txt"),
            (4, ""),
            (0, "ENDTAB"),
            (0, "ENDSEC"),
        )
        return out

    def _blocks(self):
        out = []
        self._pairs(out, (0, "SECTION"), (2, "BLOCKS"))
        self._pairs(
            out,
            (0, "BLOCK"),
            (8, "0"),
            (2, "$MODEL_SPACE"),
            (70, 0),
            (10, 0.0),
            (20, 0.0),
            (30, 0.0),
            (3, "$MODEL_SPACE"),
            (0, "ENDBLK"),
            (8, "0"),
            (0, "BLOCK"),
            (67, 1),
            (8, "0"),
            (2, "$PAPER_SPACE"),
            (70, 0),
            (10, 0.0),
            (20, 0.0),
            (30, 0.0),
            (3, "$PAPER_SPACE"),
            (0, "ENDBLK"),
            (67, 1),
            (8, "0"),
            (0, "ENDSEC"),
        )
        return out

    def save(self, path: Path):
        header, view_height, aspect = self._header()
        # ENTITIES only written once (model space). Paper-space duplication removed.
        out = header + self._tables(view_height, aspect) + self._blocks()
        self._pairs(out, (0, "SECTION"), (2, "ENTITIES"))
        out.extend(self._write_entities(paper_space=False))
        self._pairs(out, (0, "ENDSEC"), (0, "EOF"))
        path.write_text("\n".join(out) + "\n", encoding="ascii")


class DXF3DWriter:
    def __init__(self, joints, members, paper_canvas: Canvas, scale: float = SCALE):
        self.joints = joints
        self.members = members
        self.paper_canvas = paper_canvas
        self.scale = scale
        cad_points = [self.source_to_cad(p) for p in joints.values()]
        self.model_center = tuple(
            (min(p[i] for p in cad_points) + max(p[i] for p in cad_points)) / 2
            for i in range(3)
        )
        self.model_extmin = tuple(
            (min(p[i] for p in cad_points) - self.model_center[i]) * scale
            for i in range(3)
        )
        self.model_extmax = tuple(
            (max(p[i] for p in cad_points) - self.model_center[i]) * scale
            for i in range(3)
        )
        xmin, ymin, xmax, ymax = paper_canvas.bounds()
        self.paper_center = ((xmin + xmax) / 2, (ymin + ymax) / 2)
        self.paper_extmin = self.transform_paper((xmin, ymin))
        self.paper_extmax = self.transform_paper((xmax, ymax))
        self.margin = 500.0

    def source_to_cad(self, pt):
        # STAAD Y is vertical; AutoCAD Z is vertical.
        return (pt[0], pt[2], pt[1])

    def transform_model(self, pt):
        cad = self.source_to_cad(pt)
        return tuple((cad[i] - self.model_center[i]) * self.scale for i in range(3))

    def transform_paper(self, pt):
        return (
            (pt[0] - self.paper_center[0]) * self.scale,
            (pt[1] - self.paper_center[1]) * self.scale,
        )

    def _pairs(self, out: list[str], *pairs):
        for code, value in pairs:
            out.append(str(code))
            if isinstance(value, float):
                out.append(dxf_num(value))
            else:
                out.append(str(value))

    def _common(self, out: list[str], layer, paper_space=False, color=None, ltype=None):
        if paper_space:
            self._pairs(out, (67, 1))
        self._pairs(out, (8, layer))
        if color is not None:
            self._pairs(out, (62, color))
        if ltype is not None:
            self._pairs(out, (6, ltype))

    def _write_model_line(self, out, p1, p2, layer="PIPES", color=None, ltype=None):
        p1 = self.transform_model(p1)
        p2 = self.transform_model(p2)
        self._pairs(out, (0, "LINE"))
        self._common(out, layer, False, color, ltype)
        self._pairs(
            out,
            (10, p1[0]),
            (20, p1[1]),
            (30, p1[2]),
            (11, p2[0]),
            (21, p2[1]),
            (31, p2[2]),
        )

    def _write_paper_line(self, out, p1, p2, layer, color, ltype):
        p1 = self.transform_paper(p1)
        p2 = self.transform_paper(p2)
        self._pairs(out, (0, "LINE"))
        self._common(out, layer, True, color, ltype)
        self._pairs(
            out,
            (10, p1[0]),
            (20, p1[1]),
            (30, 0.0),
            (11, p2[0]),
            (21, p2[1]),
            (31, 0.0),
        )

    def _write_paper_circle(self, out, center, radius, layer, color):
        center = self.transform_paper(center)
        self._pairs(out, (0, "CIRCLE"))
        self._common(out, layer, True, color)
        self._pairs(out, (10, center[0]), (20, center[1]), (30, 0.0), (40, radius * self.scale))

    def _write_paper_text(self, out, text, point, height, rotation, layer, color, align):
        point = self.transform_paper(point)
        self._pairs(out, (0, "TEXT"))
        self._common(out, layer, True, color)
        self._pairs(
            out,
            (10, point[0]),
            (20, point[1]),
            (30, 0.0),
            (40, height * self.scale),
            (1, text),
            (50, rotation),
            (7, "STANDARD"),
        )
        if align == "center":
            self._pairs(out, (72, 1), (73, 2), (11, point[0]), (21, point[1]), (31, 0.0))
        elif align == "right":
            self._pairs(out, (72, 2), (73, 2), (11, point[0]), (21, point[1]), (31, 0.0))

    def _write_paper_entities(self):
        out = []
        for entity in self.paper_canvas.entities:
            if entity[0] == "LINE":
                _, p1, p2, layer, color, ltype = entity
                self._write_paper_line(out, p1, p2, layer, color, ltype)
            elif entity[0] == "CIRCLE":
                _, center, radius, layer, color = entity
                self._write_paper_circle(out, center, radius, layer, color)
            elif entity[0] == "TEXT":
                _, text, point, height, rotation, layer, color, align = entity
                self._write_paper_text(out, text, point, height, rotation, layer, color, align)
        return out

    def _header(self):
        minx, miny, minz = self.model_extmin
        maxx, maxy, maxz = self.model_extmax
        pminx, pminy = self.paper_extmin
        pmaxx, pmaxy = self.paper_extmax
        limmin = (min(pminx, minx) - self.margin, min(pminy, miny) - self.margin)
        limmax = (max(pmaxx, maxx) + self.margin, max(pmaxy, maxy) + self.margin)
        out = []
        self._pairs(
            out,
            (0, "SECTION"),
            (2, "HEADER"),
            (9, "$ACADVER"),
            (1, "AC1009"),
            (9, "$INSUNITS"),
            (70, 4),
            (9, "$MEASUREMENT"),
            (70, 1),
            (9, "$LUNITS"),
            (70, 2),
            (9, "$LUPREC"),
            (70, 1),
            (9, "$TILEMODE"),
            (70, 1),
            (9, "$EXTMIN"),
            (10, minx),
            (20, miny),
            (30, minz),
            (9, "$EXTMAX"),
            (10, maxx),
            (20, maxy),
            (30, maxz),
            (9, "$PEXTMIN"),
            (10, pminx),
            (20, pminy),
            (30, 0.0),
            (9, "$PEXTMAX"),
            (10, pmaxx),
            (20, pmaxy),
            (30, 0.0),
            (9, "$LIMMIN"),
            (10, limmin[0]),
            (20, limmin[1]),
            (9, "$LIMMAX"),
            (10, limmax[0]),
            (20, limmax[1]),
            (9, "$PLIMMIN"),
            (10, pminx - self.margin),
            (20, pminy - self.margin),
            (9, "$PLIMMAX"),
            (10, pmaxx + self.margin),
            (20, pmaxy + self.margin),
            (0, "ENDSEC"),
        )
        return out

    def _tables(self):
        width = max(self.paper_extmax[0] - self.paper_extmin[0], self.model_extmax[0] - self.model_extmin[0], 1000.0)
        height = max(self.paper_extmax[1] - self.paper_extmin[1], self.model_extmax[1] - self.model_extmin[1], 1000.0)
        view_height = height + self.margin * 2
        aspect = max((width + self.margin * 2) / view_height, 0.1)
        out = []
        self._pairs(out, (0, "SECTION"), (2, "TABLES"))
        self._pairs(out, (0, "TABLE"), (2, "VPORT"), (70, 1))
        self._pairs(
            out,
            (0, "VPORT"),
            (2, "*ACTIVE"),
            (70, 0),
            (10, 0.0),
            (20, 0.0),
            (11, 1.0),
            (21, 1.0),
            (12, 0.0),
            (22, 0.0),
            (13, 0.0),
            (23, 0.0),
            (14, 10.0),
            (24, 10.0),
            (15, 10.0),
            (25, 10.0),
            (16, 1.0),
            (26, -1.0),
            (36, 0.8),
            (17, 0.0),
            (27, 0.0),
            (37, 0.0),
            (40, view_height),
            (41, aspect),
            (42, 50.0),
            (43, 0.0),
            (44, 0.0),
            (50, 0.0),
            (51, 0.0),
            (71, 0),
            (72, 100),
            (73, 1),
            (74, 3),
            (75, 0),
            (76, 0),
            (77, 0),
            (78, 0),
        )
        self._pairs(out, (0, "ENDTAB"))
        self._pairs(out, (0, "TABLE"), (2, "LTYPE"), (70, 2))
        self._pairs(
            out,
            (0, "LTYPE"),
            (2, "CONTINUOUS"),
            (70, 0),
            (3, "Solid line"),
            (72, 65),
            (73, 0),
            (40, 0.0),
            (0, "LTYPE"),
            (2, "DASHED"),
            (70, 0),
            (3, "Dashed"),
            (72, 65),
            (73, 2),
            (40, 240.0),
            (49, 120.0),
            (74, 0),
            (49, -120.0),
            (74, 0),
            (0, "ENDTAB"),
        )
        layers = [
            ("PIPES",       5, "CONTINUOUS"),  # Blue  — structure
            ("PIPE_ENDS",   5, "CONTINUOUS"),  # Blue  — structure
            ("DIMENSION",   1, "CONTINUOUS"),  # Red   — dimensions
            ("LEVEL_GUIDE", 1, "DASHED"),      # Red   — level guides
            ("LEVEL_TEXT",  1, "CONTINUOUS"),  # Red   — dimension text
            ("FRAME",       5, "CONTINUOUS"),  # Blue  — border
        ]
        self._pairs(out, (0, "TABLE"), (2, "LAYER"), (70, len(layers)))
        for name, color, ltype in layers:
            self._pairs(out, (0, "LAYER"), (2, name), (70, 0), (62, color), (6, ltype))
        self._pairs(out, (0, "ENDTAB"))
        self._pairs(out, (0, "TABLE"), (2, "STYLE"), (70, 1))
        self._pairs(
            out,
            (0, "STYLE"),
            (2, "STANDARD"),
            (70, 0),
            (40, 0.0),
            (41, 1.0),
            (50, 0.0),
            (71, 0),
            (42, 100.0),
            (3, "txt"),
            (4, ""),
            (0, "ENDTAB"),
            (0, "ENDSEC"),
        )
        return out

    def _blocks(self):
        out = []
        self._pairs(out, (0, "SECTION"), (2, "BLOCKS"))
        self._pairs(
            out,
            (0, "BLOCK"),
            (8, "0"),
            (2, "$MODEL_SPACE"),
            (70, 0),
            (10, 0.0),
            (20, 0.0),
            (30, 0.0),
            (3, "$MODEL_SPACE"),
            (0, "ENDBLK"),
            (8, "0"),
            (0, "BLOCK"),
            (67, 1),
            (8, "0"),
            (2, "$PAPER_SPACE"),
            (70, 0),
            (10, 0.0),
            (20, 0.0),
            (30, 0.0),
            (3, "$PAPER_SPACE"),
            (0, "ENDBLK"),
            (67, 1),
            (8, "0"),
            (0, "ENDSEC"),
        )
        return out

    def save(self, path: Path):
        out = self._header() + self._tables()
        self._pairs(out, (0, "SECTION"), (2, "ENTITIES"))
        source_center = (self.model_center[0], self.model_center[2], self.model_center[1])
        self._write_model_line(
            out,
            (source_center[0] - 0.35, source_center[1], source_center[2]),
            (source_center[0] + 0.35, source_center[1], source_center[2]),
            "0",
            1,
        )
        self._write_model_line(
            out,
            (source_center[0], source_center[1], source_center[2] - 0.35),
            (source_center[0], source_center[1], source_center[2] + 0.35),
            "0",
            1,
        )
        for _, (start, end) in self.members.items():
            self._write_model_line(out, self.joints[start], self.joints[end])
        cx, cy = self.paper_center
        self._write_paper_line(out, (cx - 0.35, cy), (cx + 0.35, cy), "0", 1, None)
        self._write_paper_line(out, (cx, cy - 0.35), (cx, cy + 0.35), "0", 1, None)
        self._write_paper_text(out, "VISIBLE ISOMETRIC LAYOUT COPY", (cx + 0.05, cy + 0.05), 0.12, 0.0, "0", 1, "left")
        out.extend(self._write_paper_entities())
        self._pairs(out, (0, "ENDSEC"), (0, "EOF"))
        path.write_text("\n".join(out) + "\n", encoding="ascii")


def ezdxf_available() -> bool:
    return ezdxf is not None


def configure_ezdxf_doc():
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 1
    layer_specs = [
        ("PIPES",       5),   # Blue  — structure
        ("PIPE_ENDS",   5),   # Blue  — structure
        ("DIMENSION",   1),   # Red   — dimensions
        ("LEVEL_GUIDE", 1),   # Red   — level guides
        ("LEVEL_TEXT",  1),   # Red   — dimension text
        ("FRAME",       5),   # Blue  — border
        ("VIEWPORTS",   8),
    ]
    for name, color in layer_specs:
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    return doc


def layer_color(layer, explicit=None):
    if explicit is not None:
        return explicit
    return {
        # Structure — Blue (ACI 5): prints solid on white paper
        "PIPES":       5,
        "PIPE_ENDS":   5,
        "FRAME":       5,
        # Dimensions — Red (ACI 1): clearly distinct from structure on white paper
        "DIMENSION":   1,
        "LEVEL_GUIDE": 1,
        "LEVEL_TEXT":  1,
        "VIEWPORTS":   8,
    }.get(layer, 5)


def text_align(align):
    if TextEntityAlignment is None:
        return None
    return {
        "center": TextEntityAlignment.MIDDLE_CENTER,
        "right": TextEntityAlignment.MIDDLE_RIGHT,
    }.get(align, TextEntityAlignment.LEFT)


def add_ezdxf_text(layout, text, point, height, rotation=0.0, layer="TEXT", color=None, align="left"):
    entity = layout.add_text(
        text,
        height=height,
        rotation=rotation,
        dxfattribs={"layer": layer, "color": layer_color(layer, color)},
    )
    align_value = text_align(align)
    if align_value is None:
        entity.dxf.insert = point
    else:
        entity.set_placement(point, align=align_value)
    return entity


def save_canvas_ezdxf(canvas: Canvas, path: Path, scale: float = SCALE):
    doc = configure_ezdxf_doc()
    msp = doc.modelspace()
    xmin, ymin, xmax, ymax = canvas.bounds()
    center = ((xmin + xmax) / 2, (ymin + ymax) / 2)

    def tx(pt):
        return ((pt[0] - center[0]) * scale, (pt[1] - center[1]) * scale, 0.0)

    for entity in canvas.entities:
        if entity[0] == "LINE":
            _, p1, p2, layer, color, _ = entity
            msp.add_line(tx(p1), tx(p2), dxfattribs={"layer": layer, "color": layer_color(layer, color)})
        elif entity[0] == "CIRCLE":
            _, c, radius, layer, color = entity
            msp.add_circle(tx(c), radius * scale, dxfattribs={"layer": layer, "color": layer_color(layer, color)})
        elif entity[0] == "TEXT":
            _, text, p, height, rotation, layer, color, align = entity
            add_ezdxf_text(
                msp,
                text,
                tx(p),
                height * scale,
                rotation=rotation,
                layer=layer,
                color=layer_color(layer, color),
                align=align,
            )

    width  = max((xmax - xmin) * scale, 1000.0)
    height = max((ymax - ymin) * scale, 1000.0)
    doc.set_modelspace_vport(height=max(height + 100.0, 1000.0), center=(0, 0))
    doc.saveas(path)


def axis_values(joints, axis):
    return sorted(dict.fromkeys(round(p[axis], 5) for p in joints.values()))


def major_axis_values(joints, axis, max_values=12, min_gap=0.25):
    counts = Counter(round(p[axis], 5) for p in joints.values())
    values = sorted(counts)
    if len(values) <= max_values:
        return values

    max_count = max(counts.values())
    threshold = max(3, math.ceil(max_count * 0.10))
    selected = {v for v, count in counts.items() if count >= threshold}
    selected.update([values[0], values[-1]])

    if len(selected) > max_values:
        top = {v for v, _ in counts.most_common(max_values - 2)}
        top.update([values[0], values[-1]])
        selected = top

    endpoints = {values[0], values[-1]}
    ranked = sorted(
        selected,
        key=lambda v: (0 if v in endpoints else 1, -counts[v], v),
    )
    filtered = []
    for value in ranked:
        if value in endpoints or all(abs(value - kept) >= min_gap for kept in filtered):
            filtered.append(value)
    return sorted(filtered)


GAP = 0.06   # clearance between structure and start of witness/extension lines


def arrow(canvas: Canvas, tip, angle, size=0.07, layer="DIMENSION"):
    for delta in (math.radians(155), math.radians(-155)):
        end = (tip[0] + size * math.cos(angle + delta), tip[1] + size * math.sin(angle + delta))
        canvas.line(tip, end, layer=layer)


def dim_horizontal(canvas: Canvas, x0, x1, y, ext_from, text=None, text_height=0.085):
    if abs(x1 - x0) < 1e-9:
        return
    sign = math.copysign(1, y - ext_from)           # direction: dim line relative to structure
    ext_start = ext_from + sign * GAP               # witness line starts with clearance from structure
    canvas.line((x0, ext_start), (x0, y), layer="DIMENSION")
    canvas.line((x1, ext_start), (x1, y), layer="DIMENSION")
    canvas.line((x0, y), (x1, y), layer="DIMENSION")
    arrow(canvas, (x0, y), 0.0)
    arrow(canvas, (x1, y), math.pi)
    label = text if text is not None else fmt_m(abs(x1 - x0))
    canvas.text(label, ((x0 + x1) / 2, y + sign * DIM_TEXT_OFFSET), text_height, layer="DIMENSION", align="center")


def dim_vertical(canvas: Canvas, y0, y1, x, ext_from, text=None, text_height=0.085):
    if abs(y1 - y0) < 1e-9:
        return
    sign = math.copysign(1, x - ext_from)           # direction: dim line relative to structure
    ext_start = ext_from + sign * GAP               # witness line starts with clearance from structure
    canvas.line((ext_start, y0), (x, y0), layer="DIMENSION")
    canvas.line((ext_start, y1), (x, y1), layer="DIMENSION")
    canvas.line((x, y0), (x, y1), layer="DIMENSION")
    arrow(canvas, (x, y0), math.pi / 2)
    arrow(canvas, (x, y1), -math.pi / 2)
    label = text if text is not None else fmt_m(abs(y1 - y0))
    canvas.text(label, (x + sign * DIM_TEXT_OFFSET, (y0 + y1) / 2), text_height, rotation=90, layer="DIMENSION", align="center")


def add_chain_horizontal(canvas: Canvas, coords, y, ext_from, total_y=None):
    clean = sorted(dict.fromkeys(round(v, 5) for v in coords))
    if len(clean) < 2:
        return
    for a, b in zip(clean, clean[1:]):
        dim_horizontal(canvas, a, b, y, ext_from)
    if total_y is not None:
        dim_horizontal(canvas, clean[0], clean[-1], total_y, ext_from, text=f"TOTAL {fmt_m(clean[-1] - clean[0])}")


def add_chain_vertical(canvas: Canvas, coords, x, ext_from, total_x=None):
    clean = sorted(dict.fromkeys(round(v, 5) for v in coords))
    if len(clean) < 2:
        return
    for a, b in zip(clean, clean[1:]):
        dim_vertical(canvas, a, b, x, ext_from)
    if total_x is not None:
        dim_vertical(canvas, clean[0], clean[-1], total_x, ext_from, text=f"TOTAL {fmt_m(clean[-1] - clean[0])}")


def add_level_table(canvas: Canvas, levels, x, y_top, title="ALL Y LEVELS (m)"):
    columns = max(2, math.ceil(len(levels) / 24))
    canvas.text(title, (x, y_top), 0.105, layer="LEVEL_TEXT")
    rows = math.ceil(len(levels) / columns)
    row_h = 0.135
    col_w = 0.85
    for i, level in enumerate(levels):
        col = i // rows
        row = i % rows
        canvas.text(f"EL {fmt_m(level)}", (x + col * col_w, y_top - 0.20 - row * row_h), 0.075, layer="LEVEL_TEXT")


def add_title(canvas: Canvas, title, subtitle, x, y):
    canvas.text(title, (x, y), 0.16, layer="TITLE")
    canvas.text(subtitle, (x, y - 0.22), 0.085, layer="TEXT")


def add_axis_note(canvas: Canvas, note, x, y):
    canvas.text(note, (x, y), 0.075, layer="TEXT")


def projected_lines(joints, members, projection):
    lines = {}
    collapsed = defaultdict(int)
    for _, (a, b) in members.items():
        p0 = projection(joints[a])
        p1 = projection(joints[b])
        if math.hypot(p0[0] - p1[0], p0[1] - p1[1]) < 1e-5:
            collapsed[key_pt(p0, 4)] += 1
            continue
        k0, k1 = key_pt(p0, 5), key_pt(p1, 5)
        key = tuple(sorted((k0, k1)))
        lines[key] = (p0, p1)
    return list(lines.values()), collapsed


def draw_projection(canvas: Canvas, joints, members, projection):
    lines, collapsed = projected_lines(joints, members, projection)
    for p0, p1 in lines:
        canvas.line(p0, p1, layer="PIPES")
    for center, count in collapsed.items():
        radius = 0.025 if count <= 1 else 0.032
        canvas.circle(center, radius, layer="PIPE_ENDS")
    return len(lines), len(collapsed)


def add_level_guides(canvas: Canvas, levels, x0, x1, major_levels):
    for level in levels:
        if any(abs(level - m) < 0.002 for m in major_levels):
            canvas.line((x0, level), (x1, level), layer="LEVEL_GUIDE", ltype="DASHED")


def draw_frame(canvas: Canvas, x0, y0, x1, y1):
    canvas.line((x0, y0), (x1, y0), layer="FRAME")
    canvas.line((x1, y0), (x1, y1), layer="FRAME")
    canvas.line((x1, y1), (x0, y1), layer="FRAME")
    canvas.line((x0, y1), (x0, y0), layer="FRAME")


def make_view(joints, members, levels, outdir: Path, name, axis_a, axis_b):
    canvas = Canvas()
    draw_projection(canvas, joints, members, lambda p: (p[axis_a], p[axis_b]))

    vals_a = [p[axis_a] for p in joints.values()]
    vals_b = [p[axis_b] for p in joints.values()]
    amin, amax = min(vals_a), max(vals_a)
    bmin, bmax = min(vals_b), max(vals_b)

    major_a = major_axis_values(joints, axis_a, max_values=12, min_gap=0.35)
    major_b = major_axis_values(joints, axis_b, max_values=12, min_gap=0.30 if axis_b == 1 else 0.35)
    if axis_b == 1:
        add_level_guides(canvas, levels, amin - 0.18, amax + 0.18, major_b)

    add_chain_horizontal(canvas, major_a, bmin - 0.38, bmin, bmin - 0.75)
    add_chain_vertical(canvas, major_b, amax + 0.70, amax, amax + 1.15)

    path = outdir / f"scaffold_{name}_view.dxf"
    if ezdxf_available():
        save_canvas_ezdxf(canvas, path, scale=SCALE)
    else:
        DXFWriter(canvas, scale=SCALE).save(path)
    return {
        "dxf_path": path,
        "canvas": canvas,
        "title": f"{name.title()} View",
        "suffix": f"{name.upper()}-VIEW",
    }


def make_plan(joints, members, levels, outdir: Path):
    return make_view(joints, members, levels, outdir, "plan", 0, 2)


def make_front(joints, members, levels, outdir: Path):
    return make_view(joints, members, levels, outdir, "front", 0, 1)


def make_side(joints, members, levels, outdir: Path):
    return make_view(joints, members, levels, outdir, "side", 2, 1)


def isometric_projection(pt):
    # +Z → left (front face toward viewer), +X → right, +Y → up
    angle = math.radians(30.0)
    return ((pt[0] - pt[2]) * math.cos(angle), pt[1] + (pt[0] + pt[2]) * math.sin(angle))


def isometric_bounds(joints):
    pts = [isometric_projection(p) for p in joints.values()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def add_tie_callout(canvas: Canvas, joints, tie_joints):
    points = [isometric_projection(joints[jid]) for jid in tie_joints if jid in joints]
    if not points:
        return
    _, ymin, xmax, ymax = isometric_bounds(joints)
    for point in points:
        canvas.circle(point, 0.085, layer="DIMENSION", color=6)

    leader_x = xmax + 0.55
    text_x = leader_x + 0.35
    label_y = min(max(v for _, v in points) + 0.18, ymax + 0.35)
    label_y = max(label_y, ymin + 0.75)
    for point in points:
        elbow = (leader_x, point[1])
        canvas.line(point, elbow, layer="DIMENSION", color=6)
        canvas.line(elbow, (leader_x, label_y), layer="DIMENSION", color=6)
    canvas.line((leader_x, label_y), (text_x - 0.08, label_y), layer="DIMENSION", color=6)
    for i, line in enumerate(["Tie points to", "existing structures", "at indicated points."]):
        canvas.text(line, (text_x, label_y - i * 0.13), 0.075, layer="DIMENSION", color=6)


def add_isometric_axes(canvas: Canvas, joints):
    xs = [p[0] for p in joints.values()]
    ys = [p[1] for p in joints.values()]
    zs = [p[2] for p in joints.values()]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
    axis_len = min(span * 0.18, 0.80)
    origin = (min(xs), min(ys), min(zs))
    axes = [
        ("X", (origin[0] + axis_len, origin[1], origin[2])),
        ("Y", (origin[0], origin[1] + axis_len, origin[2])),
        ("Z", (origin[0], origin[1], origin[2] + axis_len)),
    ]
    start = isometric_projection(origin)
    for label, end3d in axes:
        end = isometric_projection(end3d)
        canvas.line(start, end, layer="DIMENSION")
        canvas.text(label, (end[0] + 0.05, end[1] + 0.03), 0.075, layer="DIMENSION")


def make_3d(joints, members, levels, tie_joints, outdir: Path):
    canvas = Canvas()
    draw_projection(canvas, joints, members, isometric_projection)
    add_tie_callout(canvas, joints, tie_joints)

    iso_points = [isometric_projection(p) for p in joints.values()]
    us = [p[0] for p in iso_points]
    vs = [p[1] for p in iso_points]

    path = outdir / "scaffold_3D_view.dxf"
    if ezdxf_available():
        save_canvas_ezdxf(canvas, path, scale=SCALE)
    else:
        DXFWriter(canvas, scale=SCALE).save(path)
    return {"dxf_path": path, "canvas": canvas, "title": "3D View", "suffix": "3D-VIEW"}


def main():
    data, source = load_staad_text()
    joints, members = parse_staad(data)
    supports = parse_supports(data)
    tie_joints = tie_joints_from_supports(joints, supports)
    levels = axis_values(joints, 1)
    OUTPUT_DIR.mkdir(exist_ok=True)
    views = [
        make_front(joints, members, levels, OUTPUT_DIR),
        make_side(joints, members, levels, OUTPUT_DIR),
        make_plan(joints, members, levels, OUTPUT_DIR),
        make_3d(joints, members, levels, tie_joints, OUTPUT_DIR),
    ]
    pdf_paths = export_engineering_sheet_pdfs(views, root_dir=Path.cwd())
    print(f"Input source: {source}")
    print(f"Parsed {len(joints)} joints and {len(members)} members.")
    print(f"Detected {len(levels)} unique Y levels.")
    print(f"Supports: {len(supports)}    Tie callout joints: {', '.join(map(str, tie_joints)) if tie_joints else 'none'}")
    print(f"Scale factor: {fmt(SCALE, 0)}. DXF units: millimetres.")
    print("DXF output:")
    for view in views:
        print(view["dxf_path"])
    print("PDF output:")
    for path in pdf_paths:
        print(path)


if __name__ == "__main__":
    main()
