# Scaffold Report Generator

Generates an NLNG-branded scaffold design report from STAAD.Pro command and output files. This Desktop `SCAFFOLD` copy is intended for general scaffold types such as independent, tower, birdcage, hanging, cantilever, and composite scaffolds.

## Setup

```bash
pip install jinja2 playwright Pillow pypdf
playwright install chromium
```

If browser PDF generation is unavailable, open the generated HTML in Chrome or Edge and print to PDF.

## Workflow

1. Fill `inputs/project_info.txt` with project, scaffold, personnel, SWL, and optional equipment details.
2. Paste the STAAD.Pro `.std` content into `inputs/staad_command.txt`.
3. Paste the STAAD.Pro `.out` content into `inputs/staad_output.txt`.
4. Drop logos into `logo/` as `nlng_logo.png` and `company_logo.png`, or set URLs in `logo/logo_url.txt`.
5. Drop screenshots into `images/` using the names in `images/README.txt`.
6. Run `python generate_report.py`.
7. Collect the generated HTML and PDF from `output/`.

## Key Project Info Fields

| Field | Purpose |
|---|---|
| `SCAFFOLD_TYPE` | Used in title text, description, and scaffold-specific sections such as hanging-scaffold friction omission. |
| `EQUIPMENT_NAME`, `EQUIPMENT_TAG`, `LINE_NUMBER`, `WORK_ORDER` | Added to the brief description when provided. Each field can stand alone. `EQUIPMENT_TAG` and `LINE_NUMBER` are alternatives for jobs without an equipment tag (e.g. line-only work) — fill in only whichever applies; `EQUIPMENT_TAG` takes precedence if both are set. |
| `SAFE_WORKING_LOAD`, `SAFE_WORKING_LOAD_KN_M2`, `SERVICE_LOAD_KN_M2`, `LOAD_INTENSITY_KN_M2` | Optional SWL/service-load intensity in kN/m2. These override inferred values. |
| `LOAD_CLASS` | Optional load class 1-6. Used when no direct kN/m2 intensity is provided. |
| `TRIBUTARY_WIDTH_M` | Optional override for platform live-load tributary width. Leave blank to auto-infer edge tributary width as half the smallest plan bay spacing. |
| `CATEGORY_1_ASSURANCE_NOTE` | Defaults to yes; controls the category 1 assurance note below SWL. |

## STAAD Values Parsed

| Value | Source | Method |
|---|---|---|
| Scaffold height, length, width | `.std` | Maximum Y, X, and Z joint coordinates |
| Lift heights | `.std` | Distinct Y levels |
| KFX spring stiffness | `.std` | SUPPORTS line |
| Platform live load | `.std` / `.out` | LL member UDL and applied-load summary |
| Handrail loads | `.std` / `.out` | HLX/HLZ member UDL and applied-load summary |
| Tie node positions | `.std` | FIXED BUT FY nodes |
| Load combinations | `.std` | LOAD COMB lines |
| Wind totals | `.out` | SUMMATION FORCE-X/Z |
| Maximum UC ratio and member | `.out` | Code check block |
| Maximum axial force | `.out` | FX column in code check |
| Maximum displacements | `.out` | MAXIMUM DISPLACEMENTS |

## Calculations

| Item | Inputs |
|---|---|
| SWL | Project info first; otherwise highest platform live-load intensity from STAAD line load divided by tributary width |
| Platform live-load working | Service load (kN/m2) x tributary width (m) = member line load (kN/m) |
| Auto tributary width | Smallest plan bay spacing / 2 when `TRIBUTARY_WIDTH_M` is blank |
| Wind UDL | Height from `.std` and fixed NLNG wind parameters |
| Frictional resistance | KFX from `.std`; Resistance = KFX, FR = KFX x 0.15, Max_fy = FR / 0.3 |
| Coupler class | EN 12811 Table C.1: Class A up to 10 kN, Class B up to 15 kN |
| Deflection allowables | L/100 vertical, L/200 horizontal |

## Fixed NLNG Wind Parameters

| Parameter | Value |
|---|---|
| V3, 3-sec gust | 36 m/s |
| V3 / V3600 | 1.52 |
| V600 / V3600 | 1.06 |
| Vb basic wind speed | 25.11 m/s |
| z0, Terrain 0 | 0.003 m |
| z0, Terrain II | 0.05 m |
| Air density rho | 1.25 kg/m3 |
| Force coefficient Cf | 1.2 |
| Tube diameter Af | 0.048 m |

## Output Layout

| Page | Content |
|---|---|
| 1 | Cover, logos, project info, signatures |
| 2 | General note, material properties, 3D model, load summary |
| 3 | Model geometry |
| 4 | Load cases |
| 5 | Wind load diagrams and EN 1991-1-4 calculation table |
| 6 | Load combinations |
| 7 | UC ratio summary, highest 50 members |
| 8 | Connection stability and frictional resistance |
| 9 | Deflection check |
| 10 | Conclusion, recommendations, installation notes |
