"""Thermal layers: THEMIS quantitative thermal inertia (100 m, own CRS) put onto the 1 m DTM grid.

TODO(M2).
- resample_to(ti, target): rasterio.warp.reproject(ti.data -> empty target-shaped array,
  src_transform/src_crs = ti.grid, dst_transform/dst_crs = target.grid, Resampling.bilinear).
  The two CRSs differ (lon_0 = 0 vs 137.38), and GDAL handles that.
- sand_flag(ti_on_dtm, threshold): bool mask, TI < threshold (config: 300 J m^-2 K^-1 s^-1/2).

Honest limitation: at the stops TI is 371-403, nearly uniform. At 100 m it cannot see sand
filling individual boxwork hollows. It is a regional context layer. Local sand detection
(dark + smooth in the 25 cm ortho) is a later upgrade.
"""
from __future__ import annotations

from marswalk.geo import Raster


def resample_to(ti: Raster, target: Raster) -> Raster:
    raise NotImplementedError("M2: reproject TI onto the DTM grid")


def sand_flag(ti_on_dtm: Raster, threshold: float) -> Raster:
    raise NotImplementedError("M2: TI < threshold mask")
