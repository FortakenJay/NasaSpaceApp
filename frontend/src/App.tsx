import { Suspense, lazy, useCallback, useMemo, useState } from 'react';
import { AskPanel } from './components/AskPanel';
import { formatHours } from './format';

const SimulationView = lazy(() => import('./sim/SimulationView'));
import { describeError, useAddStop, useComputePlan, useDeleteStop, useLayers, usePlans, useSite, useUpdateStop } from './api';
import type { CostModel, LayerInfo, StopOrder } from './api';
import { MarsMap } from './map/MarsMap';
import { MAX_ADDED_STOPS, PLACEHOLDER_LEGS } from './map/layers';
import { LayerToggles } from './components/LayerToggles';
import type { MapView } from './components/LayerToggles';
import { MapLegend } from './components/MapLegend';
import { PlanPanel } from './components/PlanPanel';
import { PlanResult } from './components/PlanResult';
import { SafeZonePanel } from './components/SafeZonePanel';
import { SourcesPanel } from './components/SourcesPanel';
import { SpaceWeatherPanel } from './components/SpaceWeatherPanel';
import { Step } from './components/Step';
import { StopList } from './components/StopList';
import { StopLog } from './components/StopLog';
import { SuitDisplayPanel } from './components/SuitDisplayPanel';

const NO_OVERLAYS: LayerInfo[] = [];
const DEFAULT_USABLE_H = 5.6; // 8 h of oxygen less the 30% walk-home reserve, if the API does not say
const PHOTO = 'photo';
const EXPECTED_API = '1.1'; // major.minor this app was built against (src/marswalk/__init__.py)
const VIEW_LABELS: Record<string, string> = {
  hillshade: 'Relief',
  slope5: 'Slope',
  roughness: 'Roughness',
  ti: 'Sand or rock',
  nogo: 'Off limits',
  radio: 'Radio',
  shelter: 'Storm shelter',
  uncertain: 'Certainty',
};

