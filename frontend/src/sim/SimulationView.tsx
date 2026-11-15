import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { FormEvent } from 'react';
import * as THREE from 'three';
import {
  describeError,
  einkLiveUrl,
  simTextureUrl,
  useAsk,
  useSimFine,
  useSimSun,
  useSimTerrain,
  useSpaceWeather,
  useWalkHome,
} from '../api';
import type { AskAnswer, PlanResult, SimTerrain, Stop } from '../api';
import { formatHours } from '../format';
import { canListen, listen, speak, stopSpeaking } from '../voice';
import { SimEngine, TIME_SCALES } from './engine';
import type { SimStatus, SimStop } from './engine';
import { SimAudio } from './audio';
import { report, runQa } from './qa';
import type { QaResult } from './qa';
import { Terrain, WalkGrid } from './terrain';

const STEP = 3; // terrain grid: one vertex every 3 m
const KJ_PER_KG_O2 = (4.825 * 4.184) / 1.429e-3; // as in route/plan.py

interface Props {
  stops: Stop[];
  result: PlanResult | null;
  live: boolean;
  onClose: () => void;
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
const NO_SUBSCRIBE = () => () => {};
const NO_STATUS = (): SimStatus | null => null;
// a mouse or trackpad, in a browser that can capture it (pointer lock)
const CAN_CAPTURE = typeof window !== 'undefined' && window.matchMedia('(pointer: fine)').matches && 'requestPointerLock' in Element.prototype;
const compass = (deg: number) => COMPASS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
const dist = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.max(Math.round(m), 1)} m`);
const hm = (min: number) => formatHours(Math.max(min, 0) / 60);
const clock = (h: number) => {
  const m = Math.floor((((h % 24) + 24) % 24) * 60);
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
};
const ground = (s: SimStatus) =>
  s.sand ? (s.roughM >= 0.05 ? 'rough sand' : 'loose sand') : s.roughM >= 0.15 ? 'rough' : s.roughM >= 0.05 ? 'uneven' : 'firm';

function loadTexture(url: string): Promise<THREE.Texture> {
  return new Promise((resolve, reject) => new THREE.TextureLoader().load(url, resolve, undefined, reject));
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

/** The walk simulator: the planned walk on the real Gale terrain, on foot, with the suit display and voice. */
export default function SimulationView({ stops, result, live, onClose }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<SimEngine | null>(null);
  const terrainRef = useRef<Terrain | null>(null);
  const photoImg = useRef<HTMLImageElement | null>(null);
  const mini = useRef<HTMLCanvasElement>(null);
  // the HUD follows the engine through an external store that only changes when something shown changes (E9)
  const [eng, setEng] = useState<SimEngine | null>(null);
  const status = useSyncExternalStore(eng ? eng.subscribe : NO_SUBSCRIBE, eng ? eng.getSnapshot : NO_STATUS);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [qa, setQa] = useState<QaResult[] | null>(null);
  const [sound, setSound] = useState(false);
  const audio = useRef<SimAudio | null>(null);
  const [help, setHelp] = useState(true);
  const [miniScale, setMiniScale] = useState(3); // metres per minimap pixel
  const data = useSimTerrain(STEP, live);
  const fine = useSimFine(data.data?.fine.url ?? null, live);
  const sunTrack = useSimSun(live);
  const weather = useSpaceWeather(live);

  const simStops: SimStop[] = useMemo(() => {
    if (!data.data) return [];
    const t = data.data;
    return stops.map((s) => ({
      id: s.id,
      name: s.name,
      kind: s.kind,
      x: (s.lon - t.lon0) * t.kx,
      z: -(s.lat - t.lat0) * t.kz,
      workMin: s.work_time_min || 30,
    }));
  }, [stops, data.data]);
  const order = useMemo(
    () => (result ? result.timeline.filter((w) => w.kind === 'stop').map((w) => w.id) : simStops.filter((s) => s.kind !== 'start').map((s) => s.id)),
    [result, simStops],
  );
  const { route, routeBack } = useMemo(() => {
    const empty = { route: [] as { x: number; z: number }[], routeBack: [] as { x: number; z: number }[] };
    if (!data.data || !result) return empty;
    const t: SimTerrain = data.data;
    const startId = stops.find((s) => s.kind === 'start')?.id;
    const route: { x: number; z: number }[] = [];
    const routeBack: { x: number; z: number }[] = [];
    for (const f of result.route.features) {
      if (f.geometry.type !== 'LineString') continue;
      const home = startId !== undefined && (f.properties as { to?: string } | null)?.to === startId;
      const bucket = home ? routeBack : route;
      for (const [lon, lat] of f.geometry.coordinates as number[][]) bucket.push({ x: (lon - t.lon0) * t.kx, z: -(lat - t.lat0) * t.kz });
    }
    return { route, routeBack };
  }, [result, data.data, stops]);

  // build the world once the terrain and its textures are in
  const fineReady = fine.isSuccess || fine.isError;
  const sunReady = sunTrack.isSuccess || sunTrack.isError;
  // the physics walks on the planner's own 1 m grid; without it (an older server) it falls back to the 3 m mesh
  const walkGrid = useMemo((): { grid: WalkGrid | null; error: string | null } => {
    if (!data.data || !fine.data) return { grid: null, error: fine.isError ? 'The 1 m walking grid did not load.' : null };
    try {
      return { grid: new WalkGrid(data.data.fine, fine.data), error: null };
    } catch (err) {
      return { grid: null, error: `The 1 m walking grid did not load (${String(err)}).` };
    }
  }, [data.data, fine.data, fine.isError]);
  useEffect(() => {
    if (!data.data || !host.current || !fineReady || !sunReady) return;
    let cancelled = false;
    const t = new Terrain(data.data);
    const walk = walkGrid.grid;
    terrainRef.current = t;
    Promise.all([loadTexture(simTextureUrl('photo', STEP)), loadTexture(simTextureUrl('hazard', STEP)).catch(() => null), loadImage(simTextureUrl('photo', STEP))])
      .then(([photo, hazard, img]) => {
        if (cancelled || !host.current) return;
        photoImg.current = img;
        const e = new SimEngine(host.current, t, data.data.physics, simStops, route, routeBack, photo, hazard, walk, sunTrack.data ?? null);
        (window as unknown as { __walk?: WalkGrid | null }).__walk = walk; // for QA scripts
        engine.current = e;
        setEng(e);
        (window as unknown as { __sim?: SimEngine }).__sim = e; // for QA scripts
        if (new URLSearchParams(window.location.search).has('qa')) {
          runQa(e, walk, data.data.physics, simStops, sunTrack.data ?? null).then((r) => {
            report(r);
            if (!cancelled) setQa(r);
          });
        }
      })
      .catch((err) => setLoadError(String(err)));
    return () => {
      cancelled = true;
      engine.current?.dispose();
      engine.current = null;
      setEng(null);
      stopSpeaking();
    };
  }, [data.data, simStops, route, routeBack, fineReady, sunReady, walkGrid, sunTrack.data]);

  // sound (off until asked for: browsers only start audio after a click): footsteps through the suit, the rover
  // through the thin air, the radio
  const toggleSound = () => {
    if (audio.current) {
      audio.current.dispose();
      audio.current = null;
      setSound(false);
      return;
    }
    const a = new SimAudio();
    a.resume();
    audio.current = a;
    setSound(true);
  };
  useEffect(() => {
    if (!eng) return;
    eng.setFootstep(sound ? () => audio.current?.footstep() : null);
  }, [eng, sound]);
  useEffect(() => {
    const a = audio.current;
    if (!a || !status) return;
    const r = simStops.find((x) => x.kind === 'start');
    if (r) a.roverAt(Math.hypot(r.x - status.x, r.z - status.z));
    a.radio(status.radioShadow);
  }, [status, simStops, sound]);
  useEffect(
    () => () => {
      audio.current?.dispose();
      audio.current = null;
    },
    [],
  );

  // keyboard shortcuts that belong to the screen, not the walker
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      if (tgt.tagName === 'INPUT') return;
      if (e.key === '?') {
        setHelp(false);
        engine.current?.setPaused(true);
      }
      else if (e.key === 'm' || e.key === 'M') setMiniScale((s) => (s === 1 ? 3 : s === 3 ? 8 : 1));
      else if (e.key === 'Escape') engine.current?.escape();
      else if (e.key === '/') {
        e.preventDefault();
        document.getElementById('sim-ask-input')?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const tMin = (status?.tS ?? 0) / 60;
  const elapsedH = tMin / 60;
  const home = useWalkHome(status?.lat ?? null, status?.lon ?? null, elapsedH, live && !!status);
  const phys = data.data?.physics;
  const usableMin = phys ? phys.o2_capacity_h * 60 * (1 - phys.walkback_reserve_frac) : 0;
  const totalMin = phys ? phys.o2_capacity_h * 60 : 0;
  const energyBudget = phys ? phys.metabolic_budget_kj * (1 - phys.walkback_reserve_frac) : 1;
  const visited = useMemo(() => status?.visited ?? [], [status?.visited]);
  const nextId = order.find((id) => !visited.includes(id)) ?? null;

  // the minimap: north-up photo around the walker, the route, stops, the rover and you. It redraws only when the walker
  // has moved a minimap pixel or turned a degree (E9), not on every status update.
  const mx = status ? Math.round(status.x / miniScale) : null;
  const mz = status ? Math.round(status.z / miniScale) : null;
  const mh = status ? Math.round(status.headingDeg) : 0;
  useEffect(() => {
    const c = mini.current;
    const t = terrainRef.current;
    if (!c || !t || mx === null || mz === null) return;
    const ctx = c.getContext('2d') as CanvasRenderingContext2D;
    const W = c.width;
    const s = miniScale;
    const toPx = (x: number, z: number) => [W / 2 + (x - mx * s) / s, W / 2 + (z - mz * s) / s];
    ctx.fillStyle = '#5a3a26';
    ctx.fillRect(0, 0, W, W);
    const img = photoImg.current;
    if (img) {
      const td = t.t;
      const left = td.x0 - td.dx / 2;
      const top = td.z0 - td.dz / 2;
      const [px, py] = toPx(left, top);
      ctx.drawImage(img, px, py, (td.cols * td.dx) / s, (td.rows * td.dz) / s);
    }
    const strokeRoute = (pts: { x: number; z: number }[], color: string) => {
      if (pts.length < 2) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      pts.forEach((p, i) => {
        const [x, y] = toPx(p.x, p.z);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    };
    strokeRoute(route, '#3dd6e8');
    strokeRoute(routeBack, '#ff6a00');
    ctx.font = '600 12px Barlow, system-ui, sans-serif';
    for (const st of simStops) {
      const [x, y] = toPx(st.x, st.z);
      ctx.beginPath();
      ctx.arc(x, y, st.kind === 'start' ? 6 : 5, 0, Math.PI * 2);
      ctx.fillStyle = st.kind === 'start' ? '#2fa36b' : visited.includes(st.id) ? '#3ad07c' : st.id === nextId ? '#ffd257' : '#f0a030';
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = '#111';
      ctx.stroke();
      ctx.fillStyle = '#fff';
      ctx.strokeStyle = 'rgba(0,0,0,0.8)';
      ctx.lineWidth = 3;
      const label = st.kind === 'start' ? 'Rover' : st.id;
      ctx.strokeText(label, x + 8, y + 4);
      ctx.fillText(label, x + 8, y + 4);
    }
    // you
    const a = (mh * Math.PI) / 180;
    ctx.save();
    ctx.translate(W / 2, W / 2);
    ctx.rotate(a);
    ctx.beginPath();
    ctx.moveTo(0, -9);
    ctx.lineTo(6, 7);
    ctx.lineTo(0, 3);
    ctx.lineTo(-6, 7);
    ctx.closePath();
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.restore();
    // north and scale
    ctx.fillStyle = '#fff';
    ctx.font = '600 13px Barlow, system-ui, sans-serif';
    ctx.fillText('N ↑', 8, 18);
    const bar = s * 60 >= 100 ? Math.round((s * 60) / 100) * 100 : 50;
    ctx.fillRect(10, W - 14, bar / s, 3);
    ctx.fillText(dist(bar), 10, W - 20);
    if (import.meta.env.DEV) (window as unknown as { __miniDraws?: number }).__miniDraws = ((window as unknown as { __miniDraws?: number }).__miniDraws ?? 0) + 1;
  }, [mx, mz, mh, miniScale, route, routeBack, simStops, visited, nextId]);

  // the suit display follows the walker. The ESP32 downloads the screen once a minute, so here it redraws once per
  // minute of mission time (and when a stop is done), but never more often than every 1.5 s of real time at x60.
  const [einkSrc, setEinkSrc] = useState<string | null>(null);
  const [einkLarge, setEinkLarge] = useState(false);
  const latest = useRef(status);
  useEffect(() => {
    latest.current = status;
  }, [status]);
  useEffect(() => {
    if (!live || !result?.plan_id) return;
    let shownMin = -1;
    let shownVisits = -1;
    let lastAt = 0;
    const tick = () => {
      const s = latest.current;
      if (!s) return;
      const min = Math.floor(s.tS / 60);
      if (min === shownMin && s.visited.length === shownVisits) return;
      if (performance.now() - lastAt < 1500) return;
      shownMin = min;
      shownVisits = s.visited.length;
      lastAt = performance.now();
      const url = einkLiveUrl({
        planId: result.plan_id as string, elapsedH: s.tS / 3600, lat: s.lat, lon: s.lon, walkedM: s.walkedM, energyKj: s.energyKj, visited: s.visited,
      });
      const img = new Image();
      img.onload = () => setEinkSrc(url);
      img.src = url;
    };
    tick();
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [live, result?.plan_id]);

  // voice and typed questions, answered from where the walker actually is
  const ask = useAsk();
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [listening, setListening] = useState(false);
  const [voiceErr, setVoiceErr] = useState<string | null>(null);
  const [headingThere, setHeadingThere] = useState(false);
  const guidePts = useRef<{ x: number; z: number }[]>([]);
  const submit = (q: string, byVoice: boolean) => {
    const s = latest.current;
    if (!q.trim() || !s) return;
    ask.mutate(
      { question: q.trim(), plan_id: result?.plan_id ?? null, elapsed_h: s.tS / 3600, here_lat: s.lat, here_lon: s.lon, visited: s.visited },
      {
        onSuccess: (r) => {
          setAnswer(r);
          setHeadingThere(false);
          const ground = terrainRef.current;
          const lineOf = (role: string) => {
            const f = r.highlight?.features.find((feat) => feat.properties?.role === role && feat.geometry.type === 'LineString');
            if (!ground || !f || f.geometry.type !== 'LineString') return [];
            return (f.geometry.coordinates as number[][]).map(([lon, lat]) => ground.toLocal(lat, lon));
          };
          const going = lineOf('route');
          guidePts.current = going;
          if (going.length > 1) engine.current?.setLiveRoute(going, lineOf('back'));
          if (byVoice) speak(r.speech);
        },
      },
    );
  };
  const mic = () => {
    stopSpeaking();
    if (listening) return;
    setVoiceErr(null);
    setListening(true);
    listen({
      onInterim: setQuestion,
      onFinal: (q) => {
        setQuestion(q);
        submit(q, true);
      },
      onError: setVoiceErr,
      onEnd: () => setListening(false),
    });
  };
  const onAsk = (e: FormEvent) => {
    e.preventDefault();
    submit(question, false);
    (document.activeElement as HTMLElement | null)?.blur();
  };

  const s = status;
  const o2Left = usableMin - tMin;
  const turnBack = home.data?.reachable && home.data.walkback_min !== undefined ? o2Left - home.data.walkback_min : null;
  const leadMin = phys?.sep_warning_lead_min ?? 30;
  const shelterFar = !!home.data?.reachable && (home.data.walkback_min ?? 0) > leadMin;
  const lvl = weather.data?.level;
  let prompt: string | null = null;
  const over = !!s && (s.finished || s.outOfOxygen);
  if (over) prompt = null;
  else if (s?.working) prompt = `Working at ${s.working.id}: ${hm(s.working.leftS / 60)} left`;
  else if (s?.nearEgg === 'alien') prompt = 'Press E to say hi';
  else if (s?.nearEgg === 'board') prompt = 'Press E to pick up the skateboard';
  else if (answer?.go_to && !headingThere) prompt = `Go to ${answer.go_to.label}? The path from here is on the ground.`;
  else if (s?.skate.riding) prompt = 'Skateboarding: W push · S brake · mouse or A/D steer · Space ollie · B step off';
  else if (s?.near && s.near.kind !== 'start' && !visited.includes(s.near.id)) prompt = `Press E to work at ${s.near.id} (${s.near.workMin} min)`;
  else if (s?.near && s.near.kind === 'start' && visited.length > 0) prompt = 'Press E to end the walk at the rover';
  else if (s && !s.mouseLocked && !s.paused && !help && CAN_CAPTURE) prompt = 'Click the scene to look around with the mouse';
  const warnings: string[] = [];
  if (over) {
    // the debrief says it all
  } else if (s?.reserveBreached) warnings.push('You are into the walk-home reserve. Head back to the rover now.');
  else if (turnBack !== null && turnBack < 30) warnings.push(turnBack <= 0 ? 'Turn back now.' : `Turn back within ${hm(turnBack)}.`);
  if (!over && s?.inNoGo) warnings.push('Off-limits ground: too steep or too rough. Get back on the route.');
  if (!over && s?.tooSteep && phys)
    warnings.push(`Too steep to walk: ${Math.abs(s.gradeDeg).toFixed(0)}° ahead, the limit is ${phys.max_grade_deg.toFixed(0)}°. Find another way.`);
  if (!over && walkGrid.error) warnings.push(`${walkGrid.error} Walking on the 3 m mesh: slopes are smoother and rough ground and sand don't slow you.`);
  if (!over && s && s.sunElDeg < 0) warnings.push('The Sun has set. Walking in the dark is outside the plan: head for the rover.');
  if (!over && home.data && !home.data.reachable) warnings.push('No safe walk home from here. Retrace your steps.');

  return (
    <div className="sim" role="dialog" aria-label="Walk simulation">
      <div className="sim-canvas" ref={host} />
      {!s && (
        <div className="sim-loading">
          {!live ? 'The simulation needs the planner service (marswalk serve).' : loadError || data.isError ? `Could not load the terrain. ${describeError(data.error, 'Loading')} ${loadError ?? ''}` : 'Building Gale crater…'}
        </div>
      )}

      <div className="sim-top">
        <div className="sim-title">
          <b>Simulation</b>
          <span>{s ? `Mission time ${hm(tMin)}` : ''}</span>
          {s && s.ltstH !== null && (
            <span title={`Sol ${s.sol ?? '?'} (Mars Sol Date) · local true solar time, the Sun's own clock${s.lmstH !== null ? ` (mean solar time ${clock(s.lmstH)})` : ''}`}>
              {s.sol !== null ? `Sol ${s.sol} · ` : ''}
              {clock(s.ltstH)} local
            </span>
          )}
        </div>
        <div className="sim-speed" role="group" aria-label="Time speed">
          {TIME_SCALES.map((v) => (
            <button key={v} type="button" className={s?.timeScale === v ? 'on' : ''} onClick={() => engine.current?.setTimeScale(v)}>
              ×{v}
            </button>
          ))}
        </div>
        <div className="sim-actions">
          <button type="button" onClick={() => engine.current?.toggleHazard()} aria-pressed={s?.hazard}>Off-limits {s?.hazard ? 'on' : 'off'}</button>
          <button type="button" onClick={() => engine.current?.toggleCamera()}>{s?.camera === 'first' ? 'First person' : 'Third person'}</button>
          <button type="button" onClick={toggleSound} aria-pressed={sound} title="Footsteps through the suit, the rover through Mars's thin air, the radio">
            Sound {sound ? 'on' : 'off'}
          </button>
          <button type="button" onClick={() => { setHelp(false); engine.current?.setPaused(true); }}>Controls</button>
          <button type="button" className="exit" onClick={onClose}>Exit</button>
        </div>
      </div>

      {qa && (
        <section className="sim-qa" aria-label="Simulator checks">
          <h2>
            Simulator QA: {qa.filter((r) => r.ok).length} of {qa.length} pass <small>(reload to walk normally)</small>
          </h2>
          <ul>
            {qa.map((r) => (
              <li key={r.name} className={r.ok ? 'ok' : 'bad'}>
                <b>{r.ok ? '✓' : '✗'}</b> {r.name}: {r.got} <small>(expected {r.expected})</small>
              </li>
            ))}
          </ul>
        </section>
      )}

      {s?.perf.on && (
        <section className="sim-perf" aria-label="Engine statistics">
          <span>{s.perf.fps.toFixed(0)} fps · {s.perf.ms.toFixed(1)} ms</span>
          <span>{s.perf.calls} draw calls · {(s.perf.tris / 1000).toFixed(0)}k triangles</span>
          <span>ground tiles in view {s.perf.chunksDrawn} of {s.perf.chunks}</span>
          <span>resolution ×{s.perf.pixelRatio.toFixed(2)} · shadow redraws {s.perf.shadowUpdates}/s</span>
        </section>
      )}

      {s && phys && (
        <section className="sim-status" aria-label="Status report">
          <div className="o2">
            <span>Oxygen before reserve</span>
            <b className={o2Left < 30 ? 'low' : ''}>{o2Left >= 0 ? hm(o2Left) : 'reserve in use'}</b>
            <div className="gauge" aria-hidden="true">
              <i style={{ width: `${Math.min(100, (100 * tMin) / totalMin)}%` }} />
              <em style={{ width: `${100 * phys.walkback_reserve_frac}%` }} />
            </div>
          </div>
          <dl>
            <dt>Walk home</dt>
            <dd>{home.data?.reachable ? `${hm(home.data.walkback_min ?? 0)}` : home.isFetching ? '…' : '—'}</dd>
            <dt>Turn back within</dt>
            <dd>{turnBack === null ? '—' : turnBack > 0 ? hm(turnBack) : 'now'}</dd>
            <dt>Walked</dt>
            <dd>{dist(s.walkedM)}</dd>
            <dt>Effort</dt>
            <dd>{Math.round((100 * s.energyKj) / energyBudget)}% · {(s.energyKj / KJ_PER_KG_O2).toFixed(2)} kg O₂</dd>
            <dt>Dose so far</dt>
            <dd>{((phys.rad_mgy_per_day * tMin) / 1440).toFixed(3)} mGy</dd>
            <dt>Sun in the sky</dt>
            <dd className={s.sunElDeg < 5 ? 'warn' : ''}>
              {s.sunElDeg >= 0 ? `${s.sunElDeg.toFixed(0)}° up, ${compass(s.sunAzDeg)}` : `set (${s.sunElDeg.toFixed(0)}°)`}
            </dd>
            <dt>Space weather</dt>
            <dd className={lvl === 'NO-GO' ? 'bad' : lvl === 'CAUTION' ? 'warn' : ''}>
              {lvl === 'GO' ? 'Quiet' : lvl === 'CAUTION' ? 'Caution' : lvl === 'NO-GO' ? 'Storm: go inside' : 'No data'}
            </dd>
            <dt>Storm shelter</dt>
            <dd className={shelterFar ? 'warn' : ''}>
              {home.data?.reachable && home.data.walkback_min !== undefined
                ? shelterFar
                  ? `rover too far (${hm(home.data.walkback_min)} > ${leadMin} min warning)`
                  : `rover within ${leadMin} min`
                : '—'}
            </dd>
            <dt>Radio</dt>
            <dd className={s.radioShadow ? 'warn' : ''}>
              {walkGrid.grid ? (s.radioShadow ? 'no contact: a ridge is in the way' : 'in contact with the rover') : '—'}
              {s.radioShadowS >= 60 ? ` · ${hm(s.radioShadowS / 60)} out so far` : ''}
            </dd>
            <dt>Gravity</dt>
            <dd>{phys.gravity_mps2.toFixed(2)} m/s² ({(phys.gravity_mps2 / SimEngine.gEarth).toFixed(2)} g)</dd>
            <dt>Pace</dt>
            <dd>
              {s.speedMps.toFixed(2)} m/s{s.skate.riding ? ' on board' : ''} · {s.gradeDeg >= 0 ? '+' : ''}
              {s.gradeDeg.toFixed(0)}° · {Math.round(s.powerW)} W
            </dd>
            <dt>Ground</dt>
            <dd className={s.terrainMult > 1.3 ? 'warn' : ''}>
              {ground(s)}
              {s.terrainMult > 1.005 ? ` · ×${s.terrainMult.toFixed(2)} slower` : ''}
            </dd>
          </dl>
        </section>
      )}

      {s && (
        <section className="sim-right" aria-label="Map and distances">
          <div className="sim-mini">
            <canvas ref={mini} width={220} height={220} aria-label="Minimap, north up" />
            <button type="button" onClick={() => setMiniScale((v) => (v === 1 ? 3 : v === 3 ? 8 : 1))}>
              Zoom
            </button>
          </div>
          <ul className="sim-dist">
            {order.map((id) => {
              const st = simStops.find((x) => x.id === id);
              if (!st) return null;
              const d = Math.hypot(st.x - s.x, st.z - s.z);
              const brg = (Math.atan2(st.x - s.x, -(st.z - s.z)) * 180) / Math.PI;
              const done = visited.includes(id);
              return (
                <li key={id} className={done ? 'done' : id === nextId ? 'next' : ''}>
                  <b>{id}</b>
                  <span>{done ? 'done' : `${dist(d)} ${compass(brg)}`}</span>
                </li>
              );
            })}
            {(() => {
              const r = simStops.find((x) => x.kind === 'start');
              if (!r) return null;
              const d = Math.hypot(r.x - s.x, r.z - s.z);
              return (
                <li className="rover">
                  <b>Rover</b>
                  <span>
                    {dist(d)} {compass((Math.atan2(r.x - s.x, -(r.z - s.z)) * 180) / Math.PI)}
                  </span>
                </li>
              );
            })()}
          </ul>
        </section>
      )}

      {s && result?.plan_id && einkSrc && (
        <button type="button" className="sim-eink" onClick={() => setEinkLarge(true)} aria-label="Suit display, larger">
          <img src={einkSrc} width={800} height={480} alt="Suit display: next stop, distance, oxygen, walk home" />
        </button>
      )}
      {einkLarge && einkSrc && (
        <div className="eink-large" onClick={() => setEinkLarge(false)} role="dialog" aria-label="Suit display">
          <img src={einkSrc} width={800} height={480} alt="Suit display" />
          <p>Click anywhere to close</p>
        </div>
      )}

      {s && !help && !s.paused && (
        <div className="sim-bottom">
          {warnings.map((w) => (
            <p key={w} className="sim-warn" role="alert">
              {w}
            </p>
          ))}
          {s?.message && !over && <p className="sim-egg" aria-live="polite">{s.message}</p>}
          {s?.skate.riding && !over && <p className="sim-offplan">Off-plan: skateboarding. The plan has no skateboard; your oxygen still counts.</p>}
          {prompt && <p className="sim-prompt">{prompt}</p>}
          {(answer || voiceErr || ask.isError) && (
            <div className="sim-answer" aria-live="polite">
              {answer && (
                <>
                  <button type="button" className="ask-close" onClick={() => setAnswer(null)} aria-label="Close the answer">×</button>
                  <p className="ask-q">{answer.question}</p>
                  <p className="ask-a">{answer.answer}</p>
                  {answer.go_to && !headingThere && (
                    <button
                      type="button"
                      className="ask-go-there"
                      onClick={() => {
                        if (engine.current?.goAlongPath()) setHeadingThere(true);
                      }}
                    >
                      Go to {answer.go_to.label}
                    </button>
                  )}
                </>
              )}
              {voiceErr && <p className="ask-error">{voiceErr}</p>}
              {ask.isError && <p className="ask-error">{describeError(ask.error, 'Answering')}</p>}
            </div>
          )}
          <form className="ask-bar" onSubmit={onAsk}>
            {canListen() && (
              <button type="button" className={`mic${listening ? ' listening' : ''}`} onClick={mic} aria-label="Ask by voice" aria-pressed={listening}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
                </svg>
              </button>
            )}
            <input
              id="sim-ask-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={listening ? 'Listening…' : 'Ask: how far is the next stop?  (press / to type)'}
              aria-label="Question"
            />
            <button type="submit" className="ask-go" disabled={!question.trim() || ask.isPending}>
              {ask.isPending ? '…' : 'Ask'}
            </button>
          </form>
        </div>
      )}

      {help && s && !s.paused && (
        <div className="sim-help" role="note">
          <h2>Walk the plan</h2>
          <p>
            You walk on the planner’s own 1 m terrain with its walking model: slopes, rough ground and loose sand slow
            you down, climbing costs more oxygen, and anything steeper than {phys ? phys.max_grade_deg.toFixed(0) : 20}° can’t be
            walked. Gravity is Mars’s 0.38 g. The Sun is where it will really be at the rover on the planned morning
            {sunTrack.data ? ` (starting ${clock(sunTrack.data.lmst_h)} local time, ${new Date(sunTrack.data.start_utc).toUTCString().slice(5, 22)} UTC)` : ''}.
          </p>
          <SimKeys />
          <button
            type="button"
            className="primary"
            onClick={() => {
              setHelp(false);
              engine.current?.captureMouse();
            }}
          >
            Start walking
          </button>
        </div>
      )}

      {s?.paused && !s.finished && !s.outOfOxygen && (
        <div className="sim-modal pause" role="dialog" aria-label="Paused">
          <h2>Paused</h2>
          {s.lockNote && <p role="status">{s.lockNote}</p>}
          <SimKeys />
          <button type="button" className="primary" onClick={() => engine.current?.resume()}>Resume</button>
          <button type="button" onClick={onClose}>Exit the simulation</button>
        </div>
      )}

      {s && (s.finished || s.outOfOxygen) && (
        <Debrief status={s} result={result} usableMin={usableMin} order={order} onClose={onClose} />
      )}
    </div>
  );
}

