#!/usr/bin/env python3
"""
scaffold_renderer.py  —  STAAD.Pro Scaffold 3D Renderer
========================================================
Converts STAAD.Pro geometry (JOINT COORDINATES + MEMBER INCIDENCES)
into a professional, AutoCAD-style solid 3D rendered image.

Requirements
------------
    pip install pyvista numpy

Usage
-----
    # Render from STAAD .std file
    python scaffold_renderer.py scaffold.std

    # With boarded platforms and custom output
    python scaffold_renderer.py scaffold.std --platforms platforms.txt --output render.png

    # Interactive preview, then save
    python scaffold_renderer.py scaffold.std --interactive

    # 4K output, custom pipe size, SE camera angle
    python scaffold_renderer.py scaffold.std --width 3840 --height 2160 --azimuth 135

    # Pipe radius in metres (default 0.024 = 48.3 mm OD scaffold tube)
    python scaffold_renderer.py scaffold.std --pipe-radius 0.030

Platform config file  (platforms.txt)
--------------------------------------
    BOARDED_PLATFORMS:
    # Corner node IDs listed in order (at least 3 nodes per platform)
    1,2,3,4
    10,11,12,13,14,15
    40,41,42,43

Output
------
    scaffold_render.png   (and .jpg) — high-resolution, white background,
    no annotations, no axes, no title block.

Notes
-----
    - STAAD coordinate convention: Y is vertical (up).
    - Camera up-vector set to (0, 1, 0) accordingly.
    - On Linux, a virtual display (Xvfb) is NOT required; PyVista uses
      VTK's OSMesa / EGL off-screen backend automatically.
    - For headless servers, set env var: VTK_DEFAULT_RENDER_WINDOW_BACKEND=osmesa
"""

import os
import re
import sys
import argparse
import textwrap
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Optional: set display before importing pyvista on Linux headless ───────────
os.environ.setdefault("DISPLAY", ":99")

try:
    import pyvista as pv
    pv.global_theme.allow_empty_mesh = True
    _PYVISTA = True
except ImportError:
    _PYVISTA = False

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS  —  adjust these for visual style
# ══════════════════════════════════════════════════════════════════════════════

# Scaffold tube
PIPE_RADIUS      : float = 0.024     # metres  (48.3 mm OD → radius 24 mm)
PIPE_RESOLUTION  : int   = 14        # cylinder facets (12–20 recommended)
PIPE_COLOR       : str   = "#9EAAB5" # steel blue-grey

# Base plates
BASE_PLATE_SIZE  : float = 0.150     # metres (150 mm × 150 mm footprint)
BASE_PLATE_THICK : float = 0.012     # metres (12 mm thick)
BASE_PLATE_COLOR : str   = "#4E5861" # dark steel

# Boarded platform
PLATFORM_THICK   : float = 0.080     # metres (80 mm board thickness)
PLATFORM_COLOR   : str   = "#C8934A" # amber/timber

# Rendering
BG_COLOR         : str   = "#FFFFFF" # pure white
RENDER_WIDTH     : int   = 2400
RENDER_HEIGHT    : int   = 2400
AMBIENT          : float = 0.20
DIFFUSE          : float = 0.75
SPECULAR_PIPE    : float = 0.55
SPECULAR_PLAT    : float = 0.20
SPECULAR_PWR     : float = 40.0

# Camera
CAM_AZIMUTH_DEG  : float = 210.0    # horizontal angle in XZ plane
CAM_ELEVATION_DEG: float = 48.0     # angle above horizontal
CAM_DIST_FACTOR  : float = 1.85     # multiple of bounding-box diagonal
CAM_FOV_DEG      : float = 22.0     # narrow FOV → near-isometric feel

# Lighting
LIGHT_KEY_INTENSITY  : float = 1.00
LIGHT_FILL_INTENSITY : float = 0.45
LIGHT_RIM_INTENSITY  : float = 0.18


# ══════════════════════════════════════════════════════════════════════════════
# 1.  STAAD FILE PARSER
# ══════════════════════════════════════════════════════════════════════════════

