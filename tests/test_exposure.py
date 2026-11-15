"""Radio shadow, storm-shelter reach and the gait limit, on the synthetic site (a 6 m wall with one gap)."""
import dataclasses
import math

import numpy as np
import pytest

from marswalk.config import load_eva, load_site
from marswalk.cost.base import model_from_eva
from marswalk.cost.physics import walk_speed_cap
from marswalk.export.payload import plan_payload
from marswalk.layers import radio as rd
from marswalk.layers import render
from marswalk.layers.stack import build_stack
from marswalk.route.astar import snap
from marswalk.route.plan import build_plan, radio_field, walkback_field

EVA = load_eva("configs/eva/artemis_default.toml")


@pytest.fixture
def world(synthetic_site):
    site = load_site(synthetic_site)
    return site, build_stack(site, EVA, use_cache=False)


def _rover(site, st):
    return snap(st, st.grid.latlon_to_rc(site.start.lat, site.start.lon))


def test_the_wall_casts_a_radio_shadow(world):
    site, st = world
    g = radio_field(st, EVA, _rover(site, st))
    assert g[40, 160] == rd.CONTACT and g[100, 60] == rd.CONTACT        # the rover's side of the wall
    assert g[250, 80] == rd.SHADOW                                       # B, behind the wall
    assert g[200, 160] == rd.SHADOW                                      # straight behind it
    assert (g == rd.SHADOW).sum() > 0.1 * g.size


def test_higher_antennas_see_over_the_wall(world):
    site, st = world
    low = radio_field(st, EVA, _rover(site, st))
    tall = dataclasses.replace(EVA, comms={"rover_antenna_m": 40.0, "suit_antenna_m": 2.0})
    high = radio_field(st, tall, _rover(site, st))
    assert (high == rd.SHADOW).sum() < (low == rd.SHADOW).sum()
    assert high[250, 80] == rd.CONTACT


def test_line_of_sight_matches_a_hand_computed_ray():
    """Flat ground with one 10 m block: the shadow starts right behind it and ends where the line clears it."""
    from types import SimpleNamespace
    z = np.zeros((1, 400), dtype=np.float32)
    z = np.vstack([z] * 3)
    z[:, 100] = 10.0
    st = SimpleNamespace(elevation_m=z, grid=SimpleNamespace(pixel_m=1.0))
    g = rd.contact_grid(st, (1, 0), {"rover_antenna_m": 3.0, "suit_antenna_m": 2.0}, 399.0, radius_m=1e12)
    # horizon behind the block: slope (10 - 3) / 100; the suit (2 m) clears it once 2 - 3 >= 0.07 d - 3 ... never on
    # flat ground below the antenna, so everything behind the block stays in shadow; in front of it, contact.
    assert (g[1, 1:100] == rd.CONTACT).all() and (g[1, 101:] == rd.SHADOW).all()


def test_plan_reports_radio_and_shelter_minutes_that_add_up(world):
    site, st = world
    plan = build_plan(site, EVA, st)
    s = plan_payload(plan, st)["summary"]
    assert 0 < s["radio_shadow_min"] <= plan.total_time_s / 60 + 0.1
    assert s["radio_longest_shadow_min"] <= s["radio_shadow_min"]
    assert "B" in s["radio_shadow_stops"]
    assert any(v.rule == "radio_shadow" for v in plan.violations)
    # every point of this small site is a few minutes from the rover: inside a 30 min warning
    assert s["shelter_lead_min"] == 30 and s["shelter_beyond_min"] == 0
    assert 0 < s["shelter_max_walk_home_min"] < 30


