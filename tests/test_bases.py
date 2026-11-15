"""Bases: TOML writer, registry (focus, delete), the creation job (network replaced), and the API routes."""
import json
import threading
import tomllib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from marswalk.bases import tomlw


def test_tomlw_round_trip():
    data = {"site": {"id": "b_x", "name": "Jezero \"delta\"", "bbox": {"lat_min": -1.5, "lat_max": 1.25}},
            "body": {"radius_m": 3396190.0, "gravity_mps2": 3.71},
            "products": {"dtm": {"id": "D", "transform": [1.0, 0.0, -2.5, 0.0, -1.0, 3.0], "width": 10,
                                 "basemap_offset_m": {"east": -10.07, "north": -26.95}, "flag": True},
                         "context_tiles": [{"name": "A", "max_zoom": 9}, {"name": "B", "max_zoom": 11}]}}
    text = tomlw.dumps(data, "header line")
    assert text.startswith("# header line")
    assert tomllib.loads(text) == data


# --- a fake Base job: catalog, network reads and alignment replaced by the synthetic site -------------------------

@pytest.fixture
def fake_world(synthetic_site, isolated_data, monkeypatch):
    """Point the job at the synthetic site's rasters instead of the HiRISE archive."""
    from marswalk.config import load_site
    from marswalk.geo import GeoGrid
    from marswalk.sources import catalog, fetch
    from marswalk.sources import raster as rs

    synth = load_site(synthetic_site)
    src = isolated_data / "raw" / synth.id
    grid = rs.read_geotiff(src / "dtm.tif").grid
    lat_c, lon_c = grid.rc_to_latlon(40, 160)                # H1 of the synthetic site (flat, north of the wall)
    lat0, lon0, lat1, lon1 = grid.bounds_latlon()
    entry = catalog.DtmEntry("DTEEC_SYNTH", "synthetic-dtm", "f", 1.0, "EQUIRECTANGULAR",
                             [[lat1, lon0], [lat1, lon1], [lat0, lon1], [lat0, lon0]], rationale="Synthetic strip",
                             orthos={"RED_C": "synthetic/SYNTH_RED_C_01_ORTHO.JP2"})
    monkeypatch.setattr(catalog, "ensure_index", lambda **k: [entry])
    monkeypatch.setattr(rs, "open_grid", lambda url: GeoGrid(grid.transform, grid.crs, grid.height, grid.width))
    monkeypatch.setattr(rs, "read_point_window", lambda url, lat, lon, half_px=32: (np.zeros((4, 4), np.float32), grid))
    calls = {"n": 0}

    def fake_fetch(site, include_optional=False, log=print, progress=None, cancel=None):
        import shutil
        out = fetch.raw_dir(site)
        out.mkdir(parents=True, exist_ok=True)
        if cancel is not None and calls.get("block"):
            calls["started"].set()
            while not cancel.is_set():
                cancel.wait(0.05)
            raise rs.Cancelled("cancelled")
        shutil.copy(src / "dtm.tif", out / "dtm.tif")
        if progress:
            progress("dtm", 1.0)
        (out / "manifest.json").write_text(json.dumps({"bbox": dict(site.bbox), "products": {
            "dtm": {"file": "dtm.tif"}, "thermal_inertia": {"error": "offline"}, "ortho_1m": {"error": "offline"}}}))
        calls["n"] += 1
        return out
    monkeypatch.setattr(fetch, "fetch_site", fake_fetch)
    from marswalk.layers import align
    monkeypatch.setattr(align, "auto", lambda site, raw, cancel=None, progress=None: {
        "source": "hirise_global", "quality": "good", "east_m": 0.0, "north_m": 0.0, "corr": 0.9, "spread_m": 1.0, "n_patches": 5})
    return {"lat": lat_c, "lon": lon_c, "calls": calls}


def _registry():
    from marswalk.bases.registry import BaseRegistry
    from marswalk.config import load_site
    from marswalk.db.engine import make_engine, make_session_factory
    return BaseRegistry(load_site("configs/sites/gale_boxwork.toml"), make_session_factory(make_engine("sqlite://")))


def test_job_creates_a_ready_base_and_registry_lists_it(fake_world):
    from marswalk.bases.jobs import JobRunner
    from marswalk.config import load_eva
    reg = _registry()
    runner = JobRunner(reg, load_eva("configs/eva/artemis_default.toml"))
    snap = runner.start(fake_world["lat"], fake_world["lon"], "Test Base", background=False)
    snap = runner.snapshot()
    assert snap["status"] == "ready", snap
    bid = snap["base_id"]
    info = reg.info(bid)
    assert info["status"] == "ready" and info["radiation"]["estimate"] is True
    assert any("thermal inertia" in w.lower() for w in info["warnings"])        # TI failed -> warned
    site = reg.site(bid)
    assert site.start.id == "H1" and site.stops == ()
    assert site.dtm["alignment"]["quality"] == "good"
    assert site.spaceweather["rad_estimate"]["elevation_m"] < 0
    assert [b["id"] for b in reg.list()] == ["gale_boxwork", bid]


