"""Least-cost search over the DTM grid, compiled with numba.

One compiled core (`_search`) serves two uses:
- astar(start, goal): goal-directed (A* with an admissible straight-line heuristic), cropped to the leg.
- cost_field(source): Dijkstra from one cell to every cell. With reverse=True the field holds the cost of
  walking FROM each cell TO the source, which is the walk-back cost. The walk-back safe zone, the
  walk-back margin along a route and "route to wherever I click" all read from that one field.

Edges are 8-connected and DIRECTIONAL (uphill costs more than downhill). The cost model's njit `kernel`
prices each edge. Hard rules: no-go cells are never entered, and a diagonal step may not cut the corner
of a no-go cell. Edge grades come from stack.walk_elev_m (stride-scale smoothed DTM) when present.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numba
import numpy as np

from marswalk.cost.base import CostModel
from marswalk.layers.stack import LayerStack

SQRT2 = math.sqrt(2.0)


@numba.njit
def _search(elev, slope5, rough, sand, nogo, pixel_m, kernel, params,
            sr, sc, gr, gc, hrate, reverse, max_cost, max_radius_px):
    H, W = elev.shape
    N = H * W
    g = np.full(N, np.inf)
    tt = np.full(N, np.inf, np.float32)
    ee = np.full(N, np.inf, np.float32)
    prev = np.full(N, -1, np.int32)
    done = np.zeros(N, np.bool_)
    src = np.int64(sr * W + sc)
    goal = np.int64(gr * W + gc) if gr >= 0 else np.int64(-1)
    g[src] = 0.0
    tt[src] = 0.0
    ee[src] = 0.0
    heap = [(0.0, src)]
    drs = (-1, -1, -1, 0, 0, 1, 1, 1)
    dcs = (-1, 0, 1, -1, 1, -1, 0, 1)
    r2max = max_radius_px * max_radius_px
    while len(heap) > 0:
        _, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        if u == goal:
            break
        gu = g[u]
        if gu > max_cost:
            break
        r = u // W
        c = u % W
        for k in range(8):
            rr = r + drs[k]
            cc = c + dcs[k]
            if rr < 0 or rr >= H or cc < 0 or cc >= W or nogo[rr, cc]:
                continue
            v = rr * W + cc
            if done[v]:
                continue
            diag = drs[k] != 0 and dcs[k] != 0
            if diag and (nogo[r, cc] or nogo[rr, c]):
                continue
            if (rr - sr) * (rr - sr) + (cc - sc) * (cc - sc) > r2max:
                continue
            dz = elev[rr, cc] - elev[r, c]
            if reverse:
                dz = -dz
            run = pixel_m * SQRT2 if diag else pixel_m
            cost, t, e = kernel(params, dz, run, 0.5 * (slope5[r, c] + slope5[rr, cc]),
                                max(rough[r, c], rough[rr, cc]), max(sand[r, c], sand[rr, cc]))
            if not cost < np.inf:
                continue
            ng = gu + cost
            if ng < g[v]:
                g[v] = ng
                tt[v] = tt[u] + t
                ee[v] = ee[u] + e
                prev[v] = u
                h = 0.0
                if goal >= 0:
                    h = hrate * pixel_m * math.sqrt((rr - gr) * (rr - gr) + (cc - gc) * (cc - gc))
                heapq.heappush(heap, (ng + h, np.int64(v)))
    return g, tt, ee, prev


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
    max_grade_deg: float = 0.0      # steepest step actually walked (along the path, on the walk surface)
    cum_dist_m: list[float] = field(default_factory=list)     # per cell, from the leg start
    cum_time_s: list[float] = field(default_factory=list)
    cum_energy_kj: list[float] = field(default_factory=list)


@dataclass
class Field:
    """Dijkstra result on the stack grid. Unreached cells are inf (prev = -1)."""
    cost: np.ndarray        # (H, W) float64
    time_s: np.ndarray      # (H, W) float32
    energy_kj: np.ndarray   # (H, W) float32
    prev: np.ndarray        # (H*W,) int32 flat index of the neighbour on the best path towards the source
    source: tuple[int, int]
    reverse: bool

    def reached(self, rc: tuple[int, int]) -> bool:
        return bool(np.isfinite(self.cost[rc]))

    def trace(self, rc: tuple[int, int]) -> list[tuple[int, int]]:
        """Cells from `rc` to the source (inclusive). For a reverse field this is the walk-back route in
        walking order; for a forward field reverse the list to get source -> rc."""
        w = self.cost.shape[1]
        out, u = [], rc[0] * w + rc[1]
        while u >= 0:
            out.append((int(u // w), int(u % w)))
            u = int(self.prev[u])
        return out


def _arrays(stack: LayerStack, window: tuple[int, int, int, int] | None = None):
    elev = stack.walk_elev_m if stack.walk_elev_m is not None else stack.elevation_m
    arrs = (elev, stack.slope_5m_deg, stack.roughness_m, stack.sand, stack.nogo)
    if window is not None:
        r0, r1, c0, c1 = window
        arrs = tuple(a[r0:r1, c0:c1] for a in arrs)
    elev, s5, rough, sand, nogo = arrs
    c = np.ascontiguousarray
    return c(elev, dtype=np.float32), c(s5, dtype=np.float32), c(rough, dtype=np.float32), c(sand, dtype=np.float32), c(nogo, dtype=np.bool_)


def snap(stack: LayerStack, rc: tuple[int, int], max_m: float = 10.0) -> tuple[int, int] | None:
    """Nearest traversable cell within max_m of rc (rc itself if it is fine). None if there is none."""
    r, c = rc
    h, w = stack.shape
    if 0 <= r < h and 0 <= c < w and not stack.nogo[r, c]:
        return r, c
    k = int(math.ceil(max_m / stack.grid.pixel_m))
    r0, r1, c0, c1 = max(r - k, 0), min(r + k + 1, h), max(c - k, 0), min(c + k + 1, w)
    if r1 <= r0 or c1 <= c0:
        return None
    rr, cc = np.nonzero(~stack.nogo[r0:r1, c0:c1])
    if rr.size == 0:
        return None
    d2 = (rr + r0 - r) ** 2 + (cc + c0 - c) ** 2
    i = int(np.argmin(d2))
    if d2[i] * stack.grid.pixel_m ** 2 > max_m ** 2:
        return None
    return int(rr[i] + r0), int(cc[i] + c0)


def cost_field(stack: LayerStack, model: CostModel, source: tuple[int, int], reverse: bool = False,
               max_cost: float = math.inf, max_radius_m: float = math.inf) -> Field:
    elev, s5, rough, sand, nogo = _arrays(stack)
    px = stack.grid.pixel_m
    g, tt, ee, prev = _search(elev, s5, rough, sand, nogo, px, model.kernel, model.params,
                              source[0], source[1], -1, -1, 0.0, reverse, max_cost,
                              max_radius_m / px if math.isfinite(max_radius_m) else 1e12)
    return Field(g.reshape(elev.shape), tt.reshape(elev.shape), ee.reshape(elev.shape), prev, source, reverse)


def _one_leg(stack, model, start, goal, window):
    r0, r1, c0, c1 = window
    elev, s5, rough, sand, nogo = _arrays(stack, window)
    px = stack.grid.pixel_m
    s, t = (start[0] - r0, start[1] - c0), (goal[0] - r0, goal[1] - c0)
    g, tt, ee, prev = _search(elev, s5, rough, sand, nogo, px, model.kernel, model.params,
                              s[0], s[1], t[0], t[1], model.min_rate(), False, math.inf, 1e12)
    w = elev.shape[1]
    gi = t[0] * w + t[1]
    if not np.isfinite(g[gi]):
        return None
    idx, u = [], gi
    while u >= 0:
        idx.append(u)
        u = int(prev[u])
    idx = np.array(idx[::-1])
    rows, cols = idx // w, idx % w
    # Distance, climb and grade come from the stride-scale walking surface, like the edge costs in the search:
    # the raw 1 m stereo DTM has ~0.2 m of cell-to-cell noise, which would add length and phantom climbing.
    walk = stack.walk_elev_m if stack.walk_elev_m is not None else stack.elevation_m
    z = walk[rows + r0, cols + c0].astype(np.float64)
    run = np.hypot(np.diff(rows), np.diff(cols)) * px
    dz = np.diff(z)
    seg = np.hypot(run, dz)
    grade = np.degrees(np.arctan2(np.abs(dz), run)) if run.size else np.zeros(1)
    return Path(cells=[(int(a + r0), int(b + c0)) for a, b in zip(rows, cols)],
                cost=float(g[gi]), distance_m=float(seg.sum()), time_s=float(tt[gi]), energy_kj=float(ee[gi]),
                climb_m=float(dz[dz > 0].sum()), descent_m=float(-dz[dz < 0].sum()), max_grade_deg=float(grade.max()),
                cum_dist_m=np.concatenate([[0.0], np.cumsum(seg)]).tolist(),
                cum_time_s=tt[idx].astype(float).tolist(), cum_energy_kj=ee[idx].astype(float).tolist())


def astar(stack: LayerStack, model: CostModel, start: tuple[int, int], goal: tuple[int, int],
          margin_m: float = 300.0, snap_m: float = 10.0) -> Path | None:
    """Least-cost path start -> goal, or None if the goal cannot be reached. Start/goal on a no-go cell
    are snapped to the nearest traversable cell within snap_m (recorded in Path.snapped)."""
    snapped = {}
    s, t = snap(stack, start, snap_m), snap(stack, goal, snap_m)
    if s is None or t is None:
        return None
    if s != tuple(start):
        snapped["start"] = s
    if t != tuple(goal):
        snapped["goal"] = t
    h, w = stack.shape
    m = int(math.ceil(margin_m / stack.grid.pixel_m))
    crop = (max(min(s[0], t[0]) - m, 0), min(max(s[0], t[0]) + m + 1, h),
            max(min(s[1], t[1]) - m, 0), min(max(s[1], t[1]) + m + 1, w))
    path = _one_leg(stack, model, s, t, crop)
    if path is None and crop != (0, h, 0, w):
        path = _one_leg(stack, model, s, t, (0, h, 0, w))     # widen once: the detour may leave the crop
    if path is not None:
        path.snapped = snapped
    return path
