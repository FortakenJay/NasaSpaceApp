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
| GET | `/api/layers`, `/api/layers/{name}.png` | Terrain overlays: hillshade, slope5, roughness, ti, nogo, safezone (`?elapsed_h=`) |
| GET | `/api/status` | Space-weather go/no-go and radiation dose |
| GET | `/api/sources` · POST `/api/sources/refresh` | State of every NASA feed; ask again now |
| POST | `/api/ask` | A question in plain words. Body: `{question, plan_id, selected_stop_id, elapsed_h}` |
| GET | `/api/eink.png`, `/api/eink.bin` | The suit display at `?elapsed_h=` (latest plan unless `plan_id`) |

Terrain routes answer **409** until `marswalk fetch` has run. `/api/ask` returns the answer as text, the same text
for speech, the topics it understood, what "here" meant, and GeoJSON to highlight on the map.
