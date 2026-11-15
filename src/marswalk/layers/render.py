"""Overlay PNGs for the map (RGBA, transparent where there is no data), plus the walk-back safe zone.

Every overlay covers the whole stack grid. The grid is equirectangular with lat_ts = 0, so it is linear
in lon/lat and the app can place the PNG with a plain [lon_min, lat_min, lon_max, lat_max] extent.
"""
from __future__ import annotations

import io

import numpy as np

from marswalk.layers.stack import LayerStack

# name -> (label shown in the app, default opacity)
LAYERS = {
    "hillshade": ("Hillshade", 0.55),
    "slope5": ("Slope (5 m baseline)", 0.6),
    "roughness": ("Roughness (rock proxy)", 0.6),
    "ti": ("Thermal inertia (THEMIS)", 0.5),
    "nogo": ("No-go (hard limits)", 0.55),
    "safezone": ("Walk-back safe zone", 0.45),
    "radio": ("Radio shadow", 0.55),
    "shelter": ("Storm shelter reach", 0.5),
}
OPS_LAYERS = ("safezone", "radio", "shelter")   # computed from the rover, not from the terrain alone


TI_RANGE = (150.0, 600.0)   # fixed colour scale: dust and loose sand at the low end, bedrock at the high end
MAX_OVERLAY_PX = 2600   # long side; the browser stretches the PNG over the same lon/lat extent


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    k = max(int(np.ceil(max(rgba.shape[:2]) / MAX_OVERLAY_PX)), 1)
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba[::k, ::k]), "RGBA").save(buf, format="PNG", compress_level=3)
    return buf.getvalue()


COARSE_ALPHA = 105   # faded: terrain without trusted 1 m HiRISE data (shown for context, never planned on)


def _alpha(valid: np.ndarray, coarse: np.ndarray | None) -> np.ndarray:
    a = np.where(valid, 255, 0).astype(np.uint8)
    if coarse is not None:
        a[valid & coarse] = COARSE_ALPHA
    return a


def _colorize(a: np.ndarray, vmin: float, vmax: float, cmap: str, coarse: np.ndarray | None = None) -> np.ndarray:
    import matplotlib
    valid = np.isfinite(a)
    x = np.clip((np.where(valid, a, vmin) - vmin) / max(vmax - vmin, 1e-9), 0.0, 1.0)
    rgba = (matplotlib.colormaps[cmap](x) * 255).astype(np.uint8)
    rgba[..., 3] = _alpha(valid, coarse)
    return rgba


def overlay_step(shape) -> int:
    """Pixel stride that brings the long side down to MAX_OVERLAY_PX (the PNG never needs more)."""
    return max(int(np.ceil(max(shape[:2]) / MAX_OVERLAY_PX)), 1)


def layer_png(stack: LayerStack, name: str) -> bytes:
    # Subsample FIRST: colouring the full 1 m grid (tens of millions of cells) would cost gigabytes of RAM.
    k = overlay_step(stack.shape)
    sub = (slice(None, None, k), slice(None, None, k))
    coarse = None if stack.coarse is None else stack.coarse[sub]
    if name == "hillshade":
        from affine import Affine

        from marswalk.geo import GeoGrid, Raster
        from marswalk.layers.terrain import hillshade
        z = stack.elevation_m[sub]
        hs = hillshade(Raster(z, GeoGrid(stack.grid.transform @ Affine.scale(k), stack.grid.crs, *z.shape)))
        rgba = np.dstack([hs, hs, hs, _alpha(np.isfinite(z), coarse)])
        return _png(np.ascontiguousarray(rgba))
    if name == "slope5":
        return _png(_colorize(stack.slope_5m_deg[sub], 0.0, 30.0, "turbo", coarse))
    if name == "roughness":
        return _png(_colorize(stack.roughness_m[sub], 0.0, 0.8, "magma", coarse))
    if name == "ti":
        return _png(_colorize(stack.ti[sub], TI_RANGE[0], TI_RANGE[1], "viridis"))
    if name == "nogo":
        nogo = stack.nogo[sub]
        rgba = np.zeros((*nogo.shape, 4), dtype=np.uint8)
        rgba[nogo] = (220, 40, 40, 255)                            # too steep or too rough
        if coarse is not None:
            rgba[coarse] = (110, 110, 125, 210)                    # no trusted 1 m terrain: planning blocked
        return _png(rgba)
    raise KeyError(name)


def safezone_fraction(back, eva, elapsed_h: float = 0.0, used_energy_kj: float = 0.0, step: int = 1) -> np.ndarray:
    """Share of the REMAINING usable consumables that a walk back to the rover from each cell would take.

    <= 1 means "you can still walk home from here with the reserve intact" (Apollo-style walk-back limit),
    recomputed for any elapsed EVA time. Uses the larger of the time and energy shares. Unreachable = inf.
    `step` > 1 samples every step-th cell (for the map overlay, which never needs the full 1 m grid).
    """
    from marswalk.route.plan import usable_budgets
    b = usable_budgets(eva)
    margin = float(eva.eva.get("time_margin_factor", 1.0))
    t_left = max(b["time_s"] - elapsed_h * 3600.0, 1e-6)
    e_left = max(b["energy_kj"] - used_energy_kj, 1e-6)
    t, e = back.time_s[::step, ::step], back.energy_kj[::step, ::step]
    with np.errstate(invalid="ignore"):
        return np.maximum(t * (margin / t_left), e * (margin / e_left))


