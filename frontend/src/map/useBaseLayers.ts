// The Base layers of the map: every saved Base (marker + terrain window), the popup card at the selected one, the
// HiRISE footprints and the picked point while choosing a new Base. Driven by props; MarsMap owns the sources.
import { useEffect } from 'react';
import type { RefObject } from 'react';
import Feature from 'ol/Feature';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import GeoJSONFormat from 'ol/format/GeoJSON';
import type OlMap from 'ol/Map';
import type Overlay from 'ol/Overlay';
import type VectorSource from 'ol/source/Vector';
import type { BaseInfo, BBox, FootprintCollection } from '../api';

export interface BaseLayerHandles {
  map: OlMap;
  baseSource: VectorSource;
  footprintSource: VectorSource;
  pickSource: VectorSource;
  popup: Overlay;
}

export function boxRing(b: BBox): number[][] {
  return [[b.lon_min, b.lat_min], [b.lon_max, b.lat_min], [b.lon_max, b.lat_max], [b.lon_min, b.lat_max], [b.lon_min, b.lat_min]];
}

interface Args {
  bases: BaseInfo[];
  focusedBaseId: string;
  selectedBaseId: string | null;
  picking: boolean;
  footprints: FootprintCollection | null;
  pickPoint: { lat: number; lon: number } | null;
  pickBox: BBox | null;
}

export function useBaseLayers(handles: RefObject<BaseLayerHandles | null>,
  { bases, focusedBaseId, selectedBaseId, picking, footprints, pickPoint, pickBox }: Args) {
  // Every saved Base: marker + terrain window.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.baseSource.clear();
    for (const b of bases) {
      const lat = b.base_lat ?? b.lat;
      const lon = b.base_lon ?? b.lon;
      const marker = new Feature({ geometry: new Point([lon, lat]), base: b, focused: b.id === focusedBaseId, selected: b.id === selectedBaseId });
      marker.setId(`base:${b.id}`);
      h.baseSource.addFeature(marker);
      if (b.bbox) h.baseSource.addFeature(new Feature({ geometry: new Polygon([boxRing(b.bbox)]), base: b, focused: b.id === focusedBaseId }));
    }
  }, [handles, bases, focusedBaseId, selectedBaseId]);

  // The popup card follows the selected Base's marker.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    const b = bases.find((x) => x.id === selectedBaseId);
    h.popup.setPosition(b ? [b.base_lon ?? b.lon, b.base_lat ?? b.lat] : undefined);
  }, [handles, bases, selectedBaseId]);

  // HiRISE footprints while picking a new Base; zoom out so they can be seen.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.footprintSource.clear();
    if (picking && footprints) h.footprintSource.addFeatures(new GeoJSONFormat().readFeatures(footprints));
  }, [handles, picking, footprints]);
  useEffect(() => {
    const h = handles.current;
    if (!h || !picking) return;
    const view = h.map.getView();
    if ((view.getZoom() ?? 0) > 6) view.animate({ zoom: 4, duration: 500 });
  }, [handles, picking]);

  // The point picked for a new Base and the terrain window it would download.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.pickSource.clear();
    if (!picking) return;
    if (pickBox) h.pickSource.addFeature(new Feature(new Polygon([boxRing(pickBox)])));
    if (pickPoint) h.pickSource.addFeature(new Feature(new Point([pickPoint.lon, pickPoint.lat])));
  }, [handles, picking, pickPoint, pickBox]);
}
