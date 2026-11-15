// One typed function per server route. Components never call these directly: they use the hooks in queries.ts.
import { OfflineError, request, staticJson } from './client';
import type {
  AskAnswer,
  AskRequest,
  LayerInfo,
  NewObservation,
  NewStop,
  Observation,
  PlanRequest,
  PlanResult,
  SavePlanRequest,
  SavedPlan,
  SiteData,
  SitePayload,
  SourcesInfo,
  SpaceWeatherStatus,
  Stop,
  StopPatch,
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
export const getSources = () => request<SourcesInfo>('/api/sources');
export const refreshSources = () =>
  request<{ status: SpaceWeatherStatus; sources: SourcesInfo }>('/api/sources/refresh', { method: 'POST' });
/** The suit display (e-ink, 800 x 480) at a moment of a plan, as an image URL (an <img> loads it). */
export const einkUrl = (planId: string, elapsedH: number) =>
  `/api/eink.png?plan_id=${enc(planId)}&elapsed_h=${elapsedH.toFixed(3)}`;
export const ask = (req: AskRequest) => request<AskAnswer>('/api/ask', { method: 'POST', json: req });
export const computePlan = (req: PlanRequest) => request<PlanResult>('/api/plan', { method: 'POST', json: req });

export const listPlans = () => request<SavedPlan[]>('/api/plans');
export const savePlan = (req: SavePlanRequest) => request<SavedPlan>('/api/plans', { method: 'POST', json: req });

export const addStop = (stop: NewStop) => request<Stop>('/api/stops', { method: 'POST', json: stop });
export const updateStop = ({ id, ...patch }: StopPatch) =>
  request<Stop>(`/api/stops/${enc(id)}`, { method: 'PATCH', json: patch });
export const deleteStop = (id: string) => request<{ deleted: string }>(`/api/stops/${enc(id)}`, { method: 'DELETE' });

export const listObservations = (stopId: string) => request<Observation[]>(`/api/stops/${enc(stopId)}/observations`);
export const addObservation = (stopId: string, obs: NewObservation) =>
  request<Observation>(`/api/stops/${enc(stopId)}/observations`, { method: 'POST', json: obs });
