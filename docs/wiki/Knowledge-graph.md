# Knowledge graph of the code

`docs/graph/` holds a knowledge graph of the whole codebase, built by
[graphify](https://github.com/safishamsi/graphify) from the code's syntax trees (no AI service involved):
**1,037 nodes, 2,433 edges, 63 communities** across the Python backend, the React app and its 3-D simulator, and
the tests.

- `graph.html`: open it in a browser to explore. Nodes are functions, classes and files; edges are calls, imports
  and uses; colours are communities.
- `GRAPH_REPORT.md`: the most connected nodes, the communities and surprising links.
- `graph.json`: the raw graph, for `graphify query "..."`, `graphify path "A" "B"` or `graphify explain "X"`.

## What it shows

The most connected nodes are the spine of the system:

| Node | Edges | Role |
|---|---|---|
| `create_app()` | 57 | The API: every feature meets here |
| `SimEngine` | 35 | The walk simulator: scene, controls and the mission-time loop |
| `load_site()` | 28 | Site config: one file per place on Mars |
| `build_plan()` | 27 | Plan: route, timeline, budgets, checks |
| `Raster` / `GeoGrid` | 27 / 23 | Georeferenced arrays shared by fetch, layers and routing |
| `build_stack()` | 26 | Terrain layers: everything downstream reads them |
| `AskContext` / `answer()` | 25 / 20 | Voice questions |
| `App()` | 25 | The planner's screen |

## Rebuild it

```bash
pip install graphifyy
graphify update .          # re-extracts the code; no API key needed
```
