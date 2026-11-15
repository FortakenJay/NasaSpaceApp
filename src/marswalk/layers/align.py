"""Line a HiRISE terrain strip up with the map photo it is drawn on.

A DTM's own coordinates can sit tens of metres off the photo mosaic a map shows (Gale: 45 m). Every overlay, route
and stop value would then be read from the wrong ground. The DTM's orthophoto shares the DTM's grid exactly, so
matching that photo against the map's photo tiles measures the terrain's offset.

Method:
- Both images on the tile grid; the orthophoto averaged down to it (rasterio, Resampling.average).
- A band-pass (difference of Gaussians, 1 and 8 px) so brightness and shading differences between the two photos
  do not dominate, then phase correlation (scikit-image, 1/10 px), then the normalized cross-correlation (NCC) of the
  band-passed images at that shift as the quality number.
- Coarse to fine: a 3 km window at ~5 m/px finds the offset (searches up to about +-700 m), then 5 patches of 512 m at
  ~1.3 m/px around the Base refine it. Their spread says how sure the result is.
- Quality: good = NCC >= 0.5 and >= 3 of 5 patches within 3 m of their median; fair = NCC >= 0.35 and spread <= 6 m;
  otherwise weak, and the caller keeps the file's own coordinates with a warning.

Measured at Gale 2026-11-15 (H1): DTM vs Trek curiosity_hirise_mosaic +34.0 m N / -33.5 m E, good (team: +33.5 / -30.5);
DTM vs the global astro.arcgis HiRISE mosaic -66 m N / -10 m E, fair: that mosaic sits about 102 m S / 25 m E of the
Trek one there, so each Base is aligned to the mosaic it actually displays.

The offset returned is in the DTM's own map units (what coverage.shifted moves), east/north metres.
"""
from __future__ import annotations

import math
import threading
from typing import Callable

import numpy as np
from scipy import ndimage

from marswalk.geo import Raster
from marswalk.sources import tiles

COARSE_M, FINE_M = 5.0, 1.3
COARSE_HALF_M, FINE_HALF_M = 1500.0, 256.0
PATCH_OFFSETS_M = [(0, 0), (300, 0), (-300, 0), (0, 300), (0, -300)]   # (north, east) of the Base
# Calibrated at Gale (2026-11-15): the DTM's own photo against the Trek mosaic built from the same images matched at
# NCC 0.92 with 5 patches within 2.2 m ("good"); against the global HiRISE mosaic (other images, other lighting) at
# NCC 0.45, patches spread 8 m ("fair").
GOOD_NCC, FAIR_NCC, AGREE_M, FAIR_SPREAD_M = 0.6, 0.3, 3.0, 10.0


def _bbox(lat: float, lon: float, half_m: float, north_m: float = 0.0, east_m: float = 0.0) -> dict:
    k = math.pi / 180.0 * tiles.R_MARS
    lat_c = lat + north_m / k
    lon_c = lon + east_m / (k * math.cos(math.radians(lat)))
    dlat, dlon = half_m / k, half_m / (k * math.cos(math.radians(lat)))
    return {"lat_min": lat_c - dlat, "lat_max": lat_c + dlat, "lon_min": lon_c - dlon, "lon_max": lon_c + dlon}


def onto(src: Raster, target: Raster) -> np.ndarray:
    """src averaged onto target's grid (NaN outside)."""
    from rasterio.warp import Resampling, reproject
    dst = np.full(target.shape, np.nan, dtype=np.float32)
    reproject(source=src.data.astype(np.float32), destination=dst, src_transform=src.grid.transform,
              src_crs=src.grid.crs.to_wkt(), src_nodata=np.nan, dst_transform=target.grid.transform,
              dst_crs=target.grid.crs.to_wkt(), dst_nodata=np.nan, resampling=Resampling.average)
    return dst


def _bandpass(a: np.ndarray) -> np.ndarray:
    a = np.where(np.isfinite(a), a, np.nanmean(a) if np.isfinite(a).any() else 0.0)
    return ndimage.gaussian_filter(a, 1.0) - ndimage.gaussian_filter(a, 8.0)


def measure(src_on: np.ndarray, tgt: np.ndarray, min_px: int = 96) -> dict | None:
    """Shift (rows, cols) that moves src_on onto tgt, with its NCC. None if they overlap too little."""
    from skimage.registration import phase_cross_correlation
    valid = np.isfinite(src_on) & np.isfinite(tgt)
    rows = np.nonzero(valid.mean(axis=1) > 0.9)[0]
    cols = np.nonzero(valid.mean(axis=0) > 0.9)[0]
    if rows.size < min_px or cols.size < min_px:
        return None
    rs, cs = slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1)
    a, b = _bandpass(tgt[rs, cs]), _bandpass(src_on[rs, cs])
    # Plain (not phase-normalized) cross-correlation: on the astro.arcgis tiles the phase-normalized peak locks onto
    # fixed-pattern tile artifacts at zero shift (checked at Gale 2026-11-15: phase gave (0, 0), plain and a brute-force
    # NCC search both gave the same 102 m offset).
    shift, _err, _ = phase_cross_correlation(a, b, upsample_factor=10, normalization=None)
    dy, dx = float(shift[0]), float(shift[1])
    moved = ndimage.shift(b, (dy, dx), order=1, mode="nearest")
    m = int(math.ceil(max(abs(dy), abs(dx)))) + 4
    if a.shape[0] <= 2 * m + 16 or a.shape[1] <= 2 * m + 16:
        return None
    x, y = a[m:-m, m:-m].ravel(), moved[m:-m, m:-m].ravel()
    ncc = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else 0.0
    return {"dy": dy, "dx": dx, "ncc": ncc}


