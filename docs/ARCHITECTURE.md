# MarsWalk Traverse Planner: Architecture

Status: **skeleton v0.3** (2026-11-13). Stack: GDAL/rasterio + numba + SQLite/SQLAlchemy + FastAPI + React/TypeScript/
TanStack Query/OpenLayers. Interfaces, configs, data contracts, the DB, the API and the React app are in place and verified
end to end. React Doctor scores 100/100. Planning algorithms are stubs that raise `NotImplementedError("Mx: …")`,
with the spec in each module docstring.

## Goal
Plan a safe walking route for a suited 2-person crew from a parked pressurized rover (H1) through
5 science stops in Curiosity's 2025 boxwork campaign on Mount Sharp (Gale crater), and back. The
planner fuses 1 m topography, optical imagery, rock/roughness hazards, thermal inertia, and space
weather. It reports time, energy, walkback margins and EVA-limit violations, and shows them in a web app.
The design is site-agnostic: a new site = a new `configs/sites/*.toml` plus a stops file. Data windows
come from the site bbox, so no code changes are needed.

## Stack and why
| Layer | Choice | Why |
|---|---|---|
| Raster I/O | **rasterio (GDAL 3.12)** + **pyproj** | Reads PDS IMG, ISIS3 cubes and JP2 natively, remotely via `/vsicurl/` windows; handles Mars CRSs and reprojection. Replaces the hand-written readers from v0.1 |
| Analysis | numpy, scipy, scikit-image | Standard planetary raster toolkit |
| Route search | **numba** | A* over ~11 M cells (Gale strip at 1 m) needs compiled code; Python callbacks per edge would take minutes per leg |
| Database | **SQLite + SQLAlchemy 2** | Saved plans and the field log; zero-setup file DB; models are portable to Postgres/PostGIS later |
| Backend | **FastAPI** + uvicorn | The single server layer: every read/write goes through a route; typed request models; 501 + milestone for stages not built |
| Frontend | **React 19 + TypeScript + Vite**, **TanStack Query** | One central API layer (`src/api/`) with typed endpoints and query/mutation hooks; components only consume hooks |
| Map | **OpenLayers 10** | Supports custom projections, so the app registers a **Mars 2000 geographic projection** (correct metres per degree for the scale bar) and Mars Trek's **geographic** tile grid. Leaflet/MapLibre mostly assume Earth or Web Mercator |
| 3-D | **CesiumJS** (M6) | Mars ellipsoid, geographic tiling scheme, DTM as terrain for the habitat planning table |

## Pipeline

```
configs/sites/gale_boxwork.toml + data/sites/gale_boxwork/stops.json        configs/eva/artemis_default.toml
        │                                                                              │
   [M1] sources.fetch ── GDAL /vsicurl/ windows from site.bbox ──► data/raw/<site>/*.tif │
        ▼                                                                              │
   [M2] layers ── LayerStack on the 1 m DTM grid (slope 1/5 m, roughness, TI, sand, no-go) ◄── hazard limits
        ▼                                                                              │
   [M3] cost kernels (numba): metabolic | weighted  ──►  route.astar (numba, 8-connected) ◄── cost.model
   [M4] route.sequence (fixed | optimize) → route.plan (legs, timeline, walkback) → constraints.eva
   [M5] spaceweather.status (RAD baseline + DONKI → GO / CAUTION / NO-GO)
        ▼
   api.app (FastAPI)  ──/api/*──►  frontend (React + TanStack Query + OpenLayers)   [M6: CesiumJS planning table]
        ▲
   db.repo ── SQLAlchemy ──► data/marswalk.db (sites, stops, plans, observations)
```

## Data access layers (enforced)

```
React components ──hooks──► src/api/queries.ts ──► src/api/endpoints.ts ──► src/api/client.ts (fetch)
                                                                                  │ HTTP /api/*
                                                     FastAPI routes (api/app.py) ◄┘
                                                                │ function calls
                                                     marswalk.db.repo ──► SQLAlchemy ──► SQLite
```

1. **Components never fetch.** They import hooks, types and `describeError` from `src/api` (index.ts) only.
2. **`src/api/client.ts` is the only `fetch`.** It turns 501 answers into `ApiError(notBuilt, milestone)` and
   network failures or proxy gateway errors (502/504) into `OfflineError`. `getSite()` uses that to fall back to the
   static `sample-site.json`.
3. **Routes are the only server entry point.** Each hook maps to exactly one route.
4. **`marswalk.db.repo` is the only DB access.** It returns plain dicts (no ORM objects leak) and raises `NotFound` (→ 404).
5. **Guards:** ESLint `no-restricted-globals` (fetch, XMLHttpRequest) and `no-restricted-imports` (API internals,
   axios) outside `src/api/`; `tests/test_architecture.py` fails if anything outside `marswalk/db` imports SQLAlchemy,
   if a route runs queries itself, or if frontend code outside `src/api/` calls the network.

## Modules

