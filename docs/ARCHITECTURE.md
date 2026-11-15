# MarsWalk Traverse Planner: Architecture

Status: **v0.4** (2026-11-14). The terrain pipeline (M1-M4) is implemented and tested on synthetic terrain (42 tests):
fetch, layers, numba cost kernels, least-cost search, plan assembly, walk-back safe zone, overlays, and the app views for
them. It has **not been run on the real Gale data yet** (the build sandbox cannot reach the NASA hosts): run
`marswalk fetch` and compare `marswalk layers` with the M2 reference values below. Open: M5 space weather, M6 3-D table.

### Added in v0.9 (voice, suit display, audit)
- **`ask.py` + `POST /api/ask`:** keyword parser (topics + places, speech-to-text spellings) answering from the stored
  plan, the stack, the walk-home field and the space-weather status. Returns text, speech text, topics, "here",
  and GeoJSON highlights. Frontend: `voice.ts` (browser speech in and out), `AskPanel` on the map.
- **`eink.py` + `GET /api/eink.png|.bin`:** 800 x 480 1-bit navigation screen at any moment of a plan; `.bin` is
  48 000 bytes, MSB first, 1 = black. `SuitDisplayPanel` (step 5) previews and plays it; `firmware/suit_display` is
  the ESP32 + Waveshare 7.5" V2 sketch. Fonts: Barlow TTF in `eink_fonts/` (SIL OFL 1.1).
- **`audit.py` + `marswalk audit`:** 30 independent recomputations (constants vs sources, walking model, terrain,
  plan arithmetic, safety, radiation); `docs/wiki/Audit-results.md`. Fixes it drove: O2 energy equivalent 20.9 ->
  20.19 kJ/L; route distance/climb on the walking surface instead of the noisy 1 m DTM; RAD dose equivalent 0.67 ->
  0.64 mSv/day.
- `api_client.plain_error()` turns transport errors into one sentence; the optional flare feed gets 30 s.
- Docs: `docs/wiki/` (wiki pages), `docs/img/` (screenshots and suit-display frames), `docs/graph/` (graphify).

### Added in v0.8 (terrain over the whole map, and on the right spot)
- **Merged DEM base:** `[products.merged_dem]` = USGS `MSL_Gale_DEM_Mosaic_1m_v3` (GeoTIFF on S3, LZW, one row per
  strip, so a window read pulls whole 33 km rows: ~0.5 GB for the rover +- 3 km window). `fetch` writes
  `raw/dem_merged.tif` (optional: on failure the app plans on the HiRISE strip alone). `read_bbox(crs=...)` takes the
  CRS from the config instead of parsing the file's Mars WKT, and `read_merged_dem` refuses a window whose centre lands
  > 250 m from the bbox centre.
- **Planning footprint:** `layers/coverage.py`. The stack sits on the merged grid; the HiRISE DTM, resampled onto it and
  trimmed 6 px from its ragged edge, is the only area routes may use (`LayerStack.coarse` = the rest, always no-go).
  Overlays fade `coarse` cells; the off-limits view shows them grey. `agreement` compares the two DEMs inside the
  footprint (median |slope difference|, elevation offset, roughness ratio); if the merged DEM disagrees (> 4 deg) or is
  smoother (< 75 % of the HiRISE roughness, which would hide rocks), the stack falls back to the HiRISE strip alone and
  the map key says why.
- **Registration:** the HiRISE DTM's georeferencing is 45 m off the USGS/MSL base map (33.5 m S, 30.5 m E of it), which
  the Mars Trek `curiosity_hirise_mosaic`, the merged DEM and the Curiosity waypoint coordinates all share. Measured
  2026-11-14 by block cross-correlation: DTM vs merged DEM r = 0.9998 at (33 m N, 30 m W) vs 0.935 unshifted; HiRISE
  ortho vs Trek photo r = 0.93 at (34 m N, 31 m W) vs 0.47 unshifted. `products.dtm.basemap_offset_m` applies it at load
  time; with the merged DEM present, `coverage.register` re-measures the residual (4 m blocks, 512 m patch, +- 60 m,
  sub-metre parabola) and applies it when r >= 0.9. Before v0.8 every overlay, route and stop value was read 45 m off.
  H1 was picked on the DTM's own frame, so `stops.json` moves it by the same offset; S1-S5 are rover waypoints, already
  in the base-map frame. Config stops in an existing DB are re-synced from `stops.json` at start-up.
- **Memory:** overlays are subsampled before colouring (the 6.2 k x 6.2 k grid would otherwise need ~4.5 GB);
  a full stand-in run peaks at ~2.5 GB (stack ~19 s incl. registration, walk-back field ~13 s, overlays ~1.5 s).

### Added in v0.5 / v0.6
- **Space weather (M5):** `spaceweather/status.py` asks DONKI for WSA-ENLIL runs (their `impactList` names Mars), SEP events
  and flares, in parallel with a 20 s cap; requests go over IPv4 first and fall back to the system `curl`. Unreachable or
  partial feeds give CAUTION with `data_ok = false`. Results are cached for 30 minutes (memory + `data/cache/spaceweather.json`).
