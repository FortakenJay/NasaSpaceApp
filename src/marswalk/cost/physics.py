"""Shared walking physics for every cost model: speed and metabolic power as functions of grade.

Both cost models fill time_s and energy_kj from edge_time_energy(), so timelines and consumables stay
comparable when only the route-choosing cost differs.

Model (SEXTANT heritage). Checked 2026-11-14 against Johnson, Hoffman, Newman et al., "An Integrated Traverse Planner
and Analysis Tool for Planetary Exploration", AIAA SPACE 2010 (Table 1: Marquez speed curve; Table 2: Santee et al.
2001 metabolic rate): every coefficient below matches. The one departure is marked "Assumption" below.
- walk_speed_mps(grade): piecewise-linear suited walking speed vs slope (Marquez 2008 form):
  1.6 m/s on the flat, falling to 0.05 m/s at +15 deg and at -20 deg.
- metabolic_power_w(...): Santee et al. (2001) load-carriage form used by SEXTANT,
    level   = (3.28 m + 71.1) (0.661 v cos a + 0.115)
    uphill  = 3.5 m g v sin a
    downhill= 2.4 m g v sin a * 0.3^(|a| / 7.65)          (a in degrees in the exponent; term is negative)
  with m = body + suit (+ carried) mass, as in SEXTANT. Assumption made here, NOT in SEXTANT (which puts g only in the
  slope terms): the mass-dependent part of the level term is scaled by g / g_earth, so level walking costs less on
  Mars and the model reduces to the published form at 1 g. Without it, level-walking power at 140 kg is about twice
  as high (energy shares rise; time shares are unchanged).
- Terrain multipliers: (1 + roughness_penalty_per_m * roughness) and sand_penalty on loose sand. They
  stretch time (you walk slower), and energy follows because power is held.
- Edges steeper than max_grade_deg are not walkable (returned as inf).
- Optional gait limit (walk_run_froude > 0): walking speed is capped at the walk-run transition,
  v = sqrt(Fr g L). Kram, Domingo & Ferris 1997 (J. Exp. Biol. 200: 821, Table 1) measured the preferred transition
  at 1.39 +- 0.06 m/s at 0.4 g, Froude 0.56, leg length 0.89 m (unsuited subjects); Fr = 0.56 and L = 0.89 m give
  1.36 m/s at 3.71 m/s^2, below the curve's 1.6 m/s on the flat. Above the cap a walker would lope; no loping model
  is used, so the cap means "the crew walks". Off by default (walk_run_froude = 0).
"""
from __future__ import annotations

import math

import numba

# index layout of the physics block inside a params array
G, G_EARTH, BODY, SUIT, ROUGH_PEN, SAND_PEN, MAX_GRADE, V_CAP = range(8)
PHYSICS_ORDER = ("gravity_mps2", "earth_gravity_mps2", "body_mass_kg", "suit_mass_kg",
                 "roughness_penalty_per_m", "sand_penalty", "max_grade_deg", "walk_speed_cap_mps")
PHYSICS_DEFAULTS = {"gravity_mps2": 3.71, "earth_gravity_mps2": 9.81, "body_mass_kg": 80.0, "suit_mass_kg": 60.0,
                    "roughness_penalty_per_m": 2.0, "sand_penalty": 1.2, "max_grade_deg": 20.0,
                    "walk_run_froude": 0.0, "leg_length_m": 0.89}
MIN_POWER_W = 60.0


def walk_speed_cap(cfg: dict | None) -> float:
    """Walk-run transition speed sqrt(Fr g L) in m/s, or inf when the gait limit is off (walk_run_froude <= 0)."""
    cfg = {**PHYSICS_DEFAULTS, **(cfg or {})}
    fr = float(cfg["walk_run_froude"])
    return math.sqrt(fr * float(cfg["gravity_mps2"]) * float(cfg["leg_length_m"])) if fr > 0 else math.inf


def physics_params(cfg: dict | None) -> list[float]:
    cfg = cfg or {}
    return [float(cfg.get(k, PHYSICS_DEFAULTS[k])) for k in PHYSICS_ORDER[:-1]] + [walk_speed_cap(cfg)]


@numba.njit(cache=True)
def walk_speed_mps(grade_deg):
    a = grade_deg
    if a < -20.0:
        return 0.05
    if a < -10.0:
        return 0.095 * a + 1.95
    if a < 0.0:
        return 0.06 * a + 1.6
    if a < 6.0:
        return -0.2 * a + 1.6
    if a < 15.0:
        return -0.039 * a + 0.634
    return 0.05


@numba.njit(cache=True)
def metabolic_power_w(mass_kg, g, g_earth, grade_deg, v):
    a = math.radians(grade_deg)
    level = (3.28 * mass_kg * (g / g_earth) + 71.1) * (0.661 * v * math.cos(a) + 0.115)
    if grade_deg >= 0.0:
        slope = 3.5 * mass_kg * g * v * math.sin(a)
    else:
        slope = 2.4 * mass_kg * g * v * math.sin(a) * 0.3 ** (abs(grade_deg) / 7.65)
    return max(level + slope, MIN_POWER_W)


@numba.njit(cache=True)
def edge_time_energy(g, g_earth, mass_kg, rough_pen, sand_pen, max_grade_deg, dz_m, run_m, rough_m, sand, v_cap):
    """(time_s, energy_kj) to walk one edge; (inf, inf) if the edge is steeper than max_grade_deg.
    v_cap: walking speed limit in m/s (inf = none; see walk_speed_cap)."""
    grade = math.degrees(math.atan2(dz_m, run_m))
    if abs(grade) > max_grade_deg:
        return math.inf, math.inf
    v = min(walk_speed_mps(grade), v_cap)
    mult = 1.0 + rough_pen * max(rough_m, 0.0)
    if sand > 0.5:
        mult *= sand_pen
    t = math.sqrt(run_m * run_m + dz_m * dz_m) / v * mult
    return t, metabolic_power_w(mass_kg, g, g_earth, grade, v) * t / 1000.0