| Module | Responsibility | State |
|---|---|---|
| `config.py` | Load site/EVA TOML and stops JSON into dataclasses | ✅ |
| `geo.py` | `GeoGrid` (affine transform + pyproj CRS: lat/lon ↔ pixel, windows, bounds), `Raster`, haversine | ✅ tested against GDAL's own pixel for S3 and H1 |
| `sources/raster.py` | GDAL env, `bbox_window` ✅, `download` ✅; `read_bbox`, `write_geotiff` | M1 |
| `sources/fetch.py` | `marswalk fetch`: DTM, ortho, TI windows → GeoTIFF cache + manifest | M1 |
| `layers/terrain.py` | slope (1 m, 5 m), roughness, steep fraction, hillshade | M2 |
| `layers/thermal.py` | TI → DTM grid via `rasterio.warp.reproject`, sand flag | M2 |
| `layers/stack.py` | `LayerStack` (numba-ready arrays) ✅; `nogo_mask` ✅; `build_stack` | M2 |
| `cost/base.py` | `CostModel` contract: `params` array + njit `kernel` + `min_rate`; factory ✅ | ✅ interface |
| `cost/metabolic.py`, `cost/weighted.py` | params arrays ✅; edge kernels | M3 |
| `route/astar.py` | numba A*, crop window, start/goal snapping | M3 |
| `route/sequence.py` | Fixed order / brute-force reorder ✅ | ✅ |
| `route/plan.py` | `EVAPlan`, legs, timeline, walkback margins | M4 |
| `constraints/eva.py` | `Violation`; duration ✅ and distance ✅ checks; reserve check | M4 |
| `spaceweather/status.py` | dose estimate ✅, DONKI range split ✅; fetch + go/no-go | M5 |
| `export/payload.py` | `site_payload(site, stops)` ✅ (stops from the DB in the API; from config for the static export) | ✅; plan/layers M2/M4 |
| `db/models.py` | `Site`, `Stop`, `Plan`, `Observation` (SQLAlchemy 2, typed) | ✅ |
| `db/engine.py` | Engine + session factory; `data/marswalk.db`, or in-memory for tests | ✅ |
| `db/repo.py` | Seed from config (idempotent), stops, plans, observations; UTC-labelled timestamps | ✅ tested |
| `api/app.py` | FastAPI app; DB session dependency; stages not built answer 501 + milestone | ✅ |
| `cli.py` | `info`, `serve`, `export` ✅; other stages report their milestone | ✅ |
| `frontend/src/api/` | `client.ts` (only fetch), `endpoints.ts`, `queries.ts` (TanStack Query hooks), `types.ts`, `errors.ts`, `index.ts` | ✅ |
| `frontend/src/App.tsx`, `components/*` | Layout state; Plan (compute + save + saved list), StopList, StopLog (field log), LayerToggles, SpaceWeather | ✅ verified end to end |
| `frontend/src/map/` | `MarsMap.tsx` (OpenLayers in React: create once, effects sync props, full cleanup), `mars.ts` (projection + Trek grid), `layers.ts` | ✅ |
| `frontend/src/views/planningTable.ts` | CesiumJS 3-D planning table | M6 (spec only) |

## API
| Method | Path | Returns | State |
|---|---|---|---|
| GET | `/api/health` | `{ok, version, site}` | ✅ |
| GET | `/api/site` | site + stops (`SitePayload`; stops from the DB) | ✅ `useSite` |
| GET | `/api/stops/{id}/observations` | field log, newest first | ✅ `useObservations` |
| POST | `/api/stops/{id}/observations` | add `{note, author?, sample_id?}` → 201 | ✅ `useAddObservation` |
| GET | `/api/plans` | saved plans, newest first | ✅ `usePlans` |
| POST | `/api/plans` | save `{name?, cost, order, stop_ids}` → 201 (`status: requested`) | ✅ `useSavePlan` |
| GET | `/api/plans/{id}` | one saved plan | ✅ |
| POST | `/api/plan` | compute `{cost?, order?, stop_ids?}` → `{route, summary, violations}`, persisted as a `computed` plan | 501 M4 · `useComputePlan` |
| GET | `/api/layers` | `[{name, url, bounds:[lon_min,lat_min,lon_max,lat_max], opacity}]` | `[]` until M2 · `useLayers` |
| GET | `/api/layers/{name}.png` | overlay PNG (hillshade, slope5, roughness, ti, nogo) | 501 M2 |
| GET | `/api/status` | `{level, reason, …}` | 501 M5 · `useSpaceWeather` |

Not-yet-built stages answer `501 {"milestone": "Mx", "detail": …}`; unknown stops/plans answer 404; invalid bodies 422.
The app shows these messages instead of failing. TypeScript mirrors live in `frontend/src/api/types.ts`; keep them in
sync with `export/payload.py` and `db/repo.py`.

