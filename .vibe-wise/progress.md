# Progress

## 2026-11-15: orientation (read only)
- Jih asked for a read of the Claude outputs, the TODO list, what is missing, where things are, and the scope.
- No code changed. Created `.vibe-wise/` notes.
- Started API (:8000) and web (:5173).

## 2026-11-15: "finish the todo list" (Jih: "just do it your style" = explicit checkpoint skip)
- Order chosen by Claude: foundation first (zip applied as unstaged changes over the staged v1.0, `three` installed,
  parity test), then items needing no new data, then sourced data items as opt-ins, then docs.
- Another agent session edited frontend/src/sim in parallel until Jih closed it (01:11); its skateboard/mouse-look
  work is in the same files, unstaged, mixed with the zip and this round.
- Done: physics parity test (node vs python); gait cap (Kram 1997, opt-in); consumables accounting; radio shadow;
  storm-shelter reach (Löwe 2025); terrain uncertainty MC; mission clock; gravity bound; audit findings category;
  E1 LOD + 1 m patch, E3 binary heights + versioned URLs, E5 normal map (toggle, off), E8 fixed ticks, E9 HUD store,
  E10 sleep, E11 GPU numbers; sound; in-browser QA (`?qa=1`, 25/25); version 1.1.0; docs/TODO updated.
- Closed by measurement: E2 (15 ms startup), E7 (Sun 37-74° on the walk), E12 (8 ms frames).
- Open, data-blocked: metabolic at Mars g, sand model, rocks + E6, dust, temperature, varying radiation, validation,
  true colour, wind; E4 (no encoder); route penalty on uncertain ground.
- Decisions left to Jih: turn the gait cap on (moves headline numbers slightly)? E5 on by default (by eye)? antenna
  heights and DTM precision are assumptions; commit order of staged v1.0 vs unstaged round.
- Verified: 99 pytest, audit 38/38 + 1 finding, tsc/eslint/vite build clean, in-browser QA 25/25.

## 2026-11-15: skateboard, route colours, go-there
- Jih: a kick fires every time the foot touches the ground and adds speed, enough to climb hills. Later: kick a
  little harder uphill; gravity feels harder than Earth. Confirmed 3.71 m/s² is right; grip scales with weight, so
  each kick adds ~38 % of an Earth shove. Uphill extra is 1.5 × the slope's pull, only while climbing. Kick power
  900 W, fading by 6.2 m/s. Roughness rolling resistance 0.08 per metre (was 0.3, which cancelled downhills).
- Route colours: cyan out, orange back. Green stayed the rover, so a green return line was not used.
- "Go to S3" / "path to U1 from here": the answer draws the way there and the walk back. On the map, Go makes that
  stop next, then the stops already ticked. In the simulator the ground line changes immediately, and Go follows it.
- Controls live on the pause screen. The separate controls card covered pause.

## 2026-11-15: Supabase MCP for this repo
- Jih pasted the Supabase Cursor setup for project `kcgoeljumzgnkrvraldr`. The URL is that one project, so it went in `.cursor/mcp.json` here. A CLI add wrote the same server into the user profile; that copy was removed so other repos do not point at this project.
- The `agent` CLI is not on PATH, so `agent mcp login supabase` was not run. Cursor still has to approve and sign in to that server.
- Jih then ran `npx skills add supabase/agent-skills`. Both skills are copied into `.agents/skills/` (`supabase`, `supabase-postgres-best-practices`) and recorded in `skills-lock.json`. Postgres is not wired into the API yet.
- `.gitignore` now skips `.agents/` and `.cursor/` so the skill copies and the MCP config stay off GitHub. `skills-lock.json` stays.
- Jih: the store is `https://kcgoeljumzgnkrvraldr.supabase.co` on NasaSpaceApp, not Rosa. The publishable key is in `.env` only. Nothing was created in Rosa. The Data API refused that key ("Secret API key required"). Storage has no buckets. The API still uses SQLite.
- Jih said to build the database. The schema is `supabase/migrations/20261116013200_marswalk_store.sql` (sites, stops, plans, observations, settings, bases, stored_objects, private `marswalk` bucket, RLS on, no policies). Applying it to `kcgoeljumzgnkrvraldr` was refused. It was not run on Rosa.
- Jih: stop, fix the app, and store the preview in the database the app already uses. SQLite now sits in the writable data root (`/tmp/marswalk/marswalk.db` when the checkout cannot be written). A fresh database loads `configs/preview/gale_boxwork_plan.json` (the computed Gale route, 1.71 km, S1–S5). The map shows that stored route until someone computes a new one. Tests still use an empty in-memory database.
- Docs updated to match: README, Running, API, How it works, Decisions, ARCHITECTURE.
- Production `/api/sim/terrain` returned HTTP 500: the function tried to download the elevation file and was cut off. The Gale mesh is now in `frontend/public/sim/gale/` (3 m ground, 1 m grid, photo). The simulator uses it when that file is missing. Needs a redeploy of both services.
- Jih: a behavior change updates the docs before it is finished. Rule: `.cursor/rules/update-docs.mdc`. Simulation, API, architecture, README, and Decisions now describe the shipped mesh. `.cursor/rules/` stays in git; the rest of `.cursor/` does not.
- Jih: save a downloaded Base in the database. The disk check is now "the download fits once" (276 MB fits in 528 MB free; the old rule also wanted a second copy and 1 GB spare). After the GeoTIFFs land they are rows in `terrain_files`, and planning writes them back if the file is missing. On the hosted site the database file is on that same small disk, so both copies together can still be too big.
- A Base stuck at 2% is the NASA header read, still "running", so it holds the only slot and shows no error. A connection with no bytes for 45 s now fails visibly. Cancel frees the slot immediately. The job line shows the current step, the clock, and after 20 s says to cancel.
