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
import { boundingExtent, isEmpty } from 'ol/extent';
import { ScaleLine, defaults as defaultControls } from 'ol/control';
import { DoubleClickZoom, Translate } from 'ol/interaction';
import { Circle, Fill, Stroke, Style, Text } from 'ol/style';
import type { FeatureLike } from 'ol/Feature';
import { unByKey } from 'ol/Observable';
import type BaseLayer from 'ol/layer/Base';
import type { LayerInfo, Site, Stop } from '../api';
import { MARS_GEOGRAPHIC, METERS_PER_DEGREE, trekSource } from './mars';
import { PLACEHOLDER_LEGS, WALK_LIMIT } from './layers';

const COLORS = { start: '#4cbb6c', stop: '#e8a33d', user: '#d07cf0', skipped: '#8a9199', route: '#3dd6e8', routeBack: '#ff6a00' };

function stopStyle(stop: Stop, selected: boolean, skipped: boolean): Style {
  return new Style({
    image: new Circle({
      radius: selected ? 9 : 7,
      fill: new Fill({ color: skipped ? COLORS.skipped : COLORS[stop.kind] }),
      stroke: new Stroke({ color: selected ? '#fff' : '#000', width: 2 }),
    }),
    text: new Text({
      text: stop.id,
      offsetX: 16,
      textAlign: 'left',
      font: '700 13px system-ui, sans-serif',
      fill: new Fill({ color: skipped ? '#c9cfd4' : '#fff' }),
      stroke: new Stroke({ color: '#000', width: 3 }),
    }),
  });
}

/** What an answer is about: its route (white over a dark halo, dashed for the walk home) and its end points. */
function highlightStyle(f: FeatureLike): Style[] {
  const role = f.get('role') as string;
  if (f.getGeometry()?.getType() === 'LineString') {
    const back = role === 'home' || role === 'back';
    return [
      new Style({ stroke: new Stroke({ color: 'rgba(0,0,0,0.65)', width: 7 }) }),
      new Style({ stroke: new Stroke({ color: back ? COLORS.routeBack : COLORS.route, width: 3.5, lineDash: back ? [10, 7] : undefined }) }),
    ];
  }
  return [new Style({
    image: new Circle({ radius: 11, stroke: new Stroke({ color: '#ffffff', width: 3 }), fill: new Fill({ color: 'rgba(0,0,0,0.25)' }) }),
    text: role === 'here' ? new Text({
      text: 'here', offsetY: -20, font: '600 12px system-ui, sans-serif',
      fill: new Fill({ color: '#fff' }), stroke: new Stroke({ color: '#000', width: 3 }),
    }) : undefined,
  })];
}

/** A circle of `radiusM` metres around (lat, lon), as lon/lat vertices. */
function ring(lat: number, lon: number, radiusM: number): number[][] {
  const dLat = radiusM / METERS_PER_DEGREE;
  const dLon = dLat / Math.cos((lat * Math.PI) / 180);
  return Array.from({ length: 121 }, (_, i) => {
    const a = (i / 120) * 2 * Math.PI;
    return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)];
  });
}

interface Props {
  site: Site;
  stops: Stop[];
  /** Stops left out of the plan (drawn grey). */
  skippedIds: string[];
  selectedStopId: string | null;
  route: GeoJSON.FeatureCollection | null;
  /** The route and points the last answered question is about. */
  highlight: GeoJSON.FeatureCollection | null;
  overlays: LayerInfo[];
  visibility: Record<string, boolean>;
  /** Farthest the crew may go from the rover, drawn as a dashed ring. */
  walkLimitM: number | null;
  /** While true, a click on open ground calls onAddStop(lat, lon). */
  adding: boolean;
  /** Bump to redraw the stops from props (after a refused drag, to put the point back). */
  syncKey: number;
  onSelectStop: (id: string) => void;
  onAddStop: (lat: number, lon: number) => void;
  /** Stops the crew added themselves can be dragged to a new spot. */
  onMoveStop: (id: string, lat: number, lon: number) => void;
}

interface Handles {
  map: OlMap;
  layers: Map<string, BaseLayer>;
  stopSource: VectorSource;
  legSource: VectorSource;
  routeSource: VectorSource;
  limitSource: VectorSource;
  answerSource: VectorSource;
  overlays: Map<string, { layer: ImageLayer<ImageStatic>; url: string }>;
  fitted: boolean;
}

