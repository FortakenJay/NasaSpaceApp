"""Weighted hazard-score cost: simple, tunable, used to compare routes with the metabolic model.

TODO(M3). Design (kernel becomes @numba.njit):
  cost = run_m * (w_distance + w_slope * slope5_deg + w_roughness * rough_m + w_sand * sand)
- time_s / energy_kj: the shared speed/energy helper, so timelines compare across models.
- min_rate = w_distance (the other terms are >= 0), so the heuristic stays admissible.
"""
from __future__ import annotations

import numpy as np

PARAM_ORDER = ("w_distance", "w_slope", "w_roughness", "w_sand")


def kernel(params, dz_m, run_m, slope5_deg, rough_m, sand):  # becomes @numba.njit in M3
    raise NotImplementedError("M3: weighted edge kernel")


class WeightedHazardCostModel:
    name = "weighted"

    def __init__(self, cfg: dict):
        self.params = np.array([float(cfg[k]) for k in PARAM_ORDER], dtype=np.float64)
        self.kernel = kernel

    def min_rate(self) -> float:
        return float(self.params[0])
