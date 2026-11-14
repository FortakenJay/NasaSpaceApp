"""JSON payloads the frontend consumes. The same shapes are served by the API and written by
`marswalk export` as a static fallback (frontend/public/sample-site.json) for backend-less demos.

TypeScript mirror: frontend/src/api.ts. Keep the two in sync.

Implemented: site_payload().
TODO(M4): plan_payload(plan) -> {route: GeoJSON FeatureCollection (one LineString per leg, lon/lat),
          summary: {...}, timeline: [...], violations: [...]}
TODO(M2): layer list -> [{name, url: "/api/layers/<name>.png", bounds: [lon_min, lat_min, lon_max, lat_max], opacity}]
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
                 "basemap": site.products.get("basemap_tiles", {})},
        "stops": stops,
    }


def write_json(payload: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return out
