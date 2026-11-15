# MarsWalk

**Plan a walk on Mars that always leaves enough oxygen to get home.**

![MarsWalk planning a five-stop walk across the boxwork ridges of Mount Sharp, on real HiRISE imagery](docs/img/02-planned-photo.png)

---

## The walk home is the whole problem

Picture the first crew to step out at Gale crater. The rover is parked at the foot of Mount Sharp. Ahead, a maze
of boxwork ridges that Curiosity spent 2025 driving through: veins of rock left standing where the ground around
them eroded away. Five places worth a geologist's afternoon. Each suit carries eight hours of oxygen.

The obvious question is *how do we get there?* The real one is quieter: **from any point on this walk, can we still
make it back?**

On Earth, a hiker who misjudges a trail is tired. On Mars, a crew member who misjudges the walk back is out of air.
So MarsWalk doesn't just draw a route. It keeps asking, for every metre of the walk and every minute of the day,
whether the crew can still turn around and reach the rover with the reserve untouched. Then it shows the answer on
the map, says it out loud, and puts it on the crew member's sleeve.

This is our entry to the **NASA Space Apps Challenge 2026** (*Marswalk* mapping challenge), by Jih Bin Luo Liu and
Justin Meng.

## What it does, in one walk

**1. It reads the ground the way a boot would.** From NASA's 1-metre HiRISE stereo terrain it measures slope at the
scale of one stride and of a few strides, roughness (rocks and ledges), and loose sand (from THEMIS thermal inertia).
Anything too steep or too rough is off-limits: 28 % of the HiRISE window around the rover.

![Off-limits ground in red: too steep or too rough](docs/img/04-off-limits.png)

**2. It finds the cheapest walk, in oxygen, not metres.** The route search runs over every metre of the grid,
pricing each step with the walking-energy model from NASA-funded traverse research (SEXTANT). It knows a 10° climb
draws *less* power than flat ground, because you slow to a crawl, but costs **3.3 times more energy per metre**.
So routes bend around hills the way a tired person would.

**3. It plans the day.** For the five Curiosity waypoints, in science order:

| | |
|---|---|
| Distance | **1.71 km**, there and back |
| Time outside | **3 h 31 min**: 1 h 01 min walking, 2 h 30 min working at stops |
| Effort | **2,962 kJ** per crew member, 35 % of the budget, about **0.21 kg of oxygen** breathed |
| Tightest moment | still **2 h 05 min** to spare before the crew would have to start home |
| Steepest step | 16°, under the 20° limit; no step on off-limits ground |

**4. It shows where you can still go.** Slide the clock forward and the green *walk-back safe zone* shrinks: every
place from which the crew could still walk home with the reserve intact. At 5 h 18 min it still reaches every stop,
but only just: the map turns yellow and orange, because 18 minutes of usable oxygen are left and the walk home
from the farthest stop takes 15. Seeing that happen before anyone steps outside is the point.

![The walk-back safe zone 5 h 18 min into the walk](docs/img/06-safe-zone.png)

**5. It watches the Sun.** NASA's DONKI service predicts when solar eruptions (CMEs) will reach *Mars*, not just
Earth, and reports particle storms. MarsWalk turns that into GO, CAUTION or NO-GO, and adds the radiation dose for
the walk from Curiosity's own measurements on the ground at Gale: **0.031 mGy** for this walk.

**6. You can just ask it.** Press the microphone and say *"How far is S3 from here?"* The answer comes back out
loud, and the route it means is drawn in white: 610 m in a straight line, 730 m on foot, 28 minutes with the safety
margin. It handles oxygen, radiation, energy, the walk home, turn-back times, slopes and the schedule. There is no
AI model behind it and no network call, so every number it says is the planner's own.

![Asking out loud](docs/img/07-ask-distance.png)

**7. It goes on the suit.** A 7.5-inch e-ink panel shows the walk like car navigation: next stop and distance,
oxygen left before the reserve, the walk home, and *turn back within*, which goes black when slack runs low. The
planner draws it; an ESP32 downloads it once a minute (`firmware/suit_display`).

![The suit display while working at S2](docs/img/eink-050.png)

## The bug that moved the map 45 metres

