# Project map: MarsWalk (NasaSpaceApp)

Verified 2026-11-15 by reading the repo. Update when structure changes.

## Scope
- NASA Space Apps 2026, *Marswalk* mapping challenge. Team: Jih Bin Luo Liu, Justin Meng.
- Core question: from any point on the walk, can the crew still get back to the rover with the oxygen reserve intact?
- Fixed case: 2-person crew, rover H1, five Curiosity boxwork waypoints S1-S5 at Gale crater, out and back.
- Site-agnostic by design: new site = `configs/sites/*.toml` + a stops file.

## Backend (`src/marswalk/`, Python, FastAPI + SQLite)
- `sources/` fetch NASA rasters; `layers/` slope, roughness, sand, no-go, registration (`coverage.py`)
- `cost/` walking speed + metabolic models (numba); `route/` A*, sequencing, plan assembly
- `constraints/eva.py` limit checks; `spaceweather/` DONKI go/no-go + RAD dose
- `ask.py` voice/keyword Q&A; `eink.py` suit display frames; `audit.py` 30 recomputation checks
- `sim.py` terrain/fine-grid packages for the simulator; `sun.py` Mars24 Sun position
- `db/repo.py` is the only DB access; `api/app.py` is the only server entry point
- Limits live in `configs/eva/artemis_default.toml` and `configs/sites/gale_boxwork.toml`

## Frontend (`frontend/src/`, React + TS + OpenLayers + Three.js)
- `api/` is the only network layer (lint + test enforced)
- `components/` planner panels; `map/` OpenLayers on a Mars projection
- `sim/` walk simulator: `terrain.ts`, `physics.ts` (port of Python cost models), `engine.ts`, `astronaut.ts`, `SimulationView.tsx`
- `views/planningTable.ts`: M6 CesiumJS 3-D table, 13-line stub only

## Added 2026-11-15 (v1.1)
- `layers/radio.py` (line of sight), `layers/uncertainty.py` (off-limits Monte Carlo), `route/exposure.py` (radio,
  shelter, marginal-ground minutes/metres), `consumables.py`, `sun.mars_sol_date`
- `frontend/src/sim/qa.ts` (`?qa=1`), `audio.ts`; tests `test_physics_parity.py`, `test_exposure.py`, `test_sim_audio.py`
- Config: `[comms]`, `[consumables]`, `sep_warning_lead_min`, `walk_run_froude`/`leg_length_m` (eva);
  `products.dtm.uncertainty` (site)

## Other
- `firmware/suit_display/` ESP32 + 7.5" e-ink sketch
- `tests/` 99 pytest tests; simulator QA in `frontend/src/sim/qa.ts` (run with `?qa=1`)
- `docs/ARCHITECTURE.md`, `docs/wiki/*`, `docs/img/*`, `docs/graph/*`
- `Claude outputs/marswalk-sim-eggs-update.zip`: its sim files are now copied into the working tree byte-for-byte
  (checked 2026-11-15). `frontend/src/sim/eggs.ts`, `skate.ts` and root `TODO.md` are untracked; the rest are modified.
- Simulator input lives in `engine.ts` (`bindInput`, `onPointer*`, `step`); Esc pause is in `SimulationView.tsx`.

## State on 2026-11-15
- Branch `feat/planner-pipeline-safe-zone`; v1.0 simulator work staged, not committed; the zip, another session's
  skateboard/mouse-look work and the v1.1 round are unstaged on top (same files). Nothing committed.
