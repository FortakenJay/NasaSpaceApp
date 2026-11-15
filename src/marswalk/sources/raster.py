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

import threading
import urllib.request
from pathlib import Path
from typing import Callable

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
STRIP_ROWS = 512    # with a progress callback, windows are read in strips this tall (same bytes, progress between)

Progress = Callable[[float], None]     # fraction done, 0..1


class Cancelled(Exception):
    """A long read or download was stopped by its cancel event."""


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("cancelled")


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


SQUARE_TOL = 0.005      # pixels more than 0.5 % from square on the ground are resampled (Gale: 0.35 %, left alone)


def _proj_params(crs) -> dict:
    """PROJ parameters of a CRS (to_dict warns that a PROJ string is lossy; only the eqc numbers are needed here)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return CRS.from_user_input(crs).to_dict()


def ground_aspect(grid: GeoGrid, lat: float) -> float:
    """East-west over north-south ground size of one pixel at latitude `lat` (1.0 = square on the ground).

    An equirectangular grid is square on the ground only at its standard parallel (lat_ts): elsewhere east-west
    pixels are cos(lat) / cos(lat_ts) of their nominal size. The layers and the route search treat pixels as square.
    """
    import math
    p = _proj_params(grid.crs)
    if p.get("proj") != "eqc":
        return 1.0
    return math.cos(math.radians(lat)) / math.cos(math.radians(float(p.get("lat_ts", 0.0))))


def square_grid(src: GeoGrid, lat: float, tol: float = SQUARE_TOL) -> GeoGrid | None:
    """The same area on an equirectangular grid whose standard parallel is `lat` (so pixels are square on the ground
    there), at the source's north-south pixel size; None if `src` is already square within `tol`."""
    if abs(ground_aspect(src, lat) - 1.0) <= tol:
        return None
    from affine import Affine
    from rasterio.warp import calculate_default_transform
    p = _proj_params(src.crs)
    p["lat_ts"] = round(float(lat), 4)
    dst_crs = CRS.from_dict(p)
    x0, y0 = src.transform @ (0, 0)
    x1, y1 = src.transform @ (src.width, src.height)
    px = abs(src.transform.e)
    t, w, h = calculate_default_transform(src.crs.to_wkt(), dst_crs.to_wkt(), src.width, src.height,
                                          min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), resolution=px)
    return GeoGrid(Affine(*t[:6]), dst_crs, int(h), int(w))


def warp(r: Raster, grid: GeoGrid, bilinear: bool = True) -> Raster:
    """`r` resampled onto `grid` (NaN outside and where the source has no data)."""
    from rasterio.warp import Resampling, reproject
    dst = np.full((grid.height, grid.width), np.nan, dtype=np.float32)
    reproject(source=r.data.astype(np.float32), destination=dst, src_transform=r.grid.transform,
              src_crs=r.grid.crs.to_wkt(), dst_transform=grid.transform, dst_crs=grid.crs.to_wkt(),
              src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.bilinear if bilinear else Resampling.nearest)
    return Raster(dst, grid, name=r.name, units=r.units)


def _source(url_or_path: str | Path) -> str:
    """A local file is opened directly; anything else goes through /vsicurl/."""
    return str(url_or_path) if Path(str(url_or_path)).exists() else vsicurl(str(url_or_path))


def _to_float(a) -> np.ndarray:
    out = np.ma.filled(a.astype("float32"), np.nan)
    out[~np.isfinite(out) | (out < -1e30)] = np.nan   # PDS/ISIS "missing" constants that carry no nodata tag
    return np.ascontiguousarray(out)


def read_bbox(url: str | Path, bbox: dict, band: int = 1, pad_px: int = 0, crs: str | None = None,
              env: dict | None = None, progress: Progress | None = None,
              cancel: threading.Event | None = None) -> Raster:
    """Read the bbox window of a remote (or local) product as a float32 Raster (NaN = nodata).

    `crs` replaces the CRS GDAL reports (the affine transform still comes from the file). Use it when a file's
    own Mars CRS is spelled in a way pyproj does not understand. `env` adds GDAL options for this read.
    With `progress` or `cancel`, the window is read in strips of STRIP_ROWS rows, reporting and checking between them.
    """
    with rasterio.Env(**{**GDAL_ENV, **(env or {})}), rasterio.open(_source(url)) as ds:
        # With an override, never ask GDAL/pyproj to parse the file's own (possibly exotic) Mars CRS.
        grid = (GeoGrid(ds.transform, CRS.from_user_input(crs), ds.height, ds.width) if crs
                else GeoGrid.from_dataset(ds))
        win = bbox_window(grid, bbox, pad_px)
        sub = grid.window(win.row_off, win.col_off, int(win.height), int(win.width))
        if progress is None and cancel is None:
            return Raster(_to_float(ds.read(band, window=win, masked=True)), sub)
        h, w = int(win.height), int(win.width)
        out = np.empty((h, w), dtype="float32")
        for r in range(0, h, STRIP_ROWS):
            _check(cancel)
            n = min(STRIP_ROWS, h - r)
            out[r:r + n] = _to_float(ds.read(band, window=Window(win.col_off, win.row_off + r, w, n), masked=True))
            if progress:
                progress((r + n) / h)
        return Raster(np.ascontiguousarray(out), sub)


def open_grid(url: str | Path) -> GeoGrid:
    """The full grid (CRS, transform, size) of a remote or local raster: a header read only."""
    with rasterio.Env(**GDAL_ENV), rasterio.open(_source(url)) as ds:
        return GeoGrid.from_dataset(ds)


def read_point_window(url: str | Path, lat: float, lon: float, half_px: int = 32) -> tuple[np.ndarray, GeoGrid]:
    """A small window (2*half_px square) of a remote raster centred on a point, e.g. to check there is data there."""
    with rasterio.Env(**GDAL_ENV), rasterio.open(_source(url)) as ds:
        grid = GeoGrid.from_dataset(ds)
        r, c = grid.latlon_to_rc(lat, lon)
        if not (0 <= r < grid.height and 0 <= c < grid.width):
            return np.full((1, 1), np.nan, dtype="float32"), grid
        r0, c0 = max(r - half_px, 0), max(c - half_px, 0)
        win = Window(c0, r0, min(2 * half_px, grid.width - c0), min(2 * half_px, grid.height - r0))
        return _to_float(ds.read(1, window=win, masked=True)), grid.window(r0, c0, int(win.height), int(win.width))


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


def download(url: str, dest: Path, timeout: float = 900, progress: Progress | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Download a whole small file (e.g. a 1 m ortho JP2, 20-45 MB). Skips if already present."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(1 << 20):
                _check(cancel)
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(done / total, 1.0))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return dest