def test_a_short_warning_puts_part_of_the_walk_out_of_shelter_reach(world):
    site, st = world
    short = dataclasses.replace(EVA, eva={**EVA.eva, "sep_warning_lead_min": 1.0})
    plan = build_plan(site, short, st)
    s = plan.exposure
    assert 0 < s["shelter_beyond_min"] < plan.total_time_s / 60
    assert any(v.rule == "storm_shelter" for v in plan.violations)
    png = render.shelter_png(walkback_field(st, short, _rover(site, st)), short)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_oxygen_is_the_limit_until_a_tighter_consumable_is_configured(world):
    from marswalk import consumables
    site, st = world
    plan = build_plan(site, EVA, st)
    assert plan.consumables["limiting_consumable"] == "Oxygen"
    assert plan.consumables["consumables_used"].startswith("oxygen ")
    # 300 W for an hour: 1 080 kJ of heat, 0.44 kg of water evaporated; CO2 = O2 litres x 0.82 x 1.977 g/L
    wet = dataclasses.replace(EVA, consumables={"feedwater_kg": 1.0, "co2_capacity_kg": 5.0})
    rows = {r["name"]: r for r in consumables.time_left(wet, 3600.0, 1080.0)}
    water_left_kg = 1.0 * 0.7 - 1080.0 / 2454.0
    assert rows["water"]["minutes_left"] == pytest.approx(water_left_kg / (0.3 / 2454.0) / 60.0)
    co2_kg = 1080.0 / (4.825 * 4.184) * 0.82 * 1.977e-3
    assert rows["co2"]["used_pct"] == pytest.approx(100 * co2_kg / 3.5)
    assert consumables.time_left(wet, 3600.0, 1080.0)[0]["name"] == "water"      # 0.26 kg left: under an hour
    assert build_plan(site, wet, st).consumables["limiting_consumable"] == "Cooling water"


def test_terrain_uncertainty_separates_sure_and_unsure_ground(world):
    from marswalk.layers import uncertainty as un
    site, st = world
    win = (0, st.shape[0], 0, st.shape[1])
    f = un.offlimits_frequency(st, EVA.hazards, win, {"draws": 8, "vertical_sigma_m": 0.3})
    assert f[150, 100] >= un.ALWAYS                       # the 6 m wall is off limits whatever the noise
    assert f[60, 200] <= un.SOMETIMES                     # gentle open ground never is
    assert np.isnan(f[0, 0])                              # the data hole stays unknown
    again = un.offlimits_frequency(st, EVA.hazards, win, {"draws": 8, "vertical_sigma_m": 0.3})
    assert np.array_equal(np.nan_to_num(f, nan=-1), np.nan_to_num(again, nan=-1))   # same seed, same answer
    rough = un.offlimits_frequency(st, EVA.hazards, win, {"draws": 8, "vertical_sigma_m": 1.0})
    assert un.classes(rough)["sometimes"] >= un.classes(f)["sometimes"]        # a worse DTM is less sure
    plan = build_plan(site, EVA, st, offlimits=(f, win))
    s = plan_payload(plan, st)["summary"]
    assert s["terrain_sigma_m"] == 0.3 and s["marginal_route_m"] >= 0 and s["marginal_always_m"] == 0
    assert un.png(f)[:8] == b"\x89PNG\r\n\x1a\n"


def test_gait_limit_caps_speed_and_slows_the_plan(world):
    site, st = world
    assert math.isinf(walk_speed_cap({}))                                   # off by default
    assert walk_speed_cap({"walk_run_froude": 0.56}) == pytest.approx(math.sqrt(0.56 * 3.71 * 0.89))
    capped = dataclasses.replace(EVA, cost={**EVA.cost, "metabolic": {**EVA.cost["metabolic"], "walk_run_froude": 0.56}})
    m = model_from_eva(capped)
    _, t, _ = m.kernel(m.params, 0.0, 1.0, 0.0, 0.0, 0.0)
    assert 1.0 / t == pytest.approx(1.36, abs=0.005)                         # flat ground at the cap, not 1.6 m/s
    free, slow = build_plan(site, EVA, st), build_plan(site, capped, st)
    assert slow.walking_time_s > free.walking_time_s
