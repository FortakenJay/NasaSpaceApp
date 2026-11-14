"""Weighted hazard-score cost: simple, tunable, used to compare routes with the metabolic model.

  cost = run_m * (w_distance + w_slope * slope5_deg + w_roughness * rough_m + w_sand * sand)
time_s / energy_kj come from the shared walking physics (cost.physics), so timelines compare across models.
min_rate = w_distance (the other terms are >= 0), so the A* heuristic stays admissible.
params = 4 weights followed by the 7-value physics block.
"""
from __future__ import annotations

import math

import numba
import numpy as np

from marswalk.cost import physics as ph

PARAM_ORDER = ("w_distance", "w_slope", "w_roughness", "w_sand")


@numba.njit(cache=True)
def kernel(params, dz_m, run_m, slope5_deg, rough_m, sand):
    t, e = ph.edge_time_energy(params[4], params[5], params[6] + params[7], params[8], params[9], params[10],
                               dz_m, run_m, rough_m, sand)
    if t == math.inf:
        return math.inf, t, e
    cost = run_m * (params[0] + params[1] * slope5_deg + params[2] * max(rough_m, 0.0) + params[3] * sand)
    return cost, t, e


class WeightedHazardCostModel:
    name = "weighted"
    unit = "score"

    def __init__(self, cfg: dict, physics: dict | None = None):
        self.params = np.array([float(cfg[k]) for k in PARAM_ORDER] + ph.physics_params(physics), dtype=np.float64)
        self.kernel = kernel

    def min_rate(self) -> float:
        return float(self.params[0])
