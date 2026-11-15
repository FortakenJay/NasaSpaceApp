"""Web-map photo tiles (geographic tiling) stitched into a georeferenced Raster, for lining terrain up with the map.

Both tile services MarsWalk draws use the same geographic scheme: zoom 0 is two tiles of 180 degrees, origin (-180, 90),
row y counted down from the north pole. Tiles are 256 px on Mars Trek and 512 px on the global astro.arcgis services,
so a pixel is 180 / tile_px / 2^z degrees. On the Mars 2000 sphere that is exactly an equirectangular grid
(+proj=eqc +lat_ts=0 +lon_0=0 +R=3396190) in metres, which is what the returned Raster uses.

Tiles are cached on disk (data_root()/cache/tiles/) and fetched at most 4 at a time; a missing tile (404, or a
transparent area) becomes NaN.
"""
from __future__ import annotations

import hashlib
import io
import math
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from affine import Affine
from pyproj import CRS

from marswalk.geo import GeoGrid, Raster

R_MARS = 3396190.0
TILE_CRS = "+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m +no_defs"
MAX_PARALLEL = 4
USER_AGENT = "marswalk/1.2 (research prototype; terrain alignment)"


def deg_per_px(z: int, tile_px: int) -> float:
    return 180.0 / tile_px / (2 ** z)


def zoom_for(m_per_px: float, tile_px: int) -> int:
    """The zoom whose pixels are closest to m_per_px."""
    base = 180.0 / tile_px * math.pi / 180.0 * R_MARS
    return max(0, int(round(math.log2(base / m_per_px))))


def _cache_dir(url_template: str) -> Path:
    from marswalk.sources.fetch import data_root
    return data_root() / "cache" / "tiles" / hashlib.sha1(url_template.encode()).hexdigest()[:12]


def _decodes(data: bytes) -> bool:
    from PIL import Image
    try:
        Image.open(io.BytesIO(data)).load()
        return True
    except Exception:  # noqa: BLE001 - truncated or corrupt image
        return False


def _fetch(url_template: str, z: int, y: int, x: int, cancel: threading.Event | None, tries: int = 3) -> bytes | None:
    """One tile's bytes (cached), or None if the service has no tile there. A tile that arrives corrupt (seen on the
    arcgis service 2026-11-15: a valid PNG header with a truncated stream) is fetched again, then treated as missing."""
    if cancel is not None and cancel.is_set():
        from marswalk.sources.raster import Cancelled
        raise Cancelled("cancelled")
    p = _cache_dir(url_template) / str(z) / str(y) / f"{x}.png"
    if p.exists():
        data = p.read_bytes()
        if not data or _decodes(data):
            return data or None          # an empty file records a known-missing tile
    url = url_template.format(z=z, y=y, x=x)
    data = b""
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404):
                raise
            data = b""
            break
        if _decodes(data):
            break
        data = b""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data or None


def _decode(data: bytes | None, tile_px: int) -> np.ndarray:
    from PIL import Image
    if not data:
        return np.full((tile_px, tile_px), np.nan, dtype=np.float32)
    im = Image.open(io.BytesIO(data))
    alpha = None
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        alpha = np.asarray(rgba)[..., 3]
        im = rgba
    a = np.asarray(im.convert("L"), dtype=np.float32)
    if a.shape != (tile_px, tile_px):
        a = np.asarray(Image.fromarray(a).resize((tile_px, tile_px)), dtype=np.float32)
    if alpha is not None:
        if alpha.shape != a.shape:
            alpha = np.asarray(Image.fromarray(alpha).resize((tile_px, tile_px)))
        a[alpha < 128] = np.nan
    return a


def mosaic(url_template: str, bbox: dict, z: int, tile_px: int = 512,
           cancel: threading.Event | None = None) -> Raster:
    """The tiles covering bbox at zoom z, stitched and cropped to bbox (grey, 0-255, NaN where missing)."""
    d = deg_per_px(z, tile_px)
    tile_deg = d * tile_px
    x0 = int(math.floor((bbox["lon_min"] + 180.0) / tile_deg))
    x1 = int(math.floor((bbox["lon_max"] + 180.0) / tile_deg))
    y0 = int(math.floor((90.0 - bbox["lat_max"]) / tile_deg))
    y1 = int(math.floor((90.0 - bbox["lat_min"]) / tile_deg))
    if (x1 - x0 + 1) * (y1 - y0 + 1) > 64:
        raise ValueError("too many tiles for one alignment window")
    jobs = [(y, x) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    with ThreadPoolExecutor(MAX_PARALLEL) as ex:
        blobs = list(ex.map(lambda yx: _fetch(url_template, z, yx[0], yx[1], cancel), jobs))
    big = np.full(((y1 - y0 + 1) * tile_px, (x1 - x0 + 1) * tile_px), np.nan, dtype=np.float32)
    for (y, x), blob in zip(jobs, blobs):
        big[(y - y0) * tile_px:(y - y0 + 1) * tile_px, (x - x0) * tile_px:(x - x0 + 1) * tile_px] = _decode(blob, tile_px)
    # crop to the bbox
    lon_left = -180.0 + x0 * tile_deg
    lat_top = 90.0 - y0 * tile_deg
    c0 = max(int(math.floor((bbox["lon_min"] - lon_left) / d)), 0)
    c1 = min(int(math.ceil((bbox["lon_max"] - lon_left) / d)), big.shape[1])
    r0 = max(int(math.floor((lat_top - bbox["lat_max"]) / d)), 0)
    r1 = min(int(math.ceil((lat_top - bbox["lat_min"]) / d)), big.shape[0])
    a = np.ascontiguousarray(big[r0:r1, c0:c1])
    k = math.pi / 180.0 * R_MARS
    px_m = d * k
    t = Affine(px_m, 0.0, (lon_left + c0 * d) * k, 0.0, -px_m, (lat_top - r0 * d) * k)
    return Raster(a, GeoGrid(t, CRS.from_user_input(TILE_CRS), a.shape[0], a.shape[1]), name="tiles")