## Quality checks
- `pytest`: 33 tests (geo, config, pure logic, API + DB on an in-memory SQLite per test, architecture boundaries).
- `npm --prefix frontend run lint`: ESLint (typescript-eslint, react-hooks, API-boundary rules).
- `npm --prefix frontend run doctor`: React Doctor, **100/100** on 2026-11-13. It first found 3 issues, all fixed: the map
  click listener and OL map weren't disposed on unmount, a constant was exported from a component file, and the
  compute-plan mutation didn't invalidate the saved-plans cache.

## Key design decisions
- **Directional edge costs, compiled.** Uphill and downhill differ, so A* prices edges. Each cost model exposes a numba
  `kernel(params, dz, run, slope5, rough, sand) → (cost, time_s, energy_kj)` that the compiled A* calls. Both models
  fill time and energy the same way, so their routes compare directly (`--cost` / the app's selector).
- **One grid.** Every layer lives on the 1 m DTM window. TI (100 m, different CRS) is reprojected with GDAL.
- **Hard vs soft hazards.** `nogo_mask` (5 m slope > 25°, 1 m slope > 35°, roughness > 0.8 m, no data) is never entered.
- **Windowed remote reads.** GDAL reads only the bbox window (the Gale DTM strip, 1466 × 7426 px, in about 8 s with
  4 MB curl chunks; one TI tile instead of 2.5 GB). Results are cached as GeoTIFFs; raw data is git-ignored.
- **Ortho grid quirk.** HiRISE ortho JP2s carry a GeoJP2 header 1.5 px off the DTM, while their PDS labels match it.
  Products marked `same_grid_as = "dtm"` use the DTM grid.
- **Offline fallback.** The app loads `/api/site`, or `sample-site.json` when the API is down (a network error, or
  502/504 from a proxy), so a static build still demos. Planning, saving and the field log are disabled offline.
- **Config vs DB.** Products, projections and EVA limits stay in versioned TOML. Stops are seeded from the stops file
  into the DB once (idempotent) and served from the DB. Plans and observations live only in the DB.
- **Space weather is a panel, not a map layer.** It is one value for the whole site; DONKI is Earth/L1-centric until MAVEN SEP is added.

## Data contracts
- **stops.json:** `{start:{id,name,lat,lon,dtm_z_m,kind,notes}, stops:[{id,name,sol,lat,lon,dtm_z_m,science,work_time_min,notes?}]}`
  (Mars 2000 planetocentric, east-positive).
- **SitePayload:** `{site:{id,name,bbox,radius_m,basemap:{url_template,max_zoom}}, stops:[{id,name,lat,lon,kind,science,work_time_min,dtm_z_m}]}`.
- **SavedPlan:** `{id, site_id, created_at (ISO, UTC), name, cost_model, stop_order, stop_ids, status, result|null}`.
- **Observation:** `{id, stop_id, created_at (ISO, UTC), author, note, sample_id|null}`.
- **DB tables:** `sites(id, name)`, `stops(pk, site_id, code, seq, kind, name, lat, lon, dtm_z_m, science, work_time_min)`,
  `plans(id uuid, site_id, created_at, name, cost_model, stop_order, stop_codes JSON, status, result JSON)`,
  `observations(id, site_id, stop_code, created_at, author, note, sample_id)`.

## Milestones
| | Deliverable | Done when |
|---|---|---|
| M1 | `marswalk fetch` | dtm.tif, ortho_1m.tif, ti.tif + manifest in `data/raw/gale_boxwork/`; re-run is a no-op |
| M2 | `marswalk layers` + `/api/layers` | Values at stops match the plan (S2: 5 m slope mean ≈ 12.6°, roughness ≈ 0.31 m, TI ≈ 396); overlays toggle in the app |
| M3 | numba kernels + A* | H1→S1 routed with both models in < 2 s after warm-up; no no-go cells entered |
| M4 | `marswalk plan` + `POST /api/plan` | Full loop with timeline, walkback margins, violations; route drawn in the app |
| M5 | `marswalk status` + `/api/status` | GO/CAUTION/NO-GO in the panel from DONKI plus the RAD dose |
| M6 | CesiumJS planning table | 3-D Mars terrain from the DTM, route draped, EVA timeline playback |
| Later | Helmet HUD, deferred layers and features | See the plan's "Later" section |

## Verified facts this design relies on (2026-11-13)
- GDAL opens the DTM (PDS driver) and the THEMIS TI mosaic (ISIS3 driver) over `/vsicurl/`. S3 → pixel (4613, 4032)
  on the DTM; TI at S3 = 397, at H1 = 395 (matches the earlier manual reads).
- DTM grid: `+proj=eqc +lon_0=137.38 +R=3396190`, transform in `configs/sites/gale_boxwork.toml`.
- Mars Trek `curiosity_hirise_mosaic`: geographic tiling z0–16; the app requests e.g. z15/17258/57777 at
  (−4.804, 137.382), which is the correct index; tiles load as 256×256 PNGs.
- HiRISE server: ~15 s per small request and 503 above ~4 parallel when hit with tiny ranges; GDAL with 4 MB chunks is fast.
- DONKI via `api.nasa.gov/DONKI/SEP`: ≤60-day ranges per call; DEMO_KEY rate-limited.