- **Saved stops:** `POST/PATCH/DELETE /api/stops` (repo: `add_stop`, `update_stop`, `delete_stop`). Added stops have kind
  `user` and codes U1, U2, ...; science stops answer 403. A spot off the terrain or off limits answers 422.
  `POST /api/plan` now reads its stops from the DB, so added stops plan like the science stops.
- **Terrain window = walk range:** `site.bbox` is the rover +- 2.3 km; the walk-back field stops at 1.1 x the walk limit.
  `fetch` re-reads everything when the bbox differs from the cached manifest. `serve` warms the stack and the field up
  in a background thread (about 20 s on the larger window).
- **Stale-install guard:** `/api/site` returns `api_version` and `project_root`; the app shows a banner when the service
  is an older copy, and the CLI warns when it runs from a different folder than the current one.
- **App:** four-step checklist (stops, plan, check, walk home); map view switch, key, and the 2 km walk-limit ring.

### What changed from the v0.3 design
- **One compiled search core** (`route/astar.py::_search`) does both goal-directed A* (per leg) and one-to-all Dijkstra.
  A reverse Dijkstra from the rover is the walk-back field: it feeds the per-waypoint margins, the margin profile, the
  safe-zone overlay and `GET /api/walkback`. Legs take ~0.1 s, the field ~4 s on the Gale window (7.3 M cells), cached.
- **Edge grades come from a stride-scale smoothed DTM** (`LayerStack.walk_elev_m`, Gaussian sigma 2 px). Raw 1 m
  cell-to-cell differences carry ~0.2 m stereo noise, which would read as +-10 deg steps and inflate energy everywhere.
- **Edge slope cap** `max_grade_deg` (20) in addition to the cell no-go mask. Diagonal steps may not cut a no-go corner.
- **Terrain routes answer 409** ("run marswalk fetch") instead of 501 when the DTM is not cached. `/api/layers` is `[]` then.
- **Stack is memoised in-process**, not written to `stack.npz` (it rebuilds in ~2.5 s). Overlay PNGs are cached on disk
  and capped at 2048 px on the long side.
- **Walking physics** (`cost/physics.py`): Santee-form metabolic power and a piecewise speed-vs-slope curve, as SEXTANT
  used. The coefficients were entered from the published forms and must be checked against the thesis before being cited.

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
| `layers/stack.py` | `LayerStack` (numba-ready arrays) ✅; `nogo_mask` ✅; `build_stack` (merged base + HiRISE footprint) | ✅ |
| `layers/coverage.py` | `shifted`, `register` (HiRISE onto the base-map frame), `hires_footprint`, `agreement`, `usable` | ✅ v0.8 |
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
| POST | `/api/plan` | compute `{cost?, order?, stop_ids? \| points?}` → `{route, summary, timeline, profile, violations, plan_id?}`; site-stop plans are persisted as `computed` | ✅ `useComputePlan` (409 until fetched) |
| GET | `/api/walkback?lat&lon&elapsed_h&cost` | `{reachable, safe, walkback_min, walkback_kj, margin_min, route}` for one point | ✅ (no hook yet) |
| GET | `/api/layers` | `[{name, key, url, bounds:[lon_min,lat_min,lon_max,lat_max], opacity}]` | ✅ `useLayers` (`[]` until fetched) |
| GET | `/api/layers/{name}.png` | overlay PNG (hillshade, slope5, roughness, ti, nogo, safezone`?elapsed_h=`) | ✅ |
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

## Verified facts this design relies on (2026-11-13, merged DEM and registration 2026-11-14)
- USGS merged Gale DEM v3: `https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars/MSL/MSL_Gale_DEM_Mosaic_1m_v3.tif`,
  3,868,256,546 bytes, 32980 x 57440 px float32, LZW, RowsPerStrip 1, IFD at the end of the file, PixelIsPoint,
  tie point (8127993.99, -244781.58) in eqc lon_0 = 0 on R = 3396190, nodata -32767. Range reads work (206).
  Decoded rows put it ~15 m below the HiRISE DTM in elevation (like Curiosity's elev_geoid).
- GDAL opens the DTM (PDS driver) and the THEMIS TI mosaic (ISIS3 driver) over `/vsicurl/`. S3 → pixel (4613, 4032)
  on the DTM; TI at S3 = 397, at H1 = 395 (matches the earlier manual reads).
- DTM grid: `+proj=eqc +lon_0=137.38 +R=3396190`, transform in `configs/sites/gale_boxwork.toml`.
- Mars Trek `curiosity_hirise_mosaic`: geographic tiling z0–16; the app requests e.g. z15/17258/57777 at
  (−4.804, 137.382), which is the correct index; tiles load as 256×256 PNGs.
- HiRISE server: ~15 s per small request and 503 above ~4 parallel when hit with tiny ranges; GDAL with 4 MB chunks is fast.
- DONKI via `api.nasa.gov/DONKI/SEP`: ≤60-day ranges per call; DEMO_KEY rate-limited.
