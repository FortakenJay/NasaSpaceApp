// Mars geographic coordinates for OpenLayers.
//
// OpenLayers' built-in EPSG:4326 measures distance on Earth's radius, so the scale bar and any
// measurement would be wrong by ~1.9x on Mars. We register a Mars 2000 geographic projection
// (IAU_2015:49900: planetocentric, east-positive, sphere R = 3396190 m) with the correct metres per degree.
// Mars Trek tiles use geographic tiling (zoom 0 = two 180-degree tiles), so they get a matching tile grid.
import Projection from 'ol/proj/Projection';
import { addProjection } from 'ol/proj';
import TileGrid from 'ol/tilegrid/TileGrid';
import XYZ from 'ol/source/XYZ';

export const MARS_RADIUS_M = 3396190;
export const METERS_PER_DEGREE = (2 * Math.PI * MARS_RADIUS_M) / 360;

export const MARS_GEOGRAPHIC = new Projection({
  code: 'IAU_2015:49900',
  units: 'degrees',
  extent: [-180, -90, 180, 90],
  worldExtent: [-180, -90, 180, 90],
  global: true,
  metersPerUnit: METERS_PER_DEGREE,
  // Ground distance per pixel in projection units (degrees), measured north-south: a degree of latitude is the same
  // length everywhere, so the scale bar is right at any Base (east-west, a degree shrinks by cos(lat)).
  getPointResolution: (resolution: number) => resolution,
});
addProjection(MARS_GEOGRAPHIC);

/** Geographic tile grid: z0 = 2x1 tiles of 180 degrees. Mars Trek tiles are 256 px; the global astro.arcgis
 * HiRISE and CTX mosaics use the same tiles at 512 px (checked from their MapServer tileInfo). */
export function trekTileGrid(maxZoom: number, tileSize = 256): TileGrid {
  const resolutions = Array.from({ length: maxZoom + 1 }, (_, z) => 180 / tileSize / 2 ** z);
  return new TileGrid({ origin: [-180, 90], extent: [-180, -90, 180, 90], resolutions, tileSize });
}

/** XYZ source for a geographic tile layer. `urlTemplate` uses {z}/{y}/{x}. */
export function trekSource(urlTemplate: string, maxZoom: number, tileSize = 256): XYZ {
  return new XYZ({
    url: urlTemplate,
    projection: MARS_GEOGRAPHIC,
    tileGrid: trekTileGrid(maxZoom, tileSize),
    tileSize,
    wrapX: false,
    attributions: 'Imagery: NASA/JPL/University of Arizona (HiRISE), MSSS (CTX), ASU (THEMIS) via Mars Trek and USGS/Esri. ' +
      'Terrain: HiRISE DTM.',
  });
}
