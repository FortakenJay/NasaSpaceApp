"""Terrain layers from the 1 m HiRISE DTM (data/raw/<site>/dtm.tif).

TODO(M2). Definitions are fixed here so results match the numbers already in the plan:

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

hillshade(dem)
    uint8, matplotlib LightSource(315, 35), vert_exag 2. Served as a PNG overlay by the API.
"""
from __future__ import annotations

import numpy as np

from marswalk.geo import Raster


def slope(dem: Raster, baseline_m: float) -> Raster:
    raise NotImplementedError("M2: slope at a baseline (see module docstring)")


def roughness(dem: Raster) -> Raster:
    raise NotImplementedError("M2: detrended 5x5 std roughness (see module docstring)")


def steep_fraction(slope_1m: Raster, threshold_deg: float = 30.0, window_px: int = 11) -> Raster:
    raise NotImplementedError("M2: steep-cell fraction (see module docstring)")


def hillshade(dem: Raster, azimuth_deg: float = 315, altitude_deg: float = 35, vert_exag: float = 2.0) -> np.ndarray:
    raise NotImplementedError("M2: hillshade")
