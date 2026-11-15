# Graph Report - gfy  (2026-11-15)

## Corpus Check
- 79 files · ~44,075 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 2 file(s) not represented in the graph (top: .ino 1, .css 1)

## Summary
- 857 nodes · 2323 edges · 40 communities (28 shown, 12 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 131 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- test_pipeline.py
- create_app
- api_client.py
- ask.py
- endpoints.ts
- eink.py
- test_pure_logic.py
- test_merged_dem.py
- Raster
- MarsMap.tsx
- app.py
- cli.py
- numpy
- App.tsx
- test_api.py
- PlanResult.tsx
- index.ts
- GeoGrid
- AskPanel.tsx
- raster.py
- fetch.py
- SiteConfig
- EVAConfig
- load_site
- config.py
- conftest.py
- test_geo.py
- main.tsx
- geojson.d.ts
- Recognition
- nogo_mask
- README.md

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 67 edges
2. `build_stack()` - 44 edges
3. `load_site()` - 35 edges
4. `build_plan()` - 35 edges
5. `Raster` - 34 edges
6. `GeoGrid` - 29 edges
7. `SiteConfig` - 28 edges
8. `AskContext` - 27 edges
9. `App()` - 24 edges
10. `answer()` - 23 edges

## Surprising Connections (you probably didn't know these)
- `test_added_stops_are_saved_moved_planned_and_removed()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_api.py → marswalk/api/app.py
- `test_plan_layers_and_walkback_on_synthetic_terrain()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_api.py → marswalk/api/app.py
- `synthetic_site()` --uses--> `GeoGrid`  [INFERRED]
  tests/conftest.py → marswalk/geo.py
- `dtm_grid()` --uses--> `GeoGrid`  [INFERRED]
  tests/test_geo.py → marswalk/geo.py
- `synthetic_site()` --uses--> `Raster`  [INFERRED]
  tests/conftest.py → marswalk/geo.py

## Import Cycles
- None detected.

## Communities (40 total, 12 thin omitted)

### Community 0 - "test_pipeline.py"
Cohesion: 0.05
Nodes (36): Stop, CostModel, get_cost_model(), model_from_eva(), kernel(), MetabolicCostModel, edge_time_energy(), metabolic_power_w() (+28 more)

### Community 1 - "create_app"
Cohesion: 0.05
Nodes (56): create_app(), add_observation(), add_stop(), _api_key(), ask(), stack(), compute_plan(), delete_stop() (+48 more)

### Community 2 - "api_client.py"
Cohesion: 0.06
Nodes (22): ApiClient, fallback(), without_waiting(), _connect_ipv4(), Fetched, http_get(), _IPv4HTTPSConnection, _IPv4HTTPSHandler (+14 more)

### Community 3 - "ask.py"
Cohesion: 0.11
Nodes (43): answer(), answer_energy(), answer_limits(), answer_oxygen(), answer_radiation(), answer_route(), answer_stops(), answer_terrain() (+35 more)

### Community 4 - "endpoints.ts"
Cohesion: 0.09
Nodes (38): ApiError, ErrorBody, parseError(), request(), staticJson(), addObservation(), addStop(), ask() (+30 more)

### Community 5 - "eink.py"
Cohesion: 0.09
Nodes (26): eink_bin(), _along_route(), position_at(), _arrow(), _bearing(), _bold(), _compass(), _display() (+18 more)

### Community 6 - "test_pure_logic.py"
Cohesion: 0.10
Nodes (16): order_stops(), tour_cost(), current_status(), eva_dose_mgy(), feed_requests(), _flare_rank(), go_no_go(), mars_arrivals() (+8 more)

### Community 7 - "test_merged_dem.py"
Cohesion: 0.10
Nodes (17): register(), shifted(), usable(), build_stack(), raw_stamp(), steep_fraction(), sand_flag(), read_geotiff() (+9 more)

### Community 8 - "Raster"
Cohesion: 0.13
Nodes (10): Raster, agreement(), _crop(), hires_footprint(), _plane_removed(), _gauss_nan(), roughness(), slope() (+2 more)

### Community 9 - "MarsMap.tsx"
Cohesion: 0.12
Nodes (22): LayerInfo, Site, Stop, Props, StopList(), BASE_LAYERS, BaseLayerName, MAX_ADDED_STOPS (+14 more)

### Community 10 - "app.py"
Cohesion: 0.10
Nodes (9): AskIn, get_session(), _not_built(), ObservationIn, PlanRequest, PointIn, SavePlanRequest, StopIn (+1 more)

### Community 11 - "cli.py"
Cohesion: 0.14
Nodes (15): _client(), build_parser(), cmd_info(), cmd_serve(), main(), _run_fetch(), _run_layers(), _run_plan() (+7 more)

### Community 12 - "numpy"
Cohesion: 0.19
Nodes (15): get_layer(), _alpha(), bounds_lonlat(), _colorize(), coverage_note(), layer_list(), layer_notes(), layer_png() (+7 more)

### Community 13 - "App.tsx"
Cohesion: 0.14
Nodes (18): useLayers(), usePlans(), useSite(), CostModel, StopOrder, App(), NO_OVERLAYS, VIEW_LABELS (+10 more)

### Community 14 - "test_api.py"
Cohesion: 0.10
Nodes (6): client(), test_a_late_flare_list_does_not_block_a_go(), test_added_stops_are_saved_moved_planned_and_removed(), test_plan_layers_and_walkback_on_synthetic_terrain(), test_status_uses_mars_cme_arrivals_and_the_central_cache(), nasa()

### Community 15 - "PlanResult.tsx"
Cohesion: 0.17
Nodes (16): einkUrl(), PlanResult, RouteProfile, TimelineEntry, PlanResult(), Props, RULE_NAMES, RouteProfileChart() (+8 more)

### Community 16 - "index.ts"
Cohesion: 0.21
Nodes (14): OfflineError, describeError(), useAddObservation(), useObservations(), useRefreshSources(), useSources(), useSpaceWeather(), SourceFeed (+6 more)

### Community 18 - "AskPanel.tsx"
Cohesion: 0.21
Nodes (15): useAsk(), AskPanel(), EXAMPLES, Props, canListen(), canSpeak(), ERRORS, listen() (+7 more)

### Community 19 - "raster.py"
Cohesion: 0.16
Nodes (7): bbox_window(), read_bbox(), _source(), _to_float(), vsicurl(), write_geotiff(), test_geotiff_roundtrip_and_bbox_window()

### Community 20 - "fetch.py"
Cohesion: 0.17
Nodes (6): fetch_site(), record(), raw_dir(), read_merged_dem(), _sha256(), download()

### Community 21 - "SiteConfig"
Cohesion: 0.28
Nodes (11): Check, check_constants(), check_plan(), check_terrain(), _close(), markdown(), run(), _run_audit() (+3 more)

### Community 22 - "EVAConfig"
Cohesion: 0.27
Nodes (9): get_site(), EVAConfig, check_distance_from_rover(), check_duration(), check_plan(), check_walkback_reserve(), Violation, usable_budgets() (+1 more)

### Community 23 - "load_site"
Cohesion: 0.23
Nodes (10): _stub(), run(), load_eva(), load_site(), test_constants_match_their_sources(), test_all_points_inside_bbox(), test_eva_defaults(), test_required_products_present() (+2 more)

### Community 24 - "config.py"
Cohesion: 0.27
Nodes (6): cmd_export(), load_stops(), _resolve(), site_payload(), write_json(), Path

### Community 25 - "conftest.py"
Cohesion: 0.20
Nodes (3): isolated_data(), no_network(), synthetic_site()

### Community 26 - "test_geo.py"
Cohesion: 0.39
Nodes (8): dtm_grid(), test_bbox_window_covers_all_stops(), test_ground_distance_h1_s1(), test_known_pixel_for_h1(), test_known_pixel_for_s3(), test_pixel_size_matches_mars_degrees(), test_roundtrip_pixel_centre(), test_window_offsets()

### Community 27 - "main.tsx"
Cohesion: 0.29
Nodes (3): createQueryClient(), shouldRetry(), queryClient

### Community 28 - "geojson.d.ts"
Cohesion: 0.33
Nodes (5): Feature, FeatureCollection, GeoJSON, LineString, Position

## Knowledge Gaps
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_app()` connect `create_app` to `test_pipeline.py`, `api_client.py`, `ask.py`, `eink.py`, `test_pure_logic.py`, `test_merged_dem.py`, `app.py`, `cli.py`, `numpy`, `test_api.py`, `SiteConfig`, `EVAConfig`, `load_site`, `config.py`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `create_app()` (e.g. with `_warm()` and `EVAConfig`) actually correct?**
  _`create_app()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_pipeline.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05471956224350205 - nodes in this community are weakly interconnected._
- **Why does `GeoGrid` connect `GeoGrid` to `test_pipeline.py`, `test_merged_dem.py`, `Raster`, `numpy`, `raster.py`, `fetch.py`, `conftest.py`, `test_geo.py`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `build_stack()` (e.g. with `EVAConfig` and `SiteConfig`) actually correct?**
  _`build_stack()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Should `create_app` be split into smaller, more focused modules?**
  _Cohesion score 0.05434173669467787 - nodes in this community are weakly interconnected._
- **Why does `build_stack()` connect `test_merged_dem.py` to `test_pipeline.py`, `create_app`, `ask.py`, `eink.py`, `Raster`, `app.py`, `cli.py`, `numpy`, `fetch.py`, `SiteConfig`, `EVAConfig`, `load_site`, `nogo_mask`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._