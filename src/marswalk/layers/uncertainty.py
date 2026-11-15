"""How sure is "off limits"? Off-limits ground recomputed on perturbed terrain (Monte Carlo).

A HiRISE stereo DTM is not exact: each elevation carries a matching error of "tens of cm" for a 1 m DTM (Sutton et al.
2022, Remote Sensing 14: 2403; "under 0.5 m for most HiRISE DTMs", Sutton et al., LPSC 2015 #3010). This DTM's own
expected precision is not in its PDS label or README, so the value is an assumption in configs/eva [uncertainty]. The
registration onto the base map has its own error too (layers.coverage): each draw also shifts the terrain by a whole
pixel with a chance set by `registration_sigma_m`.

Each draw adds spatially correlated noise (white noise smoothed over `noise_corr_px`, rescaled to `vertical_sigma_m`),
recomputes the 1 m and 5 m slopes and roughness exactly as the stack does, and applies the same hazard limits. The share
of draws in which a cell is off limits is its frequency: "always" (>= 95 %), "sometimes" (5 to 95 %), "never" (<= 5 %).
It runs over the walk area only (the stops plus a margin), where the decisions are.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

from marswalk.geo import Raster

DEFAULTS = {"draws": 20, "vertical_sigma_m": 0.3, "noise_corr_px": 1.0, "registration_sigma_m": 0.5, "seed": 0}
ALWAYS, SOMETIMES = 0.95, 0.05
PAD = 12   # pixels around the window, so the slope and roughness filters see real terrain at its edges


def offlimits_frequency(stack, hazards: dict, window: tuple[int, int, int, int], cfg: dict | None = None) -> np.ndarray:
    """Share of draws (0..1) in which each cell of `window` = (r0, r1, c0, c1) is off limits. NaN where the terrain has
    no data. Untrusted terrain (stack.coarse) is off limits in every draw, as in the stack."""
    from marswalk.layers import terrain
    from marswalk.layers.stack import nogo_mask
    c = {**DEFAULTS, **(cfg or {})}
    r0, r1, c0, c1 = window
    a0, a1 = max(r0 - PAD, 0), min(r1 + PAD, stack.shape[0])
    b0, b1 = max(c0 - PAD, 0), min(c1 + PAD, stack.shape[1])
    z = np.asarray(stack.elevation_m[a0:a1, b0:b1], dtype=np.float32)
    grid = stack.grid.window(a0, b0, a1 - a0, b1 - b0)
    rng = np.random.default_rng(int(c["seed"]))
    px = float(stack.grid.pixel_m)
    p_shift = min(float(c["registration_sigma_m"]) / px, 1.0)     # chance of a whole-pixel shift, each axis
    count = np.zeros((r1 - r0, c1 - c0), dtype=np.float32)
    inner = (slice(r0 - a0, r0 - a0 + (r1 - r0)), slice(c0 - b0, c0 - b0 + (c1 - c0)))
    for _ in range(int(c["draws"])):
        noise = gaussian_filter(rng.standard_normal(z.shape).astype(np.float32), float(c["noise_corr_px"]))
        noise *= float(c["vertical_sigma_m"]) / max(float(noise.std()), 1e-9)
        zz = z + noise
        dr, dc = (int(rng.choice([-1, 1])) if rng.random() < p_shift else 0 for _ in range(2))
        if dr or dc:
            zz = np.roll(zz, (dr, dc), axis=(0, 1))
        dem = Raster(zz, grid)
        s1, s5, rough = terrain.slope(dem, 1.0).data, terrain.slope(dem, 5.0).data, terrain.roughness(dem).data
        bad = nogo_mask(s1, s5, rough, zz, hazards) | ~np.isfinite(s5) | ~np.isfinite(rough)
        count += bad[inner]
    freq = count / float(c["draws"])
    if stack.coarse is not None:
        freq[stack.coarse[r0:r1, c0:c1]] = 1.0
    freq[~np.isfinite(stack.elevation_m[r0:r1, c0:c1])] = np.nan
    return freq


def walk_window(site, stack, margin_m: float = 400.0) -> tuple[int, int, int, int]:
    """The walk area: the rover and every stop, plus a margin (the simulator's window)."""
    from marswalk.sim import area
    return area(stack, [(site.start.lat, site.start.lon), *[(s.lat, s.lon) for s in site.stops]], margin_m)


def png(freq: np.ndarray) -> bytes:
    """Amber where the off-limits test changes from draw to draw; red where it is off limits in (nearly) every one."""
    from marswalk.layers.render import _png
    rgba = np.zeros((*freq.shape, 4), dtype=np.uint8)
    with np.errstate(invalid="ignore"):
        rgba[(freq > SOMETIMES) & (freq < ALWAYS)] = (245, 170, 40, 190)
        rgba[freq >= ALWAYS] = (220, 40, 40, 200)
    return _png(rgba)


def classes(freq: np.ndarray) -> dict:
    """Shares of the window that are always, sometimes and never off limits."""
    ok = np.isfinite(freq)
    n = max(int(ok.sum()), 1)
    return {"always": float(((freq >= ALWAYS) & ok).sum()) / n,
            "sometimes": float(((freq > SOMETIMES) & (freq < ALWAYS) & ok).sum()) / n,
            "never": float(((freq <= SOMETIMES) & ok).sum()) / n}


def route_marginal_m(freq: np.ndarray, window: tuple[int, int, int, int], plan, px_m: float) -> tuple[float, float]:
    """(metres of the route on "sometimes" ground, metres on "always" ground) inside the window."""
    r0, r1, c0, c1 = window
    some = always = 0.0
    for leg in plan.legs:
        cells = leg.path.cells
        for (ra, ca), (rb, cb) in zip(cells, cells[1:]):
            if not (r0 <= rb < r1 and c0 <= cb < c1):
                continue
            f = freq[rb - r0, cb - c0]
            if not np.isfinite(f):
                continue
            step = px_m * (2 ** 0.5 if ra != rb and ca != cb else 1.0)
            if f >= ALWAYS:
                always += step
            elif f > SOMETIMES:
                some += step
    return some, always
