"""
EN 1991-1-4:2005 Wind Load Calculator
Fixed parameters for NLNG Bonny Island — only height varies per job.
"""
import math


class WindCalculator:
    # ── Fixed NLNG Bonny Island parameters ────────────────────────────────────
    V3          = 36.0      # 3-second gust wind speed (m/s)
    V3_V3600    = 1.52      # V3 / V3600 ratio
    V600_V3600  = 1.06      # V600 / V3600 ratio
    Z0          = 0.003     # Roughness length, Terrain category 0 (m)
    Z0_II       = 0.05      # Terrain category II reference roughness length (m)
    Z_MIN       = 1.0       # Minimum height zmin (m)
    RHO         = 1.25      # Air density (kg/m³)
    CF          = 1.2       # Force coefficient for circular tube
    D_TUBE      = 0.0483    # Tube outer diameter = 48.3 mm (m)
    K1          = 1.0       # Turbulence factor k1
    CO          = 1.0       # Orography factor Co(z)

    def __init__(self, height):
        self.z_raw = float(height)
        self.z     = max(self.z_raw, self.Z_MIN)   # apply zmin floor

    def calculate(self):
        z   = self.z
        z0  = self.Z0
        z0ii = self.Z0_II

        # ── Basic wind speed ──────────────────────────────────────────────────
        vb = (self.V600_V3600 / self.V3_V3600) * self.V3    # EN 4.2

        # ── Terrain factor ────────────────────────────────────────────────────
        kr = 0.19 * (z0 / z0ii) ** 0.07                     # EN 4.3(2)

        # ── Roughness factor (case 1: zmin ≤ z) ──────────────────────────────
        cr = kr * math.log(z / z0)                           # EN 4.3(1)

        # ── Mean wind velocity ────────────────────────────────────────────────
        vm = cr * self.CO * vb                               # EN 4.3(1)

        # ── Turbulence intensity ──────────────────────────────────────────────
        iv = self.K1 / (self.CO * math.log(z / z0))         # EN 4.4(1)

        # ── Peak velocity pressure (N/m²) ─────────────────────────────────────
        qp = (1 + 7 * iv) * 0.5 * self.RHO * vm ** 2       # EN 4.5(1)

        # ── Wind load per unit length (kN/m) ──────────────────────────────────
        af       = self.D_TUBE
        wind_udl = self.CF * qp / 1000 * af

        return {
            # inputs
            'z':          self.z_raw,
            'z_used':     z,
            'v3':         self.V3,
            'v3_v3600':   self.V3_V3600,
            'v600_v3600': self.V600_V3600,
            'vb':         round(vb, 2),
            'z0':         z0,
            'z0_ii':      z0ii,
            'zmin':       self.Z_MIN,
            # computed
            'kr':         round(kr, 4),
            'cr':         round(cr, 4),
            'vm':         round(vm, 3),
            'k1':         self.K1,
            'co':         self.CO,
            'iv':         round(iv, 4),
            'rho':        self.RHO,
            'qp_nm2':     round(qp, 4),
            'qp_knm2':    round(qp / 1000, 6),
            'cf':         self.CF,
            'af':         round(af, 4),
            'wind_udl':   round(wind_udl, 6),
        }
