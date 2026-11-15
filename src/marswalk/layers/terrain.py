"""Terrain layers from the 1 m HiRISE DTM (data/raw/<site>/dtm.tif).

Definitions are fixed here so results match the numbers already in the plan:

slope(dem, baseline_m)
    Block-average z to `baseline_m` (k = round(baseline_m / pixel_m) px), then
    degrees(arctan(|grad z|)) with np.gradient spacing k * pixel_m. Upsample back to the
    1 m grid (nearest) so every layer shares one grid. The plan uses baselines of 1 m and 5 m.

roughness(dem)
    Residual relief r = z - gaussian_filter(z, sigma=5 px) (removes trends above ~10 m);
    roughness = std of r in a 5x5 window. Units: metres. This is the rock/block proxy,
    because no HiRISE rock-abundance map covers the boxwork.
    Reference values (stops +-300 m): p50 0.20 m, p90 0.42 m, p99 0.76 m.

steep_fraction(slope_1m, threshold_deg=30, window_px=11)
    Fraction of 1 m cells steeper than the threshold in a window (ledge density).

walk_surface(dem, sigma_px=2)
    The DTM smoothed at about stride scale. Route search takes edge grades from this surface, because
    1 m cell-to-cell height noise in a stereo DTM (~0.2 m) would otherwise read as +-10 deg steps.

hillshade(dem)
    uint8, matplotlib LightSource(315, 35), vert_exag 2. Served as a PNG overlay by the API.

NaN (no data) is handled with normalised convolution, so holes do not create fake cliffs.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.ndimage import gaussian_filter, uniform_filter

from marswalk.geo import Raster


def _gauss_nan(z: np.ndarray, sigma: float) -> np.ndarray:
    valid = np.isfinite(z)
    w = gaussian_filter(valid.astype(np.float32), sigma)
    zs = gaussian_filter(np.where(valid, z, 0.0).astype(np.float32), sigma)
    out = zs / np.maximum(w, 1e-6)
    out[~valid] = np.nan
    return out


def slope(dem: Raster, baseline_m: float) -> Raster:
    z = dem.data.astype(np.float32)
    px = dem.grid.pixel_m
    k = max(int(round(baseline_m / px)), 1)
    h, w = z.shape
    if k > 1:
        ph, pw = (-h) % k, (-w) % k
        zp = np.pad(z, ((0, ph), (0, pw)), mode="edge")
        blocks = zp.reshape(zp.shape[0] // k, k, zp.shape[1] // k, k)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN blocks stay NaN
            z = np.nanmean(blocks, axis=(1, 3))
    gy, gx = np.gradient(z, k * px)
    s = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    if k > 1:
        s = np.repeat(np.repeat(s, k, axis=0), k, axis=1)[:h, :w]
    s[~np.isfinite(dem.data)] = np.nan
    return Raster(np.ascontiguousarray(s), dem.grid, name=f"slope_{baseline_m:g}m", units="deg")


def roughness(dem: Raster) -> Raster:
    z = dem.data.astype(np.float32)
    valid = np.isfinite(z)
    r = np.where(valid, z - _gauss_nan(z, 5.0), 0.0).astype(np.float32)
    m = uniform_filter(r, 5)
    m2 = uniform_filter(r * r, 5)
    out = np.sqrt(np.maximum(m2 - m * m, 0.0)).astype(np.float32)
    out[~valid] = np.nan
    return Raster(out, dem.grid, name="roughness", units="m")


def steep_fraction(slope_1m: Raster, threshold_deg: float = 30.0, window_px: int = 11) -> Raster:
    with np.errstate(invalid="ignore"):
        steep = (slope_1m.data > threshold_deg).astype(np.float32)
    return Raster(uniform_filter(steep, window_px).astype(np.float32), slope_1m.grid, name="steep_frac")


def walk_surface(dem: Raster, sigma_px: float = 2.0) -> np.ndarray:
    return np.ascontiguousarray(_gauss_nan(dem.data.astype(np.float32), sigma_px))


def hillshade(dem: Raster, azimuth_deg: float = 315, altitude_deg: float = 35, vert_exag: float = 2.0) -> np.ndarray:
    from matplotlib.colors import LightSource
    z = dem.data.astype(np.float32)
    fill = np.where(np.isfinite(z), z, np.nanmean(z))
    hs = LightSource(azimuth_deg, altitude_deg).hillshade(fill, vert_exag=vert_exag, dx=dem.grid.pixel_m, dy=dem.grid.pixel_m)
    return (np.clip(hs, 0, 1) * 255).astype(np.uint8)
