"""Stop ordering: fixed science order by default, optional brute-force reorder.

Implemented (pure, tested). With 5 stops there are 120 orders, so brute force is fine.
Cost lookups come from a caller-supplied function, normally a precomputed matrix of A* leg costs.
"""
from __future__ import annotations

from itertools import permutations
from typing import Callable, Sequence

LegCost = Callable[[str, str], float]


def tour_cost(order: Sequence[str], start_id: str, leg_cost: LegCost, return_to_start: bool = True) -> float:
    ids = [start_id, *order] + ([start_id] if return_to_start else [])
    return sum(leg_cost(a, b) for a, b in zip(ids, ids[1:]))


def order_stops(stop_ids: Sequence[str], start_id: str, leg_cost: LegCost, mode: str = "fixed",
                return_to_start: bool = True) -> list[str]:
    """Return the visiting order.

    mode="fixed"    -> stop_ids unchanged (the science plan's order)
    mode="optimize" -> the permutation with the minimum tour cost (ties keep the fixed order)
    """
    if mode == "fixed":
        return list(stop_ids)
    if mode != "optimize":
        raise ValueError(f"unknown stop order mode {mode!r}")
    if len(stop_ids) > 8:
        raise ValueError("brute-force reorder is limited to 8 stops; use a heuristic for more")
    best = list(stop_ids)
    best_cost = tour_cost(best, start_id, leg_cost, return_to_start)
    for perm in permutations(stop_ids):
        c = tour_cost(perm, start_id, leg_cost, return_to_start)
        if c < best_cost - 1e-9:
            best, best_cost = list(perm), c
    return best
