"""Square pixels on the ground: a Base far from its DTM's standard parallel is resampled (plan, Phase 4)."""
import math

import numpy as np
import pytest
from affine import Affine
from pyproj import CRS

from marswalk.geo import GeoGrid, Raster, ground_distance_m
from marswalk.sources import raster as rs

R = 3394839.8133163          # the Jezero DTM's own sphere


def _eqc(lat_ts: float, lon_0: float, lat: float, lon: float, px: float = 1.0096633, n: int = 400) -> GeoGrid:
    crs = CRS.from_proj4(f"+proj=eqc +lat_ts={lat_ts} +lat_0=0 +lon_0={lon_0} +R={R} +units=m +no_defs")
    x = R * math.cos(math.radians(lat_ts)) * math.radians(lon - lon_0)
    y = R * math.radians(lat)
    return GeoGrid(Affine(px, 0, x - n / 2 * px, 0, -px, y + n / 2 * px), crs, n, n)


def _ground_ew_ns(g: GeoGrid) -> tuple[float, float]:
    a = g.rc_to_latlon(g.height // 2, g.width // 2)
    b = g.rc_to_latlon(g.height // 2, g.width // 2 + 1)
    c = g.rc_to_latlon(g.height // 2 + 1, g.width // 2)
    return ground_distance_m(*a, *b, R), ground_distance_m(*a, *c, R)


def test_aspect_of_the_jezero_dtm():
    g = _eqc(15, 77.44, 18.44, 77.45)
    assert rs.ground_aspect(g, 18.44) == pytest.approx(0.9821, abs=1e-4)
    ew, ns = _ground_ew_ns(g)
    assert ew / ns == pytest.approx(rs.ground_aspect(g, 18.44), rel=1e-4)


def test_gale_is_left_alone():
    g = _eqc(0, 137.38, -4.8, 137.385)
    assert abs(rs.ground_aspect(g, -4.8) - 1) < rs.SQUARE_TOL
    assert rs.square_grid(g, -4.8) is None


def test_square_grid_and_warp_keep_positions():
    src = _eqc(15, 77.44, 18.44, 77.45)
    dst = rs.square_grid(src, 18.44)
    assert dst is not None
    ew, ns = _ground_ew_ns(dst)
    assert ew == pytest.approx(ns, rel=1e-4) and ns == pytest.approx(src.pixel_m, rel=1e-4)
    lat0, lon0, lat1, lon1 = src.bounds_latlon()
    dlat0, dlon0, dlat1, dlon1 = dst.bounds_latlon()
    assert (dlat0, dlon0, dlat1, dlon1) == pytest.approx((lat0, lon0, lat1, lon1), abs=2e-5)   # same area
    # a height field that is linear in lat/lon comes through the warp unchanged at the same place
    rows, cols = np.mgrid[0:src.height, 0:src.width]
    lats, lons = src.rc_to_latlon_many(rows.ravel(), cols.ravel())
    field = (1000 * lats + 300 * lons).reshape(src.height, src.width).astype(np.float32)
    out = rs.warp(Raster(field, src), dst)
    for lat, lon in [(18.44, 77.45), (18.441, 77.452), (18.439, 77.447)]:
        assert out.value_at(lat, lon) == pytest.approx(1000 * lat + 300 * lon, abs=0.01)
