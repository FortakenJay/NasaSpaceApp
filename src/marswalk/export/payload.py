"""JSON payloads the frontend consumes. The same shapes are served by the API and written by
`marswalk export` as a static fallback (frontend/public/sample-site.json) for backend-less demos.

TypeScript mirror: frontend/src/api.ts. Keep the two in sync.

Implemented: site_payload().
Also: plan_payload(plan, stack) -> {route: GeoJSON FeatureCollection (one LineString per leg, lon/lat),
          summary, timeline, profile, violations}. Layer lists come from layers.render.layer_list().
"""
from __future__ import annotations

import json
from pathlib import Path

from marswalk.config import SiteConfig


def site_payload(site: SiteConfig, stops: list[dict] | None = None) -> dict:
    """Site metadata from config + stops. The API passes stops from the DB (db.repo.list_stops);
    the static export falls back to the config's stops file."""
    if stops is None:
        stops = [{"id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon, "kind": s.kind,
                  "science": s.science, "work_time_min": s.work_time_min, "dtm_z_m": s.dtm_z_m}
                 for s in (site.start, *site.stops)]
    return {
        "site": {"id": site.id, "name": site.name, "bbox": site.bbox,
                 "radius_m": site.body["radius_m"],
                 "basemap": site.products.get("basemap_tiles", {}),
                 "context": site.products.get("context_tiles", [])},
        "stops": stops,
    }


def plan_payload(plan, stack) -> dict:
    """EVAPlan -> the JSON the app draws: route (GeoJSON, one LineString per leg, lon/lat), summary,
    timeline, profile and violations."""
    from marswalk.route.plan import KJ_PER_KG_O2
    feats = []
    for leg in plan.legs:
        rows = [rc[0] for rc in leg.path.cells]
        cols = [rc[1] for rc in leg.path.cells]
        lats, lons = stack.grid.rc_to_latlon_many(rows, cols)
        feats.append({"type": "Feature",
                      "properties": {"from": leg.from_id, "to": leg.to_id, "distance_m": round(leg.path.distance_m, 1),
                                     "walk_min": round(leg.path.time_s / 60.0, 1), "energy_kj": round(leg.path.energy_kj, 1),
                                     "climb_m": round(leg.path.climb_m, 1), "descent_m": round(leg.path.descent_m, 1)},
                      "geometry": {"type": "LineString",
                                   "coordinates": [[round(float(lo), 7), round(float(la), 7)] for la, lo in zip(lats, lons)]}})
    b = plan.budgets
    margins = [m for m in plan.profile.get("margin_min", []) if m is not None]
    slopes = [x for x in plan.profile.get("slope_deg", []) if x is not None]
    summary = {
        "distance_km": round(plan.total_distance_m / 1000.0, 2),
        "duration_h": round(plan.total_time_s / 3600.0, 2),
        "walking_h": round(plan.walking_time_s / 3600.0, 2),
        "energy_kj": round(plan.total_energy_kj),
        "o2_kg_est": round(plan.total_energy_kj / KJ_PER_KG_O2, 2),
        "time_budget_used_pct": round(100.0 * plan.total_time_s / b["time_s"]) if b.get("time_s") else 0,
        "energy_budget_used_pct": round(100.0 * plan.total_energy_kj / b["energy_kj"]) if b.get("energy_kj") else 0,
        "min_walkback_margin_min": round(min(margins), 1) if margins else 0,
        "max_slope_deg": round(max(slopes), 1) if slopes else 0,          # steepest TERRAIN crossed (5 m slope)
        "max_grade_deg": round(max((leg.path.max_grade_deg for leg in plan.legs), default=0.0), 1),   # steepest step WALKED
        "cost_model": plan.cost_model,
        "order": " > ".join(plan.order),
    }
    timeline = [{"id": w.id, "name": w.name, "kind": w.kind, "lat": w.lat, "lon": w.lon,
                 "arrive_min": round(w.arrive_s / 60.0, 1), "depart_min": round(w.depart_s / 60.0, 1),
                 "walkback_min": round(w.walkback_time_s / 60.0, 1), "walkback_kj": round(w.walkback_energy_kj, 1),
                 "energy_used_kj": round(w.energy_used_kj, 1)} for w in plan.waypoints]
    return {"route": {"type": "FeatureCollection", "features": feats}, "summary": summary, "timeline": timeline,
            "profile": plan.profile,
            "violations": [{"rule": v.rule, "severity": v.severity, "detail": v.detail, "where": v.where}
                           for v in plan.violations]}


def write_json(payload: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return out