function SimKeys() {
  return (
    <dl className="sim-keys">
      <dt>Mouse</dt><dd>Look and turn (click the scene to take the mouse)</dd>
      <dt>W / S</dt><dd>Walk forward / back</dd>
      <dt>A / D</dt><dd>Step sideways</dd>
      <dt>← / →</dt><dd>Turn without the mouse</dd>
      <dt>Space</dt><dd>Hop</dd>
      <dt>E</dt><dd>Work at a stop (amber ring) · end the walk at the rover · pick up the skateboard</dd>
      <dt>B</dt><dd>Ride the skateboard, or step off</dd>
      <dt>On the board</dt><dd>W kicks each time a foot meets the ground. S brakes. Mouse or A/D steers. Space hops.</dd>
      <dt>T</dt><dd>Time speed ×1, ×5, ×20, ×60</dd>
      <dt>V</dt><dd>First or third person</dd>
      <dt>H</dt><dd>Show off-limits ground</dd>
      <dt>M</dt><dd>Minimap zoom</dd>
      <dt>/</dt><dd>Ask a question (or use the microphone)</dd>
      <dt>Wheel</dt><dd>Zoom</dd>
      <dt>Esc</dt><dd>Pause and free the mouse</dd>
      <dt>F</dt><dd>Engine statistics</dd>
      <dt>N</dt><dd>1 m relief in the light on far ground (off: the photo has its own shading)</dd>
    </dl>
  );
}

