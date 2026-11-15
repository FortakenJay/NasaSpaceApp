"""What runs out first: the time each tracked consumable has left before its reserve, at the rate it is being used.

Oxygen is time-based (suit.o2_capacity_h), as the plan has always counted it. The others follow metabolic energy or a
fixed draw, by physics; their capacities must come from a suit's specification, so they are only tracked when
[consumables] in configs/eva sets them:
- effort (suit.metabolic_budget_kj): the metabolic energy budget itself.
- cooling water (feedwater_kg): nearly all metabolic energy leaves the body as heat, and an evaporative cooler
  rejects it at the latent heat of vaporisation of water, 2 454 kJ/kg at 20 °C: a 300 W walker uses 0.44 kg/h.
- CO2 scrubber (co2_capacity_kg): CO2 breathed out = O2 burned (energy / 20.19 kJ per litre) x RQ 0.82 x 1.977 g per
  litre at 0 °C, the same Weir/Lusk numbers route/plan.py uses for oxygen.
- battery (battery_capacity_wh with battery_draw_w): a fixed electrical draw.
Every consumable keeps the same walk-home reserve (eva.walkback_reserve_frac).
"""
from __future__ import annotations

import math

LATENT_KJ_PER_KG = 2454.0
KJ_PER_L_O2 = 4.825 * 4.184
RQ = 0.82
KG_PER_L_CO2 = 1.977e-3


def tracked(eva) -> list[dict]:
    """[{name, label, kind, usable, per}] for every consumable with a capacity. kind: "time" (seconds of a tank),
    "energy" (per kJ of metabolic energy) or "draw" (per second)."""
    keep = 1.0 - float(eva.eva["walkback_reserve_frac"])
    suit, cons = eva.suit, getattr(eva, "consumables", {}) or {}
    out = [{"name": "oxygen", "label": "Oxygen", "kind": "time",
            "usable": float(suit.get("o2_capacity_h", eva.eva["max_duration_h"])) * 3600.0 * keep, "per": 1.0}]
    if suit.get("metabolic_budget_kj"):
        out.append({"name": "effort", "label": "Effort", "kind": "energy",
                    "usable": float(suit["metabolic_budget_kj"]) * keep, "per": 1.0})
    if cons.get("feedwater_kg"):
        out.append({"name": "water", "label": "Cooling water", "kind": "energy",
                    "usable": float(cons["feedwater_kg"]) * keep, "per": 1.0 / LATENT_KJ_PER_KG})
    if cons.get("co2_capacity_kg"):
        out.append({"name": "co2", "label": "CO₂ scrubber", "kind": "energy",
                    "usable": float(cons["co2_capacity_kg"]) * keep, "per": RQ * KG_PER_L_CO2 / KJ_PER_L_O2})
    if cons.get("battery_draw_w") and suit.get("battery_capacity_wh"):
        out.append({"name": "battery", "label": "Battery", "kind": "draw",
                    "usable": float(suit["battery_capacity_wh"]) * 3.6 * keep, "per": float(cons["battery_draw_w"]) / 1000.0})
    return out


def time_left(eva, t_s: float, energy_kj: float, mean_power_kw: float | None = None) -> list[dict]:
    """Minutes each consumable has left before its reserve, at t_s seconds and energy_kj used. Energy-driven ones run
    at the mean metabolic power so far (or `mean_power_kw` before anything has been used). Sorted, first out first."""
    p_kw = energy_kj / t_s if t_s > 1.0 and energy_kj > 0 else (mean_power_kw or 0.0)
    rows = []
    for c in tracked(eva):
        if c["kind"] == "time":
            used, rate = t_s, 1.0
        elif c["kind"] == "energy":
            used, rate = energy_kj * c["per"], p_kw * c["per"]
        else:
            used, rate = t_s * c["per"], c["per"]
        left = c["usable"] - used
        rows.append({"name": c["name"], "label": c["label"], "used_pct": 100.0 * used / c["usable"],
                     "minutes_left": left / rate / 60.0 if rate > 0 else math.inf})
    return sorted(rows, key=lambda r: r["minutes_left"])


def plan_summary(eva, total_s: float, energy_kj: float) -> dict:
    """At the end of a plan: which consumable is closest to its reserve, and the share of each that is used."""
    rows = sorted(time_left(eva, total_s, energy_kj), key=lambda r: -r["used_pct"])
    return {"limiting_consumable": rows[0]["label"],
            "consumables_used": ", ".join(f"{r['label'].lower()} {r['used_pct']:.0f} %" for r in rows)}
