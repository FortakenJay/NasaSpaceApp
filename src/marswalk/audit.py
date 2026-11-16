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
    finding: bool = False   # a model assumption compared with published data: reported, never a failure

    def row(self) -> str:
        fmt = lambda v: f"{v:,.4g}" if isinstance(v, float) else str(v)
        mark = "✅" if self.ok else ("⚠️" if self.finding else "❌")
        return f"| {mark} | {self.name} | {fmt(self.expected)} | {fmt(self.got)} | {self.how} |"


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
    from marswalk.spaceweather import radiation
    gy = float(site.spaceweather.get("rad_gcr_dose_mgy_per_day", 0))
    sv = float(site.spaceweather.get("rad_dose_equivalent_msv_per_day", 0))
    est = site.spaceweather.get("rad_estimate")
    if est:   # a Base away from Gale: the config's values must equal the elevation model's, recomputed here
        want = radiation.estimate(float(est["elevation_m"]))
        out.append(Check("Constants", "Surface dose rate, estimated for this Base (mGy/day)", want["rad_gcr_dose_mgy_per_day"],
                         gy, _close(gy, want["rad_gcr_dose_mgy_per_day"], rel=1e-3),
                         "spaceweather.radiation: Gale's RAD value scaled by surface pressure (Guo et al. 2017)"))
        out.append(Check("Constants", "Surface dose equivalent, estimated (mSv/day)", want["rad_dose_equivalent_msv_per_day"],
                         sv, _close(sv, want["rad_dose_equivalent_msv_per_day"], rel=1e-3), "same ratio as the dose rate"))
    else:
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
    # Gait at 0.38 g: Kram, Domingo & Ferris 1997 (J. Exp. Biol. 200: 821), Table 1, 0.4 g: 1.39 ± 0.062 m/s (S.E.M.).
    from marswalk.cost.physics import walk_speed_cap
    met = eva.cost.get("metabolic", {})
    cap = walk_speed_cap({"gravity_mps2": g, **met})
    top = min(walk_speed_mps(0.0), cap)
    out.append(Check("Walking model", "Top walking speed vs measured walk-run switch at 0.4 g (m/s)", "≤ 1.39 ± 0.12",
                     round(top, 2), top <= 1.39 + 2 * 0.062,
                     "Kram et al. 1997, Table 1 (unsuited, 2 S.E.M.); faster than this people choose to run. "
                     + ("Gait limit on." if math.isfinite(cap) else "Gait limit off: cost.metabolic.walk_run_froude = 0"),
                     finding=True))
    cap56 = walk_speed_cap({"gravity_mps2": g, "walk_run_froude": 0.56, "leg_length_m": 0.89})
    out.append(Check("Walking model", "Gait limit at Froude 0.56, leg 0.89 m (m/s)", round(math.sqrt(0.56 * g * 0.89), 4),
                     round(cap56, 4), _close(cap56, math.sqrt(0.56 * g * 0.89), rel=1e-12),
                     "v = √(Fr·g·L), Kram et al. 1997 inverted-pendulum limit"))
    lead = float(eva.eva.get("sep_warning_lead_min", 30.0))
    out.append(Check("Constants", "Solar storm warning before the dose arrives (min)", 30.0, lead, lead <= 30.0,
                     "Löwe et al. 2025, Space Weather: ≥ 30 min from RAD nowcasting at Gale (more would be optimistic)"))
    return out


