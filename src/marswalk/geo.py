"""Grids and rasters in Mars coordinates (rasterio affine transform + pyproj CRS).

Implemented. A GeoGrid is what GDAL reports for a product (or a window of it): affine transform,
CRS, and shape. lat/lon are Mars 2000 planetocentric, east-positive (the CRS's geodetic datum).
Verified: S3 (-4.807839, 137.381035) -> pixel (4613, 4032) on the full DTM grid, identical to GDAL's
own `ds.index()` and to the hand calculation done during site selection.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np
from affine import Affine
from pyproj import CRS, Transformer


@dataclass(frozen=True)
class GeoGrid:
    transform: Affine
    crs: CRS
    height: int
    width: int

    @classmethod
    def from_product(cls, product: dict) -> "GeoGrid":
        """Build from a site-config product table (crs + transform + width/height)."""
        return cls(Affine(*product["transform"][:6]), CRS.from_user_input(product["crs"]),
                   product["height"], product["width"])

    @classmethod
    def from_dataset(cls, ds, window=None) -> "GeoGrid":
        """Build from an open rasterio dataset, optionally for a rasterio Window of it."""
        t = ds.window_transform(window) if window is not None else ds.transform
        h, w = (int(window.height), int(window.width)) if window is not None else (ds.height, ds.width)
        return cls(t, CRS.from_wkt(ds.crs.to_wkt()), h, w)

    @cached_property
    def _fwd(self) -> Transformer:
        return Transformer.from_crs(self.crs.geodetic_crs, self.crs, always_xy=True)

    @cached_property
    def _inv(self) -> Transformer:
        return Transformer.from_crs(self.crs, self.crs.geodetic_crs, always_xy=True)

    @property
    def pixel_m(self) -> float:
        return abs(self.transform.a)

    def latlon_to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return self._fwd.transform(lon, lat)

    def latlon_to_rc(self, lat: float, lon: float) -> tuple[int, int]:
        x, y = self.latlon_to_xy(lat, lon)
        c, r = ~self.transform @ (x, y)
        return math.floor(r), math.floor(c)

    def rc_to_latlon(self, r: float, c: float) -> tuple[float, float]:
        """lat/lon of the CENTRE of pixel (r, c)."""
        x, y = self.transform @ (c + 0.5, r + 0.5)
        lon, lat = self._inv.transform(x, y)
        return lat, lon

    def rc_to_latlon_many(self, rows, cols) -> tuple[np.ndarray, np.ndarray]:
        """Vectorised rc_to_latlon (pixel centres). Returns (lats, lons)."""
        rows = np.asarray(rows, dtype=np.float64) + 0.5
        cols = np.asarray(cols, dtype=np.float64) + 0.5
        t = self.transform
        xs = t.a * cols + t.b * rows + t.c
        ys = t.d * cols + t.e * rows + t.f
        lons, lats = self._inv.transform(xs, ys)
        return np.asarray(lats), np.asarray(lons)

    def window(self, row_off: int, col_off: int, height: int, width: int) -> "GeoGrid":
        return GeoGrid(self.transform @ Affine.translation(col_off, row_off), self.crs, height, width)

    def bounds_latlon(self) -> tuple[float, float, float, float]:
        """(lat_min, lon_min, lat_max, lon_max) of the outer pixel edges."""
        x0, y0 = self.transform @ (0, 0)
        x1, y1 = self.transform @ (self.width, self.height)
        lon_a, lat_a = self._inv.transform(x0, y0)
        lon_b, lat_b = self._inv.transform(x1, y1)
        return min(lat_a, lat_b), min(lon_a, lon_b), max(lat_a, lat_b), max(lon_a, lon_b)


@dataclass
class Raster:
    """A 2-D float array on a GeoGrid. NaN = no data."""

    data: np.ndarray
    grid: GeoGrid
    name: str = ""
    units: str = ""

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape  # type: ignore[return-value]

    def value_at(self, lat: float, lon: float) -> float:
        r, c = self.grid.latlon_to_rc(lat, lon)
        if not (0 <= r < self.shape[0] and 0 <= c < self.shape[1]):
            return math.nan
        return float(self.data[r, c])


def ground_distance_m(lat1: float, lon1: float, lat2: float, lon2: float, radius_m: float) -> float:
    """Great-circle distance on a sphere (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))
