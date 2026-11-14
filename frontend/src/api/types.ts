// Wire types. Mirror of src/marswalk/export/payload.py, src/marswalk/db/repo.py and src/marswalk/api/app.py.

export type CostModel = 'metabolic' | 'weighted';
export type StopOrder = 'fixed' | 'optimize';

export interface Stop {
  id: string;
  name: string;
  lat: number;
  lon: number;
  kind: 'start' | 'stop';
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
}

export interface SitePayload {
  site: Site;
  stops: Stop[];
}

/** SitePayload plus where it came from: the live API, or the static sample when the API is down. */
export interface SiteData extends SitePayload {
  live: boolean;
}

export interface LayerInfo {
  name: string;
  url: string;
  bounds: [number, number, number, number]; // lon_min, lat_min, lon_max, lat_max
  opacity?: number;
}

export interface PlanRequest {
  cost?: CostModel;
  order?: StopOrder;
  stop_ids?: string[];
}

/** M4 shape (POST /api/plan answers 501 until then). */
export interface PlanResult {
  route: GeoJSON.FeatureCollection;
  summary: Record<string, string | number>;
  violations: { rule: string; severity: 'no-go' | 'caution'; detail: string; where: string }[];
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
}
