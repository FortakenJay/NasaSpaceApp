// One typed function per server route. Components never call these directly: they use the hooks in queries.ts.
import { OfflineError, request, requestBytes, staticJson } from './client';
import type {
  AskAnswer,
  AskRequest,
  BaseJob,
  BaseLookup,
  BasesPayload,
  FootprintCollection,
  NewBase,
  LayerInfo,
  LiveState,
  SimSun,
  SimTerrain,
  SimTerrainData,
  WalkHome,
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
/** The 3 m mesh: its frame and physics constants (JSON), with the heights and off-limits bits it points to (binary). */
export async function getSimTerrain(step: number): Promise<SimTerrainData> {
  const meta = await request<SimTerrain>(`/api/sim/terrain?step=${step}`);
  return { ...meta, heightsBin: await requestBytes(meta.heights.url) };
}
export const getSimFine = (url: string) => requestBytes(url);
export const getSimSun = () => request<SimSun>('/api/sim/sun');
/** The simulator's ground texture (photo or off-limits overlay), as an image URL for three.js to load. The Base id is
 * in the URL so the browser never reuses another Base's cached texture. */
export const simTextureUrl = (kind: 'photo' | 'hazard', step: number, baseId = '') =>
  `/api/sim/texture.png?kind=${kind}&step=${step}&b=${enc(baseId)}`;
export const getWalkHome = (lat: number, lon: number, elapsedH: number) =>
  request<WalkHome>(`/api/walkback?lat=${lat.toFixed(7)}&lon=${lon.toFixed(7)}&elapsed_h=${elapsedH.toFixed(3)}`);
/** The suit display following a walker's actual position, as an image URL. */
export const einkLiveUrl = (s: LiveState) =>
  `/api/eink.png?plan_id=${enc(s.planId)}&elapsed_h=${s.elapsedH.toFixed(3)}&lat=${s.lat.toFixed(7)}&lon=${s.lon.toFixed(7)}` +
  `&walked_m=${s.walkedM.toFixed(0)}&energy_kj=${s.energyKj.toFixed(0)}&visited=${enc(s.visited.join(','))}`;
export const ask = (req: AskRequest) => request<AskAnswer>('/api/ask', { method: 'POST', json: req });
export const computePlan = (req: PlanRequest) => request<PlanResult>('/api/plan', { method: 'POST', json: req });

export const listPlans = () => request<SavedPlan[]>('/api/plans');
export const savePlan = (req: SavePlanRequest) => request<SavedPlan>('/api/plans', { method: 'POST', json: req });

export const addStop = (stop: NewStop) => request<Stop>('/api/stops', { method: 'POST', json: stop });
export const updateStop = ({ id, ...patch }: StopPatch) =>
  request<Stop>(`/api/stops/${enc(id)}`, { method: 'PATCH', json: patch });
export const deleteStop = (id: string) => request<{ deleted: string }>(`/api/stops/${enc(id)}`, { method: 'DELETE' });

export const listBases = () => request<BasesPayload>('/api/bases');
export const getBaseJob = () => request<BaseJob | null>('/api/bases/job');
export const createBase = (b: NewBase) => request<BaseJob>('/api/bases', { method: 'POST', json: b });
export const cancelBase = (id: string) =>
  request<{ cancelled: boolean }>(`/api/bases/${enc(id)}/cancel`, { method: 'POST' });
export const resumeBase = (id: string) => request<BaseJob>(`/api/bases/${enc(id)}/resume`, { method: 'POST' });
export const focusBase = (id: string) => request<BasesPayload>('/api/bases/focus', { method: 'POST', json: { id } });
export const deleteBase = (id: string) => request<BasesPayload>(`/api/bases/${enc(id)}`, { method: 'DELETE' });
export const getFootprints = () => request<FootprintCollection>('/api/catalog/footprints');
export const lookupBase = (lat: number, lon: number) =>
  request<BaseLookup>(`/api/catalog/lookup?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`);

export const listObservations = (stopId: string) => request<Observation[]>(`/api/stops/${enc(stopId)}/observations`);
export const addObservation = (stopId: string, obs: NewObservation) =>
  request<Observation>(`/api/stops/${enc(stopId)}/observations`, { method: 'POST', json: obs });
