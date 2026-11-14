// Public surface of the API layer. Components import hooks, types and errors from here; never endpoints/client.
export { ApiError, OfflineError } from './client';
export { describeError } from './errors';
export {
  createQueryClient,
  useAddObservation,
  useComputePlan,
  useLayers,
  useObservations,
  usePlans,
  useSavePlan,
  useSite,
  useSpaceWeather,
} from './queries';
export type * from './types';
