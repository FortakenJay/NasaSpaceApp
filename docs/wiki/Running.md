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

## When something is off

| You see | Why | Fix |
|---|---|---|
| `zsh: command not found: marswalk` | The project's virtual environment is not active (e.g. conda `base` is) | `source .venv/bin/activate`, or run `.venv/bin/marswalk ...` |
| 404 on http://localhost:8000/ | That is the API; the app is on port 5173 | Open http://localhost:5173 |
| "terrain not cached" or a path to another folder | The package was installed from an older copy of the project | `pip install -e ".[dev]"` in this folder |
| Space weather "partly unavailable" | NASA DONKI was slow or the hourly limit was reached | Wait, add a key to `.env`, or press *Ask NASA again now* |
| Map colour stops at slanted edges | That is the end of the HiRISE stereo strip | `marswalk fetch` adds the USGS merged DEM around it |
| "No 1 m HiRISE stereo terrain covers this point" | The click was outside every cyan outline | Zoom in and click inside one; zoomed out, a click on a dot works too |
| A Base shows *interrupted* | The server stopped while it was downloading | Press **Resume** |
| Alignment *weak* on a Base | The photo tiles there are blank or too different (e.g. dust, shadows) | Plan with care: the terrain uses the file's own coordinates and may sit tens of metres off the photo |
| The microphone does nothing | Browser without speech input (e.g. Firefox) or microphone blocked | Use Chrome or Safari, allow the microphone, or type |

## The simulator

It needs `npm install` once after pulling (it adds Three.js) and `marswalk serve` running. If the Simulation button
is greyed out, the app can't reach the API. If the ground shows shaded relief but no photographed detail, the
orthophoto (`raw/ortho_1m.tif`) is missing: run `marswalk fetch` again, then restart `marswalk serve`, which caches
the simulator's terrain until the raw data changes.