export function App() {
  const site = useSite();
  const live = site.data?.live ?? false;
  const layers = useLayers(live);
  const compute = useComputePlan();
  const plans = usePlans(live);
  const addStop = useAddStop();
  const updateStop = useUpdateStop();
  const deleteStop = useDeleteStop();

  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [skippedIds, setSkippedIds] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [syncKey, setSyncKey] = useState(0);
  const [cost, setCost] = useState<CostModel>('metabolic');
  const [order, setOrder] = useState<StopOrder>('fixed');
  const [mapView, setMapView] = useState(PHOTO);
  const [safeZoneOn, setSafeZoneOn] = useState(false);
  const [elapsedH, setElapsedH] = useState(0);
  const [highlight, setHighlight] = useState<GeoJSON.FeatureCollection | null>(null);
  const [simulating, setSimulating] = useState(false);

  const result = compute.data ?? null;
  const route = result?.route ?? null;
  const toggleSelected = useCallback((id: string) => setSelectedStopId((cur) => (cur === id ? null : id)), []);

  // The safe-zone overlay is recomputed server-side for the chosen elapsed time and cost model.
  const overlays = useMemo(
    () =>
      (layers.data ?? NO_OVERLAYS).map((o) => {
        if (o.key === 'safezone') return { ...o, url: `${o.url}?elapsed_h=${elapsedH}&cost=${cost}` };
        return o.key === 'hillshade' ? { ...o, opacity: 0.9 } : o;
      }),
    [layers.data, elapsedH, cost],
  );
  // One terrain layer at a time (chosen with "Show"); the safe zone has its own switch in step 4.
  const shown = useMemo(() => {
    const v: Record<string, boolean> = { [PLACEHOLDER_LEGS]: route === null };
    for (const o of overlays) v[o.name] = o.key === 'safezone' ? safeZoneOn : o.key === mapView;
    return v;
  }, [overlays, mapView, safeZoneOn, route]);
  const views = useMemo<MapView[]>(
    () => [
      { key: PHOTO, label: 'Photo' },
      ...overlays.filter((o) => o.key in VIEW_LABELS).map((o) => ({ key: o.key, label: VIEW_LABELS[o.key] })),
    ],
    [overlays],
  );

  if (site.isPending) return <div className="loading">Loading the site…</div>;
  if (site.isError) return <div className="loading">{describeError(site.error, 'Loading the site')}</div>;

  const { site: meta, stops, eva, api_version: apiVersion, project_root: projectRoot } = site.data;
  const usableH = eva?.usable_h ?? DEFAULT_USABLE_H;
  const walkLimitM = eva?.max_distance_from_rover_m ?? null;
  const staleService = live && !(apiVersion ?? '').startsWith(EXPECTED_API);
  const selectedStop = stops.find((s) => s.id === selectedStopId) ?? null;
  const visitIds = stops.filter((s) => s.kind !== 'start' && !skippedIds.includes(s.id)).map((s) => s.id);
  const addedCount = stops.filter((s) => s.kind === 'user').length;
  const hasTerrain = overlays.length > 0;
  let hereHint = 'the rover';
  if (selectedStop) hereHint = selectedStop.kind === 'start' ? 'the rover' : `${selectedStop.id}, ${selectedStop.name}`;
  else if (result && elapsedH > 0) hereHint = `where the plan puts you ${formatHours(elapsedH)} into the walk`;

  const plan = (ids: string[]) => compute.mutate({ cost, order, stop_ids: ids });
  // "Go to U1": that stop becomes the next one, then the stops already ticked, in that order.
  const goTo = (id: string) => {
    if (!stops.some((s) => s.id === id && s.kind !== 'start')) return;
    const skip = skippedIds.filter((x) => x !== id);
    setSkippedIds(skip);
    setOrder('fixed');
    setSimulating(false);
    const rest = stops.filter((s) => s.kind !== 'start' && s.id !== id && !skip.includes(s.id)).map((s) => s.id);
    compute.mutate({ cost, order: 'fixed', stop_ids: [id, ...rest] });
  };
  // Once a route is on the map it follows every change to the stops, so the two never disagree.
  const follow = (ids: string[]) => {
    if (result === null) return;
    if (ids.length > 0) plan(ids);
    else compute.reset();
  };
  const toggleVisit = (id: string) => {
    const next = skippedIds.includes(id) ? skippedIds.filter((x) => x !== id) : [...skippedIds, id];
    setSkippedIds(next);
    follow(stops.filter((s) => s.kind !== 'start' && !next.includes(s.id)).map((s) => s.id));
  };
  const onAddStop = (lat: number, lon: number) =>
    addStop.mutate({ lat, lon }, { onSuccess: (s) => { setSelectedStopId(s.id); follow([...visitIds, s.id]); } });
  const onMoveStop = (id: string, lat: number, lon: number) =>
    updateStop.mutate({ id, lat, lon }, { onSuccess: () => follow(visitIds), onError: () => setSyncKey((k) => k + 1) });
  const onRename = (id: string, name: string) => updateStop.mutate({ id, name });
  const onRemove = (id: string) =>
    deleteStop.mutate(id, {
      onSuccess: () => {
        setSelectedStopId(null);
        setSkippedIds((cur) => cur.filter((x) => x !== id));
        follow(visitIds.filter((x) => x !== id));
      },
    });

  let stopProblem: string | null = null;
  if (addStop.isError) stopProblem = describeError(addStop.error, 'Adding the stop');
  else if (updateStop.isError) stopProblem = describeError(updateStop.error, 'Changing the stop');
  else if (deleteStop.isError) stopProblem = describeError(deleteStop.error, 'Removing the stop');
  let blocked: string | null = null;
  if (!live) blocked = 'Start the planner service first: python -m marswalk serve';
  else if (visitIds.length === 0) blocked = 'Tick at least one stop in step 1.';

  return (
    <div className="app">
      <div className="map-area">
        <MarsMap
          site={meta}
          stops={stops}
          skippedIds={skippedIds}
          selectedStopId={selectedStopId}
          route={route}
          highlight={highlight}
          overlays={overlays}
          visibility={shown}
          walkLimitM={walkLimitM}
          adding={adding}
          syncKey={syncKey}
          onSelectStop={toggleSelected}
          onAddStop={onAddStop}
          onMoveStop={onMoveStop}
        />
        {views.length > 1 && <LayerToggles views={views} value={mapView} onChange={setMapView} />}
        {adding && (
          <p className="map-banner">
            {addStop.isPending ? 'Saving the stop…' : 'Click the ground to add a stop. It is saved straight away.'}
          </p>
        )}
        <MapLegend
          mapView={mapView}
          safeZoneOn={safeZoneOn}
          hasRoute={route !== null}
          hasAdded={addedCount > 0}
          walkLimitM={walkLimitM}
          showStraight={route === null && visitIds.length > 0}
          note={overlays.find((o) => o.key === mapView)?.note ?? ''}
          hasAnswer={highlight !== null}
        />
        <AskPanel
          live={live}
          planId={result?.plan_id ?? null}
          selectedStopId={selectedStopId}
          elapsedH={elapsedH}
          hereHint={hereHint}
          onHighlight={setHighlight}
          onGoTo={goTo}
        />
      </div>

      <aside className="sheet">
        <header>
          <div className="title-row">
            <h1>MarsWalk</h1>
            <button
              type="button"
              className="sim-open"
              onClick={() => setSimulating(true)}
              disabled={!live}
              title={live ? 'Walk the plan yourself on the real terrain' : 'Needs the planner service'}
            >
              Simulation
            </button>
          </div>
          <p className="site-name">{meta.name}</p>
          <p className="lede">
            Plan a walk outside on Mars. Choose where to go, get the safest route on foot, and see how long the crew can stay
            out and still walk home.
          </p>
          {!live && <p className="problem">Offline demo: the map and stops load, but planning needs the planner service.</p>}
          {staleService && (
            <div className="problem">
              <b>The planner service is an older copy of this project</b>
              {projectRoot ? ` (running from ${projectRoot})` : ''}, so parts of this page will fail. Stop it, then in this
              project’s folder run:
              <code>.venv/bin/python -m pip install -e &quot;.[dev]&quot;</code>
              <code>.venv/bin/python -m marswalk serve</code>
            </div>
          )}
        </header>

        <SpaceWeatherPanel live={live} />

        <Step n={1} title="Choose where to go" done={visitIds.length > 0}>
          <StopList
            stops={stops}
            skippedIds={skippedIds}
            selectedId={selectedStopId}
            adding={adding}
            canAdd={live && addedCount < MAX_ADDED_STOPS}
            problem={stopProblem}
            onSelect={toggleSelected}
            onToggle={toggleVisit}
            onAdding={setAdding}
            onRename={onRename}
            onRemove={onRemove}
          />
        </Step>

        <Step n={2} title="Plan the walk" done={result !== null}>
          <PlanPanel
            cost={cost}
            order={order}
            onCost={setCost}
            onOrder={setOrder}
            onPlan={() => plan(visitIds)}
            pending={compute.isPending}
            blocked={blocked}
            error={compute.isError ? describeError(compute.error, 'Route planning') : null}
            planned={result !== null}
          />
        </Step>

        <Step n={3} title="Check the plan" done={result !== null}>
          <PlanResult result={result} usableH={usableH} />
        </Step>

        <Step n={4} title="Check the walk home">
          <SafeZonePanel
            available={hasTerrain}
            elapsedH={elapsedH}
            usableH={usableH}
            visible={safeZoneOn}
            timeline={result?.timeline ?? null}
            onElapsed={setElapsedH}
            onVisible={setSafeZoneOn}
          />
        </Step>

        <Step n={5} title="Follow it on the suit">
          <SuitDisplayPanel
            live={live}
            planId={result?.plan_id ?? null}
            elapsedH={elapsedH}
            endH={result ? (result.timeline[result.timeline.length - 1]?.arrive_min ?? 0) / 60 : null}
            onElapsed={setElapsedH}
          />
        </Step>

        {selectedStop && (
          <details className="more">
            <summary>
              Field notes for {selectedStop.id}, {selectedStop.name}
            </summary>
            <StopLog key={selectedStop.id} stop={selectedStop} live={live} />
          </details>
        )}
        <SourcesPanel live={live} />
        {(plans.data?.length ?? 0) > 0 && (
          <details className="more">
            <summary>Earlier plans ({plans.data?.length})</summary>
            <ul className="saved">
              {plans.data?.map((p) => (
                <li key={p.id}>
                  <b>{p.stop_ids.join(', ')}</b>
                  <small>
                    {new Date(p.created_at).toLocaleString()}, {p.cost_model === 'metabolic' ? 'least effort' : 'gentlest ground'}
                    {p.result ? `, ${p.result.summary.distance_km} km in ${p.result.summary.duration_h} h` : ''}
                  </small>
                </li>
              ))}
            </ul>
          </details>
        )}
      </aside>
      {simulating && (
        <Suspense fallback={<div className="sim-loading sim-fallback">Loading the simulation…</div>}>
          <SimulationView stops={stops} result={result} live={live} onClose={() => setSimulating(false)} />
        </Suspense>
      )}
    </div>
  );
}
