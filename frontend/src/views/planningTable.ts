// M6: Habitat planning table, a 3-D view with CesiumJS. Not installed yet; this file is the spec.
//
// Plan:
// - Add `cesium` + `vite-plugin-cesium` (copies Cesium's static assets). Mount as a second view
//   (route "/table") next to the 2-D OpenLayers map, sharing api.ts and the same payloads.
// - Mars globe: `new Cesium.Ellipsoid(3396190, 3396190, 3396190)` passed to the Globe and the
//   GeographicTilingScheme. Mars Trek's geographic tiles plug in as a
//   `UrlTemplateImageryProvider({ url, tilingScheme: new GeographicTilingScheme({ ellipsoid }) })`.
// - Terrain: serve the cached 1 m DTM window from the API as a heightmap
//   (`/api/terrain/{z}/{x}/{y}` via a CustomHeightmapTerrainProvider) so the route drapes on real relief.
// - Timeline: Cesium's clock plays the EVA plan (waypoint arrive/depart times from PlanResponse)
//   with sun direction for the chosen sol, matching the "planning table" idea in the plan.
export {};
