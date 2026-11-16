# Running it

Needs Python 3.11+ and Node 20+. On macOS or Linux:

```bash
git clone <repo> && cd NasaSpaceApp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # optional: put your NASA_API_KEY in it

marswalk fetch                # download the terrain window (one time; ~0.6 GB with the merged DEM)
marswalk layers               # print slope, roughness, sand at each stop; check the registration line
marswalk audit                # recompute every number and compare (39 checks)
marswalk serve                # API on :8000

cd frontend && npm install && npm run dev    # app on http://localhost:5173
```

`npm run preview` (in `frontend/`) serves the built site and proxies `/api` to the API on port 8000, the same way
`npm run dev` does.

On Windows use `.venv\Scripts\activate`. Tests: `pytest` (132) and, in `frontend/`, `npx tsc --noEmit && npx eslint src`.

## Another place on Mars

Press **New Base** in the app, or from the command line:

```bash
marswalk catalog refresh                 # the HiRISE DTM index (also done on first use; kept 30 days)
marswalk catalog lookup --lat 18.44 --lon 77.45
marswalk base create --lat 18.44 --lon 77.45 --name "Jezero delta"   # 1-3 min, 130-280 MB
marswalk base list
marswalk base focus b_jezero_delta_1f2b90          # what the app plans at
marswalk base realign b_jezero_delta_1f2b90        # measure the alignment again, no download
marswalk base delete b_jezero_delta_1f2b90
marswalk --base b_jezero_delta_1f2b90 audit        # any command, on a saved Base
```

Run `marswalk serve` with one worker (the default): the Base in focus is held in that process.

## Hosted on Vercel

The site and the API are two services in one project (`vercel.json`). The browser calls `/api` on the same host.
The elevation files are not in the deploy: they are git-ignored, and the function cannot write the project folder
(`/var/task`). Catalogs, terrain windows, added Bases, and the SQLite file go to `/tmp/marswalk` instead. The
database file there is `marswalk.db`. The same path is used when the checkout cannot be written, even if the
`VERCEL` variable is missing. On a laptop the file is `data/marswalk.db`.

That disk is empty again when the function instance is replaced. Startup then creates the tables, seeds Gale's
stops, and loads the stored route in `configs/preview/gale_boxwork_plan.json` (S1 through S5, 1.71 km, least
effort). The map draws that line until someone computes a new plan. A Base you added, and the Gale `dtm.tif` the
planner fetched on the first route, can be missing on the next request. The page then says the terrain is not
cached, or that the HiRISE catalog could not be downloaded. Planning and **New Base** start the download again.
If the API itself fails to start, the page opens the saved Gale demo (`frontend/public/sample-site.json`) and
planning stays off. That file has the site and the stops, and no route.

The Supabase project for this repo is `https://kcgoeljumzgnkrvraldr.supabase.co`. Its publishable key is
`SUPABASE_PUBLISHABLE_KEY` in `.env` (see `.env.example`). The API does not use it yet, so plans and stops still
go to SQLite. The tables and a private `marswalk` file bucket are written in
`supabase/migrations/20261116013200_marswalk_store.sql` and have not been applied. Postgres would keep the rows.
The GeoTIFFs still need that bucket, or another download. See [Decisions](Decisions.md).

## When something is off

| You see | Why | Fix |
|---|---|---|
| `zsh: command not found: marswalk` | The project's virtual environment is not active (e.g. conda `base` is) | `source .venv/bin/activate`, or run `.venv/bin/marswalk ...` |
| 404 on http://localhost:8000/ | That is the API; the app is on port 5173 | Open http://localhost:5173 |
| "terrain not cached" or a path to another folder | Locally, the package was installed from an older copy, or `marswalk fetch` has not been run. On Vercel, `/tmp` was wiped and the elevation file is gone | Locally: `pip install -e ".[dev]"` in this folder, then `marswalk fetch`. On Vercel: plan again and wait for the download; it does not survive a new instance |
| `Read-only file system: '/var/task/data/...'` | A hosted function tried to write the deployment directory | Redeploy a build that stores catalogs and terrain under `/tmp/marswalk` |
| Not enough free disk space for this Base | The download is larger than the free space on the disk the files are written to. On the hosted site that disk is about 500 MB | The download has to fit once. A 276 MB window fits in 528 MB free; a larger one does not |
| Space weather "partly unavailable" | NASA DONKI was slow or the hourly limit was reached | Wait, add a key to `.env`, or press *Ask NASA again now* |
| Map colour stops at slanted edges | That is the end of the HiRISE stereo strip | `marswalk fetch` adds the USGS merged DEM around it |
| "No 1 m HiRISE stereo terrain covers this point" | The click was outside every cyan outline | Zoom in and click inside one; zoomed out, a click on a dot works too |
| A Base shows *interrupted* | The server stopped while it was downloading | Press **Resume** |
| Alignment *weak* on a Base | The photo tiles there are blank or too different (e.g. dust, shadows) | Plan with care: the terrain uses the file's own coordinates and may sit tens of metres off the photo |
| The microphone does nothing | Browser without speech input (e.g. Firefox) or microphone blocked | Use Chrome or Safari, allow the microphone, or type |

## The simulator

It needs `npm install` once after pulling (it adds Three.js) and `marswalk serve` running. If the Simulation button
is greyed out, the app can't reach the API. On the hosted site the function has no elevation file, so the Gale
walk uses the mesh shipped with the page (`frontend/public/sim/gale/`: the 3 m ground, the 1 m walking grid, and
the photo). That mesh is the same window the planner uses for H1 and S1–S5. A new plan still needs the elevation
download. If the ground shows shaded relief but no photographed detail, the orthophoto (`raw/ortho_1m.tif`) is
missing: run `marswalk fetch` again, then restart `marswalk serve`, which caches the simulator's terrain until
the raw data changes.
