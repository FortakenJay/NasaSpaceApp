"""Check an EVAPlan against eva config limits. Defaults are Artemis-like (configs/eva/artemis_default.toml).

Scalar checks (duration, distance from rover) and the per-waypoint walk-back reserve check.
"""
from __future__ import annotations

from dataclasses import dataclass

from marswalk.config import EVAConfig


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: str     # "no-go" | "caution"
    detail: str
    where: str = ""   # waypoint or leg id


def check_duration(total_time_s: float, eva: EVAConfig) -> list[Violation]:
    limit_s = eva.eva["max_duration_h"] * 3600
    if total_time_s > limit_s:
        return [Violation("max_duration", "no-go",
                          f"plan {total_time_s/3600:.2f} h > limit {eva.eva['max_duration_h']} h")]
    if total_time_s > 0.85 * limit_s:
        return [Violation("max_duration", "caution", f"plan uses {total_time_s/limit_s:.0%} of the EVA time limit")]
    return []


def check_distance_from_rover(distances_m: dict[str, float], eva: EVAConfig) -> list[Violation]:
    lim = eva.eva["max_distance_from_rover_m"]
    return [Violation("max_distance_from_rover", "no-go", f"{d:.0f} m > {lim:.0f} m", where=k)
            for k, d in distances_m.items() if d > lim]


def check_walkback_reserve(plan, eva: EVAConfig) -> list[Violation]:
    """At each waypoint (on departure), consumables used so far + the walk back to the rover must leave
    >= walkback_reserve_frac of capacity. Checked for time (O2 hours) and metabolic energy."""
    from marswalk.route.plan import usable_budgets
    b = usable_budgets(eva)
    out = []
    for w in plan.waypoints:
        if w.kind != "stop":
            continue
        t_need, e_need = w.depart_s + w.walkback_time_s, w.energy_used_kj + w.walkback_energy_kj
        for what, need, cap, unit, scale in (("time", t_need, b["time_s"], "h", 3600.0),
                                             ("energy", e_need, b["energy_kj"], "kJ", 1.0)):
            if need > cap:
                out.append(Violation("walkback_reserve", "no-go",
                                     f"{what}: used + walk-back {need/scale:.1f} {unit} > usable {cap/scale:.1f} {unit}", where=w.id))
            elif need > 0.85 * cap:
                out.append(Violation("walkback_reserve", "caution",
                                     f"{what}: used + walk-back is {need/cap:.0%} of the usable budget", where=w.id))
    return out


def check_plan(plan, eva: EVAConfig, radius_m: float = 3396190.0) -> list[Violation]:
    """All checks on a full plan: duration, distance from the rover, walk-back reserve."""
    from marswalk.geo import ground_distance_m
    start = plan.waypoints[0]
    dists = {w.id: ground_distance_m(start.lat, start.lon, w.lat, w.lon, radius_m)
             for w in plan.waypoints if w.kind == "stop"}
    return (check_duration(plan.total_time_s, eva) + check_distance_from_rover(dists, eva)
            + check_walkback_reserve(plan, eva))
