import { useCallback, useState } from 'react';
import { describeError, useLayers, useSite } from './api';
import type { LayerInfo } from './api';
import { MarsMap } from './map/MarsMap';
import { BASE_LAYERS, PLACEHOLDER_LEGS } from './map/layers';
import { LayerToggles } from './components/LayerToggles';
import { PlanPanel } from './components/PlanPanel';
import { SpaceWeatherPanel } from './components/SpaceWeatherPanel';
import { StopList } from './components/StopList';
import { StopLog } from './components/StopLog';

const NO_OVERLAYS: LayerInfo[] = [];

export function App() {
  const site = useSite();
  const live = site.data?.live ?? false;
  const layers = useLayers(live);
  const overlays = layers.data ?? NO_OVERLAYS;

  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [route, setRoute] = useState<GeoJSON.FeatureCollection | null>(null);
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});

  const toggle = useCallback((name: string, visible: boolean) => setVisibility((v) => ({ ...v, [name]: visible })), []);
  const onRoute = useCallback((r: GeoJSON.FeatureCollection | null) => {
    setRoute(r);
    if (r) setVisibility((v) => ({ ...v, [PLACEHOLDER_LEGS]: false }));
  }, []);

  if (site.isPending) return <div className="loading">Loading site…</div>;
  if (site.isError) return <div className="loading">{describeError(site.error, 'Loading the site')}</div>;

  const { site: meta, stops } = site.data;
  const selectedStop = stops.find((s) => s.id === selectedStopId) ?? null;

  return (
    <div className="app">
      <MarsMap
        site={meta}
        stops={stops}
        selectedStopId={selectedStopId}
        route={route}
        overlays={overlays}
        visibility={visibility}
        onSelectStop={setSelectedStopId}
      />
      <aside className="panel">
        <header>
          <h1>{meta.name}</h1>
          <div className="sub">
            Suited traverse planner
            <span className={live ? 'pill ok' : 'pill warn'}>{live ? 'API connected' : 'offline demo (sample data)'}</span>
          </div>
        </header>
        <SpaceWeatherPanel live={live} />
        <PlanPanel live={live} stops={stops} onRoute={onRoute} />
        <StopList stops={stops} selectedId={selectedStopId} onSelect={setSelectedStopId} />
        {selectedStop && <StopLog key={selectedStop.id} stop={selectedStop} live={live} />}
        <LayerToggles
          names={[...BASE_LAYERS, ...overlays.map((o) => o.name)]}
          visibility={visibility}
          onToggle={toggle}
          overlaysPending={overlays.length === 0}
        />
      </aside>
    </div>
  );
}
