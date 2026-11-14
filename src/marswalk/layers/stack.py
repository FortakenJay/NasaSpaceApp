"""LayerStack: every per-pixel input the cost models and route search need, on ONE grid.

`marswalk layers` builds this from data/raw/<site>/ and caches it to data/cache/<site>/stack.npz.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from marswalk.config import EVAConfig, SiteConfig
from marswalk.geo import GeoGrid


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

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation_m.shape  # type: ignore[return-value]

    def traversable(self, r: int, c: int) -> bool:
        return (0 <= r < self.shape[0] and 0 <= c < self.shape[1]
                and not self.nogo[r, c] and np.isfinite(self.elevation_m[r, c]))


def nogo_mask(slope_1m: np.ndarray, slope_5m: np.ndarray, roughness: np.ndarray,
              elevation: np.ndarray, hazards: dict) -> np.ndarray:
    """Hard no-go: missing DEM, or any hazard limit exceeded. Implemented (pure, tested)."""
    with np.errstate(invalid="ignore"):
        return (~np.isfinite(elevation)
                | (slope_5m > hazards["max_slope_deg_5m"])
                | (slope_1m > hazards["max_slope_deg_1m"])
                | (roughness > hazards["max_roughness_m"]))


def build_stack(site: SiteConfig, eva: EVAConfig) -> LayerStack:
    """TODO(M2): load raw products, compute terrain and thermal layers, apply nogo_mask, cache."""
    raise NotImplementedError("M2: build the layer stack")
