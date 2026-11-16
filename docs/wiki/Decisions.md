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

## Bases (other places on Mars)

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Where a Base can go | Only inside a 1 m HiRISE stereo DTM (0.1 % of Mars) | Anywhere, on CTX or MOLA terrain | A suited walk needs ground resolved at the scale of a stride; 6-20 m terrain hides every ledge the off-limits test exists for |
| How many | Several saved, all on the map, one in focus | One at a time | Compare sites without downloading again; one stack (about 1 GB) in memory |
| Alignment | Measured against the photo the map shows, with a quality grade | Trust the file, or one absolute frame | The global mosaic itself differs from Trek's by about 100 m at Gale; what matters on screen is that terrain and photo agree |
| Radiation away from Gale | Gale's RAD value scaled by air pressure, labelled *estimate*, with a range | Gale's value everywhere, or no number | Dose depends on the air overhead; RAD's own pressure trend (Guo et al. 2017) is the measured link |
| Grid away from the equator | Resample to square pixels when more than 0.5 % off | Teach every layer non-square pixels | One resampling at download keeps slope, A*, radio and the simulator unchanged |

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
| Route colours | Cyan on the way out, orange on the way back | One cyan line, or green for the return | The walk is two trips. Green is already the rover, so a green return line disappeared into the start marker |
| "Go to S3" | The answer draws the path from here and the walk back, and Go makes that stop next (on the map) or replaces the line under your feet (in the simulator) | A distance sentence only | An astronaut asks where something is in order to go there. The route has to change when they say so |
| Controls in the simulator | The key list lives on the pause screen. Controls and ? pause | A second card, centred like pause | The two cards occupied the same spot and covered each other |
| Simulator when the elevation file is missing | The Gale mesh shipped in `frontend/public/sim/gale/` | Download the GeoTIFF inside the simulator request | That download is large enough that the hosted function is cut off and the game never opens |

## Hosting and what is stored

Two different things get written, and they do not belong in the same place.

| What | Today | On Vercel | A database would do |
|---|---|---|---|
| Stops you add, saved plans, field notes, which Base is in focus | SQLite file `data/marswalk.db` | `/tmp/marswalk/marswalk.db`, because `/var/task` is read-only. A fresh database also loads the stored Gale route in `configs/preview/gale_boxwork_plan.json` | Supabase (Postgres) would keep these rows across restarts. The SQLAlchemy models are ordinary tables and can move |
| HiRISE catalog, `dtm.tif`, orthophoto, thermal inertia, a new Base's `site.toml` | `data/cache` and `data/raw`, and after a Base download the GeoTIFFs are also rows in `terrain_files` | `/tmp/marswalk/...`, same reason. The database file is on that disk too, so a new instance loses the rows with the files | The download is saved in the database once it has landed. Planning writes the file back from that row when the disk copy is gone |

Chosen for the hackathon deploy: write the temporary disk (`/tmp/marswalk`) instead of failing with "read-only
file system", and if `/api/site` is down, open the saved Gale demo so the page is not blank. A fresh SQLite file
loads `configs/preview/gale_boxwork_plan.json`, so the hosted map has the Gale route (S1–S5, 1.71 km) without a
new terrain download. The Supabase project for this repo is `https://kcgoeljumzgnkrvraldr.supabase.co`. The
publishable key lives in `.env` as `SUPABASE_PUBLISHABLE_KEY`. The API still reads and writes SQLite. The tables
and a private `marswalk` file bucket are written in `supabase/migrations/20261116013200_marswalk_store.sql` and
have not been applied: the logged-in Supabase account cannot open this project. That project would stop plans
and stops from disappearing, and the bucket is where `dtm.tif` would go. A database row still does not hold the
GeoTIFF itself. The first new plan on a fresh instance still has to fetch the elevation window. A full HiRISE
download can also be cut off by the function's time limit.

## Verification

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| Checking numbers | `marswalk audit`: independent recomputation, 39 checks | Unit tests alone | Tests prove code does what it says; the audit asks whether what it says is right |
| Thresholds | All limits in `configs/` | Constants in code | A reviewer can see and change every assumption in one place |

## The simulator's skateboard (off the plan)

The walk uses the planner's model. The skateboard does not: it is an easter egg, and it must not move the headline
numbers. Its own choices:

| Decision | Chosen | Instead of | Why |
|---|---|---|---|
| A push | One kick each time the back foot meets the ground (the same slice of the animation), then coast | A steady force for as long as W is held | The foot hitting the ground was not moving the board |
| How hard | Boot friction μ = 0.6 times Mars weight, and 900 W while the foot is down, fading out by 6.2 m/s | The first 60 N motor, which could not climb | 60 N on a 143 kg suited crew is smaller than rolling resistance on this ground. The fade keeps a kick from throwing you into the 7 m/s wobble; a downhill still can |
| Uphill | While climbing, the kick also pushes 1.5 times the slope's pull | Grip alone | Mars weight is 0.38 of Earth's, so the legal kick is a small shove and a slope stalls it. The extra is past the slip limit, and only uphill |
| Roughness | +0.08 rolling resistance per metre of the planner's roughness | +0.3 | 0.3 cancelled a real downhill on this site. 0.08 lets a slope build speed; sand still stops the board |
| Gravity | 3.71 m/s², the same number as the walk and the hop | A skateboard tuned to feel like Earth | It feels harder than Earth because grip scales with weight, not because gravity was set high |