class StaadParser:
    """
    Parse JOINT COORDINATES and MEMBER INCIDENCES from STAAD .std content.

    Handles:
     - Multiple records per line (semicolon-separated)
     - In-line comments ($ or *)
     - Non-sequential node/member numbering
     - Scientific notation floats
    """

    _FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"

    def __init__(self, content: str):
        self.nodes:   dict[int, np.ndarray]  = {}  # id → [x, y, z]
        self.members: list[tuple[int, int]]  = []  # [(start, end), …]
        self.supports: dict[int, str]        = {}  # id → support spec string
        self.base_node_ids: list[int]        = []  # FY-restrained support nodes
        self._parse(content)

    # ── Public helpers ─────────────────────────────────────────────────────────

    def node_coords(self) -> np.ndarray:
        """Return (N, 3) array of all node coordinates, sorted by node ID."""
        ids = sorted(self.nodes)
        return np.array([self.nodes[i] for i in ids], dtype=float)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (min_xyz, max_xyz) of the node cloud."""
        coords = self.node_coords()
        return coords.min(axis=0), coords.max(axis=0)

    def summary(self) -> str:
        lo, hi = self.bounds()
        return (
            f"  Joints : {len(self.nodes)}\n"
            f"  Members: {len(self.members)}\n"
            f"  X range: {lo[0]:.3f} → {hi[0]:.3f} m\n"
            f"  Y range: {lo[1]:.3f} → {hi[1]:.3f} m  (vertical)\n"
            f"  Z range: {lo[2]:.3f} → {hi[2]:.3f} m"
        )

    # ── Private ────────────────────────────────────────────────────────────────

    def _clean_content(self, raw: str) -> str:
        """Normalise line endings, strip in-line comments."""
        lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        clean = []
        for ln in lines:
            # Strip everything after $ or *
            ln = re.split(r"[$*]", ln)[0]
            clean.append(ln)
        return "\n".join(clean)

    def _section_text(self, content: str, keyword: str) -> str:
        """Extract lines belonging to the named STAAD section."""

        # Keywords that indicate the start of a new / different section
        HEADERS = [
            "JOINT COORDINATES", "MEMBER INCIDENCES", "ELEMENT INCIDENCES",
            "MEMBER PROPERTY", "ELEMENT PROPERTY", "CONSTANTS", "SUPPORTS",
            "LOAD ", "DEFINE ", "PERFORM ", "FINISH", "UNIT ", "SET ",
            "MEMBER RELEASE", "MEMBER TRUSS", "MEMBER TENSION",
            "MEMBER COMPRESSION", "SECTION ", "DRAW ", "STEEL",
        ]

        lines  = content.split("\n")
        buf    = []
        active = False

        for ln in lines:
            up = ln.strip().upper()

            if keyword.upper() in up:
                active = True
                continue

            if active:
                # Check for section terminator
                terminated = any(
                    up.startswith(h) and h.strip().upper() != keyword.upper()
                    for h in HEADERS
                )
                if terminated:
                    break
                if up:
                    buf.append(ln)

        return " ".join(buf)

    def _parse_joints(self, text: str):
        pat = re.compile(
            rf"(\d+)\s+({self._FLOAT})\s+({self._FLOAT})\s+({self._FLOAT})"
        )
        for m in pat.finditer(text):
            nid = int(m.group(1))
            xyz = np.array([float(m.group(2)), float(m.group(3)), float(m.group(4))])
            self.nodes[nid] = xyz

    def _parse_members(self, text: str):
        pat = re.compile(r"(\d+)\s+(\d+)\s+(\d+)")
        for m in pat.finditer(text):
            n1, n2 = int(m.group(2)), int(m.group(3))
            if n1 in self.nodes and n2 in self.nodes:
                self.members.append((n1, n2))

    def _parse_supports(self, content: str):
        """Parse SUPPORTS block; populate self.supports and self.base_node_ids."""
        _SUPPORT_KW = {
            "FIXED", "PINNED", "ENFORCED", "SPRING", "ELASTIC", "INCLINED",
            "BUT", "FX", "FY", "FZ", "MX", "MY", "MZ",
            "KFX", "KFY", "KFZ", "KMX", "KMY", "KMZ",
        }
        _STOP = {
            "LOAD", "MEMBER", "ELEMENT", "DEFINE", "CONSTANT", "PERFORM",
            "PARAMETER", "CHECK", "FINISH", "UNIT", "JOINT", "START", "END",
        }
        # Join STAAD continuation lines (trailing -)
        text = re.sub(r"\s*-\s*\n\s*", " ", content)

        in_supports = False
        for raw_line in text.splitlines():
            line = re.split(r"[$*]", raw_line)[0].strip()
            if not line:
                continue
            upper = line.upper()

            if upper.startswith("SUPPORTS"):
                in_supports = True
                rest = line[len("SUPPORTS"):].strip()
                if not rest:
                    continue
                line = rest
                upper = line.upper()
            elif in_supports:
                if any(upper.startswith(kw) for kw in _STOP):
                    break

            if not in_supports:
                continue

            tokens = line.replace(";", " ").split()
            if not tokens:
                continue

            split_at = len(tokens)
            for i, tok in enumerate(tokens):
                if tok.upper() in _SUPPORT_KW:
                    split_at = i
                    break

            spec = " ".join(tokens[split_at:]).strip()
            id_toks = tokens[:split_at]
            if not spec or not id_toks:
                continue

            ids: list[int] = []
            i = 0
            while i < len(id_toks):
                try:
                    val = int(float(id_toks[i]))
                except ValueError:
                    i += 1
                    continue
                if i + 2 < len(id_toks) and id_toks[i + 1].upper() == "TO":
                    try:
                        end = int(float(id_toks[i + 2]))
                        step = 1 if end >= val else -1
                        ids.extend(range(val, end + step, step))
                        i += 3
                        continue
                    except (ValueError, IndexError):
                        pass
                ids.append(val)
                i += 1

            upper_spec = spec.upper()
            fy_released = False
            if "BUT" in upper_spec.split():
                after_but = upper_spec.split("BUT", 1)[1]
                fy_released = "FY" in after_but.split()

            for jid in ids:
                self.supports[jid] = spec
                if not fy_released:
                    self.base_node_ids.append(jid)

    def _parse(self, raw: str):
        content = self._clean_content(raw)
        self._parse_joints(self._section_text(content, "JOINT COORDINATES"))
        self._parse_members(self._section_text(content, "MEMBER INCIDENCES"))
        self._parse_supports(content)
        if not self.nodes:
            raise ValueError("No joint coordinates found. Check file format.")
        if not self.members:
            raise ValueError("No member incidences found. Check file format.")


# ══════════════════════════════════════════════════════════════════════════════
# 2.  PLATFORM CONFIG PARSER
# ══════════════════════════════════════════════════════════════════════════════

class PlatformParser:
    """
    Reads boarded-platform definitions from a plain-text config file.

    Format::

        BOARDED_PLATFORMS:
        # Comment lines and blank lines are ignored
        1,2,3,4
        10,11,12,13,14
    """

    def __init__(self, filepath: str | Path):
        self.platforms: list[list[int]] = []
        path = Path(filepath)
        if not path.exists():
            print(f"  [WARN] Platform file not found: {filepath}")
            return
        self._parse(path.read_text())

    def _parse(self, text: str):
        active = False
        for ln in text.splitlines():
            stripped = ln.strip()
            if "BOARDED_PLATFORMS" in stripped.upper():
                active = True
                continue
            if not active:
                continue
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue
            try:
                ids = [int(x.strip()) for x in stripped.split(",") if x.strip()]
                if len(ids) >= 3:
                    self.platforms.append(ids)
            except ValueError:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# 3.  MESH BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def build_pipe_network(
    nodes: dict[int, np.ndarray],
    members: list[tuple[int, int]],
    radius: float = PIPE_RADIUS,
    n_sides: int = PIPE_RESOLUTION,
) -> "pv.PolyData":
    """
    Build all scaffold pipes as a single PyVista PolyData via the
    fast tube filter — far more efficient than individual cylinders.
    """
    # Map node IDs to sequential indices
    node_ids = sorted(nodes)
    idx_map  = {nid: i for i, nid in enumerate(node_ids)}
    pts      = np.array([nodes[nid] for nid in node_ids], dtype=float)

    # Build lines array: [2, i0, i1,  2, i2, i3, …]
    lines = []
    for n1, n2 in members:
        if n1 in idx_map and n2 in idx_map:
            lines.extend([2, idx_map[n1], idx_map[n2]])

    if not lines:
        return pv.PolyData()

    poly       = pv.PolyData(pts)
    poly.lines = np.asarray(lines, dtype=np.int_)

    tubes = poly.tube(radius=radius, n_sides=n_sides, capping=True)
    return tubes.compute_normals(auto_orient_normals=True)


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _polygon_area_2d(poly: np.ndarray) -> float:
    x = poly[:, 0]
    y = poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _geom_eps(poly: np.ndarray) -> float:
    span = np.ptp(poly, axis=0)
    scale = max(float(np.linalg.norm(span)), 1.0)
    return scale * scale * 1e-10


def _remove_duplicate_footprint_points(pts3d: np.ndarray) -> np.ndarray:
    keep: list[int] = []
    seen: set[tuple[int, int]] = set()
    tol = 1e-7

    for idx, point in enumerate(pts3d):
        key = tuple(np.round(point[[0, 2]] / tol).astype(int))
        if key in seen:
            continue
        seen.add(key)
        keep.append(idx)

    return pts3d[keep]


def _remove_collinear_points(poly: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(poly) <= 3:
        return poly, np.arange(len(poly))

    keep: list[int] = []
    eps = _geom_eps(poly)
    n = len(poly)

    for i in range(n):
        prev_pt = poly[(i - 1) % n]
        cur_pt = poly[i]
        next_pt = poly[(i + 1) % n]
        v1 = cur_pt - prev_pt
        v2 = next_pt - cur_pt

        if np.linalg.norm(v1) <= eps or np.linalg.norm(v2) <= eps:
            continue
        if abs(_cross2(v1, v2)) <= eps and float(np.dot(v1, v2)) >= 0.0:
            continue
        keep.append(i)

    if len(keep) < 3:
        return poly, np.arange(len(poly))

    return poly[keep], np.asarray(keep, dtype=int)


def _on_segment(a: np.ndarray, b: np.ndarray, p: np.ndarray, eps: float) -> bool:
    return (
        min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
        and abs(_cross2(b - a, p - a)) <= eps
    )


def _segments_intersect(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
    eps: float,
) -> bool:
    o1 = _cross2(b - a, c - a)
    o2 = _cross2(b - a, d - a)
    o3 = _cross2(d - c, a - c)
    o4 = _cross2(d - c, b - c)

    if o1 * o2 < -eps and o3 * o4 < -eps:
        return True

    return (
        _on_segment(a, b, c, eps)
        or _on_segment(a, b, d, eps)
        or _on_segment(c, d, a, eps)
        or _on_segment(c, d, b, eps)
    )


def _polygon_is_simple(poly: np.ndarray) -> bool:
    n = len(poly)
    eps = _geom_eps(poly)

    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            c = poly[j]
            d = poly[(j + 1) % n]
            if _segments_intersect(a, b, c, d, eps):
                return False

    return True


def _angle_sorted_order(poly: np.ndarray) -> np.ndarray:
    center = poly.mean(axis=0)
    rel = poly - center
    angles = np.arctan2(rel[:, 1], rel[:, 0])
    distances = np.linalg.norm(rel, axis=1)
    return np.lexsort((distances, angles))


def _platform_outline_order(pts2d: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    candidates = [np.arange(len(pts2d), dtype=int)]
    angle_order = _angle_sorted_order(pts2d)
    if not np.array_equal(angle_order, candidates[0]):
        candidates.append(angle_order)

    for order in candidates:
        poly = pts2d[order]
        poly, keep = _remove_collinear_points(poly)
        order = order[keep]

        if len(poly) < 3:
            continue

        area = _polygon_area_2d(poly)
        if abs(area) <= _geom_eps(poly):
            continue

        if area < 0.0:
            poly = poly[::-1]
            order = order[::-1]

        if _polygon_is_simple(poly):
            return order, poly

    return None


def _point_in_triangle(
    p: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    eps: float,
) -> bool:
    c1 = _cross2(b - a, p - a)
    c2 = _cross2(c - b, p - b)
    c3 = _cross2(a - c, p - c)
    return c1 >= -eps and c2 >= -eps and c3 >= -eps


def _triangulate_polygon_2d(poly: np.ndarray) -> np.ndarray | None:
    n = len(poly)
    if n < 3:
        return None
    if n == 3:
        return np.array([[0, 1, 2]], dtype=int)

    eps = _geom_eps(poly)
    remaining = list(range(n))
    triangles: list[list[int]] = []
    guard = 0

    while len(remaining) > 3 and guard < n * n:
        guard += 1
        ear_found = False

        for pos, cur in enumerate(remaining):
            prev_i = remaining[pos - 1]
            next_i = remaining[(pos + 1) % len(remaining)]
            a = poly[prev_i]
            b = poly[cur]
            c = poly[next_i]

            if _cross2(b - a, c - a) <= eps:
                continue

            contains_other = False
            for other in remaining:
                if other in (prev_i, cur, next_i):
                    continue
                if _point_in_triangle(poly[other], a, b, c, eps):
                    contains_other = True
                    break

            if contains_other:
                continue

            triangles.append([prev_i, cur, next_i])
            del remaining[pos]
            ear_found = True
            break

        if not ear_found:
            return None

    triangles.append([remaining[0], remaining[1], remaining[2]])
    return np.asarray(triangles, dtype=int)


def build_platform_surface(
    corner_coords: list[np.ndarray],
    thickness: float = PLATFORM_THICK,
) -> "pv.PolyData | None":
    """
    Build a solid horizontal platform slab from footprint node coordinates.

    The selected nodes define the outside boundary of the platform in X/Z
    plan view, so concave footprints such as L-shapes keep their cut-outs
    instead of being filled as a convex triangulation.
    """
    pts = np.array(corner_coords, dtype=float)
    pts = _remove_duplicate_footprint_points(pts)
    n = len(pts)
    if n < 3:
        return None

    y_spread = float(np.ptp(pts[:, 1]))
    level_y = float(np.median(pts[:, 1]))
    if y_spread > 0.01:
        print(
            f"  [WARN] Platform node heights vary by {y_spread:.3f} m; "
            f"using median level Y={level_y:.3f} m"
        )

    pts2d = np.column_stack([pts[:, 0], pts[:, 2]])
    outline = _platform_outline_order(pts2d)
    if outline is None:
        print("  [WARN] Platform footprint could not be ordered; skipped")
        return None

    order, poly2d = outline
    tris = _triangulate_polygon_2d(poly2d)
    if tris is None:
        print("  [WARN] Platform footprint could not be triangulated; skipped")
        return None

    pts2d = pts2d[order]
    n = len(pts2d)

    half = thickness / 2.0
    top = np.column_stack([pts2d[:, 0], np.full(n, level_y + half), pts2d[:, 1]])
    bot = np.column_stack([pts2d[:, 0], np.full(n, level_y - half), pts2d[:, 1]])
    mesh_pts = np.vstack([top, bot])

    faces: list[int] = []
    for a, b, c in tris:
        # poly2d is CCW in X/Z, which maps to a downward 3D normal.
        # Reverse the top triangles so the visible platform face points up.
        faces.extend([3, int(c), int(b), int(a)])
        faces.extend([3, int(n + a), int(n + b), int(n + c)])

    for i in range(n):
        j = (i + 1) % n
        faces.extend([4, i, j, n + j, n + i])

    solid = pv.PolyData(mesh_pts, np.asarray(faces, dtype=np.int_))
    return solid.compute_normals(auto_orient_normals=True)

def build_base_plates(
    nodes: dict[int, np.ndarray],
    base_node_ids: list[int],
    plate_size: float = BASE_PLATE_SIZE,
    plate_thick: float = BASE_PLATE_THICK,
) -> "pv.PolyData | None":
    """
    Build a flat rectangular steel base plate at each base support node.

    Each plate is centred on the node in plan (X/Z) and sits below the node
    in the vertical (Y) direction, simulating the base plate resting on ground.
    """
    meshes: list[pv.PolyData] = []
    hw = plate_size / 2.0
    for nid in base_node_ids:
        if nid not in nodes:
            continue
        nx, ny, nz = float(nodes[nid][0]), float(nodes[nid][1]), float(nodes[nid][2])
        plate = pv.Box(bounds=[
            nx - hw,          nx + hw,
            ny - plate_thick, ny,
            nz - hw,          nz + hw,
        ])
        meshes.append(plate)
    if not meshes:
        return None
    merged = meshes[0]
    for m in meshes[1:]:
        merged = merged.merge(m)
    return merged.compute_normals(auto_orient_normals=True)


# ══════════════════════════════════════════════════════════════════════════════
# 4.  SCAFFOLD RENDERER
# ══════════════════════════════════════════════════════════════════════════════

class ScaffoldRenderer:
    """
    Orchestrates building and rendering the 3D scaffold model using PyVista.

    Parameters
    ----------
    staad : StaadParser
        Parsed STAAD geometry.
    """

    def __init__(self, staad: StaadParser):
        if not _PYVISTA:
            raise RuntimeError(
                "PyVista is required.  Install with:  pip install pyvista"
            )
        self.staad   = staad
        self.plotter: pv.Plotter | None = None

    def render(
        self,
        platforms:        list[list[int]] | None = None,
        output_path:      str  | Path            = "scaffold_render.png",
        width:            int                    = RENDER_WIDTH,
        height:           int                    = RENDER_HEIGHT,
        pipe_radius:      float                  = PIPE_RADIUS,
        azimuth_deg:      float                  = CAM_AZIMUTH_DEG,
        elevation_deg:    float                  = CAM_ELEVATION_DEG,
        show_interactive: bool                   = False,
        export_jpg:       bool                   = True,
    ) -> None:
        """
        Build, light, camera-position, and export the scaffold render.

        Parameters
        ----------
        platforms :
            List of node-ID lists defining boarded platform polygons.
        output_path :
            PNG output path.  A matching .jpg is also saved by default.
        width / height :
            Render resolution in pixels.
        pipe_radius :
            Scaffold tube radius in metres.
        azimuth_deg :
            Camera horizontal angle in XZ plane (0° = +X direction).
        elevation_deg :
            Camera angle above the horizontal plane.
        show_interactive :
            Open the interactive PyVista viewer before exporting.
        export_jpg :
            Also save a JPEG alongside the PNG.
        """
        output_path = Path(output_path)

        print("\n─── Building pipe geometry ──────────────────────────────")
        pipes = build_pipe_network(
            self.staad.nodes, self.staad.members,
            radius=pipe_radius, n_sides=PIPE_RESOLUTION
        )
        print(f"    {len(self.staad.members)} members → "
              f"{pipes.n_points:,} pts / {pipes.n_cells:,} cells")

        print("─── Building platform geometry ──────────────────────────")
        plat_meshes: list[pv.PolyData] = []
        if platforms:
            for node_ids in platforms:
                coords = [self.staad.nodes[nid] for nid in node_ids
                          if nid in self.staad.nodes]
                if len(coords) < 3:
                    continue
                m = build_platform_surface(coords)
                if m is not None:
                    plat_meshes.append(m)
            print(f"    {len(plat_meshes)} platform surface(s) built")
        else:
            print("    (none defined)")

        print("─── Building base plate geometry ────────────────────────")
        base_plate_mesh = None
        if self.staad.base_node_ids:
            base_plate_mesh = build_base_plates(
                self.staad.nodes, self.staad.base_node_ids
            )
            if base_plate_mesh is not None:
                print(f"    {len(self.staad.base_node_ids)} base plate(s) built")
            else:
                print("    (no valid base nodes found)")
        else:
            print("    (no base support nodes identified)")

        print("─── Configuring renderer ────────────────────────────────")
        self.plotter = pv.Plotter(off_screen=True, window_size=[width, height])
        self.plotter.set_background(BG_COLOR)

        # ── Add scaffold pipes ─────────────────────────────────────────────────
        self.plotter.add_mesh(
            pipes,
            color=PIPE_COLOR,
            smooth_shading=True,
            ambient=AMBIENT,
            diffuse=DIFFUSE,
            specular=SPECULAR_PIPE,
            specular_power=SPECULAR_PWR,
            show_edges=False,
            render=False,
        )

        # ── Add platform surfaces ──────────────────────────────────────────────
        for pm in plat_meshes:
            self.plotter.add_mesh(
                pm,
                color=PLATFORM_COLOR,
                smooth_shading=True,
                ambient=AMBIENT,
                diffuse=DIFFUSE + 0.05,
                specular=SPECULAR_PLAT,
                specular_power=SPECULAR_PWR / 4,
                show_edges=False,
                render=False,
            )

        # ── Add base plates ────────────────────────────────────────────────────
        if base_plate_mesh is not None:
            self.plotter.add_mesh(
                base_plate_mesh,
                color=BASE_PLATE_COLOR,
                smooth_shading=True,
                ambient=AMBIENT,
                diffuse=DIFFUSE,
                specular=SPECULAR_PIPE,
                specular_power=SPECULAR_PWR,
                show_edges=False,
                render=False,
            )

        self._setup_lighting()
        self._setup_camera(azimuth_deg, elevation_deg)

        if show_interactive:
            self.plotter.show()

        # ── Export PNG ────────────────────────────────────────────────────────
        print("─── Exporting images ────────────────────────────────────")
        self.plotter.screenshot(str(output_path), transparent_background=False)
        print(f"    PNG  → {output_path}")

        if export_jpg:
            jpg_path = output_path.with_suffix(".jpg")
            self.plotter.screenshot(str(jpg_path), transparent_background=False)
            print(f"    JPG  → {jpg_path}")

        self.plotter.close()

    # ── Private helpers ────────────────────────────────────────────────────────

    def _setup_lighting(self) -> None:
        """
        Three-point lighting rig appropriate for white-background
        industrial engineering visualisation.
        """
        self.plotter.remove_all_lights()

        # Key light  — upper front-right  → primary illumination + sheen
        self.plotter.add_light(pv.Light(
            position=(12.0, 18.0,  8.0),
            focal_point=(0.0, 0.0, 0.0),
            color="white",
            intensity=LIGHT_KEY_INTENSITY,
        ))

        # Fill light — opposite side      → lift shadow darkness
        self.plotter.add_light(pv.Light(
            position=(-10.0, 6.0, -6.0),
            focal_point=(0.0, 0.0, 0.0),
            color="#E0EEFF",
            intensity=LIGHT_FILL_INTENSITY,
        ))

        # Rim light  — behind / below     → separate model from background
        self.plotter.add_light(pv.Light(
            position=(0.0, -8.0, 14.0),
            focal_point=(0.0, 0.0, 0.0),
            color="#FFFFFF",
            intensity=LIGHT_RIM_INTENSITY,
        ))

    def _setup_camera(self, azimuth_deg: float, elevation_deg: float) -> None:
        """
        Position the camera at the requested azimuth/elevation relative to
        the model's bounding-box centroid.  Y is the vertical axis.
        """
        # Pull bounds from the plotter
        b   = self.plotter.bounds   # [xmin,xmax, ymin,ymax, zmin,zmax]
        cx  = (b[0] + b[1]) / 2.0
        cy  = (b[2] + b[3]) / 2.0
        cz  = (b[4] + b[5]) / 2.0

        diag = np.sqrt(
            (b[1] - b[0]) ** 2 +
            (b[3] - b[2]) ** 2 +
            (b[5] - b[4]) ** 2
        )
        dist = diag * CAM_DIST_FACTOR

        # Convert degrees → radians
        az  = np.radians(azimuth_deg)
        el  = np.radians(elevation_deg)

        # Camera position in STAAD coordinates (Y = up)
        off_x = dist * np.cos(el) * np.cos(az)
        off_y = dist * np.sin(el)
        off_z = dist * np.cos(el) * np.sin(az)

        self.plotter.camera.position    = (cx + off_x, cy + off_y, cz + off_z)
        self.plotter.camera.focal_point = (cx, cy, cz)
        self.plotter.camera.up          = (0.0, 1.0, 0.0)   # Y is vertical
        self.plotter.camera.view_angle  = CAM_FOV_DEG

        self.plotter.reset_camera()


# ══════════════════════════════════════════════════════════════════════════════
# 5.  COMMAND-LINE INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="scaffold_renderer.py",
        description="STAAD.Pro Scaffold 3D Renderer — professional engineering visualisation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
              python scaffold_renderer.py scaffold.std
              python scaffold_renderer.py scaffold.std --platforms platforms.txt
              python scaffold_renderer.py scaffold.std --output my_render.png --interactive
              python scaffold_renderer.py scaffold.std --width 3840 --height 2160
              python scaffold_renderer.py scaffold.std --azimuth 135 --elevation 35

            Platform config file (platforms.txt)
            ------------------------------------
              BOARDED_PLATFORMS:
              1,2,3,4
              10,11,12,13
        """),
    )
    ap.add_argument("input",
                    help="STAAD .std geometry file")
    ap.add_argument("--platforms", "-p",
                    metavar="FILE",
                    help="Boarded-platform config file")
    ap.add_argument("--output", "-o",
                    default="scaffold_render.png",
                    metavar="FILE",
                    help="Output image path  (default: scaffold_render.png)")
    ap.add_argument("--width",
                    type=int, default=RENDER_WIDTH,
                    help=f"Render width in pixels  (default: {RENDER_WIDTH})")
    ap.add_argument("--height",
                    type=int, default=RENDER_HEIGHT,
                    help=f"Render height in pixels  (default: {RENDER_HEIGHT})")
    ap.add_argument("--pipe-radius",
                    type=float, default=PIPE_RADIUS,
                    metavar="M",
                    help=f"Scaffold tube radius in metres  (default: {PIPE_RADIUS})")
    ap.add_argument("--azimuth",
                    type=float, default=CAM_AZIMUTH_DEG,
                    metavar="DEG",
                    help=f"Camera azimuth in XZ plane, degrees  (default: {CAM_AZIMUTH_DEG})")
    ap.add_argument("--elevation",
                    type=float, default=CAM_ELEVATION_DEG,
                    metavar="DEG",
                    help=f"Camera elevation above horizontal  (default: {CAM_ELEVATION_DEG})")
    ap.add_argument("--interactive",
                    action="store_true",
                    help="Open interactive 3D viewer before saving")
    ap.add_argument("--no-jpg",
                    action="store_true",
                    help="Do not export a JPEG alongside the PNG")
    return ap


