// OpenLayers inside React. The OL Map is created once per site and owned by a ref; small effects
// sync React props (stops, selection, route, overlays, visibility) into it. No data fetching here:
// the parent passes everything in as props.
import 'ol/ol.css';
import { useEffect, useRef } from 'react';
import OlMap from 'ol/Map';
import View from 'ol/View';
import Feature from 'ol/Feature';
import Point from 'ol/geom/Point';
import LineString from 'ol/geom/LineString';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import ImageLayer from 'ol/layer/Image';
import VectorSource from 'ol/source/Vector';
import ImageStatic from 'ol/source/ImageStatic';
import GeoJSONFormat from 'ol/format/GeoJSON';
import { boundingExtent } from 'ol/extent';
import { ScaleLine, defaults as defaultControls } from 'ol/control';
import { Circle, Fill, Stroke, Style, Text } from 'ol/style';
import { unByKey } from 'ol/Observable';
import type BaseLayer from 'ol/layer/Base';
import type { LayerInfo, Site, Stop } from '../api';
import { MARS_GEOGRAPHIC, trekSource } from './mars';
import { PLACEHOLDER_LEGS } from './layers';

const COLORS = { start: '#4cbb6c', stop: '#e8a33d', route: '#3dd6e8' };

function stopStyle(stop: Stop, selected: boolean): Style {
  return new Style({
    image: new Circle({
      radius: selected ? 9 : 7,
      fill: new Fill({ color: stop.kind === 'start' ? COLORS.start : COLORS.stop }),
      stroke: new Stroke({ color: selected ? '#fff' : '#000', width: 2 }),
    }),
    text: new Text({
      text: stop.id,
      offsetX: 16,
      textAlign: 'left',
      font: '700 13px system-ui, sans-serif',
      fill: new Fill({ color: '#fff' }),
      stroke: new Stroke({ color: '#000', width: 3 }),
    }),
  });
}

interface Props {
  site: Site;
  stops: Stop[];
  selectedStopId: string | null;
  route: GeoJSON.FeatureCollection | null;
  overlays: LayerInfo[];
  visibility: Record<string, boolean>;
  onSelectStop: (id: string) => void;
}

interface Handles {
  map: OlMap;
  layers: Map<string, BaseLayer>;
  stopSource: VectorSource;
  legSource: VectorSource;
  routeSource: VectorSource;
}

export function MarsMap({ site, stops, selectedStopId, route, overlays, visibility, onSelectStop }: Props) {
  const target = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  const onSelectRef = useRef(onSelectStop);

  useEffect(() => {
    onSelectRef.current = onSelectStop;
  }, [onSelectStop]);

  // Create the map once per basemap; tear it down on unmount.
  const { url_template: tileUrl, max_zoom: maxZoom } = site.basemap;
  useEffect(() => {
    if (!target.current) return;
    const stopSource = new VectorSource();
    const legSource = new VectorSource();
    const routeSource = new VectorSource();
    const layers = new Map<string, BaseLayer>([
      ['HiRISE basemap', new TileLayer({ source: trekSource(tileUrl, maxZoom) })],
      [PLACEHOLDER_LEGS, new VectorLayer({
        source: legSource, zIndex: 5,
        style: new Style({ stroke: new Stroke({ color: COLORS.route, width: 2, lineDash: [6, 6] }) }),
      })],
      ['Planned route', new VectorLayer({
        source: routeSource, zIndex: 6, style: new Style({ stroke: new Stroke({ color: COLORS.route, width: 3 }) }),
      })],
      ['Stops', new VectorLayer({ source: stopSource, zIndex: 10 })],
    ]);
    const map = new OlMap({
      target: target.current,
      layers: [...layers.values()],
      controls: defaultControls().extend([new ScaleLine({ units: 'metric' })]),
      view: new View({ projection: MARS_GEOGRAPHIC, maxZoom: 20 }),
    });
    const clickKey = map.on('singleclick', (e) => {
      map.forEachFeatureAtPixel(e.pixel, (f) => {
        const id = f.getId();
        if (typeof id === 'string' && stopSource.getFeatureById(id)) {
          onSelectRef.current(id);
          return true;
        }
        return false;
      });
    });
    handles.current = { map, layers, stopSource, legSource, routeSource };
    if (import.meta.env.DEV) (window as unknown as { __marswalk?: unknown }).__marswalk = handles.current;
    return () => {
      unByKey(clickKey);
      map.setTarget(undefined);
      map.dispose();
      handles.current = null;
    };
  }, [tileUrl, maxZoom]);

  // Stops + placeholder legs; fit the view when the stop set changes.
  useEffect(() => {
    const h = handles.current;
    if (!h || stops.length === 0) return;
    h.stopSource.clear();
    h.stopSource.addFeatures(stops.map((s) => {
      const f = new Feature({ geometry: new Point([s.lon, s.lat]), stop: s });
      f.setId(s.id);
      return f;
    }));
    h.legSource.clear();
    h.legSource.addFeature(new Feature(new LineString([...stops, stops[0]].map((s) => [s.lon, s.lat]))));
    h.map.getView().fit(boundingExtent(stops.map((s) => [s.lon, s.lat])), { padding: [60, 60, 60, 60] });
  }, [stops]);

  // Selection: restyle and pan.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    for (const f of h.stopSource.getFeatures()) f.setStyle(stopStyle(f.get('stop') as Stop, f.getId() === selectedStopId));
    const s = stops.find((x) => x.id === selectedStopId);
    if (s) h.map.getView().animate({ center: [s.lon, s.lat], zoom: Math.max(h.map.getView().getZoom() ?? 17, 17), duration: 400 });
  }, [selectedStopId, stops]);

  // Planned route (M4).
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.routeSource.clear();
    if (route) h.routeSource.addFeatures(new GeoJSONFormat().readFeatures(route));
  }, [route]);

  // Raster overlays (M2).
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    const added: BaseLayer[] = overlays.map((ly) => {
      const layer = new ImageLayer({
        source: new ImageStatic({ url: ly.url, imageExtent: ly.bounds, projection: MARS_GEOGRAPHIC }),
        opacity: ly.opacity ?? 0.6, zIndex: 2,
      });
      h.map.addLayer(layer);
      h.layers.set(ly.name, layer);
      return layer;
    });
    return () => {
      for (const [i, layer] of added.entries()) {
        h.map.removeLayer(layer);
        h.layers.delete(overlays[i].name);
      }
    };
  }, [overlays]);

  // Visibility toggles.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    for (const [name, layer] of h.layers) layer.setVisible(visibility[name] ?? true);
  }, [visibility, overlays]);

  return <div ref={target} className="map" role="application" aria-label="Traverse map" />;
}
