# MarsWalk Traverse Planner

A route planner for astronauts walking on Mars in spacesuits. It plans a safe EVA from a parked
pressurized rover through science stops and back, using NASA data: HiRISE 1 m topography and
imagery, terrain roughness (as a rock-hazard proxy), THEMIS thermal inertia, and space weather (MSL RAD + DONKI).

**Baseline site:** Gale crater / Mount Sharp boxwork, at five stops from Curiosity's 2025 campaign
(Altadena, first ridge stop, Monte Grande hollow + Nevado Sajama ridge, final-phase hollow, upper contact).

> Status: **v0.8 (2026-11-14).** Runs end to end on the real Gale data: fetch, layers, least-cost routing with two
> cost models, EVA plan with timeline and walk-back margins, the walk-back safe zone, stops added on the map and
> saved in the database, and the space-weather go/no-go (NASA DONKI: CME arrivals predicted at Mars, particle
> events, flares, plus the RAD dose). 63 Python tests.
>
> **v0.8 terrain:** the whole map now has terrain. The USGS merged 1 m Gale DEM (Parker & Calef) is the base surface
> over the rover +- 3 km; routes are still only planned where the HiRISE 1 m stereo DTM exists (the rest is drawn faded,
> grey on the off-limits view). Fixing this exposed a **45 m georeferencing offset**: the HiRISE DTM's own coordinates
> sit 33.5 m south and 30.5 m east of the USGS/MSL base map that the Mars Trek photo, the merged DEM and Curiosity's
> waypoints share. The DTM is now moved onto that frame (`basemap_offset_m`, re-measured at every build), so the
> overlays line up with the photo and the stops sit on the terrain they name. On the registered DTM, S2 reads
> 10.5 deg (5 m slope) and 0.28 m roughness, and the baseline plan is 1.72 km / 3.52 h with every stop reachable.
> Run `marswalk fetch` once more after pulling this version (about 0.5 GB, one time). Open: the 3-D planning table (M6).
> See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the shared [design doc](https://claude.ai/artifact/XrEKBZR1x5SKkNh2LXSJqc).
>
> **Moved or copied the project folder?** Re-run `python -m pip install -e ".[dev]"` in the new folder. Otherwise the
> commands keep running the code (and looking for the data) in the old folder. The CLI and the app both warn about this.

## Stack
| Layer | Tech |
|---|---|
| Raster access | **rasterio / GDAL**: PDS IMG, ISIS3 cubes and JP2 read remotely via `/vsicurl/` windows; **pyproj** for Mars CRSs |
| Analysis | numpy, scipy, scikit-image |
| Route search | **numba**-compiled A* / Dijkstra with directional edge-cost kernels (`route/astar.py`) |
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

Pipeline commands:

```bash
.venv/Scripts/python -m marswalk info      # site, products, stops, distances, EVA limits
.venv/Scripts/python -m marswalk fetch     # cache the DTM, thermal-inertia and ortho windows in data/raw/ (run once, ~1 min)
.venv/Scripts/python -m marswalk layers    # slope, roughness, TI, no-go: prints values at the stops, writes overlay PNGs
.venv/Scripts/python -m marswalk plan --cost metabolic|weighted --order fixed|optimize [--out out/plan.json]
.venv/Scripts/python -m marswalk status    # space-weather GO / CAUTION / NO-GO from DONKI (set NASA_API_KEY; DEMO_KEY is rate-limited)
```

After `fetch`, start `serve` and the app: **Plan route** draws the route with its profile, timeline and violations;
the **Walk-back safe zone** slider shows where the crew can still walk home from at any elapsed EVA time.
First check after fetching real data: `marswalk layers` should print about 12.6 deg (5 m slope) and 0.31 m roughness at S2.

## Using the app
The right-hand sheet is a four-step checklist; the map follows along.
1. **Choose where to go.** One list of stops with tick boxes. "Add a stop on the map" saves a new stop where you
   click (codes U1, U2, ...); added stops can be dragged, renamed and removed, and they survive a reload.
2. **Plan the walk.** One button. "Options" holds the cost model and the stop order.
3. **Check the plan.** A verdict against the EVA limits, four numbers (distance, time outside, energy, spare time),
   the height profile, and a stop-by-stop timeline with the latest "leave by" time for each stop.
4. **Check the walk home.** Drag the time slider or press "Play the last hour" to watch the safe zone shrink; the
   sheet names the stops the crew could no longer get home from.

"Show" on the map switches between the photo and one terrain layer at a time (relief, slope, roughness, sand or rock,
off limits). The space-weather line at the top opens for details.

## NASA web APIs: one client, few requests
Every request to an external API goes through `src/marswalk/sources/api_client.py`. It caches each feed for 30 minutes
(memory and `data/cache/api/`), reuses the last good copy when NASA does not answer, lets slow feeds finish in the
background, backs off after failures, tracks the hourly request budget, and never writes the key to disk or logs.
The app shows all of it under **NASA data connections**; `GET /api/sources` is the same information as JSON.

Put your key in `.env` (git-ignored; see `.env.example`): `NASA_API_KEY=...`. Without it the shared `DEMO_KEY` is used.

## Walk-back safe zone
One reverse Dijkstra from the rover gives the cost, time and energy of walking home from every cell. A cell is
inside the safe zone at elapsed time t when (walk-back time x margin factor) fits in what is left of the usable
budget (capacity less the 30% reserve). This is the Apollo walk-back limit, recomputed for any t and shaped by the
terrain instead of drawn as a circle. `GET /api/walkback?lat=&lon=&elapsed_h=` answers the same question for one point.

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
  Walking physics are in `cost/physics.py`; **check its coefficients against the SEXTANT thesis before citing them.**
- **Edge limit:** no step steeper than 20 deg (`cost.metabolic.max_grade_deg`); grades come from a stride-scale smoothed DTM.
- **Stop order:** fixed science order. `optimize` tries all orders.

## Data sources
- HiRISE DTM `DTEEC_019698_1750_019988_1750_U01` and orthoimages: [HiRISE PDS](https://hirise-pds.lpl.arizona.edu/PDS/DTM/ESP/ORB_019600_019699/ESP_019698_1750_ESP_019988_1750/)
- Basemap: [NASA/JPL Mars Trek](https://trek.nasa.gov/mars/) `curiosity_hirise_mosaic` WMTS
- THEMIS quantitative thermal inertia mosaic: [USGS Astrogeology](https://astrogeology.usgs.gov/search/map/themis_thermal_inertia_mosaic_quantitative_30s120e_100mpp)
- Curiosity waypoints: [MSL waypoints](https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json)
- Radiation: Hassler et al. 2014 (RAD surface dose); space weather: [NASA DONKI](https://api.nasa.gov/)
