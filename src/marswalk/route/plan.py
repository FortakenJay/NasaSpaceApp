"""Assemble a full EVA plan: legs between stops, timeline, consumables, walkback margins.

TODO(M4). build_plan():
  1. Map H1 and each stop to grid cells (stack.grid.latlon_to_rc).
  2. If eva.route.stop_order == "optimize": run A* for every ordered pair (30 legs for 5 stops
     plus the start), then sequence.order_stops() on that matrix. Otherwise use the fixed order.
  3. A* each leg in order, closing back to H1.
  4. Timeline: walking time * eva.time_margin_factor, plus each stop's work_time_min.
  5. Walkback margin at every waypoint (Apollo-style): time and energy for the A* path straight
     back to H1 from that point. Store it on Waypoint.walkback_*.
  6. Run constraints.eva.check_plan() and attach the violations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from marswalk.config import EVAConfig, SiteConfig
from marswalk.layers.stack import LayerStack
from marswalk.route.astar import Path


@dataclass
class Waypoint:
    id: str
    name: str
    lat: float
    lon: float
    arrive_s: float = 0.0          # mission elapsed time at arrival
    depart_s: float = 0.0
    walkback_time_s: float = 0.0   # time to return to start from here
    walkback_energy_kj: float = 0.0


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


def build_plan(site: SiteConfig, eva: EVAConfig, stack: LayerStack, cost_model_name: str | None = None) -> EVAPlan:
    raise NotImplementedError("M4: assemble legs, timeline, walkback margins, constraint checks")
