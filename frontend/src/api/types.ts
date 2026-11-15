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

export interface Site {
  id: string;
  name: string;
  bbox: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
  radius_m: number;
  basemap: { url_template: string; max_zoom: number };
  /** Wider imagery drawn under the basemap (bottom first), so the map is never empty when zoomed out. */
  context?: { name: string; url_template: string; max_zoom: number }[];
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
  /** Stable id of the overlay: hillshade | slope5 | roughness | ti | nogo | safezone. */
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
