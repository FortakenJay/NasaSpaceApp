"""Cost model interface, shaped for a numba-compiled A*.

Cost is DIRECTIONAL (walking uphill costs more than downhill), so a model prices an EDGE between two
neighbouring cells, not a cell. Route search runs over ~11 M cells (Gale strip, 1 m), so the edge
function must be a numba `@njit` kernel the compiled A* can call. A Python callback per edge would
take minutes per leg.

Contract every model implements:
    name:    str
    params:  1-D float64 array (built from eva.cost.<name>), the kernel's only configuration
    kernel:  @njit (params, dz_m, run_m, slope5_deg, rough_m, sand) -> (cost, time_s, energy_kj)
             dz_m signed (uphill > 0); run_m = 1 or sqrt(2) times pixel_m; sand is 0.0 or 1.0
    min_rate(): cheapest possible cost per metre, used by the admissible A* heuristic
Both models fill time_s and energy_kj the same way (cost.physics.edge_time_energy), so timelines and
consumables stay comparable when only the route-choosing cost differs.
"""
from __future__ import annotations

from typing import Callable, Protocol

import numpy as np

EdgeKernel = Callable[[np.ndarray, float, float, float, float, float], tuple[float, float, float]]


class CostModel(Protocol):
    name: str
    params: np.ndarray
    kernel: EdgeKernel

    def min_rate(self) -> float: ...


def get_cost_model(name: str, params: dict, physics: dict | None = None) -> CostModel:
    """Factory. `params` is the matching eva.cost.<name> table; `physics` is eva.cost.metabolic, which
    holds the walking-physics parameters both models share (defaults apply when it is omitted)."""
    if name == "metabolic":
        from marswalk.cost.metabolic import MetabolicCostModel
        return MetabolicCostModel(params, physics)
    if name == "weighted":
        from marswalk.cost.weighted import WeightedHazardCostModel
        return WeightedHazardCostModel(params, physics)
    raise ValueError(f"unknown cost model {name!r} (expected 'metabolic' or 'weighted')")


def model_from_eva(eva, name: str | None = None) -> CostModel:
    name = name or eva.cost_model
    return get_cost_model(name, eva.cost.get(name, {}), eva.cost.get("metabolic"))
