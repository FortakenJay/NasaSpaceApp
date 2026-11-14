"""Where the terrain is trustworthy enough to plan on, when two elevation products overlap.

The USGS merged DEM fills the whole analysis window, but it is stitched from HRSC, CTX and HiRISE DEMs, so its real
detail varies. The HiRISE stereo DTM is one known 1 m product. The merged DEM is therefore the base surface, and the
HiRISE footprint (shrunk a little from its ragged stereo edge) is the only place a route may be planned.

`hires_footprint` finds that footprint on the merged grid; `agreement` compares the two products inside it, so the user
can see whether the merged DEM really carries the same relief (and so the app can fall back if it does not).

Registration. The HiRISE DTM's own georeferencing is ~45 m from the USGS/MSL Gale base map (measured 2026-11-14 over
HTTP range reads: 33 m north and 30 m west of it), and the Mars Trek photo mosaic the app draws sits on that base map.
`shifted` moves a raster by a fixed offset (the site config carries the measured one, so the HiRISE layers line up with
the photo even without the merged DEM); `register` re-measures what is left by block cross-correlation of the two DEMs.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_erosion

from marswalk.geo import Raster
from marswalk.layers import terrain, thermal

EDGE_PX = 6                 # the stereo strip's edge is noisy: shrink the planning footprint by this many pixels
MIN_OVERLAP_PX = 50_000     # below this the two products cannot be compared (about 0.22 km x 0.22 km)
MAX_MEDIAN_SLOPE_DIFF_DEG = 4.0
MIN_ROUGHNESS_RATIO = 0.75   # a smoother merged surface would hide rocks from the no-go mask: do not accept it


REG_BLOCK_PX = 4        # registration compares 4 m block means (robust to 1 m stereo noise)
REG_PATCH_PX = 512      # over a 512 m patch of the HiRISE footprint
REG_SEARCH_PX = 60      # searching +-60 m around the configured offset
MIN_REG_CORR = 0.9      # below this the residual is not trusted and not applied


def shifted(r: Raster, offset_m: dict | None) -> Raster:
    """The same raster moved `offset_m` = {east, north} metres in its map coordinates (no resampling)."""
    if not offset_m or not (offset_m.get("east") or offset_m.get("north")):
        return r
    from affine import Affine
    t = Affine.translation(float(offset_m.get("east", 0.0)), float(offset_m.get("north", 0.0))) @ r.grid.transform
    return Raster(r.data, type(r.grid)(t, r.grid.crs, r.grid.height, r.grid.width), name=r.name, units=r.units)


def _plane_removed(a: np.ndarray, ok: np.ndarray) -> np.ndarray:
    yy, xx = np.nonzero(ok)
    A = np.column_stack([np.ones(len(yy)), xx, yy])
    coef, *_ = np.linalg.lstsq(A, a[ok].astype(np.float64), rcond=None)
    gy, gx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    return a - (coef[0] + coef[1] * gx + coef[2] * gy)


def register(hires: Raster, merged: Raster, patch_px: int = REG_PATCH_PX, search_px: int = REG_SEARCH_PX) -> dict:
    """Residual offset {east_m, north_m, corr} that moves `hires` onto `merged`, or {} if it cannot be measured.

    A 512 m patch of the HiRISE DTM (resampled onto the merged grid) is compared, as 4 m block means with a plane
    removed, with the merged DEM shifted by every whole metre within +-60 m; the best shift is refined to sub-metre
    with a parabola through its neighbours.
    """
    B, P, S = REG_BLOCK_PX, patch_px - patch_px % REG_BLOCK_PX, search_px
    on = thermal.resample_to(hires, merged).data
    ok = np.isfinite(on)
    if ok.sum() < P * P:
        return {}
    # centre the patch on the part of the strip farthest from its edges
    from scipy.ndimage import distance_transform_edt
    step = 8
    dist = distance_transform_edt(ok[::step, ::step]) * step
    rc, cc = np.unravel_index(int(np.argmax(dist)), dist.shape)
    rc, cc = rc * step, cc * step
    if on.shape[0] < P + 2 * S or on.shape[1] < P + 2 * S:
        return {}
    r0 = int(np.clip(rc - P // 2, S, on.shape[0] - P - S))
    c0 = int(np.clip(cc - P // 2, S, on.shape[1] - P - S))
    h = on[r0:r0 + P, c0:c0 + P]
    hok = np.isfinite(h)
    m = merged.data[r0 - S:r0 + P + S, c0 - S:c0 + P + S].astype(np.float64)
    mok = np.isfinite(m)
    if hok.mean() < 0.95 or mok.mean() < 0.95:
        return {}
    M = P // B
    hb = np.where(hok, h, 0.0).reshape(M, B, M, B).sum(axis=(1, 3)) / np.maximum(hok.reshape(M, B, M, B).sum(axis=(1, 3)), 1)
    hb_ok = hok.reshape(M, B, M, B).all(axis=(1, 3))
    hb = _plane_removed(hb, hb_ok)
    I = np.zeros((m.shape[0] + 1, m.shape[1] + 1))
    I[1:, 1:] = np.where(mok, m, 0.0).cumsum(0).cumsum(1)
    idx = np.arange(M) * B
    # Correlation with a plane removed from each shifted merged patch, without fitting 14,641 planes: hv is already
    # orthogonal to the plane basis, so only the merged patch's norm needs the plane taken out (via its projection).
    yy, xx = np.nonzero(hb_ok)
    Q, _ = np.linalg.qr(np.column_stack([np.ones(len(yy)), xx, yy]))
    hv = hb[hb_ok]
    hv = (hv - hv.mean()) / max(hv.std(), 1e-9)
    n = hv.size
    cols_all = S + np.arange(-S, S + 1)[:, None] + idx[None, :]          # (2S+1, M) block starts for every dx
    corr = np.full((2 * S + 1, 2 * S + 1), -1.0)
    for i, dy in enumerate(range(-S, S + 1)):
        rows = S + dy + idx
        Ir = I[rows + B] - I[rows]                                         # (M, W+1) row-band sums
        D = Ir[:, B:] - Ir[:, :-B]                                         # (M, W+1-B) block sums at every column
        blk = np.transpose(D[:, cols_all], (1, 0, 2)) / (B * B)           # (2S+1, M, M) one patch per dx
        v = blk[:, hb_ok]                                                  # (2S+1, n)
        num = v @ hv
        proj = v @ Q                                                       # (2S+1, 3)
        den = np.sqrt(np.maximum(n * (np.einsum("ij,ij->i", v, v) - np.einsum("ij,ij->i", proj, proj)), 1e-12))
        corr[i] = num / den
    i, j = np.unravel_index(int(np.argmax(corr)), corr.shape)

    def vertex(a, b, c):   # sub-pixel peak of a parabola through three samples
        d = a - 2 * b + c
        return 0.0 if d >= 0 else 0.5 * (a - c) / d
    fy = vertex(corr[i - 1, j], corr[i, j], corr[i + 1, j]) if 0 < i < 2 * S else 0.0
    fx = vertex(corr[i, j - 1], corr[i, j], corr[i, j + 1]) if 0 < j < 2 * S else 0.0
    dy, dx = i - S + fy, j - S + fx          # rows/cols: features of hires appear at (r + dy, c + dx) in merged
    px = merged.grid.pixel_m
    return {"east_m": round(float(dx * px), 2), "north_m": round(float(-dy * px), 2), "corr": round(float(corr[i, j]), 4),
            "at_edge": bool(i in (0, 2 * S) or j in (0, 2 * S))}


def hires_footprint(dtm: Raster, target: Raster, edge_px: int = EDGE_PX) -> tuple[np.ndarray, Raster]:
    """(mask, dtm resampled onto target's grid). The mask is True where the HiRISE DTM has data, edges trimmed."""
    on = thermal.resample_to(dtm, target)          # generic GDAL reprojection (bilinear); NaN outside the strip
    ok = np.isfinite(on.data)
    if edge_px > 0 and ok.any():
        ok = binary_erosion(ok, structure=np.ones((3, 3), dtype=bool), iterations=edge_px, border_value=0)
    return ok, on


CHECK_PX = 2048   # the comparison runs on at most this square of the footprint (enough samples, bounded memory)


def _crop(r: Raster, rs: slice, cs: slice) -> Raster:
    return Raster(np.ascontiguousarray(r.data[rs, cs]), r.grid.window(rs.start, cs.start, rs.stop - rs.start, cs.stop - cs.start))


def agreement(merged: Raster, hires_on_merged: Raster, mask: np.ndarray) -> dict:
    """How well the merged DEM matches the HiRISE DTM where both exist (medians over a central part of the footprint)."""
    n = int(mask.sum())
    out: dict = {"overlap_px": n}
    if n < MIN_OVERLAP_PX:
        return out
    rows, cols = np.nonzero(mask.any(axis=1))[0], np.nonzero(mask.any(axis=0))[0]
    rc, cc = (rows[0] + rows[-1]) // 2, (cols[0] + cols[-1]) // 2
    h = min(CHECK_PX, rows[-1] - rows[0] + 1) // 2
    w = min(CHECK_PX, cols[-1] - cols[0] + 1) // 2
    rs = slice(max(rc - h, 0), min(rc + h + 1, mask.shape[0]))
    cs = slice(max(cc - w, 0), min(cc + w + 1, mask.shape[1]))
    merged, hires_on_merged, mask = _crop(merged, rs, cs), _crop(hires_on_merged, rs, cs), mask[rs, cs]
    s_m = terrain.slope(merged, 5.0).data
    s_h = terrain.slope(hires_on_merged, 5.0).data
    both = mask & np.isfinite(s_m) & np.isfinite(s_h)
    if both.sum() < MIN_OVERLAP_PX:
        return out
    dz = merged.data[both] - hires_on_merged.data[both]
    out["median_slope_diff_deg"] = float(np.median(np.abs(s_m[both] - s_h[both])))
    out["median_dz_m"] = float(np.median(dz[np.isfinite(dz)]))
    r_m = terrain.roughness(merged).data
    r_h = terrain.roughness(hires_on_merged).data
    rough = both & np.isfinite(r_m) & np.isfinite(r_h) & (r_h > 0.02)
    if rough.sum() >= MIN_OVERLAP_PX:
        out["median_roughness_ratio"] = float(np.median(r_m[rough] / r_h[rough]))
    return out


def usable(check: dict) -> tuple[bool, str]:
    """Is the merged DEM good enough to be the base surface? (decision, plain-language reason)"""
    if "median_slope_diff_deg" not in check:
        return False, "the merged elevation model and the HiRISE strip overlap too little to be compared"
    d = check["median_slope_diff_deg"]
    if d > MAX_MEDIAN_SLOPE_DIFF_DEG:
        return False, f"the merged elevation model disagrees with the HiRISE strip (slopes differ by {d:.1f} deg)"
    ratio = check.get("median_roughness_ratio")
    if ratio is not None and ratio < MIN_ROUGHNESS_RATIO:
        return False, (f"the merged elevation model is smoother than the HiRISE strip (about {ratio:.0%} of its roughness), "
                       "so it would hide rocks")
    return True, ""
