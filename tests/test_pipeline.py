"""Terrain pipeline on a synthetic site: layers, cost kernels, least-cost search, plan, safe zone."""
import math

import numpy as np
import pytest

from marswalk.config import load_eva, load_site
from marswalk.cost.base import model_from_eva
from marswalk.cost.physics import metabolic_power_w, walk_speed_mps
from marswalk.export.payload import plan_payload
from marswalk.layers import render
from marswalk.layers.stack import build_stack
from marswalk.route.astar import astar, cost_field, snap
from marswalk.route.plan import build_plan, walkback_field
from marswalk.sources.raster import read_bbox, read_geotiff

EVA = load_eva("configs/eva/artemis_default.toml")


@pytest.fixture
def world(synthetic_site):
    site = load_site(synthetic_site)
    return site, build_stack(site, EVA, use_cache=False)


def test_geotiff_roundtrip_and_bbox_window(synthetic_site, isolated_data):
    site = load_site(synthetic_site)
    path = isolated_data / "raw" / site.id / "dtm.tif"
    whole = read_geotiff(path)
    assert whole.shape == (300, 320) and np.isnan(whole.data[0, 0])
    lat, lon = whole.grid.rc_to_latlon(100, 100)
    box = {"lat_min": lat - 0.0005, "lat_max": lat + 0.0005, "lon_min": lon - 0.0005, "lon_max": lon + 0.0005}
    part = read_bbox(path, box)                       # local files take the same code path as /vsicurl/
    assert part.value_at(lat, lon) == pytest.approx(whole.data[100, 100])


def test_layers_see_the_wall_and_the_sand(world):
    _, st = world
    assert st.nogo[150, 100] and not st.nogo[150, 248]          # wall is no-go, the gap is open
    assert st.nogo[0, 0]                                        # data hole
    assert st.slope_5m_deg[40, 160] < 10 and st.roughness_m[40, 160] < 0.3
    assert st.sand[100, 60] and not st.sand[100, 280]           # TI reprojected from its own CRS
    assert 200 <= st.ti[100, 60] < 300 and st.ti[100, 280] > 350


def test_walking_physics_is_directional_and_capped():
    assert walk_speed_mps(0.0) == pytest.approx(1.6)
    assert walk_speed_mps(10.0) < walk_speed_mps(-10.0) < walk_speed_mps(0.0)
    m = model_from_eva(EVA, "metabolic")
    up, _, _ = m.kernel(m.params, 0.15, 1.0, 0.0, 0.0, 0.0)
    down, _, _ = m.kernel(m.params, -0.15, 1.0, 0.0, 0.0, 0.0)
    flat, t_flat, e_flat = m.kernel(m.params, 0.0, 1.0, 0.0, 0.0, 0.0)
    assert up > flat and up > down
    assert m.kernel(m.params, 0.5, 1.0, 0.0, 0.0, 0.0)[0] == math.inf       # 26.6 deg > max_grade_deg
    assert e_flat == pytest.approx(metabolic_power_w(140.0, 3.71, 9.81, 0.0, 1.6) * t_flat / 1000.0)
    assert m.min_rate() <= flat
    rough, _, _ = m.kernel(m.params, 0.0, 1.0, 0.0, 0.5, 0.0)
    assert rough == pytest.approx(flat * 2.0)                                  # 1 + 2.0 * 0.5 m


