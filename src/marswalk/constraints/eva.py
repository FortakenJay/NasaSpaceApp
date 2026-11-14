"""Check an EVAPlan against eva config limits. Defaults are Artemis-like (configs/eva/artemis_default.toml).

Implemented: the Violation type and the scalar checks that need no terrain.
TODO(M4): per-waypoint walkback-reserve check (needs Waypoint.walkback_* from route.plan).
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
    """TODO(M4): at each waypoint, consumables used so far + walkback must leave
    >= walkback_reserve_frac of capacity (O2 hours, battery Wh, metabolic kJ)."""
    raise NotImplementedError("M4: walkback reserve check")


def check_plan(plan, eva: EVAConfig) -> list[Violation]:
    raise NotImplementedError("M4: run all checks on a full plan")
