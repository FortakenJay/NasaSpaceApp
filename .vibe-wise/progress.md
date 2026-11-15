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
