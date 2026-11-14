"""`marswalk fetch`: cache the site's data window as local GeoTIFFs in data/raw/<site>/ (git-ignored).

TODO(M1). Steps (all windows come from site.bbox, so a new site needs no code changes):
  1. DTM:  raster.read_bbox(dtm.url, bbox, pad_px=300) -> write_geotiff(raw/dtm.tif)
  2. Ortho 1 m: raster.download(ortho_1m.url, raw/<id>.JP2), then crop the same window. Products with
     same_grid_as = "dtm" take the DTM grid (their GeoJP2 header is 1.5 px off), so write raw/ortho_1m.tif
     with the DTM window's transform. Optional 25 cm / color only with --optional.
  3. Thermal inertia: raster.read_bbox(thermal_inertia.url, bbox, pad_px=2) -> raw/ti.tif (100 m, own grid)
  4. raw/manifest.json: product ids, urls, windows, sha256 of each output, fetch time
  Re-running with everything present is a no-op.
"""
from __future__ import annotations

from pathlib import Path

from marswalk.config import PROJECT_ROOT, SiteConfig


def raw_dir(site: SiteConfig) -> Path:
    return PROJECT_ROOT / "data" / "raw" / site.id


def fetch_site(site: SiteConfig, include_optional: bool = False) -> Path:
    """Fetch all required products for `site`. Returns the raw data directory."""
    raise NotImplementedError("M1: implement the fetch steps in the module docstring")
