# Data sources

Everything on the map is real NASA or USGS data. Nothing is generated or invented.

| Data | Product | Resolution | Used for |
|---|---|---|---|
| **Terrain (trusted)** | HiRISE stereo DTM `DTEEC_019698_1750_019988_1750_U01` (University of Arizona / NASA MRO) | 1 m | Slope, roughness, off-limits, routes, walk-home field |
| **Terrain (wide)** | USGS merged Gale DEM v3, `MSL_Gale_DEM_Mosaic_1m_v3` (Parker & Calef; HRSC + CTX + HiRISE tied to MOLA) | 1 m grid | Base surface over the rover ± 3 km, shown faded outside the HiRISE strip |
| **Photo** | HiRISE orthophoto `ESP_019698_1750_RED_C_01_ORTHO`; Mars Trek `curiosity_hirise_mosaic` tiles | 25 cm–1 m | Basemap; registration check |
| **Wider imagery** | Mars Trek CTX Gale mosaic (6 m) and THEMIS daytime infrared (100 m) | 6–100 m | Map context when zoomed out |
| **Ground type** | THEMIS quantitative thermal inertia mosaic (Mars Odyssey) | 100 m | Loose sand vs firm ground |
| **Radiation** | Curiosity RAD surface measurements (Hassler et al. 2014) | per day | Dose for the walk |
| **Space weather** | NASA DONKI: CME analyses with WSA-ENLIL arrival predictions, SEP events, solar flares | live | Go / caution / no-go |
| **Stops** | Curiosity (MSL) waypoints around the Mount Sharp boxwork | waypoint | S1–S5 science stops |
| **Walking model** | SEXTANT traverse planner (Johnson et al. 2010): Marquez speed curve, Santee metabolic rate | — | Time and energy of every step |

## How much is downloaded

`marswalk fetch` reads only the window around the rover, straight from the archives over HTTP range requests:

- HiRISE DTM window: about 50 MB
- HiRISE orthophoto window: about 18 MB
- THEMIS thermal inertia: one 128 × 128 tile
- USGS merged DEM: about 0.5 GB, once. The file stores one 33 km row per strip, so every row of the window comes
  down in full.

Everything is cached in `data/raw/<site>/` with a manifest of sources and checksums. The fetch re-runs only when the
window changes.

## Facts verified against the files (2026-11-13/14)

- HiRISE DTM: 7426 × 18270 px, 1.0117 m, equirectangular centred on 137.38° E, Mars 2000 sphere
  (R = 3,396,190 m).
- The orthophoto's GeoJP2 header is 1.5 px off from its PDS label. MarsWalk uses the DTM grid.
- USGS merged DEM v3: 3,868,256,546 bytes, 32980 × 57440 px float32, LZW, one row per strip, PixelIsPoint, nodata
  −32767. It reads about 15 m lower than the HiRISE DTM, like Curiosity's geoid elevations.
- **The HiRISE DTM sits 33.5 m south and 30.5 m east of the USGS/MSL base map** (see
  [Models and math → Registration](Models-and-math.md#registration-putting-hirise-on-the-map)).

## The NASA API key

DONKI works with `DEMO_KEY` (about 30 requests an hour). For more, get a free key at api.nasa.gov and put it in
`.env` as `NASA_API_KEY=...`. That file is git-ignored. Every outside request goes through one client
(`src/marswalk/sources/api_client.py`), which caches each feed for 30 minutes, reuses the last good copy when NASA
is slow, backs off after failures, and shows its state under *NASA data connections* in the app.
