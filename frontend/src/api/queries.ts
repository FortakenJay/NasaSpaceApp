// TanStack Query hooks: the interface components use for ALL server data (reads and writes).
import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from './client';
import * as api from './endpoints';
import type { AskRequest, NewObservation, NewStop, PlanRequest, SavePlanRequest, StopPatch } from './types';

export const queryKeys = {
  site: ['site'] as const,
  layers: ['layers'] as const,
  status: ['status'] as const,
  sources: ['sources'] as const,
  plans: ['plans'] as const,
  observations: (stopId: string) => ['observations', stopId] as const,
};

/** Don't retry answers the server meant (4xx, 501 not-built); retry transient failures twice. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 600 && error.status !== 503) return false;
  return failureCount < 2;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

export function useSite() {
  return useQuery({ queryKey: queryKeys.site, queryFn: api.getSite, staleTime: Infinity });
}

export function useLayers(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.layers, queryFn: api.getLayers, enabled, staleTime: 60_000 });
}

export function useSpaceWeather(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.status, queryFn: api.getStatus, enabled, staleTime: 5 * 60_000 });
}

/** How the server is using NASA's APIs (cache, saved requests, request budget). Follows the status check. */
export function useSources(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.sources, queryFn: api.getSources, enabled, staleTime: 15_000 });
}

/** "Ask NASA again now": bypasses the cache and any back-off, then updates both panels. */
export function useRefreshSources() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.refreshSources(),
    onSuccess: (r) => {
      qc.setQueryData(queryKeys.status, r.status);
      qc.setQueryData(queryKeys.sources, r.sources);
    },
  });
}

/** The walk area as a 3-D height grid, for the simulator. Loaded once per session. */
export function useSimTerrain(step: number, enabled: boolean) {
  return useQuery({ queryKey: ['sim-terrain', step], queryFn: () => api.getSimTerrain(step), enabled, staleTime: Infinity });
}

/** The 1 m walking grid (walk surface, terrain, roughness, sand, off-limits, radio shadow) for the simulator. `url`
 * comes from the terrain package (it carries the layout version), so the grid loads once that has. */
export function useSimFine(url: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['sim-fine', url],
    queryFn: () => api.getSimFine(url as string),
    enabled: enabled && url !== null,
    staleTime: Infinity,
  });
}

/** The Sun's path through the walk, starting at the next configured local morning at the rover. */
export function useSimSun(enabled: boolean) {
  return useQuery({ queryKey: ['sim-sun'], queryFn: api.getSimSun, enabled, staleTime: Infinity });
}

/** The walk home from a walker's position, refreshed as they move (position rounded to ~5 m, time to 1 min). */
export function useWalkHome(lat: number | null, lon: number | null, elapsedH: number, enabled: boolean) {
  const key = lat === null || lon === null ? null : [Math.round(lat * 12000), Math.round(lon * 12000), Math.round(elapsedH * 60)];
  return useQuery({
    queryKey: ['walk-home', key],
    queryFn: () => api.getWalkHome(lat as number, lon as number, elapsedH),
    enabled: enabled && key !== null,
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  });
}

/** Ask the plan a question ("how far is S3 from here?"). Nothing is cached: each question is answered fresh. */
export function useAsk() {
  return useMutation({ mutationFn: (req: AskRequest) => api.ask(req) });
}

/** Computing a plan stores it server-side (M4: POST /api/plan persists the result as a saved plan),
 *  so the saved-plans list is refreshed afterwards. */
export function useComputePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: PlanRequest) => api.computePlan(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plans }),
  });
}

export function usePlans(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.plans, queryFn: api.listPlans, enabled });
}

export function useSavePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: SavePlanRequest) => api.savePlan(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plans }),
  });
}

/** Stops the crew adds on the map are saved server-side; the site (and its stop list) is reloaded afterwards. */
export function useAddStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stop: NewStop) => api.addStop(stop),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.site }),
  });
}

export function useUpdateStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: StopPatch) => api.updateStop(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.site }),
  });
}

export function useDeleteStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteStop(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.site }),
  });
}

export function useObservations(stopId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.observations(stopId ?? ''),
    queryFn: () => api.listObservations(stopId as string),
    enabled: enabled && stopId !== null,
  });
}

export function useAddObservation(stopId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (obs: NewObservation) => api.addObservation(stopId, obs),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.observations(stopId) }),
  });
}
