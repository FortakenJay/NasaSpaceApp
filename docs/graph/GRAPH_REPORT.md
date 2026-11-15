# Graph Report - MarsWalk  (2026-11-15)

## Corpus Check
- 88 files · ~58,272 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: .woff2 4, .ttf 3, .ino 1)

## Summary
- 1037 nodes · 2433 edges · 63 communities (40 shown, 23 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 348 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- load_site
- api_client.py
- create_app
- ask.py
- repo.py
- endpoints.ts
- eink.py
- SimEngine
- EVAConfig
- MarsMap.tsx
- App.tsx
- formatHours
- index.ts
- build_plan
- numpy
- raster.py
- engine.ts
- math
- app.py
- coverage.py
- status.py
- weighted.py
- GeoGrid
- sim.py
- SimulationView.tsx
- AskPanel.tsx
- geo.py
- astar.py
- test_pure_logic.py
- render.py
- pytest
- test_merged_dem.py
- test_pipeline.py
- test_geo.py
- LayerStack
- Terrain
- model_from_eva
- physics.py
- client.ts
- WalkGrid
- read_geotiff
- marswalk_geo
- main.tsx
- test_spaceweather_helpers
- geojson.d.ts
- Recognition
- get_session
- _not_built
- README.md

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 57 edges
2. `SimEngine` - 35 edges
3. `load_site()` - 28 edges
4. `Raster` - 27 edges
5. `build_plan()` - 27 edges
6. `build_stack()` - 26 edges
7. `AskContext` - 25 edges
8. `App()` - 25 edges
9. `SimulationView()` - 25 edges
10. `GeoGrid` - 23 edges

## Surprising Connections (you probably didn't know these)
- `test_ask_api_on_synthetic_terrain()` --calls--> `create_app()`  [INFERRED]
  tests/test_ask.py → backend/api/app.py
- `test_suit_display_png_and_packed_bits()` --calls--> `create_app()`  [INFERRED]
  tests/test_ask.py → backend/api/app.py
- `test_added_stops_are_saved_moved_planned_and_removed()` --calls--> `create_app()`  [INFERRED]
  tests/test_api.py → backend/api/app.py
- `test_plan_layers_and_walkback_on_synthetic_terrain()` --calls--> `create_app()`  [INFERRED]
  tests/test_api.py → backend/api/app.py
- `test_simulator_terrain_texture_live_eink_and_live_ask()` --calls--> `create_app()`  [INFERRED]
  tests/test_ask.py → backend/api/app.py

## Import Cycles
- None detected.

## Communities (63 total, 23 thin omitted)

### Community 0 - "load_site"
Cohesion: 0.05
Nodes (46): build_parser(), cmd_export(), cmd_info(), cmd_serve(), main(), _run_audit(), _run_fetch(), _run_layers() (+38 more)

### Community 1 - "api_client.py"
Cohesion: 0.05
Nodes (22): ApiClient, fallback(), without_waiting(), _connect_ipv4(), Fetched, http_get(), _IPv4HTTPSConnection, _IPv4HTTPSHandler (+14 more)

### Community 2 - "create_app"
Cohesion: 0.05
Nodes (36): create_app(), add_stop(), _api_key(), ask(), stack(), _client(), compute_plan(), _eink() (+28 more)

### Community 3 - "ask.py"
Cohesion: 0.09
Nodes (47): _along_route(), answer(), answer_energy(), answer_limits(), answer_oxygen(), answer_radiation(), answer_route(), answer_stops() (+39 more)

### Community 4 - "repo.py"
Cohesion: 0.08
Nodes (27): make_engine(), make_session_factory(), Base, _now(), Observation, Plan, Site, Stop (+19 more)

### Community 5 - "endpoints.ts"
Cohesion: 0.10
Nodes (38): request(), addStop(), ask(), computePlan(), deleteStop(), getLayers(), getSimSun(), getSimTerrain() (+30 more)

### Community 6 - "eink.py"
Cohesion: 0.10
Nodes (23): _arrow(), _bearing(), _bold(), _compass(), _display(), _dist(), _dist_at(), _dither_relief() (+15 more)

### Community 8 - "EVAConfig"
Cohesion: 0.16
Nodes (16): Check, check_constants(), check_plan(), check_terrain(), _close(), markdown(), run(), EVAConfig (+8 more)

### Community 9 - "MarsMap.tsx"
Cohesion: 0.12
Nodes (21): Site, Stop, Props, StopList(), BASE_LAYERS, BaseLayerName, MAX_ADDED_STOPS, PLACEHOLDER_LEGS (+13 more)

### Community 10 - "App.tsx"
Cohesion: 0.14
Nodes (19): useLayers(), usePlans(), useSite(), CostModel, StopOrder, App(), NO_OVERLAYS, SimulationView (+11 more)

### Community 11 - "formatHours"
Cohesion: 0.16
Nodes (18): einkUrl(), PlanResult, RouteProfile, TimelineEntry, PlanResult(), Props, RULE_NAMES, RouteProfileChart() (+10 more)

### Community 12 - "index.ts"
Cohesion: 0.17
Nodes (16): OfflineError, addObservation(), listObservations(), refreshSources(), describeError(), useAddObservation(), useObservations(), useRefreshSources() (+8 more)

### Community 13 - "build_plan"
Cohesion: 0.14
Nodes (11): get_site(), Field, build_plan(), EVAPlan, Leg, PlanError, _profile(), usable_budgets() (+3 more)

### Community 14 - "numpy"
Cohesion: 0.20
Nodes (11): Raster, _gauss_nan(), hillshade(), roughness(), slope(), steep_fraction(), walk_surface(), resample_to() (+3 more)

### Community 15 - "raster.py"
Cohesion: 0.13
Nodes (8): bbox_window(), download(), read_bbox(), _source(), _to_float(), vsicurl(), write_geotiff(), test_geotiff_roundtrip_and_bbox_window()

### Community 16 - "engine.ts"
Cohesion: 0.16
Nodes (12): Astronaut, makeAstronaut(), makeRover(), SimStatus, SimStop, TIME_SCALES, edgeTimeEnergy(), G_EARTH (+4 more)

### Community 17 - "math"
Cohesion: 0.26
Nodes (10): _cos(), jd_tt(), local_times(), next_lmst(), planetographic_lat(), _sin(), solar(), sun_position() (+2 more)

### Community 18 - "app.py"
Cohesion: 0.15
Nodes (7): AskIn, ObservationIn, PlanRequest, PointIn, SavePlanRequest, StopIn, StopPatch

### Community 19 - "coverage.py"
Cohesion: 0.14
Nodes (7): agreement(), _crop(), hires_footprint(), _plane_removed(), register(), shifted(), usable()

### Community 20 - "status.py"
Cohesion: 0.20
Nodes (8): current_status(), feed_requests(), _flare_rank(), go_no_go(), mars_arrivals(), parse_time(), SpaceWeatherStatus, test_go_no_go_rules()

### Community 21 - "weighted.py"
Cohesion: 0.15
Nodes (4): kernel(), MetabolicCostModel, kernel(), WeightedHazardCostModel

### Community 23 - "sim.py"
Cohesion: 0.21
Nodes (8): area(), _blocks(), _fill_nearest(), fine_bytes(), fine_meta(), _fine_window(), frame(), terrain_package()

### Community 24 - "SimulationView.tsx"
Cohesion: 0.24
Nodes (16): einkLiveUrl(), simTextureUrl(), useSimFine(), useSimSun(), useSimTerrain(), useWalkHome(), clock(), COMPASS (+8 more)

### Community 25 - "AskPanel.tsx"
Cohesion: 0.21
Nodes (15): useAsk(), AskPanel(), EXAMPLES, Props, canListen(), canSpeak(), ERRORS, listen() (+7 more)

### Community 26 - "geo.py"
Cohesion: 0.15
Nodes (3): isolated_data(), no_network(), synthetic_site()

### Community 27 - "astar.py"
Cohesion: 0.21
Nodes (9): _arrays(), astar(), cost_field(), _one_leg(), _search(), snap(), leg(), test_route_goes_through_the_gap_and_never_enters_nogo() (+1 more)

### Community 28 - "test_pure_logic.py"
Cohesion: 0.17
Nodes (5): order_stops(), tour_cost(), test_cost_models_switchable(), test_fixed_order_unchanged(), test_optimize_order_finds_cheaper_tour()

### Community 29 - "render.py"
Cohesion: 0.27
Nodes (7): _alpha(), _colorize(), layer_png(), overlay_step(), _png(), safezone_fraction(), safezone_png()

### Community 30 - "pytest"
Cohesion: 0.21
Nodes (7): test_simulator_terrain_texture_live_eink_and_live_ask(), test_config_stops_are_resynced_into_an_existing_database(), test_full_plan_timeline_margins_and_payload(), test_unknown_cost_model(), _centric(), test_mars24_worked_examples(), test_walk_start_and_track_at_gale()

### Community 31 - "test_merged_dem.py"
Cohesion: 0.22
Nodes (5): merged_site(), surface(), test_overlays_and_notes_show_the_two_kinds_of_terrain(), test_smoother_merged_dem_is_set_aside(), write_merged()

### Community 33 - "test_geo.py"
Cohesion: 0.33
Nodes (7): dtm_grid(), test_bbox_window_covers_all_stops(), test_known_pixel_for_h1(), test_known_pixel_for_s3(), test_pixel_size_matches_mars_degrees(), test_roundtrip_pixel_centre(), test_window_offsets()

### Community 34 - "LayerStack"
Cohesion: 0.29
Nodes (5): bounds_lonlat(), coverage_note(), layer_list(), layer_notes(), LayerStack

### Community 35 - "Terrain"
Cohesion: 0.29
Nodes (4): SimFineMeta, SimTerrain, b64(), Terrain

### Community 36 - "model_from_eva"
Cohesion: 0.31
Nodes (4): CostModel, get_cost_model(), model_from_eva(), test_routes_stay_on_trusted_terrain()

### Community 37 - "physics.py"
Cohesion: 0.36
Nodes (4): edge_time_energy(), metabolic_power_w(), walk_speed_mps(), test_walking_physics_is_directional_and_capped()

### Community 38 - "client.ts"
Cohesion: 0.28
Nodes (6): ApiError, ErrorBody, parseError(), requestBytes(), staticJson(), getSimFine()

### Community 40 - "read_geotiff"
Cohesion: 0.29
Nodes (4): read_geotiff(), _misregister_dtm(), test_configured_basemap_offset_puts_the_dtm_back_on_the_frame(), test_register_measures_a_georeferencing_offset()

### Community 42 - "main.tsx"
Cohesion: 0.29
Nodes (3): createQueryClient(), shouldRetry(), queryClient

### Community 43 - "test_spaceweather_helpers"
Cohesion: 0.33
Nodes (3): eva_dose_mgy(), split_range(), test_spaceweather_helpers()

### Community 44 - "geojson.d.ts"
Cohesion: 0.33
Nodes (5): Feature, FeatureCollection, GeoJSON, LineString, Position

## Knowledge Gaps
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_app()` connect `create_app` to `load_site`, `api_client.py`, `ask.py`, `repo.py`, `EVAConfig`, `build_plan`, `app.py`, `pytest`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `create_app()` (e.g. with `_warm()` and `AskContext`) actually correct?**
  _`create_app()` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Should `load_site` be split into smaller, more focused modules?**
  _Cohesion score 0.051582278481012656 - nodes in this community are weakly interconnected._
- **Why does `SiteConfig` connect `load_site` to `create_app`, `ask.py`, `repo.py`, `EVAConfig`, `build_plan`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `load_site()` (e.g. with `create_app()` and `cmd_export()`) actually correct?**
  _`load_site()` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Should `api_client.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05407925407925408 - nodes in this community are weakly interconnected._
- **Why does `Path` connect `load_site` to `api_client.py`, `repo.py`, `read_geotiff`, `build_plan`, `raster.py`, `astar.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._