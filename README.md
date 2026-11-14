# MarsWalk Traverse Planner

A route planner for astronauts walking on Mars in spacesuits. It plans a safe EVA from a parked
pressurized rover through science stops and back, using NASA data: HiRISE 1 m topography and
imagery, terrain roughness (as a rock-hazard proxy), THEMIS thermal inertia, and space weather (MSL RAD + DONKI).

**Baseline site:** Gale crater / Mount Sharp boxwork, at five stops from Curiosity's 2025 campaign
(Altadena, first ridge stop, Monte Grande hollow + Nevado Sajama ridge, final-phase hollow, upper contact).

> Status: **skeleton v0.3.** React app, central API layer, SQLite (saved plans + field log), 33 Python tests,
> lint, and React Doctor 100/100. Pipeline stages answer with the milestone that builds them.
> See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the shared [design doc](https://claude.ai/artifact/XrEKBZR1x5SKkNh2LXSJqc).

## Stack
| Layer | Tech |
|---|---|
| Raster access | **rasterio / GDAL**: PDS IMG, ISIS3 cubes and JP2 read remotely via `/vsicurl/` windows; **pyproj** for Mars CRSs |
| Analysis | numpy, scipy, scikit-image |
| Route search | **numba**-compiled A* with directional edge-cost kernels (M3) |
| Database | **SQLite + SQLAlchemy 2**, reached only through `marswalk.db.repo` |
| Backend | **FastAPI** + uvicorn: the only server layer; all data goes through `/api/*` routes |
| Frontend | **React 19 + TypeScript + Vite**, **TanStack Query** on a central API client, **OpenLayers** with a Mars 2000 projection and Mars Trek tiles |
| 3-D planning table | **CesiumJS** with a Mars ellipsoid and the DTM as terrain (M6, spec in `frontend/src/views/planningTable.ts`) |

## Data-access rules (enforced)
1. **Components never fetch.** They use the hooks exported from `frontend/src/api` (`useSite`, `usePlans`,
   `useObservations`, `useAddObservation`, …). Only `src/api/client.ts` calls `fetch`.
2. **The API layer is the only path to data.** Every hook maps to one FastAPI route in `src/marswalk/api/app.py`.
3. **Only the repository touches the database.** Routes call `marswalk.db.repo`; nothing else imports SQLAlchemy.

Guards: ESLint (`no-restricted-globals` for `fetch`/`XMLHttpRequest`, `no-restricted-imports` for API internals)
and `tests/test_architecture.py` both fail on a violation.

## Quick start
Requires Python ≥ 3.11 and Node ≥ 20.19.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pytest
```

```bash
.venv/Scripts/python -m marswalk serve              # API on http://127.0.0.1:8000
```

```bash
npm --prefix frontend install
npm --prefix frontend run dev                       # app on http://127.0.0.1:5173 (proxies /api)
```

```bash
npm --prefix frontend run lint                      # ESLint incl. the API-boundary rules
npm --prefix frontend run doctor                    # React Doctor
```

The SQLite file is `data/marswalk.db` (git-ignored). `serve` creates it and seeds the site and stops from the config
files on first start; delete it to reset.

Without the API, the app falls back to `frontend/public/sample-site.json` (`marswalk export` regenerates it),
so a static build (`npm --prefix frontend run build`) still shows the site and stops.

Pipeline commands, in milestone order:

```bash
.venv/Scripts/python -m marswalk info      # site, products, stops, distances, EVA limits   [works]
.venv/Scripts/python -m marswalk fetch     # M1: cache data windows as GeoTIFFs in data/raw/
.venv/Scripts/python -m marswalk layers    # M2: slope, roughness, thermal inertia, no-go mask
.venv/Scripts/python -m marswalk plan --cost metabolic|weighted --order fixed|optimize   # M3/M4
.venv/Scripts/python -m marswalk status    # M5: space-weather GO / CAUTION / NO-GO (set NASA_API_KEY)
```

## Layout
```
configs/sites/gale_boxwork.toml   products, URLs, grid, bbox (one file per site)
configs/eva/artemis_default.toml  EVA limits, hazard limits, cost-model parameters
data/sites/gale_boxwork/stops.json  H1 + S1–S5 (committed)
src/marswalk/                     config, geo, sources, layers, cost, route, constraints, spaceweather, export, db, api, cli
src/marswalk/db/                  SQLAlchemy models, engine, repo (the only DB access)
frontend/src/api/                 central API layer: client (fetch), endpoints, TanStack Query hooks, types
frontend/src/components/          React panels (plan, stops, field log, layers, space weather)
frontend/src/map/                 MarsMap (OpenLayers in React), Mars projection + Trek tiles
docs/ARCHITECTURE.md              design, API, data contracts, milestones
tests/                            pytest (geo, config, pure logic, API + DB, architecture boundaries)
```

## Defaults (editable)
- **EVA:** 8 h max, 2 crew, ≥30% walkback reserve, ≤2 km from rover, 30 min per stop, ×1.3 time margin.
- **No-go:** 5 m slope > 25°, 1 m slope > 35°, roughness > 0.8 m.
- **Cost model:** `metabolic` (SEXTANT-style, Mars gravity) or `weighted` (hazard score), switchable in the app and the CLI.
- **Stop order:** fixed science order. `optimize` tries all orders.

## Data sources
- HiRISE DTM `DTEEC_019698_1750_019988_1750_U01` and orthoimages: [HiRISE PDS](https://hirise-pds.lpl.arizona.edu/PDS/DTM/ESP/ORB_019600_019699/ESP_019698_1750_ESP_019988_1750/)
- Basemap: [NASA/JPL Mars Trek](https://trek.nasa.gov/mars/) `curiosity_hirise_mosaic` WMTS
- THEMIS quantitative thermal inertia mosaic: [USGS Astrogeology](https://astrogeology.usgs.gov/search/map/themis_thermal_inertia_mosaic_quantitative_30s120e_100mpp)
- Curiosity waypoints: [MSL waypoints](https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json)
- Radiation: Hassler et al. 2014 (RAD surface dose); space weather: [NASA DONKI](https://api.nasa.gov/)
