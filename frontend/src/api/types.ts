// Wire types. Mirror of src/marswalk/export/payload.py, src/marswalk/db/repo.py and src/marswalk/api/app.py.

export type CostModel = 'metabolic' | 'weighted';
export type StopOrder = 'fixed' | 'optimize';

export interface Stop {
  id: string;
  name: string;
  lat: number;
  lon: number;
  /** 'user' = added on the map by the crew (saved in the database, can be moved, renamed and removed). */
  kind: 'start' | 'stop' | 'user';
  science: string;
  work_time_min: number;
  dtm_z_m?: number | null;
}

export interface TileSource {
  url_template: string;
  max_zoom: number;
  /** Pixels per tile: 256 on Mars Trek, 512 on the global astro.arcgis mosaics. */
  tile_size?: number;
}

export interface BBox {
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
}

export interface Alignment {
  source: string;
  quality: 'good' | 'fair' | 'coarse' | 'weak' | 'none';
  east_m: number;
  north_m: number;
  corr?: number | null;
  spread_m?: number | null;
}

export interface RadiationInfo {
  gcr_mgy_per_day: number;
  dose_eq_msv_per_day: number;
  /** false = measured on the ground (Gale); true = estimated for this Base's elevation. */
  estimate: boolean;
  note: string;
}

export interface Site {
  id: string;
  name: string;
  bbox: BBox;
  radius_m: number;
  basemap: TileSource;
  /** Wider imagery drawn under the basemap (bottom first), so the map is never empty when zoomed out. */
  context?: (TileSource & { name: string })[];
  terrain_id?: string;
  alignment?: Alignment | null;
  radiation?: RadiationInfo;
  /** Plain-language caveats about this Base's data (e.g. weak alignment). */
  warnings?: string[];
}

export type BaseStatus = 'creating' | 'ready' | 'failed' | 'interrupted';

export interface BaseInfo {
  id: string;
  name: string;
  kind: 'builtin' | 'user';
  status: BaseStatus;
  lat: number;
  lon: number;
  base_lat?: number;
  base_lon?: number;
  bbox?: BBox;
  product_id?: string;
  terrain_name?: string;
  scale_m?: number | null;
  elevation_m?: number;
  alignment?: Alignment | null;
  radiation?: RadiationInfo;
  warnings?: string[];
  size_bytes?: number;
  created_at?: string | null;
  error?: string | null;
  deletable: boolean;
}

export interface BaseJobStep {
  key: string;
  label: string;
  state: 'pending' | 'running' | 'done' | 'skipped' | 'warning' | 'failed';
  detail: string;
}

export interface BaseJob {
  base_id: string;
  name: string;
  lat: number;
  lon: number;
  status: 'running' | 'ready' | 'failed' | 'cancelled';
  step: string;
  steps: BaseJobStep[];
  fraction: number;
  elapsed_s: number;
  error: string | null;
}

export interface BasesPayload {
  focused: string;
  bases: BaseInfo[];
  job: BaseJob | null;
}

export interface BaseLookup {
  lat: number;
  lon: number;
  bbox: BBox;
  ti_tile: string | null;
  warnings: string[];
  est_bytes: number;
  free_bytes: number;
  candidates: { product_id: string; name: string; scale_m: number; edge_m: number }[];
}

export interface NewBase {
  lat: number;
  lon: number;
  name?: string;
  product_id?: string;
}

/** HiRISE stereo terrain footprints (GeoJSON polygons, lon/lat). */
export interface FootprintCollection {
  type: 'FeatureCollection';
  features: {
    type: 'Feature';
    id: string;
    properties: { product_id: string; scale_m: number; supported: boolean; reason: string; name: string };
    geometry: { type: 'Polygon'; coordinates: number[][][] };
  }[];
}

/** EVA limits from the server config, for labels and the safe-zone slider. */
export interface EvaLimits {
  /** Hours that may be spent before the walk-home reserve is touched. */
  usable_h: number;
  max_duration_h: number;
  reserve_frac: number;
  time_margin_factor: number;
  max_distance_from_rover_m: number;
}

export interface SitePayload {
  site: Site;
  stops: Stop[];
  /** Absent in the static offline sample. */
  eva?: EvaLimits;
  /** Version and folder of the planner service that answered (absent offline and on old services). */
  api_version?: string;
  project_root?: string;
}

