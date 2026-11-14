"""SEXTANT-style metabolic cost for a suited walker, scaled to Mars gravity.

TODO(M3). Design:
- Energy per metre E(grade) from a walking-on-slope metabolic model. Candidates to evaluate:
  the model SEXTANT used (MIT/NASA, BASALT) and the suited data in Kluis et al. 2022.
  Pick one, cite it in docs/ARCHITECTURE.md, and keep the formula in `kernel`.
- Gravity scaling: load-dependent terms scale with g_mars / g_earth (3.71 / 9.81); suit mass is
  added to body mass.
- Grade = dz_m / run_m (signed). Multipliers: (1 + roughness_penalty_per_m * rough_m), and
  sand_penalty when sand = 1.
- time_s from the shared speed(grade) helper, the same one the weighted model uses.
- min_rate = min over grades of E(grade), so the A* heuristic stays admissible.
"""
from __future__ import annotations

import numpy as np

PARAM_ORDER = ("gravity_mps2", "earth_gravity_mps2", "body_mass_kg", "suit_mass_kg",
               "roughness_penalty_per_m", "sand_penalty")


def kernel(params, dz_m, run_m, slope5_deg, rough_m, sand):  # becomes @numba.njit in M3
    raise NotImplementedError("M3: metabolic edge kernel")


class MetabolicCostModel:
    name = "metabolic"

    def __init__(self, cfg: dict):
        self.params = np.array([float(cfg[k]) for k in PARAM_ORDER], dtype=np.float64)
        self.kernel = kernel

    def min_rate(self) -> float:
        raise NotImplementedError("M3: metabolic min_rate")
