# Decisions, by component

What was chosen, what it was chosen over, and why.

## Terrain

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Planning surface | HiRISE 1 m stereo DTM only | Plan on the merged DEM everywhere | The merged DEM stitches products of different detail; a 1 m stereo DTM is one known product. Outside it the map shows terrain, but routes stay out |
| Wide terrain | USGS merged 1 m Gale DEM as the base, faded outside HiRISE | HiRISE strip alone (a "blob" with slanted edges) | The map needed terrain everywhere; the base surface is checked against HiRISE (slope, roughness) and set aside if it disagrees or is smoother |
| Registration | Fixed configured shift, re-measured each build | Trust each file's georeferencing | The HiRISE DTM is 45 m off the base map; two independent correlations agree on the shift |
| Slope scales | 1 m and 5 m, plus roughness | One slope | A ledge and a hillside are different hazards |
| Sand | THEMIS thermal inertia, flagged as regional | Detect sand in the photo | TI is a physical measurement; at 100 m it is honest about its scale |

## Routing

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Search | Compiled (numba) A* on the 1 m grid, 8 neighbours | Graph libraries / coarser grid | Millions of cells in seconds; 1 m keeps ledges visible |
| Cost | Metabolic energy (SEXTANT), or weighted score | Shortest distance | A short route up a 15° slope costs more oxygen than a longer flat one |
| Walk home | One reverse Dijkstra from the rover | A* per point | Gives the walk home from every cell at once: safe zone, margins, voice answers, suit display |
| Margins | 30 % time margin, 30 % oxygen reserve | Plan to the last minute | Models are uncertain; the reserve is never planned into |
| Distance and climb | Measured on the stride-scale surface | Raw 1 m DTM | Stereo noise inflated length and climb (found by the audit) |

## Space weather and data access

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Source | NASA DONKI CME arrivals predicted at Mars (WSA-ENLIL), SEP events, flares | Earth-only alerts | The question is what reaches Mars during the walk |
| Flares | A hint (X-class → caution); a missing list does not block | Required feed | Flares are seen from Earth's side; the flare feed is the slowest |
| Requests | One central client: cache, stale-if-error, back-off, single-flight, rate-limit budget | Each feature calls NASA | DEMO_KEY allows ~30 requests an hour; a demo cannot fail on a slow feed |

## Interfaces

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Voice understanding | Keyword parser + planner numbers | A language model | Works offline, no key, and can never invent a number that disagrees with the plan |
| Speech | Browser speech-to-text and text-to-speech | A cloud speech API in the backend | Nothing to install; Chrome and Safari both work |
| Suit display | Server renders 800 × 480 1-bit; ESP32 only draws | Logic on the microcontroller | One source of truth; the board stays a dumb, reliable screen |
| Display tech | E-ink | LCD | Readable in sunlight, no power between updates, handles cold |
| App layout | Four (now five) numbered steps beside the map | A dashboard of panels | First-time users did not know where to start |

## Verification

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Checking numbers | `marswalk audit`: independent recomputation, 30 checks | Unit tests alone | Tests prove code does what it says; the audit asks whether what it says is right |
| Thresholds | All limits in `configs/` | Constants in code | A reviewer can see and change every assumption in one place |
