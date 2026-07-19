# A-Frame Scaffold Report Generator
Generates a professional, NLNG-branded PDF scaffold design report from
STAAD.Pro output files. Built for ARCO M&E — NLNG Bonny Island.

---

## Setup (one-time)

```bash
pip install jinja2 playwright Pillow pypdf
playwright install chromium
```

> If WeasyPrint fails to install (it needs Cairo/Pango system libraries),
> the script still generates a fully functional HTML file you can open in
> Chrome/Edge and print to PDF with Ctrl+P → "Save as PDF".

---

## Workflow — Every New Job

1. **Fill in** `inputs/project_info.txt` with document number, personnel, etc.

2. **Paste** your STAAD.Pro `.std` file content into `inputs/staad_command.txt`

3. **Paste** your STAAD.Pro `.out` file content into `inputs/staad_output.txt`

4. **Drop logos** into `logo/`:
   - `nlng_logo.png` → NLNG logo
   - `company_logo.png` → ARCO M&E logo
   - *(or set URLs in `logo/logo_url.txt` — URL takes priority over PNG)*

5. **Choose drawing integration** in `inputs/project_info.txt`:
   - `ENGINEERING_DRAWING_FORMAT: standard` uses `generate_scaffold_dxf.py`
   - `ENGINEERING_DRAWING_FORMAT: grid` uses `generate_scaffold_grid_dxf.py`
   - `ENGINEERING_DRAWING_FORMAT: none` skips drawing PDF generation

   You can also override it per run:
   ```bash
   python generate_report.py --drawing-format grid
   ```

6. **Drop screenshots** into `images/` (see `images/README.txt` for exact names).
   `3d_model.png` is generated automatically from `inputs/staad_command.txt`
   when the sibling `3D Renderer` project is available.
   Any missing images show as placeholder boxes — add them later and re-run.

7. **Run:**
   ```bash
   python generate_report.py
   ```

8. **Collect output** from the `output/` folder:
   - `<DOC_NO>_Report.html`
   - `<DOC_NO>_Report.pdf`  *(with the four engineering drawings appended when PDF generation succeeds and `pypdf` is installed)*

---

## What Gets Auto-Parsed from STAAD Files

| Value | Source | Method |
|---|---|---|
| Scaffold H, W, D | `.std` | Max Y, X, Z from JOINT COORDINATES |
| Lift heights | `.std` | Distinct Y levels |
| KFX spring stiffness | `.std` | SUPPORTS line |
| Chain hoist load | `.std` | FY in JOINT LOAD |
| Impact loads | `.std` | FX, FZ in JOINT LOAD |
| Tie node positions | `.std` | FIXED BUT FY nodes |
| Load combinations | `.std` | LOAD COMB lines |
| Wind totals (WLX, WLZ) | `.out` | SUMMATION FORCE-X/Z |
| Max UC ratio + member | `.out` | Code check block |
| Max axial force | `.out` | FX column in code check |
| Max displacements | `.out` | MAXIMUM DISPLACEMENTS |

## What Gets Calculated

| Item | Inputs |
|---|---|
| Wind UDL (EN 1991-1-4 chain) | Height from `.std` + fixed NLNG params |
| Frictional resistance | KFX from `.std` (back-calculated: Resistance = KFX, FR = KFX×0.15, Max_fy = FR/0.3) |
| SWL | Chain hoist FY (CL = static weight × 1.25) |
| Deflection allowables | L/100 (vertical), L/200 (horizontal) |
| Installation notes | Auto-generated from geometry + tie node positions |

---

## Fixed NLNG Wind Parameters

These are constant for all Bonny Island jobs — only height changes:

| Parameter | Value |
|---|---|
| V₃ (3-sec gust) | 36 m/s |
| V₃ / V₃₆₀₀ | 1.52 |
| V₆₀₀ / V₃₆₀₀ | 1.06 |
| V_b (basic wind speed) | 25.11 m/s |
| z₀ (Terrain 0) | 0.003 m |
| z₀,ᵢᵢ (Terrain II) | 0.05 m |
| Air density ρ | 1.25 kg/m³ |
| Force coefficient Cₓ | 1.2 |
| Tube diameter (Af) | 0.048 m |

---

## Output Layout (10 Pages)

| Page | Content |
|---|---|
| 1 | Cover — logos, project info, signatures |
| 2 | General Note, Material Properties, 3D Model, Load Summary |
| 3 | Model Geometry (plan + elevations) |
| 4 | Load Cases (chain hoist, impact, with diagrams) |
| 5 | Wind Load Diagrams + EN 1991-1-4 calculation table |
| 6 | Load Combinations (from STAAD file) |
| 7 | UC Ratio Summary (all members, PASS/FAIL) |
| 8 | Connection Stability (Table C.1) + Frictional Resistance |
| 9 | Deflection Check (vertical + horizontal) |
| 10 | Conclusion, Recommendations, Installation Notes |
