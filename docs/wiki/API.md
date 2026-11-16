# API

`marswalk serve` starts the API on http://127.0.0.1:8000 (`--host 0.0.0.0` to reach it from other devices).
Interactive docs: http://127.0.0.1:8000/docs.

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Version and where the service runs from |
| GET | `/api/site` | Site, stops, EVA limits, map tiles |
| POST | `/api/stops` · PATCH/DELETE `/api/stops/{id}` | Add, move, rename, remove your own stops (saved in SQLite; on a hosted function that file is `/tmp/marswalk/marswalk.db` and does not last) |
| POST | `/api/plan` | Plan a walk: route, timeline, budgets, limit checks, profile. Body: `{cost, order, stop_ids}` |
| GET, POST | `/api/plans`, GET `/api/plans/{id}` | Saved plans. An empty Gale database is given the stored route in `configs/preview/gale_boxwork_plan.json`. The map draws the newest saved route until a plan is computed in this session |
| GET, POST | `/api/stops/{id}/observations` | Field notes logged at a stop |
| GET | `/api/walkback?lat=&lon=` | Walk home from any point |
| GET | `/api/layers`, `/api/layers/{name}.png` | Overlays: hillshade, slope5, roughness, ti, nogo, safezone (`?elapsed_h=`), radio (no line of sight to the rover), shelter (walk home longer than the solar-storm warning), uncertain (off-limits certainty over the walk area; its own bounds) |
| GET | `/api/status` | Space-weather go/no-go and radiation dose |
| GET | `/api/sources` · POST `/api/sources/refresh` | State of every NASA feed; ask again now |
| POST | `/api/ask` | A question in plain words. Body: `{question, plan_id, selected_stop_id, elapsed_h}`, plus `here_lat`, `here_lon` and `visited` for a live position |
| GET | `/api/eink.png`, `/api/eink.bin` | The suit display at `?elapsed_h=` (latest plan unless `plan_id`). Add `lat`, `lon`, `walked_m`, `energy_kj` and `visited` (comma-separated stop ids) to draw it from a live position |
| GET | `/api/sim/terrain?step=3` | For the [simulator](Simulation.md): local frame, physics constants, and the versioned URLs of the two grids below |
| GET | `/api/sim/terrain.bin?step=3&v=` | The 3 m mesh (gzip): heights uint16 cm, then off-limits bits |
| GET | `/api/sim/texture.png?kind=photo\|hazard` | The simulator's ground photo or off-limits overlay, on the same grid |
| GET | `/api/sim/fine.bin?v=` | The 1 m grid (gzip): walk-surface heights, terrain heights, roughness, then sand, off-limits and radio-shadow bits |
| GET | `/api/sim/sun?start_utc=&hours=` | The Sun's azimuth and elevation through the walk, every 2 min (Mars24). Default start: the next `start_lmst_h` local time |
| GET | `/api/bases` | Every saved Base, the one in focus, and the creation job if there is one |
| POST | `/api/bases` | Make a Base. Body: `{lat, lon, name?, product_id?}`. **202** and the job; 422 where there is no 1 m HiRISE terrain; 507 if the disk is too full; 409 while another Base is being made |
| GET | `/api/bases/job` | Progress of the Base being made: steps, percent, error |
| POST | `/api/bases/{id}/cancel` · `/api/bases/{id}/resume` | Stop a download (its files are removed) or carry on with an interrupted one |
| POST | `/api/bases/focus` | Plan at another Base. Body: `{id}`. Every other route then answers for that Base |
| DELETE | `/api/bases/{id}` | Delete a Base, its files and its stops and plans (403 for Gale, 409 while downloading) |
| GET | `/api/catalog/footprints` | GeoJSON of every HiRISE DTM, with `supported` and the reason when not (gzip) |
| GET | `/api/catalog/lookup?lat=&lon=` | The DTMs covering a point, the window, the download size and the free disk space |

Overlay and simulator URLs carry `b=<base id>&v=<data stamp>`, so a browser never shows one Base's image at another.
Terrain routes answer **409** until `marswalk fetch` has run. `/api/ask` returns the answer as text, the same text
for speech, the topics it understood, what "here" meant, GeoJSON to highlight, and `go_to` (`{id, label}` or null)
when the answer is a walking route to a stop. A route highlight has a `route` line (the way there) and, when the
walk home from that stop exists, a `back` line. The walk-home answer uses `home` instead.
