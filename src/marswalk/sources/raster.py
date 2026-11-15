"""Remote raster access through GDAL (rasterio): HiRISE PDS IMG, THEMIS ISIS3 cubes, HiRISE JP2.

Implemented: GDAL settings, bbox -> pixel window, windowed remote reads, GeoTIFF cache, file download.

Verified 2026-11-13 with rasterio 1.5 / GDAL 3.12:
- `/vsicurl/<url>` opens the DTM (PDS driver) and the TI mosaic (ISIS3 driver) directly; transforms
  and CRS come from the files' own labels.
- The full-width Gale DTM strip (1466 x 7426 px) reads in ~8 s with 4 MB curl chunks, even though the
  HiRISE server takes ~15 s per small request when hit one request at a time.
- HiRISE ortho JP2s carry a GeoJP2 header that is 1.5 px off the DTM grid, while their PDS labels
  match it. Treat `same_grid_as = "dtm"` products as being on the DTM grid.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.windows import Window

from marswalk.geo import GeoGrid, Raster

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",   # don't list remote directories
    "CPL_VSIL_CURL_CHUNK_SIZE": str(4 * 1024 * 1024),
    "VSI_CACHE": "TRUE",
    "GDAL_HTTP_MAX_RETRY": "4",                     # HiRISE server returns 503 under load
    "GDAL_HTTP_RETRY_DELAY": "5",
}
USER_AGENT = "marswalk/0.1 (research prototype)"


def vsicurl(url: str) -> str:
    return url if url.startswith("/vsicurl/") else "/vsicurl/" + url


def bbox_window(grid: GeoGrid, bbox: dict, pad_px: int = 0) -> Window:
    """Pixel window covering a lat/lon bbox ({lat_min, lat_max, lon_min, lon_max}), clipped to the grid."""
    corners = [grid.latlon_to_rc(la, lo) for la in (bbox["lat_min"], bbox["lat_max"])
               for lo in (bbox["lon_min"], bbox["lon_max"])]
    r0 = max(min(r for r, _ in corners) - pad_px, 0)
    c0 = max(min(c for _, c in corners) - pad_px, 0)
    r1 = min(max(r for r, _ in corners) + 1 + pad_px, grid.height)
    c1 = min(max(c for _, c in corners) + 1 + pad_px, grid.width)
    if r1 <= r0 or c1 <= c0:
        raise ValueError("bbox does not overlap the product")
    return Window(c0, r0, c1 - c0, r1 - r0)


def _source(url_or_path: str | Path) -> str:
    """A local file is opened directly; anything else goes through /vsicurl/."""
    return str(url_or_path) if Path(str(url_or_path)).exists() else vsicurl(str(url_or_path))


def _to_float(a) -> np.ndarray:
    out = np.ma.filled(a.astype("float32"), np.nan)
    out[~np.isfinite(out) | (out < -1e30)] = np.nan   # PDS/ISIS "missing" constants that carry no nodata tag
    return np.ascontiguousarray(out)


def read_bbox(url: str | Path, bbox: dict, band: int = 1, pad_px: int = 0, crs: str | None = None,
              env: dict | None = None) -> Raster:
    """Read the bbox window of a remote (or local) product as a float32 Raster (NaN = nodata).

    `crs` replaces the CRS GDAL reports (the affine transform still comes from the file). Use it when a file's
    own Mars CRS is spelled in a way pyproj does not understand. `env` adds GDAL options for this read.
    """
    with rasterio.Env(**{**GDAL_ENV, **(env or {})}), rasterio.open(_source(url)) as ds:
        # With an override, never ask GDAL/pyproj to parse the file's own (possibly exotic) Mars CRS.
        grid = (GeoGrid(ds.transform, CRS.from_user_input(crs), ds.height, ds.width) if crs
                else GeoGrid.from_dataset(ds))
        win = bbox_window(grid, bbox, pad_px)
        a = ds.read(band, window=win, masked=True)
        return Raster(_to_float(a), grid.window(win.row_off, win.col_off, int(win.height), int(win.width)))


def read_geotiff(path: Path, band: int = 1) -> Raster:
    """Read a whole cached GeoTIFF written by write_geotiff()."""
    with rasterio.open(path) as ds:
        return Raster(_to_float(ds.read(band, masked=True)), GeoGrid.from_dataset(ds), name=Path(path).stem)


def write_geotiff(raster: Raster, path: Path) -> Path:
    """Write a tiled, DEFLATE-compressed float32 GeoTIFF with raster.grid's transform and CRS (nodata NaN)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = raster.shape
    tmp = path.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32",
                       crs=raster.grid.crs.to_wkt(), transform=raster.grid.transform, nodata=float("nan"),
                       tiled=True, blockxsize=256, blockysize=256, compress="deflate") as ds:
        ds.write(raster.data.astype("float32"), 1)
    tmp.replace(path)
    return path


def download(url: str, dest: Path, timeout: float = 900) -> Path:
    """Download a whole small file (e.g. a 1 m ortho JP2, 20-45 MB). Skips if already present."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return dest
