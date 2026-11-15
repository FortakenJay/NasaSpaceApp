"""Shared fixtures. Tests never touch the real data directory or the network: MARSWALK_DATA points at a
temp folder, and the terrain tests build a small synthetic site (DTM + coarse thermal inertia) there."""
import json

import numpy as np
import pytest
from affine import Affine
from pyproj import CRS
from scipy.ndimage import gaussian_filter


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MARSWALK_DATA", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """External APIs are off in tests. A test that needs an answer installs its own transport with
    monkeypatch.setattr(api_client, "http_get", ...)."""
    from marswalk.sources import api_client

    def offline(url, timeout=0):
        raise OSError("network disabled in tests")
    monkeypatch.setattr(api_client, "http_get", offline)
    monkeypatch.delenv("NASA_API_KEY", raising=False)
    # create_app() reads the developer's .env, which would put a personal key back
    from marswalk.api import app as api_app
    monkeypatch.setattr(api_app, "load_dotenv", lambda *a, **k: [])


@pytest.fixture
def synthetic_site(tmp_path, isolated_data):
    """A 300 x 320 m site at Gale's latitude: gentle regional slope, a wall with one gap, a data hole.

    Returns the path of its site TOML. Start H1 is north of the wall; A is north, B and C are south of it,
    so every route to B or C has to find the gap."""
    from marswalk.geo import GeoGrid, Raster
    from marswalk.sources.raster import write_geotiff

    crs = "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=137.38 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"
    h, w = 300, 320
    grid = GeoGrid(Affine(1.0, 0.0, 0.0, 0.0, -1.0, -284000.0), CRS.from_user_input(crs), h, w)
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    z = -3600 + 0.05 * yy + 2 * gaussian_filter(rng.standard_normal((h, w)).astype(np.float32), 20)
    wall = np.exp(-((yy - 150) ** 2) / 8.0) * 6.0          # 6 m ridge across the site (40+ deg flanks)
    wall[:, 240:256] = 0.0                                 # one 16 m gap near the east side
    z = (z + wall).astype(np.float32)
    z[:10, :10] = np.nan
    site_id = "synthetic"
    write_geotiff(Raster(z, grid), isolated_data / "raw" / site_id / "dtm.tif")

    # coarse thermal inertia on a DIFFERENT CRS (lon_0 = 0), like the THEMIS mosaic: low TI (sand) in the west
    ti_crs = "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"
    x0 = np.radians(137.38) * 3396190.0
    ti_grid = GeoGrid(Affine(100.0, 0.0, x0 - 200.0, 0.0, -100.0, -283800.0), CRS.from_user_input(ti_crs), 8, 8)
    ti = np.full((8, 8), 400.0, dtype=np.float32)
    ti[:, :3] = 200.0
    write_geotiff(Raster(ti, ti_grid), isolated_data / "raw" / site_id / "ti.tif")

    def ll(r, c):
        lat, lon = grid.rc_to_latlon(r, c)
        return {"lat": lat, "lon": lon}

    stops = {"site": site_id, "start": {"id": "H1", "name": "Rover", **ll(40, 160), "kind": "start"},
             "stops": [{"id": "A", "name": "North stop", **ll(100, 60), "work_time_min": 20},
                       {"id": "B", "name": "South stop", **ll(250, 80), "work_time_min": 20},
                       {"id": "C", "name": "South-east stop", **ll(230, 280), "work_time_min": 20}]}
    stops_path = tmp_path / "stops.json"
    stops_path.write_text(json.dumps(stops))
    lat_min, lon_min, lat_max, lon_max = grid.bounds_latlon()
    toml = tmp_path / "site.toml"
    toml.write_text(f'''
[site]
id = "{site_id}"
name = "Synthetic test site"
stops_file = "{stops_path.as_posix()}"
bbox = {{ lat_min = {lat_min}, lat_max = {lat_max}, lon_min = {lon_min}, lon_max = {lon_max} }}
[body]
radius_m = 3396190.0
gravity_mps2 = 3.71
[products.dtm]
id = "SYNTH"
url = "none"
crs = "{crs}"
transform = [1.0, 0.0, 0.0, 0.0, -1.0, -284000.0]
width = {w}
height = {h}
[products.thermal_inertia]
id = "SYNTH_TI"
url = "none"
sand_ti_threshold = 300.0
[products.basemap_tiles]
url_template = "https://example.invalid/{{z}}/{{y}}/{{x}}.png"
max_zoom = 16
[spaceweather]
donki_base_url = "https://example.invalid"
''')
    return toml
