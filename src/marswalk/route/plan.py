"""Assemble a full EVA plan: legs between stops, timeline, consumables, walk-back margins.

build_plan():
  1. Map the start (rover) and each stop to grid cells, snapping off no-go cells (<= 10 m).
  2. One reverse cost field from the start: the walk-back time/energy from every cell (Apollo-style
     walk-back limit). It feeds the per-waypoint margins, the margin profile and the safe-zone overlay.
  3. Stop order: fixed, or brute-force optimise on a matrix of leg costs.
  4. Least-cost path for each leg, closing back to the start.
  5. Timeline: walking time and energy * eva.time_margin_factor (BASALT lesson), plus work time and
     work power at each stop.
  6. constraints.eva.check_plan() attaches the violations.
Stops can come from the site (optionally a subset via stop_ids) or be arbitrary clicked points.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from marswalk.config import EVAConfig, SiteConfig, Stop
from marswalk.cost.base import model_from_eva
from marswalk.layers.stack import LayerStack
from marswalk.route.astar import Field, Path, astar, cost_field, snap
from marswalk.route.sequence import order_stops

DEFAULT_WORK_POWER_W = 250.0     # suited work at a stop (placeholder; override with suit.work_power_w)
KJ_PER_KG_O2 = 20.9 / 1.429e-3   # ~20.9 kJ per litre O2 at 1.429 g/L  ->  ~14 600 kJ per kg


class PlanError(ValueError):
    """The request cannot be planned at all (e.g. the start is off the terrain window)."""


@dataclass
class Waypoint:
    id: str
    name: str
    lat: float
    lon: float
    arrive_s: float = 0.0          # mission elapsed time at arrival
    depart_s: float = 0.0
    walkback_time_s: float = 0.0   # time to return to start from here (margin factor applied)
    walkback_energy_kj: float = 0.0
    energy_used_kj: float = 0.0    # cumulative at departure
    kind: str = "stop"


@dataclass
class Leg:
    from_id: str
    to_id: str
    path: Path


@dataclass
class EVAPlan:
    site_id: str
    cost_model: str
    order: list[str]
    waypoints: list[Waypoint]
    legs: list[Leg]
    total_time_s: float = 0.0
    total_distance_m: float = 0.0
    total_energy_kj: float = 0.0
    violations: list = field(default_factory=list)
    walking_time_s: float = 0.0
    profile: dict = field(default_factory=dict)       # arrays along the route (see _profile)
    budgets: dict = field(default_factory=dict)       # usable time/energy after the reserve


def usable_budgets(eva: EVAConfig) -> dict:
    """Consumables that may be spent before the walk-back reserve is touched."""
    keep = 1.0 - float(eva.eva["walkback_reserve_frac"])
    return {"time_s": float(eva.suit.get("o2_capacity_h", eva.eva["max_duration_h"])) * 3600.0 * keep,
            "energy_kj": float(eva.suit.get("metabolic_budget_kj", math.inf)) * keep}


def walkback_field(stack: LayerStack, eva: EVAConfig, start_rc: tuple[int, int], cost_model_name: str | None = None) -> Field:
    """Reverse cost field from the rover: walk-back cost/time/energy from every cell within reach."""
    radius = 1.1 * float(eva.eva["max_distance_from_rover_m"])   # nobody may be farther out than the walk limit
    return cost_field(stack, model_from_eva(eva, cost_model_name), start_rc, reverse=True, max_radius_m=radius)


def _profile(stack: LayerStack, legs: list[Leg], leg_t0: list[float], leg_e0: list[float], back: Field,
             margin: float, budgets: dict, max_points: int = 500) -> dict:
    dist, t, e, rows, cols, d0 = [], [], [], [], [], 0.0
    for leg, t0, e0 in zip(legs, leg_t0, leg_e0):
        p = leg.path
        dist += [d0 + d for d in p.cum_dist_m]
        t += [t0 + margin * x for x in p.cum_time_s]
        e += [e0 + margin * x for x in p.cum_energy_kj]
        rows += [rc[0] for rc in p.cells]
        cols += [rc[1] for rc in p.cells]
        d0 += p.distance_m
    if not rows:
        return {}
    step = max(len(rows) // max_points, 1)
    sel = np.unique(np.concatenate([np.arange(0, len(rows), step), [len(rows) - 1]]))
    r, c = np.array(rows)[sel], np.array(cols)[sel]
    t, e = np.array(t)[sel], np.array(e)[sel]
    wb_t = back.time_s[r, c].astype(np.float64) * margin
    wb_e = back.energy_kj[r, c].astype(np.float64) * margin
    margin_min = np.minimum(budgets["time_s"] - (t + wb_t), np.inf) / 60.0
    rnd = lambda a, n: [None if not math.isfinite(x) else round(float(x), n) for x in a]   # noqa: E731
    return {"dist_m": rnd(np.array(dist)[sel], 1), "elev_m": rnd(stack.elevation_m[r, c], 2),
            "slope_deg": rnd(stack.slope_5m_deg[r, c], 1), "t_min": rnd(t / 60.0, 2), "energy_kj": rnd(e, 1),
            "walkback_min": rnd(wb_t / 60.0, 2), "walkback_kj": rnd(wb_e, 1), "margin_min": rnd(margin_min, 1)}


def build_plan(site: SiteConfig, eva: EVAConfig, stack: LayerStack, cost_model_name: str | None = None,
               stop_ids: Sequence[str] | None = None, points: Sequence[Stop] | None = None,
               order: str | None = None, back: Field | None = None) -> EVAPlan:
    from marswalk.constraints.eva import Violation, check_plan

    model = model_from_eva(eva, cost_model_name)
    margin = float(eva.eva.get("time_margin_factor", 1.0))
    work_w = float(eva.suit.get("work_power_w", DEFAULT_WORK_POWER_W))
    default_work = float(eva.eva.get("default_work_time_min", 0.0))
    grid = stack.grid

    if points is not None:
        stops = list(points)
    elif stop_ids is not None:
        known = {s.id: s for s in site.stops}
        missing = [i for i in stop_ids if i not in known]
        if missing:
            raise PlanError(f"unknown stops {missing}")
        stops = [known[i] for i in stop_ids]
    else:
        stops = list(site.stops)

    start = site.start
    start_rc = snap(stack, grid.latlon_to_rc(start.lat, start.lon))
    if start_rc is None:
        raise PlanError(f"start {start.id} is outside the terrain window or inside a no-go area")
    if back is None:
        back = walkback_field(stack, eva, start_rc, model.name)

    violations: list = []
    cells: dict[str, tuple[int, int]] = {start.id: start_rc}
    usable: list[Stop] = []
    for s in stops:
        rc = snap(stack, grid.latlon_to_rc(s.lat, s.lon))
        if rc is None or not back.reached(rc):
            violations.append(Violation("unreachable", "no-go",
                                        "no walkable route between this point and the rover" if rc is not None
                                        else "point is off the terrain window or in a no-go area", where=s.id))
            continue
        cells[s.id] = rc
        usable.append(s)

    by_id = {s.id: s for s in usable}
    ids = [s.id for s in usable]
    mode = order or eva.route.get("stop_order", "fixed")
    leg_cache: dict[tuple[str, str], Path | None] = {}

    def leg(a: str, b: str) -> Path | None:
        if (a, b) not in leg_cache:
            leg_cache[(a, b)] = astar(stack, model, cells[a], cells[b])
        return leg_cache[(a, b)]

    if mode == "optimize" and len(ids) > 1:
        ids = order_stops(ids, start.id, lambda a, b: (leg(a, b).cost if leg(a, b) else math.inf), mode="optimize")

    seq = [start.id, *ids, start.id]
    legs: list[Leg] = []
    wps = [Waypoint(start.id, start.name, start.lat, start.lon, kind="start")]
    t = e = walk_t = dist = 0.0
    leg_t0, leg_e0 = [], []
    for a, b in zip(seq, seq[1:]):
        p = leg(a, b)
        if p is None:
            violations.append(Violation("unreachable", "no-go", f"no walkable route {a} -> {b}", where=b))
            continue
        leg_t0.append(t)
        leg_e0.append(e)
        legs.append(Leg(a, b, p))
        t += p.time_s * margin
        e += p.energy_kj * margin
        walk_t += p.time_s * margin
        dist += p.distance_m
        if b == start.id:
            wps.append(Waypoint(start.id, start.name, start.lat, start.lon, arrive_s=t, depart_s=t,
                                energy_used_kj=e, kind="end"))
            continue
        s = by_id[b]
        work_s = 60.0 * (s.work_time_min if s.work_time_min else default_work)
        arrive = t
        t += work_s
        e += work_w * work_s / 1000.0
        rc = cells[b]
        wps.append(Waypoint(s.id, s.name, s.lat, s.lon, arrive_s=arrive, depart_s=t,
                            walkback_time_s=float(back.time_s[rc]) * margin,
                            walkback_energy_kj=float(back.energy_kj[rc]) * margin, energy_used_kj=e))

    budgets = usable_budgets(eva)
    plan = EVAPlan(site_id=site.id, cost_model=model.name, order=ids, waypoints=wps, legs=legs,
                   total_time_s=t, total_distance_m=dist, total_energy_kj=e, violations=violations,
                   walking_time_s=walk_t, budgets=budgets,
                   profile=_profile(stack, legs, leg_t0, leg_e0, back, margin, budgets))
    plan.violations = violations + check_plan(plan, eva, radius_m=float(site.body["radius_m"]))
    return plan
