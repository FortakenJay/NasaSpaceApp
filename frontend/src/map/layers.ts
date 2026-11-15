// Names of the map's built-in layers (raster overlays from /api/layers are added after these).
export const BASE_LAYERS = ['HiRISE basemap', 'Walk limit', 'Stops', 'Straight legs (placeholder)', 'Planned route'] as const;
export type BaseLayerName = (typeof BASE_LAYERS)[number];
export const PLACEHOLDER_LEGS: BaseLayerName = 'Straight legs (placeholder)';
export const WALK_LIMIT: BaseLayerName = 'Walk limit';
/** How many stops the crew may add on the map. */
export const MAX_ADDED_STOPS = 12;