function Debrief({ status: s, result, usableMin, order, onClose }: { status: SimStatus; result: PlanResult | null; usableMin: number; order: string[]; onClose: () => void }) {
  const tMin = s.tS / 60;
  const plan = result?.summary;
  const ok = s.finished && !s.reserveBreached;
  const verdict = s.outOfOxygen ? 'Out of oxygen' : s.reserveBreached ? 'Back, but into the reserve' : 'Walk complete';
  const rows: [string, string, string][] = [
    ['Stops done', `${s.visited.filter((v) => order.includes(v)).length} of ${order.length}`, ''],
    ['Distance walked', dist(s.walkedM), plan ? `${plan.distance_km} km` : ''],
    ['Time outside', hm(tMin), plan ? hm(Number(plan.duration_h) * 60) : ''],
    ['Effort', `${Math.round(s.energyKj).toLocaleString()} kJ`, plan ? `${Number(plan.energy_kj).toLocaleString()} kJ` : ''],
    ['Oxygen left before reserve', usableMin - tMin >= 0 ? hm(usableMin - tMin) : 'none', ''],
    ['Time on off-limits ground', s.noGoS < 1 ? 'none' : hm(s.noGoS / 60), ''],
    ['Out of radio contact', s.radioShadowS < 30 ? 'none' : hm(s.radioShadowS / 60),
      plan?.radio_shadow_min !== undefined ? (Number(plan.radio_shadow_min) < 0.5 ? 'none' : hm(Number(plan.radio_shadow_min))) : ''],
  ];
  if (s.skate.distM > 0)
    rows.push(['Skateboard (off-plan)', `${dist(s.skate.distM)}${s.skate.wipeouts ? `, ${s.skate.wipeouts} wipeout${s.skate.wipeouts > 1 ? 's' : ''}` : ''}`, 'none']);
  if (s.eggsFound.length > 0) rows.push(['Easter eggs found', `${s.eggsFound.length} of 2`, '']);
  return (
    <div className="sim-modal debrief" role="dialog" aria-label="Debrief">
      <h2 className={ok ? 'good' : 'bad'}>{verdict}</h2>
      <table>
        <thead>
          <tr>
            <th />
            <th>You</th>
            <th>Plan</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, a, b]) => (
            <tr key={k}>
              <th>{k}</th>
              <td>{a}</td>
              <td>{b}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">The plan’s times include its 30 % margin, so a walker at the model’s pace finishes ahead of it.</p>
      <button type="button" className="primary" onClick={onClose}>Back to the planner</button>
    </div>
  );
}
