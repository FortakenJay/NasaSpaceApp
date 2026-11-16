"""LayerStack: every per-pixel input the cost models and route search need, on ONE grid.

`marswalk layers` builds this from data/raw/<site>/ (memoised in-process; overlay PNGs are cached in data/cache/<site>/).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from marswalk.config import EVAConfig, SiteConfig
from marswalk.geo import GeoGrid, Raster


@dataclass
class LayerStack:
    """All arrays share `grid` (the DTM window) and are C-contiguous float32/bool, ready for numba."""

    grid: GeoGrid
    elevation_m: np.ndarray       # float32, NaN = no data
    slope_1m_deg: np.ndarray
    slope_5m_deg: np.ndarray
    roughness_m: np.ndarray
    steep_frac: np.ndarray        # fraction of 1 m cells >30 deg nearby
    ti: np.ndarray                # THEMIS TI on the DTM grid (NaN where missing)
    sand: np.ndarray              # bool
    nogo: np.ndarray              # bool: hard constraint, never enter
    walk_elev_m: np.ndarray | None = None   # stride-scale smoothed DTM; route search takes edge grades from it
    coarse: np.ndarray | None = None        # bool: no trusted 1 m HiRISE terrain here (shown faded; always in nogo)
    terrain_source: str = "hirise"          # "hirise" (the stereo strip alone) or "merged" (USGS merged DEM base)
    terrain_note: str = ""                  # plain-language reason when the merged DEM was set aside
    terrain_check: dict = field(default_factory=dict)   # merged vs HiRISE agreement (median slope / elevation offset)

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation_m.shape  # type: ignore[return-value]

def nogo_mask(slope_1m: np.ndarray, slope_5m: np.ndarray, roughness: np.ndarray,
              elevation: np.ndarray, hazards: dict) -> np.ndarray:
    """Hard no-go: missing DEM, or any hazard limit exceeded. Implemented (pure, tested)."""
    with np.errstate(invalid="ignore"):
        return (~np.isfinite(elevation)
                | (slope_5m > hazards["max_slope_deg_5m"])
                | (slope_1m > hazards["max_slope_deg_1m"])
                | (roughness > hazards["max_roughness_m"]))


_MEMO: dict[tuple, LayerStack] = {}


def raw_stamp(site: SiteConfig) -> str:
    """Changes whenever the cached terrain files (or the choice of merged DEM) change. Keys the overlay PNG cache."""
    from marswalk.sources.fetch import MERGED_FILE, raw_dir
    raw = raw_dir(site)
    parts = [(raw / "dtm.tif").stat().st_mtime_ns]
    if site.merged_dem is not None and (raw / MERGED_FILE).exists():
        parts.append((raw / MERGED_FILE).stat().st_mtime_ns)
    return "-".join(str(p) for p in parts)


def build_stack(site: SiteConfig, eva: EVAConfig, use_cache: bool = True) -> LayerStack:
    """Load data/raw/<site>/ (dtm.tif, dem_merged.tif and ti.tif when present), compute terrain and thermal layers,
    apply nogo_mask.

    With a merged DEM the stack sits on ITS grid and the HiRISE DTM only decides where planning is allowed
    (`coarse` = everywhere else, always no-go). Without one, or if the merged DEM disagrees with the HiRISE strip,
    the stack is the HiRISE DTM alone, as before.

    Raises FileNotFoundError when the DTM has not been fetched yet. The stack is memoised per process
    (keyed by the files and the hazard limits); building it takes some seconds on the Gale window.
    """
    from marswalk.layers import coverage, terrain, thermal
    from marswalk.sources.fetch import MERGED_FILE, raw_dir
    from marswalk.sources.raster import read_geotiff

    raw = raw_dir(site)
    dtm_path = raw / "dtm.tif"
    if not dtm_path.exists():
        import os
        from marswalk.config import PROJECT_ROOT
        # A hosted deploy has no cached GeoTIFF (the files are git-ignored) and cannot write the
        # project directory. Download the elevation window into the writable data directory.
        hosted = bool(os.environ.get("VERCEL")) or not os.access(PROJECT_ROOT, os.W_OK)
        if hosted and not os.environ.get("MARSWALK_DATA"):
            from marswalk.sources.fetch import fetch_site
            fetch_site(site, essentials_only=True)
        if not dtm_path.exists():
            raise FileNotFoundError(f"terrain not cached: {dtm_path} is missing. Run `python -m marswalk fetch` first.")
    ti_path = raw / "ti.tif"
    merged_path = raw / MERGED_FILE
    use_merged = site.merged_dem is not None and merged_path.exists()
    key = (str(dtm_path), raw_stamp(site), use_merged, ti_path.exists(), tuple(sorted(eva.hazards.items())))
    if use_cache and key in _MEMO:
        return _MEMO[key]

    # The HiRISE DTM goes onto the base-map frame first (config: measured offset), so overlays line up with the photo.
    configured = site.dtm.get("basemap_offset_m")
    hires = coverage.shifted(read_geotiff(dtm_path), configured)
    dem, coarse, source, note = hires, None, "hirise", ""
    check: dict = {"basemap_offset_m": dict(configured) if configured else None}
    if use_merged:
        merged = read_geotiff(merged_path)
        reg = coverage.register(hires, merged)
        check["registration"] = reg
        if reg and reg["corr"] >= coverage.MIN_REG_CORR and not reg["at_edge"]:
            hires = coverage.shifted(hires, {"east": reg["east_m"], "north": reg["north_m"]})   # what is left over
        footprint, hires_on = coverage.hires_footprint(hires, merged)
        check.update(coverage.agreement(merged, hires_on, footprint))
        ok, why = coverage.usable(check)
        if ok:
            dem, coarse, source = merged, ~footprint, "merged"
        else:
            note = why
        del hires_on, footprint
    del hires
    s1 = terrain.slope(dem, 1.0).data
    s5 = terrain.slope(dem, 5.0).data
    rough = terrain.roughness(dem).data
    steep = terrain.steep_fraction(Raster(s1, dem.grid)).data
    if ti_path.exists():
        ti_on = thermal.resample_to(read_geotiff(ti_path), dem)
        threshold = float(site.products.get("thermal_inertia", {}).get("sand_ti_threshold", 300.0))
        ti, sand = ti_on.data, thermal.sand_flag(ti_on, threshold).data
    else:
        ti, sand = np.full(dem.shape, np.nan, dtype=np.float32), np.zeros(dem.shape, dtype=bool)
    nogo = nogo_mask(s1, s5, rough, dem.data, eva.hazards) | ~np.isfinite(s5) | ~np.isfinite(rough)
    if coarse is not None:
        nogo |= coarse
    c = np.ascontiguousarray
    stack = LayerStack(grid=dem.grid, elevation_m=c(dem.data, dtype=np.float32), slope_1m_deg=c(s1), slope_5m_deg=c(s5),
                       roughness_m=c(rough), steep_frac=c(steep), ti=c(ti, dtype=np.float32), sand=c(sand, dtype=bool),
                       nogo=c(nogo, dtype=bool), walk_elev_m=terrain.walk_surface(dem),
                       coarse=None if coarse is None else c(coarse, dtype=bool),
                       terrain_source=source, terrain_note=note, terrain_check=check)
    _MEMO.clear()
    _MEMO[key] = stack
    return stack
