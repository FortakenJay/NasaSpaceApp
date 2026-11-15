# API

`marswalk serve` starts the API on http://127.0.0.1:8000 (`--host 0.0.0.0` to reach it from other devices).
Interactive docs: http://127.0.0.1:8000/docs.

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Version and where the service runs from |
| GET | `/api/site` | Site, stops, EVA limits, map tiles |
| POST | `/api/stops` · PATCH/DELETE `/api/stops/{id}` | Add, move, rename, remove your own stops (saved in SQLite) |
| POST | `/api/plan` | Plan a walk: route, timeline, budgets, limit checks, profile. Body: `{cost, order, stop_ids}` |
| GET, POST | `/api/plans`, GET `/api/plans/{id}` | Saved plans |
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

Terrain routes answer **409** until `marswalk fetch` has run. `/api/ask` returns the answer as text, the same text
for speech, the topics it understood, what "here" meant, GeoJSON to highlight, and `go_to` (`{id, label}` or null)
when the answer is a walking route to a stop. A route highlight has a `route` line (the way there) and, when the
walk home from that stop exists, a `back` line. The walk-home answer uses `home` instead.
