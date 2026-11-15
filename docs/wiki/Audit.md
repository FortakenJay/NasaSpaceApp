# The audit: checking every number

A planner that tells someone when to turn around for home has to be right, not just plausible. So before the
deadline we stopped adding features and asked a blunt question of every number on the screen: *where does this
come from, and can we get the same answer a different way?*

`marswalk audit` is the result. It recomputes each value by an independent path: haversine distances along the drawn
route instead of grid steps, the timeline re-added leg by leg, budgets straight from the config, the slope layer
hand-computed at random cells. Then it compares the two answers. On the real Gale data: **30 of 30 checks pass**
([full table](Audit-results.md)). Run it yourself after `marswalk fetch`:

```bash
marswalk audit --out docs/wiki/Audit-results.md
```

## What it caught

Four things were wrong. All four are fixed, and each one now has a check so it cannot come back.

| What | Was | Now | Effect |
|---|---|---|---|
| **HiRISE terrain was 45 m off the map.** The DTM's own coordinates sit 33.5 m south and 30.5 m east of the base map the photo and Curiosity's waypoints use. | Overlays, routes and stop values read 45 m away from where they were drawn | DTM moved onto the base map at load time; leftover offset re-measured every build | S2 slope 12.2° → 10.5°, roughness 0.35 → 0.28 m. The route now follows the ground in the photo |
| **Oxygen per joule.** The code used 20.9 kJ per litre of O₂. | 0.20 kg breathed | 20.19 kJ/L (4.825 kcal/L at RQ 0.82) | Oxygen use was understated by 3.5 % |
| **Stereo noise counted as walking.** Distance and climb were summed on the raw 1 m DTM, whose ~0.2 m cell-to-cell noise adds length. | 1.72 km | 1.71 km, measured on the stride-scale surface the route search already uses | Distances agree with the sphere to 0.1 % |
| **Radiation dose equivalent.** | 0.67 mSv/day | 0.64 mSv/day, the published RAD value | Spoken dose answers are now the cited number |

## What the checks cover

- **Constants:** Mars radius, map scale, gravity, RAD dose rates, O₂ energy equivalent, usable oxygen time. Each one is
  compared with its published source.
- **Walking model:** the speed curve has no jumps at its breakpoints, flat speed is 1.6 m/s, and power on the flat
  and on a 10° climb matches the Santee formulas computed by hand.
- **Terrain:** pixel size north-south and east-west against haversine, the 5 m slope layer against a hand-computed
  slope at 200 random cells, the share of off-limits ground, and the leftover HiRISE registration offset.
- **Plan:** distance against the route measured on the sphere, the route longer than the straight lines, the timeline
  re-added, time outside, budget shares, energy re-summed, oxygen, walk-home margins, and the walk home never
  faster than flat walking.
- **Safety:** no route cell in off-limits ground, the steepest step under the 20° limit, and every stop inside 2 km.
- **Radiation:** the dose for the walk.

## Assumptions to be honest about

These are inputs, not errors, and a reviewer should know them:

- **Walking speed and power come from Earth and Apollo-era data** (Marquez curve, Santee model). They are the
  published SEXTANT forms, not measurements of a future Mars suit.
- **Level walking is scaled by Mars gravity.** This is our assumption, not SEXTANT's (see
  [Models and math](Models-and-math.md)).
- **The budgets are placeholders for a real suit:** an 8 h oxygen tank, a 12,000 kJ effort budget, 250 W of work at
  each stop, a 30 % reserve and a 30 % time margin. Every one of them is a line in `configs/eva/artemis_default.toml`.
- **The radiation dose is the cosmic-ray background measured by Curiosity's RAD.** A suit shields less than the rover's
  surroundings, and a solar storm adds on top. That is why the space-weather check exists.
- **Thermal inertia comes in 100 m blocks.** It flags regional sand, not one dune.
