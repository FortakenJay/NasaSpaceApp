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
  // Ground distance per pixel in projection units (degrees). Latitude spacing is constant; this
  // ignores the cos(lat) shrink of longitude, which is 0.4% at Gale (-4.8 deg).
  getPointResolution: (resolution: number) => resolution,
});
addProjection(MARS_GEOGRAPHIC);

const TILE = 256;

/** Tile grid for Mars Trek WMTS "default028mm" geographic tiling: z0 = 2x1 tiles of 180 degrees. */
export function trekTileGrid(maxZoom: number): TileGrid {
  const resolutions = Array.from({ length: maxZoom + 1 }, (_, z) => 180 / TILE / 2 ** z);
  return new TileGrid({ origin: [-180, 90], extent: [-180, -90, 180, 90], resolutions, tileSize: TILE });
}

/** XYZ source for a Mars Trek layer. `urlTemplate` uses {z}/{y}/{x}. */
export function trekSource(urlTemplate: string, maxZoom: number): XYZ {
  return new XYZ({
    url: urlTemplate,
    projection: MARS_GEOGRAPHIC,
    tileGrid: trekTileGrid(maxZoom),
    wrapX: false,
    attributions: 'HiRISE mosaic via NASA/JPL Mars Trek · DTM/ortho NASA/JPL/UArizona',
  });
}
