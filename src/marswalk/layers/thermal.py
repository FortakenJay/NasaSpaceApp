"""Thermal layers: THEMIS quantitative thermal inertia (100 m, own CRS) put onto the 1 m DTM grid.

- resample_to(ti, target): GDAL reprojection (bilinear). The two CRSs differ (lon_0 = 0 vs 137.38).
- sand_flag(ti_on_dtm, threshold): bool mask, TI < threshold (config: 300 J m^-2 K^-1 s^-1/2).

Honest limitation: at the stops TI is 371-403, nearly uniform. At 100 m it cannot see sand
filling individual boxwork hollows. It is a regional context layer. Local sand detection
(dark + smooth in the 25 cm ortho) is a later upgrade.
"""
from __future__ import annotations

import numpy as np

from marswalk.geo import Raster


def resample_to(ti: Raster, target: Raster) -> Raster:
    from rasterio.warp import Resampling, reproject
    dst = np.full(target.shape, np.nan, dtype=np.float32)
    reproject(source=ti.data.astype(np.float32), destination=dst,
              src_transform=ti.grid.transform, src_crs=ti.grid.crs.to_wkt(), src_nodata=np.nan,
              dst_transform=target.grid.transform, dst_crs=target.grid.crs.to_wkt(), dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    return Raster(dst, target.grid, name="ti", units="J m^-2 K^-1 s^-1/2")


def sand_flag(ti_on_dtm: Raster, threshold: float) -> Raster:
    with np.errstate(invalid="ignore"):
        return Raster(ti_on_dtm.data < threshold, ti_on_dtm.grid, name="sand")
