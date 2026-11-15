"""Data for the 3-D walk simulator: the terrain as a height grid in local metres, and its photo as a texture.

Local frame: origin at the rover, x east, z south (so north is -z, as in three.js), y up, metres. The analysis grid is
equirectangular, so grid columns are linear in longitude and rows linear in latitude; with
    x = (lon - lon0) * kx,   z = -(lat - lat0) * kz,   kx = kz * cos(lat0),   kz = 2 pi R / 360
the grid maps to (x0 + c dx, z0 + r dz) exactly, and the browser converts any lat/lon with the same four numbers.
"""
from __future__ import annotations

import io
import math
import warnings

import numpy as np
from affine import Affine

from marswalk.cost.physics import walk_speed_cap
from marswalk.geo import GeoGrid, Raster
from marswalk.layers.radio import SHADOW
from marswalk.spaceweather import radiation

MAX_TEXTURE_PX = 2048
FORMAT = 2   # binary layouts of terrain.bin / fine.bin; part of their URLs, so a browser never decodes a stale copy


def area(stack, points: list[tuple[float, float]], margin_m: float = 400.0) -> tuple[int, int, int, int]:
    """Grid window (r0, r1, c0, c1) around the points plus a margin, clipped to the terrain."""
    rc = [stack.grid.latlon_to_rc(lat, lon) for lat, lon in points]
    pad = math.ceil(margin_m / stack.grid.pixel_m)
    r0 = max(min(r for r, _ in rc) - pad, 0)
    r1 = min(max(r for r, _ in rc) + pad + 1, stack.shape[0])
    c0 = max(min(c for _, c in rc) - pad, 0)
    c1 = min(max(c for _, c in rc) + pad + 1, stack.shape[1])
    return r0, r1, c0, c1


