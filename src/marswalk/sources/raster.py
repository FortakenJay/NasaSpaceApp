"""Remote raster access through GDAL (rasterio): HiRISE PDS IMG, THEMIS ISIS3 cubes, HiRISE JP2.

Implemented: GDAL settings, bbox -> pixel window (pure, tested), and plain file download.
TODO(M1): read_bbox() and write_geotiff() (specs below).

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


def read_bbox(url: str, bbox: dict, band: int = 1, pad_px: int = 0) -> Raster:
    """TODO(M1): read the bbox window of a remote product as a float32 Raster (NaN = nodata).

        with rasterio.Env(**GDAL_ENV), rasterio.open(vsicurl(url)) as ds:
            grid = GeoGrid.from_dataset(ds)
            win = bbox_window(grid, bbox, pad_px)
            a = ds.read(band, window=win, masked=True).astype("float32").filled(np.nan)
            return Raster(a, GeoGrid.from_dataset(ds, win))
    """
    raise NotImplementedError("M1: windowed remote read via GDAL (see docstring)")


def write_geotiff(raster: Raster, path: Path) -> Path:
    """TODO(M1): write a tiled, DEFLATE-compressed GeoTIFF with raster.grid's transform and CRS (nodata NaN)."""
    raise NotImplementedError("M1: local GeoTIFF cache")


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
