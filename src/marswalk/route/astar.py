"""A* over the 1 m DTM grid, compiled with numba.

TODO(M3). Design:
- `_astar_core` is `@numba.njit(cache=True)` and takes only arrays and scalars: elevation, slope_5m,
  roughness, sand (float32), nogo (bool), pixel_m, the cost model's `kernel` (an njit dispatcher
  passed as a first-class function) and `params`, `min_rate`, start/goal (r, c), and a crop window.
  Open set = numba typed heap of (f, g, idx) tuples; came_from = int64 array; 8-connected.
- Python wrapper `astar()`:
  - crops to the bbox of (start, goal) + margin_m (default 300 m), and widens and retries once if unreachable
  - snaps a no-go start/goal to the nearest traversable cell within 10 m and records it in Path.snapped
  - accumulates distance, time_s, energy_kj, climb and descent along the returned cells
- Performance target: one Gale leg (≤ 500 m) in < 2 s after JIT warm-up. Pure-Python A* on this grid
  would take minutes per leg, which is why the A* must be compiled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from marswalk.cost.base import CostModel
from marswalk.layers.stack import LayerStack


@dataclass
class Path:
    cells: list[tuple[int, int]]
    cost: float
    distance_m: float
    time_s: float
    energy_kj: float
    climb_m: float = 0.0
    descent_m: float = 0.0
    snapped: dict[str, tuple[int, int]] = field(default_factory=dict)


def astar(stack: LayerStack, model: CostModel, start: tuple[int, int], goal: tuple[int, int],
          margin_m: float = 300.0) -> Path | None:
    raise NotImplementedError("M3: numba A* with directional edge kernels")
