"""Time along a plan spent out of radio contact, and out of reach of shelter if a solar particle storm is called.

Both walk the plan's own timeline: each step of each leg (time x margin, as the plan times it) and the work at each
stop, so the minutes add up to the plan's time outside.

Radio: a step counts as out of contact when the cell it ends on is in radio shadow (layers.radio).
Shelter: the rover is the storm shelter. A step counts as out of reach when the walk home from its cell (the walk-back
field x margin) takes longer than the warning a crew can expect before the dose arrives, `sep_warning_lead_min`:
30 min, from Löwe et al. 2025 (Space Weather, doi:10.1029/2025SW004372), whose RAD-based nowcasting at Gale gave at
least 30 min to avoid the peak and 90 % of the dose of every SEP event since 2012. Rapp 2006 (Mars journal) used a
shorter 20 min, the X-ray warning before protons arrive at 1 AU.
"""
from __future__ import annotations

from marswalk.layers.radio import SHADOW

DEFAULT_LEAD_MIN = 30.0


def marginal(plan, offlimits, px_m: float, sigma_m: float) -> dict:
    """Metres of the route on ground whose off-limits test flips between terrain draws (layers.uncertainty)."""
    from marswalk.constraints.eva import Violation
    from marswalk.layers.uncertainty import route_marginal_m
    freq, window = offlimits
    some, always = route_marginal_m(freq, window, plan, px_m)
    out = {"marginal_route_m": round(some), "marginal_always_m": round(always), "terrain_sigma_m": sigma_m}
    violations = []
    if some >= 1.0 or always >= 1.0:
        violations.append(Violation("marginal_ground", "caution",
                                    f"{some:.0f} m of the route crosses ground that is off limits in some versions of the "
                                    f"terrain within its {sigma_m:g} m stereo precision"
                                    + (f", {always:.0f} m in nearly all of them" if always >= 1.0 else "")
                                    + ": check those stretches on the photo"))
    return {"summary": out, "violations": violations}


def _segments(plan, margin: float):
    """(cell, seconds) for every step of every leg and every stop's work, in walk order."""
    by_id = {w.id: w for w in plan.waypoints}
    for leg in plan.legs:
        p = leg.path
        prev = 0.0
        for rc, t in zip(p.cells, p.cum_time_s):
            yield rc, (t - prev) * margin
            prev = t
        w = by_id.get(leg.to_id)
        if w is not None and w.kind == "stop" and p.cells:
            yield p.cells[-1], w.depart_s - w.arrive_s


def exposure(plan, back, radio, eva) -> dict:
    """Summary fields and violations for radio shadow and shelter reach."""
    from marswalk.constraints.eva import Violation
    margin = float(eva.eva.get("time_margin_factor", 1.0))
    lead_s = 60.0 * float(eva.eva.get("sep_warning_lead_min", DEFAULT_LEAD_MIN))
    shadow_s = longest_s = run_s = beyond_s = 0.0
    worst_home_s = 0.0
    shadow_stops: list[str] = []
    stop_cells = {w.id: None for w in plan.waypoints if w.kind == "stop"}
    for leg in plan.legs:
        if leg.to_id in stop_cells and leg.path.cells:
            stop_cells[leg.to_id] = leg.path.cells[-1]
    for rc, dt in _segments(plan, margin):
        if radio is not None and radio[rc] == SHADOW:
            shadow_s += dt
            run_s += dt
            longest_s = max(longest_s, run_s)
        else:
            run_s = 0.0
        home = float(back.time_s[rc]) * margin
        worst_home_s = max(worst_home_s, home)
        if home > lead_s:
            beyond_s += dt
    if radio is not None:
        shadow_stops = [sid for sid, rc in stop_cells.items() if rc is not None and radio[rc] == SHADOW]
    out = {"radio_shadow_min": round(shadow_s / 60.0, 1), "radio_longest_shadow_min": round(longest_s / 60.0, 1),
           "radio_shadow_stops": ", ".join(shadow_stops), "shelter_lead_min": round(lead_s / 60.0, 1),
           "shelter_beyond_min": round(beyond_s / 60.0, 1), "shelter_max_walk_home_min": round(worst_home_s / 60.0, 1)}
    violations = []
    if shadow_s >= 60.0:                 # a few cells of shadow on a ridge crest are not worth a caution
        where = f" (at {', '.join(shadow_stops)})" if shadow_stops else ""
        violations.append(Violation("radio_shadow", "caution",
                                    f"{shadow_s / 60:.0f} min out of radio contact with the rover{where}, longest stretch "
                                    f"{longest_s / 60:.0f} min: terrain blocks the line of sight"))
    if beyond_s > 0.0:
        violations.append(Violation("storm_shelter", "caution",
                                    f"{beyond_s / 60:.0f} min of the walk is more than {lead_s / 60:.0f} min from the rover: "
                                    f"a solar particle alert there leaves the crew outside when the dose arrives"))
    return {"summary": out, "violations": violations}
