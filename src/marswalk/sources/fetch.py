"""`marswalk fetch`: cache the site's data window as local GeoTIFFs in data/raw/<site>/ (git-ignored).

All windows come from site.bbox, so a new site needs no code changes:
  1. DTM:  raster.read_bbox(dtm.url, bbox, pad_px=100) -> raw/dtm.tif            (required)
  2. Thermal inertia: raster.read_bbox(thermal_inertia.url, bbox, pad_px=2) -> raw/ti.tif (100 m, own grid)
  3. Ortho 1 m: download the JP2, crop the DTM window, write raw/ortho_1m.tif on the DTM grid
     (products with same_grid_as = "dtm": their GeoJP2 header is 1.5 px off, so the DTM transform is used).
  4. raw/manifest.json: product ids, urls, shapes, sha256 of each output, fetch time.
  2b. Merged DEM (optional): the USGS 1 m merged Gale DEM over the same window -> raw/dem_merged.tif. It is the base
     surface when present; the HiRISE DTM then marks where routes may be planned (see layers.stack).
Only the DTM is required to plan. TI and ortho failures are recorded in the manifest and reported, not fatal:
the planner then runs without the sand flag, and the map still has the Mars Trek basemap.
Re-running with everything present is a no-op. If site.bbox changed since the last fetch, everything is re-read.

Set MARSWALK_DATA to move the data directory (tests use this).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

import numpy as np

from marswalk.config import PROJECT_ROOT, SiteConfig
from marswalk.geo import ground_distance_m


DTM_PAD_PX = 100   # margin around the bbox so slope/roughness filters have neighbours at the edge


def data_root() -> Path:
    """Where rasters, the HiRISE catalog, and added Bases are stored.

    MARSWALK_DATA overrides this (tests point it at a temp folder). On Vercel the
    deployment directory is read-only, so the writable disk is /tmp. The same
    fallback applies if the checkout itself cannot be written, even when the
    VERCEL variable is missing.
    """
    override = os.environ.get("MARSWALK_DATA")
    if override:
        return Path(override)
    if os.environ.get("VERCEL") or not os.access(PROJECT_ROOT, os.W_OK):
        return Path("/tmp/marswalk")
    return PROJECT_ROOT / "data"


def raw_dir(site: SiteConfig) -> Path:
    return data_root() / "raw" / site.id


def cache_dir(site: SiteConfig) -> Path:
    return data_root() / "cache" / site.id


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


MERGED_FILE = "dem_merged.tif"


def read_merged_dem(site: SiteConfig, url: str | None = None, log: Callable[[str], None] = print):
    """Read the site's window of the merged DEM as a Raster. Raises if the window is not where it should be.

    The file stores one row per strip, so every row of the window is read in full (the file is 33 km wide);
    that is the price of this product and it is paid once.
    """
    from marswalk.sources import raster as rs

    cfg = site.merged_dem
    if cfg is None:
        raise ValueError("this site has no enabled [products.merged_dem]")
    src = url or cfg["url"]
    log(f"merged DEM: reading window from {src} (about 0.5 GB for the Gale window, one time) ...")
    dem = rs.read_bbox(src, site.bbox, pad_px=DTM_PAD_PX, crs=cfg.get("crs"),
                       env={"CPL_VSIL_CURL_CHUNK_SIZE": str(16 * 1024 * 1024)})   # rows are contiguous: bigger chunks
    # Sanity: the window centre must be where the bbox centre is (guards CRS or half-pixel mistakes).
    lat, lon = dem.grid.rc_to_latlon(dem.shape[0] / 2, dem.shape[1] / 2)
    want_lat = (site.bbox["lat_min"] + site.bbox["lat_max"]) / 2
    want_lon = (site.bbox["lon_min"] + site.bbox["lon_max"]) / 2
    off_m = ground_distance_m(lat, lon, want_lat, want_lon, site.body["radius_m"])
    if off_m > 250.0:
        raise ValueError(f"merged DEM window is {off_m:.0f} m from the requested centre: wrong CRS or transform")
    if not np.isfinite(dem.data).any():
        raise ValueError("merged DEM window holds no elevation values")
    return dem


def fetch_site(site: SiteConfig, include_optional: bool = False, log: Callable[[str], None] = print,
               progress: Callable[[str, float], None] | None = None, cancel=None,
               essentials_only: bool = False) -> Path:
    """Fetch the products for `site`. Returns the raw data directory. Raises only if the DTM fails (or on cancel).

    `progress(step, fraction)` reports "dtm", "ti" and "ortho" progress; `cancel` (a threading.Event) stops the
    fetch between strips and download chunks with raster.Cancelled.
    """
    import rasterio

    from marswalk.geo import GeoGrid, Raster
    from marswalk.sources import raster as rs

    def step(name: str):
        return (lambda f: progress(name, f)) if progress else None

    out = raw_dir(site)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"site": site.id, "products": {}}
    prods = manifest["products"]
    if manifest.get("bbox") != dict(site.bbox):
        # The analysis window changed (or this cache predates the check): every cached window is stale.
        if any((out / f).exists() for f in ("dtm.tif", "ti.tif")):
            log("analysis window changed: re-reading every product")
        stale, manifest["bbox"], prods = True, dict(site.bbox), {}
        manifest["products"] = prods
    else:
        stale = False

    def record(key: str, product: dict, path: Path, shape) -> None:
        prods[key] = {"id": product.get("id"), "url": product.get("url"), "file": path.name,
                      "shape": list(shape), "sha256": _sha256(path),
                      "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    # 1. DTM (required)
    dtm_tif = out / "dtm.tif"
    if dtm_tif.exists() and not stale:
        log(f"dtm: cached ({dtm_tif})")
    else:
        log(f"dtm: reading window from {site.dtm['url']} ...")
        dtm = rs.read_bbox(site.dtm["url"], site.bbox, pad_px=DTM_PAD_PX, progress=step("dtm"), cancel=cancel)
        rs.write_geotiff(dtm, dtm_tif)
        record("dtm", site.dtm, dtm_tif, dtm.shape)
        log(f"dtm: {dtm.shape[0]} x {dtm.shape[1]} px -> {dtm_tif}")
    # The DTM window on the file's own grid (what the orthos are cropped to, before any squaring below).
    full = GeoGrid.from_product(site.dtm)
    win = rs.bbox_window(full, site.bbox, pad_px=DTM_PAD_PX)
    src_grid = full.window(int(win.row_off), int(win.col_off), int(win.height), int(win.width))
    if essentials_only:
        # Planning only needs the elevation window. Skip the orthos and thermal inertia so a hosted
        # function can finish inside its time limit.
        _square_pixels(site, out, prods, manifest, src_grid, log)
        manifest_path.write_text(json.dumps(manifest, indent=1))
        return out

    # 2b. Merged DEM (optional: without it the app plans on the HiRISE strip alone)
    merged_tif = out / MERGED_FILE
    if site.merged_dem is None:
        prods.pop("merged_dem", None)
        merged_tif.unlink(missing_ok=True)
    elif stale or not merged_tif.exists():
        try:
            merged = read_merged_dem(site, log=log)
            rs.write_geotiff(merged, merged_tif)
            record("merged_dem", site.merged_dem, merged_tif, merged.shape)
            log(f"merged DEM: {merged.shape[0]} x {merged.shape[1]} px -> {merged_tif}")
        except Exception as e:  # noqa: BLE001 - recorded, not fatal
            merged_tif.unlink(missing_ok=True)
            prods["merged_dem"] = {"error": f"{type(e).__name__}: {e}"}
            log(f"merged DEM: FAILED ({e}); the app keeps planning on the HiRISE strip alone")
    else:
        log(f"merged DEM: cached ({merged_tif})")

    # 2. Thermal inertia (optional for planning)
    ti_cfg = site.products.get("thermal_inertia")
    ti_tif = out / "ti.tif"
    if ti_cfg and (stale or not ti_tif.exists()):
        try:
            log("ti: reading window ...")
            ti = rs.read_bbox(ti_cfg["url"], site.bbox, pad_px=2, progress=step("ti"), cancel=cancel)
            rs.write_geotiff(ti, ti_tif)
            record("thermal_inertia", ti_cfg, ti_tif, ti.shape)
            log(f"ti: {ti.shape[0]} x {ti.shape[1]} px -> {ti_tif}")
        except rs.Cancelled:
            raise
        except Exception as e:  # noqa: BLE001 - recorded, not fatal
            prods["thermal_inertia"] = {"error": f"{type(e).__name__}: {e}"}
            log(f"ti: FAILED ({e}); planning continues without the sand flag")

    # 3. Ortho image(s) on the DTM grid
    wanted = ["ortho_1m"] + (["ortho_25cm", "ortho_color_1m"] if include_optional else [])
    for key in wanted:
        cfg = site.products.get(key)
        tif = out / f"{key}.tif"
        if not cfg or (tif.exists() and not stale):
            continue
        if cfg.get("same_grid_as") != "dtm":
            log(f"{key}: skipped (not on the DTM grid; add a reprojection step for this product)")
            continue
        try:
            prog = step("ortho") if key == "ortho_1m" else None
            jp2 = rs.download(cfg["url"], out / f"{cfg['id']}.JP2",
                              progress=(lambda f: prog(0.9 * f)) if prog else None, cancel=cancel)
            with rasterio.open(jp2) as ds:
                a = ds.read(1, window=win).astype("float32")
            rs.write_geotiff(Raster(a, src_grid, name=key), tif)    # on the file's grid; squared below if needed
            record(key, cfg, tif, a.shape)
            log(f"{key}: {a.shape[0]} x {a.shape[1]} px -> {tif}")
            if prog:
                prog(1.0)
        except rs.Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            prods[key] = {"error": f"{type(e).__name__}: {e}"}
            log(f"{key}: FAILED ({e}); the map still has the Mars Trek basemap")

    # 4. Square pixels on the ground (a Base far from its DTM's standard parallel)
    _square_pixels(site, out, prods, manifest, src_grid, log)
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return out


def _square_pixels(site: SiteConfig, out: Path, prods: dict, manifest: dict, src_grid, log) -> None:
    """Resample the DTM and the orthos (all on `src_grid`) onto one grid whose pixels are square on the ground.

    The layers and the route search treat a pixel as a square of pixel_m metres. An equirectangular DTM is square on
    the ground only at its standard parallel: Gale's DTM (lat_ts 0) at -4.8 deg is 0.35 % off and kept as is; the
    Jezero DTM (lat_ts 15) at 18.4 deg is 1.8 % off, and a lat_ts-0 DTM at 40 deg would be 23 % off. Done once per file
    (marked "square" in the manifest), always onto the same target grid.
    """
    from marswalk.sources import raster as rs
    lat = (site.bbox["lat_min"] + site.bbox["lat_max"]) / 2
    dst = rs.square_grid(src_grid, lat)
    if dst is None:
        manifest.pop("grid", None)
        return
    t = dst.transform
    manifest["grid"] = {"note": "resampled so pixels are square on the ground at the site's latitude",
                        "aspect_before": round(rs.ground_aspect(src_grid, lat), 5), "crs": dst.crs.to_wkt(),
                        "transform": [t.a, t.b, t.c, t.d, t.e, t.f], "width": dst.width, "height": dst.height}
    for key in ("dtm", "ortho_1m", "ortho_25cm", "ortho_color_1m"):
        rec, tif = prods.get(key), out / f"{key}.tif"
        if not rec or "error" in rec or rec.get("square") or not tif.exists():
            continue
        rs.write_geotiff(rs.warp(rs.read_geotiff(tif), dst), tif)
        rec.update(square=True, shape=[dst.height, dst.width], sha256=_sha256(tif))
        log(f"{key}: resampled to square {abs(t.a):.2f} m pixels (was {rs.ground_aspect(src_grid, lat):.4f} : 1)")
