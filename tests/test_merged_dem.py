"""The wider USGS merged DEM as the base surface, with the HiRISE strip as the only plannable area.

Both products are sampled from ONE analytic surface on two different grids and CRSs (like the real ones:
HiRISE eqc lon_0 = 137.38, merged eqc lon_0 = 0), the merged one 100 m wider on every side."""
import math

import numpy as np
import pytest
from affine import Affine
from pyproj import CRS
from scipy.ndimage import gaussian_filter

from marswalk.config import load_eva, load_site
from marswalk.cost.base import model_from_eva
from marswalk.geo import GeoGrid, Raster
from marswalk.layers import render
from marswalk.layers.stack import build_stack, raw_stamp
from marswalk.route.astar import astar
from marswalk.route.plan import build_plan
from marswalk.sources.fetch import MERGED_FILE, read_merged_dem
from marswalk.sources.raster import write_geotiff

EVA = load_eva("configs/eva/artemis_default.toml")
R = 3396190.0
MERGED_CRS = "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"
PAD = 100


def surface(r: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Elevation at HiRISE-grid pixel (r, c), defined everywhere (also outside the strip)."""
    wall = np.exp(-((r - 150) ** 2) / 8.0) * 6.0 * ~((c >= 240) & (c < 256))
    texture = 0.25 * np.sin(2 * np.pi * c / 7.0) * np.cos(2 * np.pi * r / 9.0)
    return (-3600 + 0.05 * r + 0.8 * np.sin(2 * np.pi * c / 61.0) + wall + texture).astype(np.float32)


def write_merged(path, smooth_px: float = 0.0, shift_m: float = 0.0):
    h, w = 300 + 2 * PAD, 320 + 2 * PAD
    rr, cc = np.mgrid[0:h, 0:w].astype(np.float32)
    z = surface(rr - PAD, cc - PAD)
    if smooth_px:
        z = gaussian_filter(z, smooth_px).astype(np.float32)
    x0 = math.radians(137.38) * R
    grid = GeoGrid(Affine(1.0, 0.0, x0 - PAD + shift_m, 0.0, -1.0, -284000.0 + PAD - shift_m), CRS.from_user_input(MERGED_CRS), h, w)
    write_geotiff(Raster(z, grid), path)


@pytest.fixture
def merged_site(synthetic_site, isolated_data):
    """The synthetic site, with its DTM replaced by the analytic surface and a wider merged DEM next to it."""
    from marswalk.sources.raster import read_geotiff
    raw = isolated_data / "raw" / "synthetic"
    dtm = read_geotiff(raw / "dtm.tif")
    rr, cc = np.mgrid[0:300, 0:320].astype(np.float32)
    write_geotiff(Raster(surface(rr, cc), dtm.grid), raw / "dtm.tif")
    write_merged(raw / MERGED_FILE)
    text = synthetic_site.read_text() + f'''
[products.merged_dem]
id = "SYNTH_MERGED"
url = "{(raw / MERGED_FILE).as_posix()}"
crs = "{MERGED_CRS}"
enabled = true
'''
    synthetic_site.write_text(text)
    return synthetic_site, raw


def test_merged_dem_is_the_base_and_only_the_strip_is_plannable(merged_site):
    toml, _ = merged_site
    site = load_site(toml)
    st = build_stack(site, EVA, use_cache=False)
    assert st.terrain_source == "merged" and st.shape == (500, 520) and st.grid.pixel_m == 1.0
    assert st.coarse is not None and st.coarse[0, 0] and st.coarse[499, 519]
    r, c = st.grid.latlon_to_rc(site.start.lat, site.start.lon)
    assert (r, c) == (PAD + 40, PAD + 160) and not st.coarse[r, c] and not st.nogo[r, c]
    assert st.nogo[st.coarse].all()                                     # no trusted 1 m data: never planned on
    assert 0.30 < 1 - st.coarse.mean() < 0.36                           # the strip, trimmed at its edge
    ck = st.terrain_check
    assert ck["median_slope_diff_deg"] < 0.5 and abs(ck["median_dz_m"]) < 0.05
    assert 0.85 < ck["median_roughness_ratio"] < 1.3
    assert np.isfinite(st.slope_5m_deg[0, 0])                           # context terrain exists outside the strip


def test_routes_stay_on_trusted_terrain(merged_site):
    toml, _ = merged_site
    site = load_site(toml)
    st = build_stack(site, EVA, use_cache=False)
    model = model_from_eva(EVA, "metabolic")
    b = next(s for s in site.stops if s.id == "B")
    path = astar(st, model, st.grid.latlon_to_rc(site.start.lat, site.start.lon), st.grid.latlon_to_rc(b.lat, b.lon))
    assert path is not None and not any(st.coarse[rc] or st.nogo[rc] for rc in path.cells)
    crossing = [c - PAD for r, c in path.cells if r == PAD + 150]
    assert crossing and all(240 <= c < 256 for c in crossing)           # still has to find the gap in the wall
    plan = build_plan(site, EVA, st, "metabolic")
    assert plan.order == ["A", "B", "C"] and not [v for v in plan.violations if v.severity == "no-go"]


def test_smoother_merged_dem_is_set_aside(merged_site):
    toml, raw = merged_site
    write_merged(raw / MERGED_FILE, smooth_px=4.0)                       # hides the 1 m texture (rocks)
    st = build_stack(load_site(toml), EVA, use_cache=False)
    assert st.terrain_source == "hirise" and st.coarse is None and st.shape == (300, 320)
    assert "smoother" in st.terrain_note and "median_roughness_ratio" in st.terrain_check
    notes = {l["key"]: l["note"] for l in render.layer_list(st)}
    assert "not used" in notes["slope5"] and "HiRISE stereo strip" in notes["slope5"]


def test_disabled_merged_dem_is_ignored(merged_site):
    toml, _ = merged_site
    toml.write_text(toml.read_text().replace("enabled = true", "enabled = false"))
    site = load_site(toml)
    assert site.merged_dem is None
    st = build_stack(site, EVA, use_cache=False)
    assert st.terrain_source == "hirise" and st.terrain_note == ""


def test_read_merged_dem_window_and_crs_guard(merged_site):
    toml, raw = merged_site
    site = load_site(toml)
    dem = read_merged_dem(site, log=lambda _: None)
    assert dem.shape == (500, 520)
    assert dem.value_at(site.start.lat, site.start.lon) == pytest.approx(float(surface(np.float32(40), np.float32(160))), abs=1e-3)
    # A file georeferenced 450 m off in x and y only half-overlaps the window: refused, not silently misplaced.
    bad = raw / "bad.tif"
    write_merged(bad, shift_m=450.0)
    with pytest.raises(ValueError):
        read_merged_dem(site, url=str(bad), log=lambda _: None)


def test_overlays_and_notes_show_the_two_kinds_of_terrain(merged_site):
    toml, raw = merged_site
    site = load_site(toml)
    st = build_stack(site, EVA, use_cache=False)
    for name in ("hillshade", "slope5", "roughness", "nogo"):
        assert render.layer_png(st, name)[:8] == b"\x89PNG\r\n\x1a\n"
    notes = {l["key"]: l["note"] for l in render.layer_list(st)}
    assert "Faded" in notes["slope5"] and "Grey" in notes["nogo"]
    before = raw_stamp(site)
    write_merged(raw / MERGED_FILE)
    assert raw_stamp(site) != before                                    # overlay PNG cache key follows the file


def _misregister_dtm(raw, east: float, north: float):
    """Rewrite dtm.tif with its georeferencing off by (east, north) metres, like the real HiRISE DTM."""
    from marswalk.layers.coverage import shifted
    from marswalk.sources.raster import read_geotiff
    dtm = read_geotiff(raw / "dtm.tif")
    write_geotiff(shifted(dtm, {"east": east, "north": north}), raw / "dtm.tif")


def test_register_measures_a_georeferencing_offset(merged_site):
    from marswalk.layers.coverage import register
    from marswalk.sources.raster import read_geotiff
    _, raw = merged_site
    _misregister_dtm(raw, east=6.0, north=-4.0)
    reg = register(read_geotiff(raw / "dtm.tif"), read_geotiff(raw / MERGED_FILE), patch_px=160, search_px=12)
    assert reg["corr"] > 0.99 and not reg["at_edge"]
    assert reg["east_m"] == pytest.approx(-6.0, abs=0.5) and reg["north_m"] == pytest.approx(4.0, abs=0.5)


def test_configured_basemap_offset_puts_the_dtm_back_on_the_frame(merged_site):
    toml, raw = merged_site
    _misregister_dtm(raw, east=6.0, north=-4.0)
    text = toml.read_text().replace('url = "none"\ncrs', 'url = "none"\nbasemap_offset_m = { east = -6.0, north = 4.0 }\ncrs', 1)
    toml.write_text(text)
    site = load_site(toml)
    assert site.dtm["basemap_offset_m"] == {"east": -6.0, "north": 4.0}
    st = build_stack(site, EVA, use_cache=False)
    assert st.terrain_source == "merged" and st.terrain_check["median_slope_diff_deg"] < 0.5
    r, c = st.grid.latlon_to_rc(site.start.lat, site.start.lon)
    assert not st.coarse[r, c]


def test_config_stops_are_resynced_into_an_existing_database(synthetic_site):
    import dataclasses

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from marswalk.db import repo
    from marswalk.db.models import Base
    site = load_site(synthetic_site)
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        assert repo.seed_site(db, site)
        user = repo.add_stop(db, site.id, lat=site.start.lat, lon=site.start.lon, name="mine")
        moved = dataclasses.replace(site, start=dataclasses.replace(site.start, lat=site.start.lat + 0.0003))
        assert not repo.seed_site(db, moved)
        stops = {s["id"]: s for s in repo.list_stops(db, site.id)}
        assert stops["H1"]["lat"] == pytest.approx(site.start.lat + 0.0003)
        assert stops[user["id"]]["lat"] == pytest.approx(site.start.lat)           # user stops are left alone
