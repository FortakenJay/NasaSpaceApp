"""Radio line of sight from the rover: where a crew member's suit antenna can see the rover's antenna.

Behind a ridge the crew cannot talk to the rover. The model is pure line of sight over the terrain: no relay, and
no diffraction over ridge tops (which would sometimes let a VHF/UHF signal through), so it errs on the side of
"out of contact". For each azimuth a ray walks outward from the rover, keeping the steepest elevation angle the
ground has reached so far; a cell is in contact when the suit antenna standing on it rises above that horizon.
Mars is curved: the ground falls d^2 / 2R below the rover's horizontal plane (0.8 m at 2.3 km), which is included.

Antenna heights are assumptions in configs/eva ([comms]); the terrain is the stack's elevation (the merged base DEM
where it exists, so ridges outside the HiRISE strip still block the signal).
"""
from __future__ import annotations

import math

import numba
import numpy as np

NO_DATA, CONTACT, SHADOW = 0, 1, 2
DEFAULTS = {"rover_antenna_m": 3.0, "suit_antenna_m": 2.0}


@numba.njit(cache=True)
def _sweep(z, r0, c0, z_ant, h_suit, max_r_px, px_m, radius_m, out):
    h, w = z.shape
    n_rays = int(2.0 * math.pi * max_r_px * 1.5) + 8           # rays no more than ~0.7 px apart at the edge
    out[r0, c0] = CONTACT
    for k in range(n_rays):
        a = 2.0 * math.pi * k / n_rays
        dr, dc = -math.cos(a), math.sin(a)                     # azimuth clockwise from north (north = row - 1)
        best = -math.inf
        s = 0.5
        while s <= max_r_px:
            r = int(math.floor(r0 + dr * s + 0.5))
            c = int(math.floor(c0 + dc * s + 0.5))
            if r < 0 or c < 0 or r >= h or c >= w:
                break
            zz = z[r, c]
            if math.isfinite(zz):
                d = s * px_m
                drop = d * d / (2.0 * radius_m)
                ground = (zz - drop - z_ant) / d
                suit = (zz + h_suit - drop - z_ant) / d
                if suit >= best:
                    out[r, c] = CONTACT
                elif out[r, c] != CONTACT:
                    out[r, c] = SHADOW
                if ground > best:
                    best = ground
            s += 0.5


def contact_grid(stack, start_rc: tuple[int, int], comms: dict | None, max_radius_m: float,
                 radius_m: float = 3396190.0) -> np.ndarray:
    """uint8 grid on the stack: CONTACT (1) where the suit can see the rover's antenna, SHADOW (2) where terrain is in
    the way, NO_DATA (0) beyond `max_radius_m` or without elevation."""
    cfg = {**DEFAULTS, **(comms or {})}
    z = np.ascontiguousarray(stack.elevation_m, dtype=np.float64)
    r0, c0 = start_rc
    if not np.isfinite(z[r0, c0]):
        raise ValueError("the rover's cell has no elevation")
    out = np.zeros(z.shape, dtype=np.uint8)
    px = float(stack.grid.pixel_m)
    _sweep(z, int(r0), int(c0), float(z[r0, c0]) + float(cfg["rover_antenna_m"]), float(cfg["suit_antenna_m"]),
           max_radius_m / px, px, float(radius_m), out)
    return out