def _blocks(a: np.ndarray, k: int, how: str) -> np.ndarray:
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    b = a[:h, :w].reshape(h // k, k, w // k, k)
    if how == "any":
        return b.any(axis=(1, 3))
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # all-NaN blocks become NaN, filled below
        return np.nanmean(b, axis=(1, 3))


def _fill_nearest(z: np.ndarray) -> np.ndarray:
    ok = np.isfinite(z)
    if ok.all() or not ok.any():
        return np.where(ok, z, 0.0)
    from scipy.ndimage import distance_transform_edt
    _, (ri, ci) = distance_transform_edt(~ok, return_indices=True)
    return z[ri, ci]


def frame(site, start_lat: float, start_lon: float) -> dict:
    kz = 2 * math.pi * float(site.body["radius_m"]) / 360.0
    return {"lat0": start_lat, "lon0": start_lon, "kz": kz, "kx": kz * math.cos(math.radians(start_lat))}


def _coarse(stack, start_lat: float, start_lon: float, points, step: int, margin_m: float):
    r0, r1, c0, c1 = area(stack, [(start_lat, start_lon), *points], margin_m)
    k = max(int(step), 1)
    z = _blocks(stack.elevation_m[r0:r1, c0:c1], k, "mean")
    nogo = _blocks(stack.nogo[r0:r1, c0:c1], k, "any") | ~np.isfinite(z)
    return (r0, c0, k), _fill_nearest(z).astype(np.float64), nogo


def terrain_bytes(stack, start_lat: float, start_lon: float, points, step: int = 3, margin_m: float = 400.0) -> bytes:
    """The 3 m mesh for the simulator's eyes: heights uint16 LE (cm above the lowest block) | off-limits bits
    (np.packbits, row-major, MSB first). Shape, frame and h0 are in terrain_package()."""
    _, z, nogo = _coarse(stack, start_lat, start_lon, points, step, margin_m)
    cm = np.round((z - float(z.min())) * 100.0).clip(0, 65535).astype("<u2")
    return cm.tobytes() + np.packbits(nogo.astype(bool), axis=None).tobytes()


def terrain_package(site, eva, stack, start_lat: float, start_lon: float, points: list[tuple[float, float]],
                    step: int = 3, margin_m: float = 400.0, stamp: str = "") -> dict:
    """Shape and local frame of the 3 m mesh (heights in terrain_bytes), the 1 m grid's frame, and the physics
    constants, as JSON. The binary URLs carry FORMAT and `stamp` (the raw-data stamp), so they change when either does."""
    v = f"{FORMAT}-{stamp}" if stamp else str(FORMAT)
    (r0, c0, k), z, _ = _coarse(stack, start_lat, start_lon, points, step, margin_m)
    rows, cols = z.shape
    fr = frame(site, start_lat, start_lon)
    # centres of the first and second block along each axis -> local x, z (exactly linear on this grid)
    la, lo = stack.grid.rc_to_latlon_many([r0 + (k - 1) / 2, r0 + (k - 1) / 2 + k], [c0 + (k - 1) / 2, c0 + (k - 1) / 2 + k])
    x0, x1 = (lo[0] - fr["lon0"]) * fr["kx"], (lo[1] - fr["lon0"]) * fr["kx"]
    z0, z1 = -(la[0] - fr["lat0"]) * fr["kz"], -(la[1] - fr["lat0"]) * fr["kz"]
    sr, sc = stack.grid.latlon_to_rc(start_lat, start_lon)
    base = float(stack.elevation_m[sr, sc]) if np.isfinite(stack.elevation_m[sr, sc]) else float(np.mean(z))
    lo_h = float(z.min())
    m = eva.cost.get("metabolic", {})
    cap = walk_speed_cap({"gravity_mps2": site.body.get("gravity_mps2", 3.71), **m})
    return {
        **fr,
        "rows": rows, "cols": cols, "x0": x0, "dx": x1 - x0, "z0": z0, "dz": z1 - z0,
        "h0": lo_h - base,                       # height of cm = 0, relative to the rover
        "heights": {"url": f"/api/sim/terrain.bin?step={k}&v={v}",
                    "layout": "heights uint16 LE (cm above h0) | off-limits bits (np.packbits, row-major, MSB first)"},
        "terrain_source": stack.terrain_source,
        "fine": {**fine_meta(site, stack, start_lat, start_lon, points, margin_m),
                 "h0": _fine_zero(stack, start_lat, start_lon, points, margin_m) - base,   # cm = 0, relative to the rover
                 "url": f"/api/sim/fine.bin?v={v}"},
        "physics": {
            "gravity_mps2": float(m.get("gravity_mps2", site.body.get("gravity_mps2", 3.71))),
            "body_mass_kg": float(m.get("body_mass_kg", 80.0)), "suit_mass_kg": float(m.get("suit_mass_kg", 60.0)),
            "max_grade_deg": float(m.get("max_grade_deg", 20.0)),
            "walk_speed_cap_mps": cap if math.isfinite(cap) else None,     # gait limit, None = off
            "sep_warning_lead_min": float(eva.eva.get("sep_warning_lead_min", 30.0)),
            # the planner's terrain multipliers on walking time (cost/physics.py edge_time_energy)
            "roughness_penalty_per_m": float(m.get("roughness_penalty_per_m", 2.0)),
            "sand_penalty": float(m.get("sand_penalty", 1.2)),
            "start_lmst_h": float(eva.eva.get("start_lmst_h", 9.0)),
            "work_power_w": float(eva.suit.get("work_power_w", 250.0)),
            "o2_capacity_h": float(eva.suit.get("o2_capacity_h", eva.eva["max_duration_h"])),
            "walkback_reserve_frac": float(eva.eva["walkback_reserve_frac"]),
            "metabolic_budget_kj": float(eva.suit.get("metabolic_budget_kj", 12000.0)),
            "time_margin_factor": float(eva.eva.get("time_margin_factor", 1.0)),
            "rad_mgy_per_day": radiation.rates(site.spaceweather)[0],
            "rad_msv_per_day": radiation.rates(site.spaceweather)[1],
        },
    }


def _fine_window(stack, start_lat: float, start_lon: float, points, margin_m: float) -> tuple[int, int, int, int]:
    return area(stack, [(start_lat, start_lon), *points], margin_m)


def fine_meta(site, stack, start_lat: float, start_lon: float, points, margin_m: float = 400.0) -> dict:
    """Shape and local frame of the 1 m walking grid (`fine_bytes`), at the planner's own resolution."""
    r0, r1, c0, c1 = _fine_window(stack, start_lat, start_lon, points, margin_m)
    fr = frame(site, start_lat, start_lon)
    la, lo = stack.grid.rc_to_latlon_many([r0, r0 + 1], [c0, c0 + 1])
    x0, x1 = (lo[0] - fr["lon0"]) * fr["kx"], (lo[1] - fr["lon0"]) * fr["kx"]
    z0, z1 = -(la[0] - fr["lat0"]) * fr["kz"], -(la[1] - fr["lat0"]) * fr["kz"]
    return {"rows": r1 - r0, "cols": c1 - c0, "x0": x0, "dx": x1 - x0, "z0": z0, "dz": z1 - z0,
            "height_unit_m": 0.01, "rough_unit_m": 0.01,
            "layout": "walk heights uint16 LE (cm above h0) | terrain heights uint16 LE (cm above h0) | roughness uint8 "
                      "(cm, capped 2.55 m) | sand bits | off-limits bits | radio-shadow bits (np.packbits, row-major, "
                      "MSB first)"}


def _fine_heights(stack, start_lat: float, start_lon: float, points, margin_m: float):
    r0, r1, c0, c1 = _fine_window(stack, start_lat, start_lon, points, margin_m)
    win = (slice(r0, r1), slice(c0, c1))
    walk = stack.walk_elev_m if stack.walk_elev_m is not None else stack.elevation_m
    zw = _fill_nearest(np.asarray(walk[win], dtype=np.float64))
    zd = _fill_nearest(np.asarray(stack.elevation_m[win], dtype=np.float64))
    return win, zw, zd, min(float(zw.min()), float(zd.min()))


def _fine_zero(stack, start_lat: float, start_lon: float, points, margin_m: float) -> float:
    return _fine_heights(stack, start_lat, start_lon, points, margin_m)[3]


def fine_bytes(stack, start_lat: float, start_lon: float, points, margin_m: float = 400.0, radio=None) -> bytes:
    """The planner's walking surface, roughness, sand and off-limits mask at 1 m over the simulator window, plus the
    1 m terrain itself (for drawing near the walker) and the radio shadow (layers.radio). The simulator takes its
    grades, terrain multipliers and off-limits test from these, exactly as the route search does (it takes edge
    grades from the walk surface, not the raw DTM). Both height grids share one zero (fine.h0 in terrain_package)."""
    win, zw, zd, lo = _fine_heights(stack, start_lat, start_lon, points, margin_m)
    cm = lambda z: np.round((z - lo) * 100.0).clip(0, 65535).astype("<u2")   # noqa: E731
    rough = np.nan_to_num(np.asarray(stack.roughness_m[win], dtype=np.float64), nan=2.55)
    rough_cm = np.round(rough * 100.0).clip(0, 255).astype(np.uint8)
    sand = np.packbits(np.asarray(stack.sand[win], dtype=bool), axis=None)
    nogo = np.packbits(np.asarray(stack.nogo[win], dtype=bool), axis=None)
    shadow = np.zeros(zw.shape, dtype=bool) if radio is None else (np.asarray(radio[win]) == SHADOW)
    return (cm(zw).tobytes() + cm(zd).tobytes() + rough_cm.tobytes() + sand.tobytes() + nogo.tobytes()
            + np.packbits(shadow, axis=None).tobytes())


def _window_raster(stack, r0: int, r1: int, c0: int, c1: int, k: int) -> Raster:
    g = stack.grid.window(r0, c0, r1 - r0, c1 - c0)
    h, w = (r1 - r0) // k, (c1 - c0) // k
    return Raster(np.zeros((h, w), np.float32), GeoGrid(g.transform @ Affine.scale(k), g.crs, h, w))


def texture_png(site, stack, start_lat: float, start_lon: float, points: list[tuple[float, float]], kind: str = "photo",
                margin_m: float = 400.0, step: int = 3) -> bytes:
    """The window's photo (HiRISE orthophoto, tinted to Mars colours, relief where there is no photo), or the
    off-limits overlay, aligned with terrain_package's grid (same window, same block size grid edges)."""
    from PIL import Image

    from marswalk.layers import coverage, thermal
    from marswalk.layers.terrain import hillshade
    from marswalk.sources.fetch import raw_dir
    from marswalk.sources.raster import read_geotiff

    r0, r1, c0, c1 = area(stack, [(start_lat, start_lon), *points], margin_m)
    k0 = max(int(step), 1)
    r1, c1 = r0 + ((r1 - r0) // k0) * k0, c0 + ((c1 - c0) // k0) * k0       # same extent as the height grid
    k = max(1, math.ceil(max(r1 - r0, c1 - c0) / MAX_TEXTURE_PX))
    target = _window_raster(stack, r0, r1, c0, c1, k)
    sub = (slice(r0, r1, k), slice(c0, c1, k))
    if kind == "hazard":
        nogo = stack.nogo[sub][: target.shape[0], : target.shape[1]]
        coarse = None if stack.coarse is None else stack.coarse[sub][: target.shape[0], : target.shape[1]]
        rgba = np.zeros((*nogo.shape, 4), np.uint8)
        rgba[nogo] = (225, 45, 35, 150)
        if coarse is not None:
            rgba[coarse] = (90, 90, 100, 110)
        img = Image.fromarray(rgba, "RGBA")
    else:
        z = stack.elevation_m[sub][: target.shape[0], : target.shape[1]]
        hs = hillshade(Raster(z, target.grid)).astype(np.float32) / 255.0
        gray = 0.25 + 0.65 * hs
        ortho = raw_dir(site) / "ortho_1m.tif"
        if ortho.exists():
            o = coverage.shifted(read_geotiff(ortho), site.dtm.get("basemap_offset_m"))
            o.data[o.data <= 0] = np.nan
            on = thermal.resample_to(o, target).data
            ok = np.isfinite(on)
            if ok.any():
                lo, hi = np.nanpercentile(on[ok], [1, 99.5])
                gray = np.where(ok, np.clip((on - lo) / max(hi - lo, 1e-6), 0, 1), gray)
        # Mars palette: dark basalt brown -> butterscotch -> pale dust
        ramp = np.array([[52, 30, 20], [128, 74, 44], [186, 120, 74], [226, 178, 128], [244, 214, 176]], np.float32)
        x = np.clip(gray, 0, 1) * (len(ramp) - 1)
        i = np.clip(np.floor(x).astype(int), 0, len(ramp) - 2)
        f = (x - i)[..., None]
        rgb = ramp[i] * (1 - f) + ramp[i + 1] * f
        img = Image.fromarray(rgb.astype(np.uint8), "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()