def main(argv=None):
    ap   = _build_arg_parser()
    args = ap.parse_args(argv)

    # ── Read STAAD file ───────────────────────────────────────────────────────
    src = Path(args.input)
    if not src.exists():
        ap.error(f"Input file not found: {src}")

    print(f"\nScaffold Renderer")
    print(f"  Input : {src}")
    print(f"  Output: {args.output}")
    print(f"  Size  : {args.width} × {args.height} px\n")

    print("─── Parsing STAAD geometry ──────────────────────────────")
    staad = StaadParser(src.read_text())
    print(staad.summary())

    # ── Platform config ───────────────────────────────────────────────────────
    platforms: list[list[int]] = []
    if args.platforms:
        print("\n─── Parsing platform config ─────────────────────────────")
        pp = PlatformParser(args.platforms)
        platforms = pp.platforms
        print(f"    {len(platforms)} platform polygon(s) loaded")

    # ── Render ────────────────────────────────────────────────────────────────
    renderer = ScaffoldRenderer(staad)
    renderer.render(
        platforms        = platforms,
        output_path      = args.output,
        width            = args.width,
        height           = args.height,
        pipe_radius      = args.pipe_radius,
        azimuth_deg      = args.azimuth,
        elevation_deg    = args.elevation,
        show_interactive = args.interactive,
        export_jpg       = not args.no_jpg,
    )

    print("\n✓  Render complete.")