export function MarsMap({
  site, stops, skippedIds, selectedStopId, route, highlight, overlays, visibility, walkLimitM, adding, syncKey,
  onSelectStop, onAddStop, onMoveStop,
}: Props) {
  const target = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  const actions = useRef({ adding, onSelectStop, onAddStop, onMoveStop });

  useEffect(() => {
    actions.current = { adding, onSelectStop, onAddStop, onMoveStop };
    if (target.current) target.current.style.cursor = adding ? 'crosshair' : '';
    // While adding stops a double click would zoom AND drop two stops, so zoom-on-double-click is paused.
    handles.current?.map.getInteractions().forEach((i) => {
      if (i instanceof DoubleClickZoom) i.setActive(!adding);
    });
  }, [adding, onSelectStop, onAddStop, onMoveStop]);

  // Create the map once per basemap; tear it down on unmount.
  const { url_template: tileUrl, max_zoom: maxZoom } = site.basemap;
  // Wider imagery under the basemap, as a stable string so the map is not rebuilt on every render.
  const contextKey = JSON.stringify(site.context ?? []);
  useEffect(() => {
    if (!target.current) return;
    const stopSource = new VectorSource();
    const legSource = new VectorSource();
    const routeSource = new VectorSource();
    const limitSource = new VectorSource();
    const answerSource = new VectorSource();
    const stopLayer = new VectorLayer({ source: stopSource, zIndex: 10 });
    const context = JSON.parse(contextKey) as { name: string; url_template: string; max_zoom: number }[];
    const layers = new Map<string, BaseLayer>([
      ...context.map((c): [string, BaseLayer] => [c.name, new TileLayer({ source: trekSource(c.url_template, c.max_zoom) })]),
      ['HiRISE basemap', new TileLayer({ source: trekSource(tileUrl, maxZoom) })],
      [WALK_LIMIT, new VectorLayer({
        source: limitSource, zIndex: 4,
        style: new Style({ stroke: new Stroke({ color: 'rgba(255,255,255,0.85)', width: 1.5, lineDash: [2, 7] }) }),
      })],
      [PLACEHOLDER_LEGS, new VectorLayer({
        source: legSource, zIndex: 5,
        style: (f) => new Style({
          stroke: new Stroke({ color: f.get('returning') ? COLORS.routeBack : COLORS.route, width: 2, lineDash: [6, 6] }),
        }),
      })],
      ['Planned route', new VectorLayer({
        source: routeSource, zIndex: 6,
        style: (f) => new Style({
          stroke: new Stroke({ color: f.get('returning') ? COLORS.routeBack : COLORS.route, width: 3 }),
        }),
      })],
      ['Answer', new VectorLayer({ source: answerSource, zIndex: 8, style: highlightStyle })],
      ['Stops', stopLayer],
    ]);
    const map = new OlMap({
      target: target.current,
      layers: [...layers.values()],
      controls: defaultControls().extend([new ScaleLine({ units: 'metric' })]),
      view: new View({ projection: MARS_GEOGRAPHIC, maxZoom: 20 }),
    });
    // Stops the crew added can be dragged; the science stops and the rover stay put.
    const translate = new Translate({
      layers: [stopLayer],
      hitTolerance: 8,
      filter: (f) => (f.get('stop') as Stop | undefined)?.kind === 'user',
    });
    map.addInteraction(translate);
    const translateKey = translate.on('translateend', (e) => {
      const f = e.features.item(0);
      const geometry = f?.getGeometry();
      const id = f?.getId();
      if (!(geometry instanceof Point) || typeof id !== 'string') return;
      const [lon, lat] = geometry.getCoordinates();
      actions.current.onMoveStop(id, lat, lon);
    });
    // 'click' answers at once ('singleclick' waits 250 ms to rule out a double click).
    const clickKey = map.on('click', (e) => {
      const hitStop = map.forEachFeatureAtPixel(
        e.pixel,
        (f) => {
          const id = f.getId();
          if (typeof id !== 'string') return false;
          actions.current.onSelectStop(id);
          return true;
        },
        { layerFilter: (l) => l === stopLayer, hitTolerance: 8 },
      );
      // The view is in Mars geographic degrees, so the click coordinate is [lon, lat].
      if (!hitStop && actions.current.adding) actions.current.onAddStop(e.coordinate[1], e.coordinate[0]);
    });
    handles.current = { map, layers, stopSource, legSource, routeSource, limitSource, answerSource, overlays: new Map(), fitted: false };
    if (import.meta.env.DEV) (window as unknown as { __marswalk?: unknown }).__marswalk = handles.current;
    return () => {
      unByKey(clickKey);
      unByKey(translateKey);
      map.setTarget(undefined);
      map.dispose();
      handles.current = null;
    };
  }, [tileUrl, maxZoom, contextKey]);

  // Stops, the straight-line preview and the walk-limit ring. The view is fitted once, not on every edit.
  useEffect(() => {
    const h = handles.current;
    if (!h || stops.length === 0) return;
    h.stopSource.clear();
    h.stopSource.addFeatures(stops.map((s) => {
      const f = new Feature({ geometry: new Point([s.lon, s.lat]), stop: s });
      f.setId(s.id);
      return f;
    }));
    const visited = stops.filter((s) => s.kind === 'start' || !skippedIds.includes(s.id));
    h.legSource.clear();
    if (visited.length > 1) {
      const coords = visited.map((s) => [s.lon, s.lat]);
      h.legSource.addFeature(new Feature(new LineString(coords)));
      const back = new Feature(new LineString([coords[coords.length - 1], coords[0]]));
      back.set('returning', true);
      h.legSource.addFeature(back);
    }
    const start = stops.find((s) => s.kind === 'start');
    h.limitSource.clear();
    if (start && walkLimitM) h.limitSource.addFeature(new Feature(new LineString(ring(start.lat, start.lon, walkLimitM))));
    if (!h.fitted) {
      h.map.getView().fit(boundingExtent(stops.map((s) => [s.lon, s.lat])), { padding: [70, 70, 180, 70] });
      h.fitted = true;
    }
  }, [stops, skippedIds, walkLimitM, syncKey]);

  // Selection and skipped state: restyle; pan to a newly selected stop.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    for (const f of h.stopSource.getFeatures()) {
      const id = f.getId();
      f.setStyle(stopStyle(f.get('stop') as Stop, id === selectedStopId, typeof id === 'string' && skippedIds.includes(id)));
    }
  }, [selectedStopId, stops, skippedIds, syncKey]);
  useEffect(() => {
    const h = handles.current;
    const f = selectedStopId ? h?.stopSource.getFeatureById(selectedStopId) : null;
    const geometry = f?.getGeometry();
    if (!h || !(geometry instanceof Point)) return;
    h.map.getView().animate({ center: geometry.getCoordinates(), duration: 300 });
  }, [selectedStopId]);

  // Planned route.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.routeSource.clear();
    if (route) {
      const startId = stops.find((s) => s.kind === 'start')?.id;
      const features = new GeoJSONFormat().readFeatures(route);
      for (const f of features) if (startId && f.get('to') === startId) f.set('returning', true);
      h.routeSource.addFeatures(features);
    }
  }, [route, stops]);

  // What the last answer is about; the view moves to show all of it.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.answerSource.clear();
    if (!highlight) return;
    h.answerSource.addFeatures(new GeoJSONFormat().readFeatures(highlight));
    const extent = h.answerSource.getExtent();
    if (extent && !isEmpty(extent)) h.map.getView().fit(extent, { padding: [90, 90, 200, 90], maxZoom: 18, duration: 400 });
  }, [highlight]);

  // Raster overlays. Layers are kept between renders: only an overlay whose URL changed is reloaded, and the
  // old picture stays up until the new one has arrived (the safe zone changes URL on every slider step).
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    const wanted = new Set(overlays.map((o) => o.name));
    for (const [name, entry] of h.overlays) {
      if (wanted.has(name)) continue;
      h.map.removeLayer(entry.layer);
      h.overlays.delete(name);
      h.layers.delete(name);
    }
    for (const ly of overlays) {
      const makeSource = () => new ImageStatic({ url: ly.url, imageExtent: ly.bounds, projection: MARS_GEOGRAPHIC });
      const entry = h.overlays.get(ly.name);
      if (!entry) {
        const layer = new ImageLayer({ source: makeSource(), opacity: ly.opacity ?? 0.6, zIndex: ly.key === 'safezone' ? 3 : 2, visible: false });
        h.map.addLayer(layer);
        h.overlays.set(ly.name, { layer, url: ly.url });
        h.layers.set(ly.name, layer);
      } else if (entry.url !== ly.url) {
        entry.url = ly.url; // the newest request wins if answers arrive out of order
        const preload = new Image();
        preload.onload = () => {
          if (handles.current === h && entry.url === ly.url) entry.layer.setSource(makeSource());
        };
        preload.src = ly.url;
      }
    }
  }, [overlays]);

  // Visibility toggles.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    for (const [name, layer] of h.layers) layer.setVisible(visibility[name] ?? true);
  }, [visibility, overlays]);

  return <div ref={target} className="map" role="application" aria-label="Traverse map" />;
}