@pytest.mark.parametrize("model_name", ["metabolic", "weighted"])
def test_route_goes_through_the_gap_and_never_enters_nogo(world, model_name):
    site, st = world
    model = model_from_eva(EVA, model_name)
    b = next(s for s in site.stops if s.id == "B")
    start = st.grid.latlon_to_rc(site.start.lat, site.start.lon)
    goal = st.grid.latlon_to_rc(b.lat, b.lon)
    path = astar(st, model, start, goal)
    assert path is not None and path.cells[0] == start and path.cells[-1] == goal
    assert not any(st.nogo[rc] for rc in path.cells)
    crossing = [c for r, c in path.cells if r == 150]
    assert crossing and all(240 <= c < 256 for c in crossing)                 # only the gap crosses row 150
    assert path.distance_m > math.dist(start, goal)                           # detour, so longer than straight
    assert path.cum_time_s[-1] == pytest.approx(path.time_s) and len(path.cum_dist_m) == len(path.cells)
    # A* with the heuristic finds the same cost as plain Dijkstra
    field = cost_field(st, model, start)
    assert field.cost[goal] == pytest.approx(path.cost, rel=1e-6)


def test_walkback_field_is_the_reverse_direction(world):
    site, st = world
    model = model_from_eva(EVA, "metabolic")
    start = snap(st, st.grid.latlon_to_rc(site.start.lat, site.start.lon))
    back = cost_field(st, model, start, reverse=True)
    target = (250, 80)
    home = astar(st, model, target, start)                                    # walking target -> rover
    assert back.cost[target] == pytest.approx(home.cost, rel=1e-6)
    trace = back.trace(target)
    assert trace[0] == target and trace[-1] == start and not any(st.nogo[rc] for rc in trace)


def test_full_plan_timeline_margins_and_payload(world):
    site, st = world
    plan = build_plan(site, EVA, st, "metabolic")
    assert plan.order == ["A", "B", "C"] and [l.to_id for l in plan.legs] == ["A", "B", "C", "H1"]
    assert plan.total_time_s > plan.walking_time_s > 0
    assert plan.total_time_s == pytest.approx(plan.walking_time_s + 3 * 20 * 60)
    stops = [w for w in plan.waypoints if w.kind == "stop"]
    assert all(w.walkback_time_s > 0 and w.depart_s - w.arrive_s == 1200 for w in stops)
    assert not [v for v in plan.violations if v.severity == "no-go"]
    p = plan_payload(plan, st)
    assert len(p["route"]["features"]) == 4
    lon, lat = p["route"]["features"][0]["geometry"]["coordinates"][0]
    assert (lat, lon) == pytest.approx((site.start.lat, site.start.lon), abs=2e-5)
    assert p["summary"]["distance_km"] > 0.5 and p["summary"]["min_walkback_margin_min"] > 0
    assert 0 < p["summary"]["max_grade_deg"] <= 20.0                              # never above max_grade_deg
    n = len(p["profile"]["dist_m"])
    assert n > 10 and all(len(v) == n for v in p["profile"].values())
    opt = build_plan(site, EVA, st, "metabolic", order="optimize")
    assert opt.total_energy_kj <= plan.total_energy_kj + 1e-6


def test_unreachable_stop_is_reported_not_fatal(world):
    from marswalk.config import Stop
    site, st = world
    off = Stop("P1", "Off the map", site.start.lat + 0.05, site.start.lon, work_time_min=5)
    plan = build_plan(site, EVA, st, "metabolic", points=[off, site.stops[0]])
    assert [(v.rule, v.where) for v in plan.violations if v.rule == "unreachable"] == [("unreachable", "P1")]
    assert plan.order == ["A"] and [l.to_id for l in plan.legs] == ["A", "H1"]      # the rest is still planned


def test_safe_zone_shrinks_as_consumables_run_down(world):
    site, st = world
    start = snap(st, st.grid.latlon_to_rc(site.start.lat, site.start.lon))
    back = walkback_field(st, EVA, start)
    area = [int(np.sum(render.safezone_fraction(back, EVA, h) <= 1.0)) for h in (0.0, 5.55, 5.59)]
    assert area[0] >= area[1] > area[2] > 0
    assert render.safezone_png(render.safezone_fraction(back, EVA, 5.55))[:4] == b"\x89PNG"
    for name in ("hillshade", "slope5", "roughness", "ti", "nogo"):
        assert render.layer_png(st, name)[:4] == b"\x89PNG"
