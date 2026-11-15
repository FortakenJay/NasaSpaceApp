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

## 2026-11-15: skateboard kick
- Jih: a kick fires every time the foot touches the ground and adds speed, enough to climb hills. A downhill run
  should build speed. The old push was a steady 60 N for the whole time W was held, not tied to the foot.
- Chosen: one traction-limited kick (μ = 0.6, same as the brake) for the animation's ground-contact slice
  (0.18–0.55 of each 1.1 s push), power-capped at 340 W so the flat top stays under the 7 m/s wobble.
  Rolling resistance unchanged. Off-plan, so the planner's headline numbers are untouched.
