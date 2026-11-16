# Bases: planning anywhere HiRISE has stereo terrain

Gale crater is built in. A **Base** is any other place you choose: MarsWalk finds that area's data in NASA's
archives, downloads it, and plans walks there with exactly the same code. You can keep several Bases. All of them
are on the map, and one is in focus: planning, overlays, voice answers, the suit display and the simulator follow it.

## Where a Base can go

Only inside a **1 m HiRISE stereo terrain model** (DTM). There are 1,370 of them, about 0.1 % of Mars. 843 can be
used: they need to be equirectangular, 1 m or finer, have a 1 m photo, and not cross 180° longitude. Coarser terrain
(CTX at 6–20 m, MOLA at 460 m) hides the ledges and blocks the off-limits test exists to catch, so it is not used for
walking.

Press **New Base** and the outlines appear in cyan; unusable ones are grey, with the reason. Zoomed out, each is a
dot, and a click near a dot snaps to it. The lookup card then shows the DTM chosen, the ± 3 km window, the download
size against your free disk space, and a name to edit. The hosted site uses the catalog shipped with MarsWalk
(`src/marswalk/sources/data/hirise_dtm_catalog.json.gz`, 1,370 DTMs) instead of downloading the 8 MB index on
that click. A failed download used to answer 503 and the card never opened.

## What happens when you press *Download and create*

| Step | What it does |
|---|---|
| Find HiRISE stereo terrain | Looks the point up in the PDS DTM index (`DTMCUMINDEX`, cached 30 days). Of several DTMs, the finest, then the one whose edge is farthest from the point, then the newest |
| Check the terrain at the Base | Reads the exact grid from the DTM file and a small window at the point; stops if it is on the strip's empty edge |
| Download the 1 m terrain | The ± 3 km window, read straight from the archive in strips |
| Download thermal inertia | The THEMIS tile for that latitude band (±60° only) |
| Download the 1 m photo | The orthophoto from the same PDS folder (left image of the stereo pair), cropped to the window |
| *(square pixels)* | If the DTM's standard parallel is far from the Base, terrain and photo are resampled so each pixel is a 1 m square on the ground ([why](Models-and-math.md#square-pixels-away-from-the-equator)) |
| Line the terrain up with the map photo | Measures the offset against the global HiRISE photo tiles ([how](Models-and-math.md#a-new-base-measured-against-the-global-photo)) |
| Place the rover and save | Nearest walkable cell within 100 m of the click; median elevation within 200 m for the radiation estimate |

A Base takes one to three minutes and 130–280 MB. The button stays off only when the download itself is larger
than the free disk. After the files land, each GeoTIFF is stored in the database (`terrain_files`). If that copy
on disk is later missing, planning writes it back from the row. **Cancel** removes everything it downloaded and
frees the slot at once, even if a NASA read is still stuck. A connection that sends nothing for 45 seconds
fails on its own and the error is shown on that step. If the server stops mid-download, the Base comes back
as *interrupted*, with **Resume**.

## What differs from Gale

| | Gale (built in) | A Base |
|---|---|---|
| Science stops | Curiosity's five boxwork waypoints | None at first: add your own on the map |
| Radiation | Measured by Curiosity's RAD | Estimated from air pressure at the Base's elevation, with a range ([model](Models-and-math.md#away-from-gale-an-estimate-from-air-pressure)) |
| Alignment | Measured by hand, re-checked against the merged DEM | Measured automatically, graded good / fair / coarse / weak |
| Wide terrain | USGS merged 1 m DEM around the strip | The HiRISE strip only |
| Photo map | Mars Trek Gale mosaic | Global HiRISE mosaic (z ≤ 17), CTX and THEMIS for context |

Warnings (no thermal inertia, weak alignment, rover moved to walkable ground) appear under the Base's name.

## Tested Bases

| Base | Terrain | Size | Alignment | Radiation |
|---|---|---|---|---|
| Jezero delta (18.44° N, 77.45° E, −2,569 m) | `DTEEC_045994_1985_046060_1985_U01` | 134 MB | good, 29 m, r = 0.90 | 0.230 mGy/day (estimate) |
| Nili Fossae (22.44° N, 75.02° E) | `DTEEC_035484_2025_037106_2025_A01` | 149 MB | good, r = 0.95, but **900 m** from the file's coordinates | 0.249 mGy/day (estimate) |

The Jezero result was measured twice, from two separate downloads, and agreed to 0.15 m. The Jezero Base passes all
17 audit checks that apply to it (`marswalk --base b_jezero_delta_1f2b90 audit`). The Nili Fossae offset matched the
photo very confidently, but is large enough that it should be checked against an independent source before a walk
there is trusted.

## From the command line

See [Running it](Running.md#another-place-on-mars). The routes are in [API](API.md).

## Not covered yet

- 2 m DTMs, polar (stereographic) DTMs, and strips that cross 180°.
- Thermal inertia across a THEMIS tile edge.
- Two browser tabs focusing different Bases at once: the focus is held by the server, one per server.
