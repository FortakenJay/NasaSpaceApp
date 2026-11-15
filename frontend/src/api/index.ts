// Public surface of the API layer. Components import hooks, types and errors from here; never endpoints/client.
export { ApiError, OfflineError } from './client';
export { describeError } from './errors';
export {
  createQueryClient,
  useAddObservation,
  useAddStop,
  useAsk,
  useSimFine,
  useSimSun,
  useSimTerrain,
  useWalkHome,
  useComputePlan,
  useDeleteStop,
  useLayers,
  useObservations,
  useRefreshSources,
  usePlans,
  useSavePlan,
  useSite,
  useSources,
  useSpaceWeather,
  useUpdateStop,
} from './queries';
export { einkLiveUrl, einkUrl, simTextureUrl } from './endpoints';
export type * from './types';
