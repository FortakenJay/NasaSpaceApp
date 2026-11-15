# Knowledge graph of the code

`docs/graph/` holds a knowledge graph of the whole codebase, built by
[graphify](https://github.com/safishamsi/graphify) from the code's syntax trees (no AI service involved):
**857 nodes, 2,323 edges, 40 communities** across the Python backend, the React app, the tests and the firmware.

- `graph.html`: open it in a browser to explore. Nodes are functions, classes and files; edges are calls, imports
  and uses; colours are communities.
- `GRAPH_REPORT.md`: the most connected nodes, the communities and surprising links.
- `graph.json`: the raw graph, for `graphify query "..."`, `graphify path "A" "B"` or `graphify explain "X"`.

## What it shows

The most connected nodes are the spine of the system:

| Node | Edges | Role |
|---|---|---|
| `create_app()` | 67 | The API: every feature meets here |
| `build_stack()` | 44 | Terrain layers: everything downstream reads them |
| `load_site()` | 35 | Site config: one file per place on Mars |
| `build_plan()` | 35 | Plan: route, timeline, budgets, checks |
| `Raster` / `GeoGrid` | 34 / 29 | Georeferenced arrays shared by fetch, layers and routing |
| `AskContext` / `answer()` | 27 / 23 | Voice questions |

## Rebuild it

```bash
pip install graphifyy
graphify update .          # re-extracts the code; no API key needed
```
