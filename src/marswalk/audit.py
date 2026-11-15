"""`marswalk audit`: recompute every number the app shows, independently, and say whether it matches.

Each check states the formula and where its constant comes from, recomputes the value by a different path than
the planner (e.g. distances along the drawn route with the haversine formula instead of grid steps, timeline
times by re-adding legs and stop work, budgets from the config), and compares within a stated tolerance.
Run it on your own data after `marswalk fetch`; `--out` writes the table as markdown for the wiki.
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
from dataclasses import dataclass

import numpy as np

from marswalk.config import EVAConfig, SiteConfig
from marswalk.geo import ground_distance_m


@dataclass
class Check:
    group: str
    name: str
    expected: float | str
    got: float | str
    ok: bool
    how: str          # formula / source, one line

    def row(self) -> str:
        fmt = lambda v: f"{v:,.4g}" if isinstance(v, float) else str(v)
        return f"| {'✅' if self.ok else '❌'} | {self.name} | {fmt(self.expected)} | {fmt(self.got)} | {self.how} |"


def _close(a: float, b: float, rel: float = 0.0, abs_: float = 0.0) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def check_constants(site: SiteConfig, eva: EVAConfig) -> list[Check]:
    from marswalk.cost.physics import metabolic_power_w, walk_speed_mps
    from marswalk.route.plan import KJ_PER_KG_O2, usable_budgets
    out: list[Check] = []
    R = float(site.body["radius_m"])
    out.append(Check("Constants", "Mars radius (m)", 3396190.0, R, R == 3396190.0,
                     "IAU Mars 2000 sphere, the datum of HiRISE DTMs, THEMIS mosaics and the USGS Gale DEM"))
    mpd = 2 * math.pi * R / 360
    out.append(Check("Constants", "Metres per degree on the map", 59274.7, mpd, _close(mpd, 59274.7, abs_=0.5),
                     "2πR/360 (frontend/src/map/mars.ts uses the same formula)"))
    g = float(eva.cost.get("metabolic", {}).get("gravity_mps2", 3.71))
    out.append(Check("Constants", "Mars surface gravity (m/s²)", 3.71, g, _close(g, 3.721, abs_=0.02),
                     "NASA Mars fact sheet: 3.71-3.72 m/s²"))
    gy = float(site.spaceweather.get("rad_gcr_dose_mgy_per_day", 0))
    sv = float(site.spaceweather.get("rad_dose_equivalent_msv_per_day", 0))
    out.append(Check("Constants", "Surface dose rate (mGy/day)", 0.21, gy, gy == 0.21,
                     "Hassler et al. 2014, Science 343: 0.21 ± 0.04 mGy/day (Curiosity RAD, Gale)"))
    out.append(Check("Constants", "Surface dose equivalent (mSv/day)", 0.64, sv, sv == 0.64,
                     "Hassler et al. 2014: 0.64 ± 0.12 mSv/day"))
    out.append(Check("Constants", "Energy per kg of O₂ (kJ/kg)", 4.825 * 4.184 / 1.429e-3, KJ_PER_KG_O2,
                     _close(KJ_PER_KG_O2, 14127.0, rel=0.002), "4.825 kcal/L O₂ at RQ 0.82 (Lusk/Weir) ÷ 1.429 g/L"))
    b = usable_budgets(eva)
    keep = 1 - float(eva.eva["walkback_reserve_frac"])
    t_exp = float(eva.suit.get("o2_capacity_h", eva.eva["max_duration_h"])) * keep * 60
    out.append(Check("Constants", "Usable oxygen time (min)", t_exp, b["time_s"] / 60, _close(b["time_s"] / 60, t_exp, abs_=1e-6),
                     "o2_capacity_h × (1 − walkback_reserve_frac): 8 h × 0.7 = 5 h 36 min"))
    # Marquez speed curve: continuous at every breakpoint (Johnson et al. 2010, Table 1)
    jumps = [abs(walk_speed_mps(x - 1e-9) - walk_speed_mps(x + 1e-9)) for x in (-10.0, 0.0, 6.0)]
    out.append(Check("Walking model", "Speed curve has no jumps (m/s)", 0.0, max(jumps), max(jumps) < 1e-6,
                     "Marquez piecewise speed vs grade, breakpoints at −10°, 0°, 6°"))
    out.append(Check("Walking model", "Flat speed (m/s)", 1.6, walk_speed_mps(0.0), walk_speed_mps(0.0) == 1.6,
                     "Johnson et al. 2010, Table 1"))
    m = float(eva.cost.get("metabolic", {}).get("body_mass_kg", 80)) + float(eva.cost.get("metabolic", {}).get("suit_mass_kg", 60))
    p_flat = (3.28 * m * (g / 9.81) + 71.1) * (0.661 * 1.6 + 0.115)
    got = metabolic_power_w(m, g, 9.81, 0.0, 1.6)
    out.append(Check("Walking model", "Flat walking power at 1.6 m/s (W)", p_flat, got, _close(got, p_flat, rel=1e-9),
                     "Santee et al. 2001 level term, mass scaled by g/g_earth (MarsWalk assumption)"))
    up = metabolic_power_w(m, g, 9.81, 10.0, walk_speed_mps(10.0))
    v10 = walk_speed_mps(10.0)
    exp_up = (3.28 * m * g / 9.81 + 71.1) * (0.661 * v10 * math.cos(math.radians(10)) + 0.115) + 3.5 * m * g * v10 * math.sin(math.radians(10))
    out.append(Check("Walking model", "Power on a 10° climb (W)", exp_up, up, _close(up, exp_up, rel=1e-9),
                     "Santee uphill term 3.5·m·g·v·sin θ"))
    return out


def check_plan(site: SiteConfig, eva: EVAConfig, stack, plan, payload: dict) -> list[Check]:
    from marswalk.route.plan import KJ_PER_KG_O2, usable_budgets
    out: list[Check] = []
    R = float(site.body["radius_m"])
    s, tl = payload["summary"], payload["timeline"]
    b = usable_budgets(eva)
    margin = float(eva.eva.get("time_margin_factor", 1.0))
    work_w = float(eva.suit.get("work_power_w", 250.0))

    # Distance: the planner sums grid steps along the slope; here: haversine between route points on the sphere,
    # combined with the height change on the walking surface (the distance walked is along the ground).
    hav = flat = 0.0
    walk = stack.walk_elev_m if stack.walk_elev_m is not None else stack.elevation_m
    for f, leg in zip(payload["route"]["features"], plan.legs):
        c = f["geometry"]["coordinates"]
        h = np.array([ground_distance_m(a[1], a[0], b_[1], b_[0], R) for a, b_ in itertools.pairwise(c)])
        dz = np.diff(np.array([walk[rc] for rc in leg.path.cells], dtype=float))
        hav += float(np.hypot(h, dz).sum())
        flat += float(h.sum())
    out.append(Check("Plan", "Distance walked (km): planner vs on the sphere", float(s["distance_km"]), round(hav / 1000, 3),
                     _close(hav / 1000, float(s["distance_km"]), rel=0.006),
                     "Σ √(haversine² + Δz²) along the route; the grid overstates east-west steps by 1/cos(lat) − 1 = 0.35 %"))
    straight = sum(ground_distance_m(a["lat"], a["lon"], b_["lat"], b_["lon"], R) for a, b_ in itertools.pairwise(tl))
    out.append(Check("Plan", "Route is longer than straight lines", f"> {straight / 1000:.2f} km", f"{flat / 1000:.2f} km",
                     flat >= straight * 0.999, "a walking route (measured flat) can never beat the straight line between stops"))
    # Timeline: re-add each leg (with the time margin) and each stop's work time.
    t, worst = 0.0, 0.0
    for leg, (a, b_) in zip(plan.legs, itertools.pairwise(tl)):
        t += leg.path.time_s * margin / 60
        worst = max(worst, abs(t - b_["arrive_min"]))
        t = b_["depart_min"]
    out.append(Check("Plan", "Timeline: arrivals = departure + leg × margin (max error, min)", 0.0, round(worst, 3),
                     worst < 0.1, f"time_margin_factor {margin}"))
    dur = tl[-1]["arrive_min"]
    out.append(Check("Plan", "Time outside (h)", round(dur / 60, 2), float(s["duration_h"]), _close(dur / 60, float(s["duration_h"]), abs_=0.006),
                     "last arrival at the rover"))
    work = sum(w["depart_min"] - w["arrive_min"] for w in tl if w["kind"] == "stop")
    out.append(Check("Plan", "Walking + stops = time outside (min)", round(dur, 1), round(float(s["walking_h"]) * 60 + work, 1),
                     _close(float(s["walking_h"]) * 60 + work, dur, abs_=0.6), "walking_h + Σ stop work times"))
    out.append(Check("Plan", "Share of usable oxygen time (%)", round(100 * dur * 60 / b["time_s"]), s["time_budget_used_pct"],
                     round(100 * dur * 60 / b["time_s"]) == s["time_budget_used_pct"], "time outside ÷ 5 h 36 min"))
    # Energy: walking legs × margin + stop work at work_power_w.
    e = sum(l.path.energy_kj for l in plan.legs) * margin + work_w * work * 60 / 1000
    out.append(Check("Plan", "Energy (kJ): legs × margin + stop work", round(e), s["energy_kj"], _close(e, s["energy_kj"], abs_=1),
                     f"stop work at {work_w:g} W (suit.work_power_w)"))
    out.append(Check("Plan", "Share of usable energy (%)", round(100 * e / b["energy_kj"]), s["energy_budget_used_pct"],
                     round(100 * e / b["energy_kj"]) == s["energy_budget_used_pct"], "energy ÷ (12 000 kJ × 0.7)"))
    o2 = e / KJ_PER_KG_O2
    out.append(Check("Plan", "Oxygen breathed (kg per person)", round(o2, 2), s["o2_kg_est"], _close(o2, s["o2_kg_est"], abs_=0.006),
                     "energy ÷ 14 127 kJ/kg"))
    # Walk-back margins: recompute at every stop departure from the timeline.
    margins = [b["time_s"] / 60 - (w["depart_min"] + w["walkback_min"]) for w in tl if w["kind"] == "stop"]
    out.append(Check("Plan", "Smallest walk-home margin ≤ margin at any stop (min)", f"≤ {min(margins):.1f}",
                     s["min_walkback_margin_min"], s["min_walkback_margin_min"] <= min(margins) + 0.1,
                     "usable time − (departure + walk home); the summary also checks every route point"))
    # Walk home never faster than the flat walking speed.
    worst_v = 0.0
    for w in tl:
        if w["kind"] != "stop":
            continue
        d = ground_distance_m(w["lat"], w["lon"], tl[0]["lat"], tl[0]["lon"], R)
        worst_v = max(worst_v, d / max(w["walkback_min"] * 60 / margin, 1e-6))
    out.append(Check("Plan", "Fastest implied walk home (m/s)", "≤ 1.6", round(worst_v, 2), worst_v <= 1.6 + 1e-6,
                     "straight-line distance ÷ walk-home time cannot beat the flat speed"))
    # Safety: route cells.
    cells = [rc for l in plan.legs for rc in l.path.cells]
    bad = sum(bool(stack.nogo[rc]) for rc in cells)
    out.append(Check("Safety", "Route cells inside off-limits ground", 0, bad, bad == 0, "nogo = slope/roughness limits ∪ untrusted terrain"))
    mg = max((l.path.max_grade_deg for l in plan.legs), default=0.0)
    lim = float(eva.cost.get("metabolic", {}).get("max_grade_deg", 20.0))
    out.append(Check("Safety", "Steepest step walked (°)", f"≤ {lim:g}", round(mg, 1), mg <= lim + 1e-6, "cost.metabolic.max_grade_deg"))
    far = max(ground_distance_m(w["lat"], w["lon"], tl[0]["lat"], tl[0]["lon"], R) for w in tl)
    lim_d = float(eva.eva["max_distance_from_rover_m"])
    out.append(Check("Safety", "Farthest stop from the rover (m)", f"≤ {lim_d:g}", round(far), far <= lim_d, "eva.max_distance_from_rover_m"))
    # Radiation for this walk.
    gy = float(site.spaceweather.get("rad_gcr_dose_mgy_per_day", 0.21))
    out.append(Check("Radiation", "Dose for this walk (mGy)", round(gy * dur / 60 / 24, 4), round(gy * float(s["duration_h"]) / 24, 4),
                     _close(gy * dur / 60 / 24, gy * float(s["duration_h"]) / 24, rel=0.01), "0.21 mGy/day × hours ÷ 24"))
    return out


def check_terrain(site: SiteConfig, stack) -> list[Check]:
    out: list[Check] = []
    g = stack.grid
    # Grid geometry: the pixel's ground size east-west vs north-south at the site's latitude.
    lat0 = (site.bbox["lat_min"] + site.bbox["lat_max"]) / 2
    a = g.rc_to_latlon(stack.shape[0] // 2, stack.shape[1] // 2)
    b = g.rc_to_latlon(stack.shape[0] // 2, stack.shape[1] // 2 + 1)
    c = g.rc_to_latlon(stack.shape[0] // 2 + 1, stack.shape[1] // 2)
    R = float(site.body["radius_m"])
    ew, ns = ground_distance_m(*a, *b, R), ground_distance_m(*a, *c, R)
    out.append(Check("Terrain", "Pixel size north-south (m)", round(g.pixel_m, 4), round(ns, 4), _close(ns, g.pixel_m, rel=1e-4),
                     "affine transform vs haversine"))
    out.append(Check("Terrain", "Pixel size east-west (m)", round(g.pixel_m * math.cos(math.radians(lat0)), 4), round(ew, 4),
                     _close(ew, g.pixel_m * math.cos(math.radians(lat0)), rel=1e-3),
                     "equirectangular with lat_ts = 0: pixel × cos(lat); slopes are within 0.4 % of the true value"))
    # Slope from the layer vs slope from a plane fit at a random sample of walkable 5 m blocks.
    rng = np.random.default_rng(0)
    ok = np.argwhere(~stack.nogo)
    if len(ok):
        pick = ok[rng.choice(len(ok), size=min(200, len(ok)), replace=False)]
        diffs = []
        z = stack.elevation_m
        for r, c_ in pick:
            r0, c0 = (r // 5) * 5, (c_ // 5) * 5
            if r0 < 5 or c0 < 5 or r0 + 10 > z.shape[0] or c0 + 10 > z.shape[1]:
                continue
            blk = z[r0 - 5:r0 + 10, c0 - 5:c0 + 10].reshape(3, 5, 3, 5).mean(axis=(1, 3))
            if not np.isfinite(blk).all():
                continue
            gy_ = (blk[2, 1] - blk[0, 1]) / (2 * 5 * g.pixel_m)
            gx_ = (blk[1, 2] - blk[1, 0]) / (2 * 5 * g.pixel_m)
            diffs.append(abs(math.degrees(math.atan(math.hypot(gx_, gy_))) - float(stack.slope_5m_deg[r, c_])))
        if diffs:
            med = float(np.median(diffs))
            out.append(Check("Terrain", "5 m slope layer vs hand-computed (median |Δ|, °)", 0.0, round(med, 3), med < 0.05,
                             "central difference on 5 m block means, 200 random walkable cells"))
    nogo_expected = float(np.mean(stack.nogo))
    out.append(Check("Terrain", "Off-limits share of the window (%)", "reported", round(100 * nogo_expected, 1), True,
                     "slope5 > 25° or slope1 > 35° or roughness > 0.8 m, plus no trusted 1 m data"))
    reg = (stack.terrain_check or {}).get("registration")
    if reg:
        out.append(Check("Terrain", "HiRISE → base map residual after the configured shift (m)", "< 3",
                         round(math.hypot(reg["east_m"], reg["north_m"]), 2),
                         math.hypot(reg["east_m"], reg["north_m"]) < 3 and reg["corr"] >= 0.9,
                         f"block cross-correlation r = {reg['corr']:.3f}"))
    return out


def run(site: SiteConfig, eva: EVAConfig, stack=None, cost: str | None = None) -> list[Check]:
    checks = check_constants(site, eva)
    if stack is not None:
        from marswalk.export.payload import plan_payload
        from marswalk.route.plan import build_plan
        checks += check_terrain(site, stack)
        plan = build_plan(site, eva, stack, cost)
        checks += check_plan(site, eva, stack, plan, plan_payload(plan, stack))
    return checks


def markdown(checks: list[Check], title: str = "Audit results") -> str:
    lines = [f"# {title}", "", (f"Generated by `marswalk audit` on {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC. "
             f"{sum(c.ok for c in checks)} of {len(checks)} checks pass."), ""]
    for group in dict.fromkeys(c.group for c in checks):
        lines += [f"## {group}", "", "| | Check | Expected | MarsWalk | How it is checked |", "|---|---|---|---|---|"]
        lines += [c.row() for c in checks if c.group == group] + [""]
    return "\n".join(lines)