def safezone_png(frac: np.ndarray) -> bytes:
    """Green -> yellow -> orange as the walk back eats the remaining budget; transparent outside the limit."""
    k = overlay_step(frac.shape)
    frac = frac[::k, ::k]
    stops = np.array([0.0, 0.5, 0.8, 1.0])
    cols = np.array([[40, 180, 90], [150, 200, 60], [240, 200, 40], [240, 120, 30]], dtype=np.float64)
    inside = np.isfinite(frac) & (frac <= 1.0)
    x = np.where(inside, frac, 0.0)
    rgba = np.zeros((*frac.shape, 4), dtype=np.uint8)
    for ch in range(3):
        rgba[..., ch] = np.interp(x, stops, cols[:, ch]).astype(np.uint8)
    rgba[..., 3] = np.where(inside, 255, 0)
    return _png(rgba)


def radio_png(grid: np.ndarray) -> bytes:
    """Violet where terrain blocks the line of sight to the rover's antenna; clear where the crew can call the rover."""
    from marswalk.layers.radio import SHADOW
    k = overlay_step(grid.shape)
    g = grid[::k, ::k]
    rgba = np.zeros((*g.shape, 4), dtype=np.uint8)
    rgba[g == SHADOW] = (110, 70, 220, 200)
    return _png(rgba)


def shelter_png(back, eva) -> bytes:
    """Magenta where the walk home (x margin) takes longer than the solar-storm warning: a crew there would still be
    outside when the dose arrives. Clear inside shelter reach and beyond the walk range."""
    from marswalk.route.exposure import DEFAULT_LEAD_MIN
    k = overlay_step(back.time_s.shape)
    t = back.time_s[::k, ::k] * float(eva.eva.get("time_margin_factor", 1.0))
    lead_s = 60.0 * float(eva.eva.get("sep_warning_lead_min", DEFAULT_LEAD_MIN))
    rgba = np.zeros((*t.shape, 4), dtype=np.uint8)
    with np.errstate(invalid="ignore"):
        rgba[np.isfinite(t) & (t > lead_s)] = (215, 50, 150, 190)
    return _png(rgba)


def bounds_lonlat(stack: LayerStack) -> list[float]:
    lat_min, lon_min, lat_max, lon_max = stack.grid.bounds_latlon()
    return [lon_min, lat_min, lon_max, lat_max]


def layer_notes(stack: LayerStack, shelter_lead_min: float = 30.0) -> dict[str, str]:
    """One plain sentence per overlay about what it shows on THIS terrain (shown in the map key)."""
    notes = {}
    if np.isfinite(stack.ti).any():
        lo, hi = np.nanpercentile(stack.ti, [2, 98])
        sand = float(np.mean(stack.sand)) * 100.0
        notes["ti"] = (f"Thermal inertia here is {lo:.0f} to {hi:.0f}, measured in 100 m blocks, so the colour is nearly even. "
                       + ("No loose sand at this resolution: firm ground throughout." if sand < 0.5
                          else f"About {sand:.0f}% of the area reads as loose sand."))
    if stack.coarse is not None:
        hazard = float(np.mean(stack.nogo & ~stack.coarse)) * 100.0
        notes["nogo"] = (f"Red: {hazard:.0f}% of this area is too steep or too rough. Grey: {float(np.mean(stack.coarse)) * 100.0:.0f}% "
                         "has no trusted 1 m terrain, so routes cannot be planned there.")
    else:
        notes["nogo"] = f"{float(np.mean(stack.nogo)) * 100.0:.0f}% of this area is off limits (too steep or too rough)."
    notes["radio"] = ("Violet: a ridge stands between the suit radio and the rover's antenna, so the crew cannot call the "
                      "rover from there. Line of sight only, antenna heights from configs/eva [comms].")
    notes["shelter"] = (f"Magenta: the walk home takes longer than the {shelter_lead_min:.0f} min warning a crew gets before a "
                        "solar particle storm's dose arrives (Löwe et al. 2025). Everywhere else the crew can reach the "
                        "rover in time.")
    return notes


def coverage_note(stack: LayerStack) -> str:
    """One sentence on where the terrain data stops, appended to every terrain layer's note."""
    if stack.coarse is not None:
        pct = float(np.mean(stack.coarse)) * 100.0
        return (f"Full colour: 1 m HiRISE stereo terrain, where routes can be planned. Faded ({pct:.0f}% of the map): the USGS merged "
                "elevation model, shown for context only and closed to planning.")
    base = ("The colour stops where 1 m terrain data stops. Its slanted sides are the edge of the HiRISE stereo strip, "
            "and routes can only be planned inside it.")
    return f"{stack.terrain_note.capitalize()}, so it is not used. {base}" if stack.terrain_note else base


def layer_list(stack: LayerStack, has_ti: bool = True, shelter_lead_min: float = 30.0) -> list[dict]:
    b = bounds_lonlat(stack)
    notes = layer_notes(stack, shelter_lead_min)
    cov = coverage_note(stack)
    return [{"name": label, "key": key, "url": f"/api/layers/{key}.png", "bounds": b, "opacity": opacity,
             "note": (notes.get(key, "") + " " + cov).strip() if key not in OPS_LAYERS else notes.get(key, "")}
            for key, (label, opacity) in LAYERS.items() if key != "ti" or has_ti]