def test_focus_and_delete(fake_world, isolated_data):
    from marswalk.bases.jobs import JobRunner
    from marswalk.config import load_eva
    from marswalk.db import repo
    reg = _registry()
    JobRunner(reg, load_eva("configs/eva/artemis_default.toml")).start(fake_world["lat"], fake_world["lon"], "B1", background=False)
    bid = reg.list()[1]["id"]
    assert reg.focused_id() == "gale_boxwork"
    reg.set_focus(bid)
    assert reg.focused_id() == bid
    with pytest.raises(repo.NotAllowed):
        reg.delete("gale_boxwork")
    reg.delete(bid)
    assert reg.focused_id() == "gale_boxwork"
    assert not (isolated_data / "bases" / bid).exists() and not (isolated_data / "raw" / bid).exists()
    with reg.sessions() as s, pytest.raises(repo.NotFound):
        repo.list_stops(s, bid)


def test_no_terrain_here_fails_with_a_plain_message(fake_world):
    from marswalk.bases.jobs import JobRunner
    from marswalk.config import load_eva
    runner = JobRunner(_registry(), load_eva("configs/eva/artemis_default.toml"))
    runner.start(40.0, -150.0, "Nowhere", background=False)
    s = runner.snapshot()
    assert s["status"] == "failed" and "HiRISE" in s["error"]


def test_cancel_removes_everything(fake_world, isolated_data):
    from marswalk.bases.jobs import Busy, JobRunner
    from marswalk.config import load_eva
    fake_world["calls"].update(block=True, started=threading.Event())
    runner = JobRunner(_registry(), load_eva("configs/eva/artemis_default.toml"))
    runner.start(fake_world["lat"], fake_world["lon"], "Cancelled Base")
    assert fake_world["calls"]["started"].wait(10)
    with pytest.raises(Busy):
        runner.start(fake_world["lat"], fake_world["lon"], "Second")
    bid = runner.snapshot()["base_id"]
    assert runner.cancel(bid)
    runner._thread.join(10)
    assert runner.snapshot()["status"] == "cancelled"
    assert not (isolated_data / "bases" / bid).exists() and not (isolated_data / "raw" / bid).exists()


def test_api_bases_routes(fake_world):
    from marswalk.api.app import create_app
    c = TestClient(create_app(db_url="sqlite://"))
    d = c.get("/api/bases").json()
    assert d["focused"] == "gale_boxwork" and d["bases"][0]["kind"] == "builtin" and d["job"] is None
    assert c.delete("/api/bases/gale_boxwork").status_code == 403
    assert c.post("/api/bases/focus", json={"id": "nope"}).status_code == 404
    assert c.post("/api/bases", json={"lat": 40.0, "lon": -150.0}).status_code == 422
    look = c.get(f"/api/catalog/lookup?lat={fake_world['lat']}&lon={fake_world['lon']}").json()
    assert look["candidates"][0]["product_id"] == "DTEEC_SYNTH"
    fp = c.get("/api/catalog/footprints")
    assert fp.status_code == 200 and fp.json()["features"][0]["properties"]["supported"] is True
    r = c.post("/api/bases", json={"lat": fake_world["lat"], "lon": fake_world["lon"], "name": "API Base"})
    assert r.status_code == 202
    app_runner = c.app.state.runner
    app_runner._thread.join(30)
    job = c.get("/api/bases/job").json()
    assert job["status"] == "ready", job
    bid = job["base_id"]
    # focus it: the site, its stops and the layer URLs now belong to the new Base
    d = c.post("/api/bases/focus", json={"id": bid}).json()
    assert d["focused"] == bid
    site = c.get("/api/site").json()
    assert site["site"]["id"] == bid and [s["id"] for s in site["stops"]] == ["H1"]
    assert site["site"]["radiation"]["estimate"] is True
    layers = c.get("/api/layers").json()
    assert layers and all(f"b={bid}" in ly["url"] for ly in layers)
    # delete the focused Base: back to Gale
    d = c.delete(f"/api/bases/{bid}").json()
    assert d["focused"] == "gale_boxwork" and [b["id"] for b in d["bases"]] == ["gale_boxwork"]
    assert d["job"] is None                       # the finished job's report went with its Base
    assert c.get("/api/site").json()["site"]["id"] == "gale_boxwork"
