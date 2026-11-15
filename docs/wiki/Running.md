# Running it

Needs Python 3.11+ and Node 20+. On macOS or Linux:

```bash
git clone <repo> && cd NasaSpaceApp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # optional: put your NASA_API_KEY in it

marswalk fetch                # download the terrain window (one time; ~0.6 GB with the merged DEM)
marswalk layers               # print slope, roughness, sand at each stop; check the registration line
marswalk audit                # recompute every number and compare (30 checks)
marswalk serve                # API on :8000

cd frontend && npm install && npm run dev    # app on http://localhost:5173
```

On Windows use `.venv\Scripts\activate`. Tests: `pytest` (80) and, in `frontend/`, `npx tsc --noEmit && npx eslint src`.

## When something is off

| You see | Why | Fix |
|---|---|---|
| `zsh: command not found: marswalk` | The project's virtual environment is not active (e.g. conda `base` is) | `source .venv/bin/activate`, or run `.venv/bin/marswalk ...` |
| 404 on http://localhost:8000/ | That is the API; the app is on port 5173 | Open http://localhost:5173 |
| "terrain not cached" or a path to another folder | The package was installed from an older copy of the project | `pip install -e ".[dev]"` in this folder |
| Space weather "partly unavailable" | NASA DONKI was slow or the hourly limit was reached | Wait, add a key to `.env`, or press *Ask NASA again now* |
| Map colour stops at slanted edges | That is the end of the HiRISE stereo strip | `marswalk fetch` adds the USGS merged DEM around it |
| The microphone does nothing | Browser without speech input (e.g. Firefox) or microphone blocked | Use Chrome or Safari, allow the microphone, or type |
