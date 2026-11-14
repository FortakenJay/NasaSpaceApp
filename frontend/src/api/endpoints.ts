// One typed function per server route. Components never call these directly: they use the hooks in queries.ts.
import { OfflineError, request, staticJson } from './client';
import type {
  LayerInfo,
  NewObservation,
  Observation,
  PlanRequest,
  PlanResult,
  SavePlanRequest,
  SavedPlan,
  SiteData,
  SitePayload,
  SpaceWeatherStatus,
} from './types';

const enc = encodeURIComponent;

export async function getSite(): Promise<SiteData> {
  try {
    return { ...(await request<SitePayload>('/api/site')), live: true };
  } catch (e) {
    if (!(e instanceof OfflineError)) throw e;
    // Backend not running: fall back to the static sample written by `marswalk export`.
    return { ...(await staticJson<SitePayload>('sample-site.json')), live: false };
  }
}

export const getLayers = () => request<LayerInfo[]>('/api/layers');
export const getStatus = () => request<SpaceWeatherStatus>('/api/status');
export const computePlan = (req: PlanRequest) => request<PlanResult>('/api/plan', { method: 'POST', json: req });

export const listPlans = () => request<SavedPlan[]>('/api/plans');
export const savePlan = (req: SavePlanRequest) => request<SavedPlan>('/api/plans', { method: 'POST', json: req });

export const listObservations = (stopId: string) => request<Observation[]>(`/api/stops/${enc(stopId)}/observations`);
export const addObservation = (stopId: string, obs: NewObservation) =>
  request<Observation>(`/api/stops/${enc(stopId)}/observations`, { method: 'POST', json: obs });