# ══════════════════════════════════════════════════════════════════════════════
# 6.  PROGRAMMATIC API  (import and call directly in Python)
# ══════════════════════════════════════════════════════════════════════════════

def render_from_string(
    staad_content: str,
    output_path:   str | Path    = "scaffold_render.png",
    platforms:     list[list[int]] | None = None,
    **kwargs,
) -> None:
    """
    Convenience function — render directly from a STAAD geometry string.

    Parameters
    ----------
    staad_content :
        Full text of a STAAD .std file (or just the JOINT/MEMBER sections).
    output_path :
        Output PNG path.
    platforms :
        List of platform node-ID polygons, e.g. [[1,2,3,4], [10,11,12,13]].
    **kwargs :
        Forwarded to :meth:`ScaffoldRenderer.render` (width, height,
        pipe_radius, azimuth_deg, elevation_deg, show_interactive).

    Example
    -------
    >>> from scaffold_renderer import render_from_string
    >>> render_from_string(open("scaffold.std").read(), "out.png",
    ...                    platforms=[[1,2,3,4]], width=3840, height=2160)
    """
    staad = StaadParser(staad_content)
    print(staad.summary())
    renderer = ScaffoldRenderer(staad)
    renderer.render(platforms=platforms, output_path=output_path, **kwargs)


if __name__ == "__main__":
    main()