def check_operations(site: SiteConfig, eva: EVAConfig, stack, plan, payload: dict, radio) -> list[Check]:
    """Radio line of sight, shelter reach and local gravity, each recomputed another way."""
    from marswalk.layers.radio import CONTACT, DEFAULTS, SHADOW
    from marswalk.route.astar import snap
    out: list[Check] = []
    R = float(site.body["radius_m"])
    s = payload["summary"]
    # Radio: the sweep against a direct line from the rover's antenna to the suit, sampled every half metre.
    comms = {**DEFAULTS, **eva.comms}
    z = stack.elevation_m
    r0, c0 = snap(stack, stack.grid.latlon_to_rc(site.start.lat, site.start.lon))
    za = float(z[r0, c0]) + float(comms["rover_antenna_m"])
    px = float(stack.grid.pixel_m)
    rng = np.random.default_rng(1)
    reach_px = 1.1 * float(eva.eva["max_distance_from_rover_m"]) / px
    agree = n = 0
    for _ in range(2000):
        if n >= 200:
            break
        a, dpx = rng.uniform(0, 2 * math.pi), rng.uniform(2, reach_px)
        r, c = int(round(r0 - math.cos(a) * dpx)), int(round(c0 + math.sin(a) * dpx))
        if not (0 <= r < z.shape[0] and 0 <= c < z.shape[1]) or radio[r, c] == 0 or not np.isfinite(z[r, c]):
            continue
        dpx = math.hypot(r - r0, c - c0)
        d_t = dpx * px
        tgt = (float(z[r, c]) + float(comms["suit_antenna_m"]) - d_t * d_t / (2 * R) - za) / d_t
        steps = int(dpx * 2)
        blocked = False
        for i in range(1, steps):
            f = i / steps
            rr, cc = int(round(r0 + (r - r0) * f)), int(round(c0 + (c - c0) * f))
            d = d_t * f
            if np.isfinite(z[rr, cc]) and (float(z[rr, cc]) - d * d / (2 * R) - za) / d > tgt:
                blocked = True
                break
        n += 1
        agree += (SHADOW if blocked else CONTACT) == radio[r, c]
    out.append(Check("Operations", "Radio sweep vs direct line of sight (cells agreeing)", n, agree, agree >= n - 2,
                     f"200 random cells in reach; antennas {comms['rover_antenna_m']:g} m (rover) and "
                     f"{comms['suit_antenna_m']:g} m (suit); the ground drops d²/2R"))
    shadow_pct = 100.0 * float((radio == SHADOW).sum()) / max(float((radio > 0).sum()), 1.0)
    out.append(Check("Operations", "Ground in walk range with no line of sight to the rover (%)", "reported",
                     round(shadow_pct, 1), True, "layers.radio: line of sight only, no relay or diffraction"))
    # Shelter: the farthest walk home anywhere on the route, from the plan's own profile (sampled) and from the field.
    lead = float(eva.eva.get("sep_warning_lead_min", 30.0))
    prof = [x for x in plan.profile.get("walkback_min", []) if x is not None]
    worst = float(s["shelter_max_walk_home_min"])
    out.append(Check("Operations", "Longest walk home on the route vs storm warning (min)", f"≤ {lead:g}", worst,
                     worst <= lead and (not prof or max(prof) <= worst + 0.05),
                     "walk-back field × margin on every route cell; the sampled profile never exceeds it"))
    # Terrain uncertainty: the route never crosses ground off limits in (nearly) every perturbed terrain.
    if "marginal_route_m" in s:
        out.append(Check("Operations", "Route on ground off limits in ≥ 95 % of perturbed terrains (m)", 0,
                         s["marginal_always_m"], s["marginal_always_m"] == 0,
                         f"layers.uncertainty: noise σ = {s['terrain_sigma_m']:g} m (HiRISE 'tens of cm'), sub-metre shifts"))
        out.append(Check("Operations", "Route on ground off limits in only some perturbed terrains (m)", "reported",
                         s["marginal_route_m"], True, "the off-limits test cannot be sure there: worth a look on the photo"))
    # Gravity: free-air change with height (2h/R) and the latitude term of a rotating, flattened Mars (Clairaut).
    elev = [x for x in plan.profile.get("elev_m", []) if x is not None]
    lats = [w.lat for w in plan.waypoints]
    dh = (max(elev) - min(elev)) if elev else 0.0
    omega = 2 * math.pi / 88642.66                                  # Mars sidereal day, s
    g_eq = float(site.body.get("gravity_mps2", 3.71))
    flat = (3396.19 - 3376.20) / 3396.19
    beta = 2.5 * omega * omega * R / g_eq - flat
    d_lat = abs(math.sin(math.radians(max(lats))) ** 2 - math.sin(math.radians(min(lats))) ** 2) * beta
    dg_pct = 100.0 * (2 * dh / R + d_lat)
    out.append(Check("Operations", "Change in gravity across the walk (%)", "< 0.1", round(dg_pct, 4), dg_pct < 0.1,
                     f"free-air 2Δh/R over {dh:.0f} m of relief + Clairaut latitude term; mass anomalies (GMM-3, "
                     "~90 km resolution) vary little across a 4 km site. One g for the whole walk is fine"))
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
    from marswalk.spaceweather.radiation import rates
    gy = rates(site.spaceweather)[0]
    out.append(Check("Radiation", "Dose for this walk (mGy)", round(gy * dur / 60 / 24, 4), round(gy * float(s["duration_h"]) / 24, 4),
                     _close(gy * dur / 60 / 24, gy * float(s["duration_h"]) / 24, rel=0.01), f"{gy:g} mGy/day × hours ÷ 24"))
    return out