/** SitePayload plus where it came from: the live API, or the static sample when the API is down. */
export interface SiteData extends SitePayload {
  live: boolean;
}

export interface NewStop {
  lat: number;
  lon: number;
  name?: string;
}

export interface StopPatch {
  id: string;
  lat?: number;
  lon?: number;
  name?: string;
}

export interface LayerInfo {
  name: string;
  /** Stable id of the overlay: hillshade | slope5 | roughness | ti | nogo | safezone | radio | shelter. */
  key: string;
  url: string;
  bounds: [number, number, number, number]; // lon_min, lat_min, lon_max, lat_max
  opacity?: number;
  /** One sentence about what this layer shows on this terrain. */
  note?: string;
}

export interface PlanRequest {
  cost?: CostModel;
  order?: StopOrder;
  stop_ids?: string[];
  /** Click-to-plan: ad-hoc stops instead of stop_ids (not saved server-side). */
  points?: { lat: number; lon: number; name?: string; work_time_min?: number }[];
}

export interface TimelineEntry {
  id: string;
  name: string;
  kind: 'start' | 'stop' | 'end';
  lat: number;
  lon: number;
  arrive_min: number;
  depart_min: number;
  walkback_min: number;
  walkback_kj: number;
  energy_used_kj: number;
}

/** Arrays of equal length sampled along the route (null where a value is unknown). */
export type RouteProfile = Record<
  'dist_m' | 'elev_m' | 'slope_deg' | 't_min' | 'energy_kj' | 'walkback_min' | 'walkback_kj' | 'margin_min',
  (number | null)[]
>;

/** POST /api/plan (answers 409 until `marswalk fetch` has cached the terrain). */
export interface PlanResult {
  route: GeoJSON.FeatureCollection;
  summary: Record<string, string | number>;
  timeline: TimelineEntry[];
  profile: Partial<RouteProfile>;
  violations: { rule: string; severity: 'no-go' | 'caution'; detail: string; where: string }[];
  plan_id?: string;
}

export interface SavePlanRequest {
  name?: string;
  cost: CostModel;
  order: StopOrder;
  stop_ids: string[];
}

export interface SavedPlan {
  id: string;
  site_id: string;
  created_at: string;
  name: string;
  cost_model: CostModel;
  stop_order: StopOrder;
  stop_ids: string[];
  status: 'requested' | 'computed' | 'failed';
  result: PlanResult | null;
}

export interface Observation {
  id: number;
  stop_id: string;
  created_at: string;
  author: string;
  note: string;
  sample_id: string | null;
}

export interface NewObservation {
  note: string;
  author?: string;
  sample_id?: string;
}

export interface SpaceWeatherStatus {
  level: 'GO' | 'CAUTION' | 'NO-GO';
  reason: string;
  baseline_dose_mgy_per_day: number;
  eva_dose_mgy: number;
  eva_duration_h: number;
  recent_sep_events: number;
  /** CME shock arrivals predicted at Mars by DONKI's WSA-ENLIL runs (past 24 h to 7 days ahead). */
  mars_arrivals: { arrival: string; glancing: boolean; hours_from_now: number }[];
  strongest_flare: string;
  checked_at: string;
  source: string;
  data_ok: boolean;
  /** Plain remarks, e.g. a saved copy was used or the flare list is late. */
  notes: string[];
}

/** POST /api/ask: a question in plain words, answered from the plan on screen. */
export interface AskRequest {
  question: string;
  plan_id?: string | null;
  /** "Here" is this stop when one is selected on the map... */
  selected_stop_id?: string | null;
  /** ...otherwise the planned position this many hours into the walk (0 = the rover). */
  elapsed_h?: number;
  /** A walker's actual position (the simulator). Overrides both. */
  here_lat?: number;
  here_lon?: number;
  /** Stops already done, so "the next stop" skips them. */
  visited?: string[];
}

/** GET /api/sim/terrain: the walk area as a height grid in local metres (origin = rover, x east, z south). */
export interface SimTerrain {
  lat0: number;
  lon0: number;
  /** Metres per degree of longitude / latitude: x = (lon - lon0) * kx, z = -(lat - lat0) * kz. */
  kx: number;
  kz: number;
  rows: number;
  cols: number;
  /** Centre of cell (row 0, col 0) and the cell spacing, in local metres. */
  x0: number;
  dx: number;
  z0: number;
  dz: number;
  /** Height of 0 cm, relative to the rover. */
  h0: number;
  /** Where the heights are (GET /api/sim/terrain.bin): uint16 LE cm above h0 | off-limits bits, row-major, MSB first. */
  heights: { url: string; layout: string };
  terrain_source: string;
  /** The 1 m walking grid the physics reads (GET /api/sim/fine.bin), at the planner's own resolution. */
  fine: SimFineMeta;
  physics: SimPhysics;
}

