"""SEXTANT-style metabolic cost for a suited walker, scaled to Mars gravity.

Route cost = metabolic energy (kJ). The walking model lives in cost.physics (speed vs grade, Santee-form
metabolic power, gravity scaling, roughness and sand multipliers) and is shared with the weighted model.
params = the 8-value physics block (cost.physics.PHYSICS_ORDER).
"""
from __future__ import annotations

import numba
import numpy as np

from marswalk.cost import physics as ph

PARAM_ORDER = ph.PHYSICS_ORDER


@numba.njit(cache=True)
def kernel(params, dz_m, run_m, slope5_deg, rough_m, sand):
    t, e = ph.edge_time_energy(params[0], params[1], params[2] + params[3], params[4], params[5], params[6],
                               dz_m, run_m, rough_m, sand, params[7])
    return e, t, e


class MetabolicCostModel:
    name = "metabolic"
    unit = "kJ"

    def __init__(self, cfg: dict, physics: dict | None = None):
        self.params = np.array(ph.physics_params({**(physics or {}), **cfg}), dtype=np.float64)
        self.kernel = kernel

    def min_rate(self) -> float:
        """Cheapest energy per horizontal metre over all walkable grades (admissible A* heuristic)."""
        best = np.inf
        for grade in np.arange(-self.params[ph.MAX_GRADE], self.params[ph.MAX_GRADE] + 0.01, 0.25):
            c, _, _ = kernel(self.params, float(np.tan(np.radians(grade))), 1.0, 0.0, 0.0, 0.0)
            best = min(best, c)
        return float(best)