def check_terrain(site: SiteConfig, stack) -> list[Check]:
    out: list[Check] = []
    g = stack.grid
    # Grid geometry: the pixel's ground size east-west vs north-south at the site's latitude.
    lat0 = (site.bbox["lat_min"] + site.bbox["lat_max"]) / 2
    a = g.rc_to_latlon(stack.shape[0] // 2, stack.shape[1] // 2)
    b = g.rc_to_latlon(stack.shape[0] // 2, stack.shape[1] // 2 + 1)
    c = g.rc_to_latlon(stack.shape[0] // 2 + 1, stack.shape[1] // 2)
    # on the grid's own sphere (HiRISE DTMs away from Gale use a local radius, e.g. 3,394,840 m at Jezero)
    ell = g.crs.ellipsoid
    R = float(ell.semi_major_metre) if ell is not None else float(site.body["radius_m"])
    ew, ns = ground_distance_m(*a, *b, R), ground_distance_m(*a, *c, R)
    out.append(Check("Terrain", "Pixel size north-south (m)", round(g.pixel_m, 4), round(ns, 4), _close(ns, g.pixel_m, rel=1e-4),
                     "affine transform vs haversine"))
    from marswalk.sources.raster import SQUARE_TOL
    out.append(Check("Terrain", f"Pixel size east-west (m), square within {100 * SQUARE_TOL:g} %", round(g.pixel_m, 4),
                     round(ew, 4), _close(ew, g.pixel_m, rel=SQUARE_TOL),
                     f"the layers and routes treat pixels as square; at {lat0:.1f}° this grid is "
                     f"{100 * abs(ew / g.pixel_m - 1):.2f} % off (fetch resamples above {100 * SQUARE_TOL:g} %)"))
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
        from marswalk.route.astar import snap
        from marswalk.route.plan import build_plan, radio_field
        checks += check_terrain(site, stack)
        if not site.stops:
            # A new Base starts with only the rover point; stops added in the app live in the database, not the file.
            checks.append(Check("Plan", "Plan checks", "science stops in the site file", "none", True,
                                "skipped: this site has no stops in its stops file (a new Base)", finding=True))
            return checks
        rc = snap(stack, stack.grid.latlon_to_rc(site.start.lat, site.start.lon))
        radio = radio_field(stack, eva, rc, float(site.body["radius_m"]))
        from marswalk.layers import uncertainty
        win = uncertainty.walk_window(site, stack)
        offlimits = (uncertainty.offlimits_frequency(stack, eva.hazards, win, site.dtm.get("uncertainty")), win)
        plan = build_plan(site, eva, stack, cost, radio=radio, offlimits=offlimits)
        payload = plan_payload(plan, stack)
        checks += check_plan(site, eva, stack, plan, payload)
        checks += check_operations(site, eva, stack, plan, payload, radio)
    return checks


def markdown(checks: list[Check], title: str = "Audit results") -> str:
    real = [c for c in checks if not c.finding]
    notes = [c for c in checks if c.finding]
    head = (f"Generated by `marswalk audit` on {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC. "
            f"{sum(c.ok for c in real)} of {len(real)} checks pass.")
    if notes:
        head += (f" {len(notes)} model assumption{'s are' if len(notes) > 1 else ' is'} compared with published data "
                 f"(⚠️ = the assumption differs from the data; these are findings, not failures).")
    lines = [f"# {title}", "", head, ""]
    for group in dict.fromkeys(c.group for c in checks):
        lines += [f"## {group}", "", "| | Check | Expected | MarsWalk | How it is checked |", "|---|---|---|---|---|"]
        lines += [c.row() for c in checks if c.group == group] + [""]
    return "\n".join(lines)
