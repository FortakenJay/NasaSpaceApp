// TanStack Query hooks: the interface components use for ALL server data (reads and writes).
import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from './client';
import * as api from './endpoints';
import type { NewObservation, PlanRequest, SavePlanRequest } from './types';

export const queryKeys = {
  site: ['site'] as const,
  layers: ['layers'] as const,
  status: ['status'] as const,
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
