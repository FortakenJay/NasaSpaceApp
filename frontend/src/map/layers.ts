// Names of the map's built-in layers (raster overlays from /api/layers are added after these).
export const BASE_LAYERS = ['HiRISE basemap', 'Stops', 'Straight legs (placeholder)', 'Planned route'] as const;
export type BaseLayerName = (typeof BASE_LAYERS)[number];
export const PLACEHOLDER_LEGS: BaseLayerName = 'Straight legs (placeholder)';