/** SimTerrain with its heights binary already fetched (what useSimTerrain returns). */
export interface SimTerrainData extends SimTerrain {
  heightsBin: ArrayBuffer;
}

/**
 * Shape and frame of /api/sim/fine.bin: walk heights uint16 LE (cm) | terrain heights uint16 LE (cm) | roughness
 * uint8 (cm) | sand bits | off-limits bits | radio-shadow bits. Both height grids are cm above h0.
 */
export interface SimFineMeta {
  rows: number;
  cols: number;
  x0: number;
  dx: number;
  z0: number;
  dz: number;
  /** Height of 0 cm, relative to the rover. */
  h0: number;
  height_unit_m: number;
  rough_unit_m: number;
  /** Where the grid is: GET /api/sim/fine.bin with a version that changes with the layout and the data. */
  url: string;
}

/** GET /api/sim/sun: the Sun through the walk (Mars24), azimuth clockwise from north and elevation, in degrees. */
export interface SimSun {
  start_utc: string;
  ls_deg: number;
  lmst_h: number;
  ltst_h: number;
  /** Sol number at the rover (Mars Sol Date counted in local mean solar time). */
  sol?: number;
  step_min: number;
  az_el: [number, number][];
}

export interface SimPhysics {
  gravity_mps2: number;
  body_mass_kg: number;
  suit_mass_kg: number;
  max_grade_deg: number;
  /** Gait limit: walking speed cap at the walk-run transition (m/s), null when off. */
  walk_speed_cap_mps?: number | null;
  /** Warning before a solar storm's dose arrives (min): beyond this walk home, the rover is out of reach. */
  sep_warning_lead_min?: number;
  /** Planner's multipliers on walking time: x (1 + this * roughness in m), and x sand_penalty on loose sand. */
  roughness_penalty_per_m: number;
  sand_penalty: number;
  /** Walk start, local mean solar time (hours). */
  start_lmst_h: number;
  work_power_w: number;
  o2_capacity_h: number;
  walkback_reserve_frac: number;
  metabolic_budget_kj: number;
  time_margin_factor: number;
  rad_mgy_per_day: number;
  rad_msv_per_day: number;
}

/** GET /api/walkback: the walk home from a point. */
export interface WalkHome {
  reachable: boolean;
  safe: boolean;
  walkback_min?: number;
  walkback_kj?: number;
  margin_min?: number;
  route: GeoJSON.Feature | null;
}

/** The suit display for a walker's actual state. */
export interface LiveState {
  planId: string;
  elapsedH: number;
  lat: number;
  lon: number;
  walkedM: number;
  energyKj: number;
  visited: string[];
}

export interface AskAnswer {
  question: string;
  answer: string;
  /** The same answer with units spelled out, for text-to-speech. */
  speech: string;
  topics: string[];
  /** What "here" meant, and whether this answer used it. */
  here: { label: string; lat: number; lon: number; used: boolean };
  /** Route and points the answer is about, to draw on the map. */
  highlight: GeoJSON.FeatureCollection | null;
  /** A stop this answer can make the next stop on the walk, when the question asked for a path. */
  go_to: { id: string; label: string } | null;
}

export interface SourceFeed {
  name: string;
  label: string;
  required: boolean;
  /** fresh = just asked; cached = reused within 30 min; stale = old copy because NASA did not answer; missing = nothing yet. */
  state: 'fresh' | 'cached' | 'stale' | 'missing';
  error: string;
  /** The error as one plain sentence. */
  problem?: string;
  age_s: number | null;
  fresh_for_s: number | null;
  retry_in_s: number | null;
}

/** GET /api/sources: how the central API client is using NASA's services. */
export interface SourcesInfo {
  feeds: SourceFeed[];
  stats: Record<'requests_sent' | 'served_from_cache' | 'served_stale' | 'skipped_backing_off' | 'skipped_low_budget' | 'failed', number>;
  rate_limit: { limit: number | null; remaining: number | null };
  key: 'personal' | 'demo';
  key_env: string;
}
