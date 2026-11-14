import math

from marswalk.config import load_site
from marswalk.geo import GeoGrid, ground_distance_m
from marswalk.sources.raster import bbox_window

SITE = load_site("configs/sites/gale_boxwork.toml")


def dtm_grid() -> GeoGrid:
    return GeoGrid.from_product(SITE.dtm)


def test_known_pixel_for_s3():
    # Verified 2026-11-13: GDAL's ds.index() and the hand calculation both give (4613, 4032).
    assert dtm_grid().latlon_to_rc(-4.807839, 137.381035) == (4613, 4032)


def test_known_pixel_for_h1():
    assert dtm_grid().latlon_to_rc(-4.798777, 137.385215) == (4082, 4277)


def test_roundtrip_pixel_centre():
    g = dtm_grid()
    lat, lon = g.rc_to_latlon(4613, 4032)
    assert g.latlon_to_rc(lat, lon) == (4613, 4032)


def test_window_offsets():
    g = dtm_grid().window(3450, 100, 1466, 7000)
    assert g.latlon_to_rc(-4.807839, 137.381035) == (4613 - 3450, 4032 - 100)


def test_pixel_size_matches_mars_degrees():
    g = dtm_grid()
    deg = math.pi / 180 * 3396190.0
    lat0, lon0 = g.rc_to_latlon(4613, 4032)
    lat1, lon1 = g.rc_to_latlon(4613, 4033)
    assert abs((lon1 - lon0) * deg - g.pixel_m) < 1e-6


def test_bbox_window_covers_all_stops():
    g = dtm_grid()
    w = bbox_window(g, SITE.bbox)
    for s in (SITE.start, *SITE.stops):
        r, c = g.latlon_to_rc(s.lat, s.lon)
        assert w.row_off <= r < w.row_off + w.height and w.col_off <= c < w.col_off + w.width, s.id


def test_ground_distance_h1_s1():
    d = ground_distance_m(-4.798777, 137.385215, -4.799847, 137.383541, 3396190.0)
    assert 110 < d < 125