Late on the first night we checked our own work and found the uncomfortable kind of bug: the kind that looks fine.

NASA's HiRISE terrain file carries its own coordinates. Those coordinates are **33.5 m south and 30.5 m east** of the
USGS base map that the Mars Trek photos, the wider USGS terrain model and Curiosity's own waypoints all share. Every
slope we had shown, every route, every value at every stop had been read 45 metres from where it was drawn. Nothing
crashed. The map just quietly lied.

We measured the shift two independent ways, and they agreed:

| Compared | Match before | Match after shifting 33 m N, 30 m W |
|---|---|---|
| HiRISE terrain vs USGS terrain | 0.935 | **0.9998** |
| HiRISE photo vs Mars Trek photo | 0.47 | **0.93** |

MarsWalk now moves the terrain onto the base map and re-measures what is left every time it builds. The slope at
the second stop went from 12.2° to 10.5°. Small numbers, but they are the difference between *the ground
under the pin* and *the ground 45 metres away*.

That night set the rule for the rest of the build: **every number gets checked by a second path.** `marswalk audit`
recomputes 30 of them: distances along the route on the sphere, the timeline added up again, budgets from the
config, the slope layer hand-computed at random points. All 30 pass on the real data. It caught three more problems
on the way, all now fixed: an oxygen constant off by 3.5 %, terrain noise counted as walking distance, and a
radiation figure that did not match its source. [The audit, in full →](docs/wiki/Audit.md)

## The data

All real, all public:

- **HiRISE** 1 m stereo terrain and orthophoto (NASA Mars Reconnaissance Orbiter, University of Arizona)
- **USGS merged 1 m Gale terrain model** (Parker & Calef) for the wider map
- **THEMIS** thermal inertia (Mars Odyssey) for sand vs rock
- **Mars Trek** HiRISE, CTX and THEMIS mosaics (NASA/JPL) for the basemap
- **Curiosity RAD** surface radiation (Hassler et al. 2014, *Science*)
- **NASA DONKI** space weather: CME arrivals at Mars, particle events, flares
- **Curiosity waypoints** for the science stops
- **SEXTANT** walking speed and energy models (Johnson et al. 2010)

Details, resolutions and the facts we verified against each file: [Data sources](docs/wiki/Data-sources.md).
Every formula, with its source: [Models and math](docs/wiki/Models-and-math.md).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
marswalk fetch            # one time: the terrain window around the rover (~0.6 GB)
marswalk audit            # recompute every number (30 checks)
marswalk serve            # API on :8000
cd frontend && npm install && npm run dev     # the app on http://localhost:5173
```

Optional: a free NASA API key in `.env` (`NASA_API_KEY=...`) raises the space-weather request limit. Stuck?
[Running it](docs/wiki/Running.md) has a table of the usual errors.

## Inside

FastAPI and SQLite on the back; React, TypeScript and OpenLayers (on a true Mars map projection) on the front. The
route search is a compiled A* over millions of 1 m cells. One reverse search from the rover gives the walk home from
everywhere at once. Every limit lives in `configs/`, never in code. In the app only the API layer may call the
network, and in the backend only the repository may touch the database; lint rules and tests fail if either rule is
broken. 80 tests.

- [How it works](docs/wiki/How-it-works.md): the pipeline, end to end
- [Decisions](docs/wiki/Decisions.md): what we chose over what, and why
- [Knowledge graph](docs/wiki/Knowledge-graph.md): a map of the code (857 nodes), built with graphify
- [API](docs/wiki/API.md) · [Voice questions](docs/wiki/Voice-questions.md) · [Suit display](docs/wiki/Suit-display.md)

## What we would do next

- **Measure, don't assume, the suit.** Speed and energy come from Apollo-era and Earth data. A Mars suit's real
  numbers would replace two lines of config.
- **A 3-D planning table** so a crew can rehearse the walk from inside the habitat.
- **Live position.** The suit display follows the plan's clock; with a position fix it would follow the walker.

## How this was built

Built during the Space Apps weekend by a two-person team. We used AI coding assistance (Claude) to help write code,
tests and documentation; the design, the data choices and the checking were ours, and every number in this README
comes from the code run on NASA's data. NASA does not endorse this project.