def _to_dtm_units(grid, lat: float, lon: float, north_tile_m: float, east_tile_m: float) -> tuple[float, float]:
    """An offset measured in tile metres (eqc lat_ts=0, lon_0=0) as east/north in the DTM grid's map units."""
    k = math.pi / 180.0 * tiles.R_MARS
    lat2, lon2 = lat + north_tile_m / k, lon + east_tile_m / k
    x1, y1 = grid.latlon_to_xy(lat, lon)
    x2, y2 = grid.latlon_to_xy(lat2, lon2)
    return x2 - x1, y2 - y1


def run(ortho: Raster, lat: float, lon: float, url_template: str, tile_px: int,
        cancel: threading.Event | None = None, progress: Callable[[float], None] | None = None,
        coarse_m: float = COARSE_M, fine_m: float = FINE_M, patches: bool = True) -> dict:
    """Measure the ortho's offset from one tile service around (lat, lon). Returns tile-frame metres + quality."""
    from marswalk.layers import coverage
    z = tiles.zoom_for(coarse_m, tile_px)
    tgt = tiles.mosaic(url_template, _bbox(lat, lon, COARSE_HALF_M), z, tile_px, cancel)
    res = measure(onto(ortho, tgt), tgt.data)
    if progress:
        progress(0.3)
    if res is None:
        return {"quality": "weak", "reason": "the photo tiles barely cover the terrain here"}
    px = tgt.grid.pixel_m
    north, east, ncc0 = -res["dy"] * px, res["dx"] * px, res["ncc"]
    if not patches:
        q = "coarse" if ncc0 >= FAIR_NCC else "weak"
        return {"quality": q, "north_m": north, "east_m": east, "corr": round(ncc0, 3), "spread_m": None,
                "n_patches": 0, "pixel_m": round(px, 2)}
    # refine on 5 patches with the coarse shift applied
    zf = tiles.zoom_for(fine_m, tile_px)
    found = []
    for i, (pn, pe) in enumerate(PATCH_OFFSETS_M):
        ft = tiles.mosaic(url_template, _bbox(lat, lon, FINE_HALF_M, pn, pe), zf, tile_px, cancel)
        de, dn = _to_dtm_units(ortho.grid, lat, lon, north, east)
        r = measure(onto(coverage.shifted(ortho, {"east": de, "north": dn}), ft), ft.data, min_px=128)
        if r is not None:
            fpx = ft.grid.pixel_m
            found.append((north - r["dy"] * fpx, east + r["dx"] * fpx, r["ncc"]))
        if progress:
            progress(0.3 + 0.7 * (i + 1) / len(PATCH_OFFSETS_M))
    if not found:
        q = "coarse" if ncc0 >= FAIR_NCC else "weak"
        return {"quality": q, "north_m": north, "east_m": east, "corr": round(ncc0, 3), "spread_m": None, "n_patches": 0}
    ns, es, cs = (np.array(v) for v in zip(*found))
    mn, me = float(np.median(ns)), float(np.median(es))
    dist = np.hypot(ns - mn, es - me)
    agree = int((dist <= AGREE_M).sum())
    spread = float(np.median(dist)) * 1.4826 if len(found) > 1 else 0.0
    ncc = float(np.median(cs))
    if ncc >= GOOD_NCC and agree >= 3:
        q = "good"
    elif ncc >= FAIR_NCC and spread <= FAIR_SPREAD_M and len(found) >= 3:
        q = "fair"
    else:
        q = "weak"
    return {"quality": q, "north_m": mn, "east_m": me, "corr": round(ncc, 3), "spread_m": round(spread, 2),
            "n_patches": len(found), "agree": agree, "pixel_m": round(fine_m, 2)}


def auto(site, raw, cancel: threading.Event | None = None, progress: Callable[[float], None] | None = None,
         url_template: str | None = None, tile_px: int | None = None) -> dict:
    """The terrain's offset from the map photo for a Base: global HiRISE tiles, then CTX if that is weak.
    Returns {source, quality, east_m, north_m (DTM map units), corr, spread_m, n_patches, target}."""
    from marswalk.sources import catalog
    from marswalk.sources.raster import read_geotiff
    ortho = read_geotiff(raw / "ortho_1m.tif")
    lat, lon = site.start.lat, site.start.lon
    if url_template is None:
        url_template, tile_px, source = catalog.HIRISE_GLOBAL_TILES, 512, "hirise_global"
    else:
        source = "custom"
    tile_px = tile_px or 512
    res = run(ortho, lat, lon, url_template, tile_px, cancel, progress)
    # No CTX fallback: the global CTX mosaic is uncontrolled (about 510 m off at Gale, measured 2026-11-15), so lining
    # the terrain up with it would put it far off the HiRISE photo the map shows. Weak -> the file's own coordinates.
    if progress:
        progress(1.0)
    if "north_m" not in res:
        return {"source": "file", "quality": "weak", "east_m": 0.0, "north_m": 0.0, "corr": None, "spread_m": None,
                "n_patches": 0, "target": url_template, "reason": res.get("reason", "")}
    east, north = _to_dtm_units(ortho.grid, lat, lon, res["north_m"], res["east_m"])
    return {"source": source, "quality": res["quality"], "east_m": round(east, 2), "north_m": round(north, 2),
            "corr": res.get("corr"), "spread_m": res.get("spread_m"), "n_patches": res.get("n_patches", 0),
            "target": url_template}
