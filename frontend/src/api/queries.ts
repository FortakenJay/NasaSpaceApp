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
