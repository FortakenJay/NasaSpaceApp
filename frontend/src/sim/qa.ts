// In-browser QA for the walk simulator: open the app with ?qa=1, plan a route, press Simulation. The checks drive the
// engine in fixed ticks (engine.advance), compare it with the planner's models, print a table to the console and
// leave the results on window.__simQA. They move the walker around, so reload the page afterwards.
import * as THREE from 'three';
import type { SimPhysics, SimSun } from '../api';
import type { SimEngine, SimStop } from './engine';
import { TICK_S } from './engine';
import { edgeTimeEnergy, metabolicPower, terrainMultiplier, walkSpeed } from './physics';
import type { WalkGrid } from './terrain';

export interface QaResult {
  name: string;
  ok: boolean;
  expected: string;
  got: string;
}

const frames = (n: number) => new Promise<void>((r) => {
  let k = 0;
  const f = () => (++k >= n ? r() : requestAnimationFrame(f));
  requestAnimationFrame(f);
});
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const f3 = (x: number) => x.toFixed(3);

/** Run every check. `stops` are the simulator's stops (local metres), `sun` the Mars24 track the engine lights from. */
export async function runQa(e: SimEngine, walk: WalkGrid | null, phys: SimPhysics, stops: SimStop[], sun: SimSun | null): Promise<QaResult[]> {
  const out: QaResult[] = [];
  const add = (name: string, ok: boolean, expected: string, got: string) => out.push({ name, ok, expected, got });
  const s = e.status;
  const mass = phys.body_mass_kg + phys.suit_mass_kg;
  const cap = phys.walk_speed_cap_mps ?? Infinity;
  const start = stops.find((x) => x.kind === 'start') ?? { x: 0, z: 0 };
  const first = stops.find((x) => x.kind !== 'start');
  e.setPaused(false);

  // 1. Physics: on 1 440 cells of the real 1 m grid, the step the engine takes equals the planner's priced edge.
  if (walk) {
    let worst = 0;
    let n = 0;
    let lo = Infinity;
    let hi = 0;
    for (let i = 0; i < 1440; i++) {
      const a = (i * 2.399963) % (2 * Math.PI); // golden-angle spread of headings and distances
      const r = 20 + ((i * 37) % 600);
      const x = start.x + Math.sin(a) * r;
      const z = start.z - Math.cos(a) * r;
      if (walk.isNoGo(x, z)) continue;
      const dx = Math.sin(a);
      const dz = -Math.cos(a);
      const climb = walk.heightAt(x + dx, z + dz) - walk.heightAt(x, z);
      const grade = (Math.atan2(climb, 1) * 180) / Math.PI;
      const rough = walk.roughnessM(x, z);
      const sand = walk.isSand(x, z);
      const ref = edgeTimeEnergy(phys.gravity_mps2, mass, phys.roughness_penalty_per_m, phys.sand_penalty, phys.max_grade_deg, climb, 1, rough, sand, cap);
      if (!Number.isFinite(ref.timeS)) continue;
      // the engine's way: model speed from the grade, slowed by the terrain multiplier, power at the model speed
      const mult = terrainMultiplier(rough, sand, phys.roughness_penalty_per_m, phys.sand_penalty);
      const vModel = walkSpeed(grade, cap);
      const t = Math.hypot(1, climb) / (vModel / mult);
      const ekj = (metabolicPower(mass, phys.gravity_mps2, grade, vModel) * t) / 1000;
      worst = Math.max(worst, Math.abs(t - ref.timeS) / ref.timeS, Math.abs(ekj - ref.energyKj) / ref.energyKj);
      lo = Math.min(lo, mult);
      hi = Math.max(hi, mult);
      n++;
    }
    add(`Engine step = planner edge on ${n} cells of the 1 m grid (largest relative difference)`, n > 1000 && worst < 1e-12, '0', `${worst.toExponential(1)}, ground ×${lo.toFixed(2)} to ×${hi.toFixed(2)}`);
  }

  // 2-3. Walking toward the first stop for 402 s: never faster than the model allows, power inside the model's range.
  if (first) {
    e.setTimeScale(1);
    e.placeAt(start.x + 14 * Math.sin(Math.atan2(first.x - start.x, -(first.z - start.z))), start.z - 14 * Math.cos(Math.atan2(first.x - start.x, -(first.z - start.z))));
    e.faceTo(first.x, first.z);
    const w0 = s.walkedM;
    const e0 = s.energyKj;
    let vmax = 0;
    let moving = 0;
    let pSum = 0;
    e.setKey('w', true);
    for (let i = 0; i < 402; i++) {
      e.faceTo(first.x, first.z);
      e.advance(1);
      vmax = Math.max(vmax, s.speedMps);
      if (s.speedMps > 0) {
        moving++;
        pSum += s.powerW;
      }
    }
    e.setKey('w', false);
    const walked = s.walkedM - w0;
    add('Walking 402 s toward the first stop: fastest speed (m/s)', vmax <= Math.min(1.6, cap) + 1e-9, `≤ ${Math.min(1.6, cap).toFixed(2)}`, `${vmax.toFixed(2)}; ${walked.toFixed(0)} m at ${(walked / 402).toFixed(2)} m/s average`);
    const pAvg = moving ? pSum / moving : 0;
    add('Average power while walking (W)', pAvg >= 60 && pAvg <= 450, '60–450', `${pAvg.toFixed(0)} (${((s.energyKj - e0) / 402 * 1000).toFixed(0)} W incl. standing)`);
  }

  // 4. A grade past the limit cannot be walked.
  if (walk) {
    const steep = walk.findSteep(phys.max_grade_deg + 1, start, 600);
    if (steep) {
      e.placeAt(steep.x, steep.z);
      e.faceTo(steep.x + steep.dirX, steep.z + steep.dirZ);
      const x0 = s.x;
      const z0 = s.z;
      e.setKey('w', true);
      e.advance(2);
      e.setKey('w', false);
      const moved = Math.hypot(s.x - x0, s.z - z0);
      add(`A ${(phys.max_grade_deg + 1).toFixed(0)}°+ grade stops the walker (m moved)`, moved < 1e-9 && s.tooSteep, '0, too steep', `${f3(moved)}, ${s.tooSteep ? 'too steep' : 'walkable'}`);
    } else add('A grade past the limit stops the walker', false, 'a steep cell within 600 m', 'none found');
  }

  // 5. The Sun at the start is the Mars24 track's first point; the clock is the track's sol and true solar time.
  if (sun && sun.az_el.length) {
    const p = e.sunAt(0);
    const [az, el] = sun.az_el[0];
    add('Sun at the start (az, el °)', !!p && Math.abs(p.az - az) < 1e-6 && Math.abs(p.el - el) < 1e-6, `${az.toFixed(1)}, ${el.toFixed(1)}`, p ? `${p.az.toFixed(1)}, ${p.el.toFixed(1)}` : 'none');
    const p3 = e.sunAt(3 * 3600);
    add('Sun 3 h later climbs toward local noon (el °)', !!p3 && p3.el > el, `> ${el.toFixed(1)}`, p3 ? p3.el.toFixed(1) : 'none');
  }

  // 6. 30 min of work at a stop at the configured power.
  if (first) {
    e.placeAt(first.x, first.z);
    e.advance(TICK_S);
    const e0 = s.energyKj;
    const t0 = s.tS;
    e.act();
    const was = s.working?.id;
    e.setTimeScale(60);
    for (let i = 0; i < 40 && s.working; i++) e.advance(1);
    e.setTimeScale(1);
    const want = (phys.work_power_w * first.workMin * 60) / 1000;
    const got = s.energyKj - e0;
    add(`${first.workMin} min of work at ${first.id} at ${phys.work_power_w} W (kJ)`, was === first.id && s.visited.includes(first.id) && Math.abs(got - want) / want < 0.03,
      want.toFixed(0), `${got.toFixed(0)} over ${((s.tS - t0) / 60).toFixed(1)} min`);
  }

  // 7. A hop under Mars gravity: 2v/g in the air.
  {
    e.placeAt(start.x + 20, start.z + 20);
    e.advance(TICK_S);
    e.jump();
    let air = 0;
    while (e.inAir && air < 5) {
      e.advance(TICK_S);
      air += TICK_S;
    }
    const want = (2 * 1.6) / phys.gravity_mps2;
    add('Hop: time in the air (s)', Math.abs(air - want) <= TICK_S + 1e-9, want.toFixed(3), air.toFixed(3));
  }

  // 8. Off-limits ground is logged; 9. radio shadow follows the planner's layer.
  if (walk) {
    let nogo: { x: number; z: number } | null = null;
    let shadow: { x: number; z: number } | null = null;
    let contact: { x: number; z: number } | null = null;
    for (let r = 30; r < 900 && !(nogo && shadow && contact); r += 7) {
      for (let k = 0; k < 24; k++) {
        const a = (k / 24) * 2 * Math.PI;
        const x = start.x + Math.sin(a) * r;
        const z = start.z - Math.cos(a) * r;
        if (!nogo && walk.isNoGo(x, z)) nogo = { x, z };
        if (!walk.isNoGo(x, z)) {
          if (!shadow && walk.inRadioShadow(x, z)) shadow = { x, z };
          if (!contact && !walk.inRadioShadow(x, z)) contact = { x, z };
        }
      }
    }
    if (nogo) {
      e.placeAt(nogo.x, nogo.z);
      const n0 = s.noGoS;
      e.advance(1);
      add('Standing on off-limits ground is flagged and timed (s)', s.inNoGo && s.noGoS > n0, '> 0, flagged', `${f3(s.noGoS - n0)}, ${s.inNoGo ? 'flagged' : 'not flagged'}`);
    }
    if (shadow && contact) {
      e.placeAt(shadow.x, shadow.z);
      const r0 = s.radioShadowS;
      e.advance(1);
      const inShadow = s.radioShadow && s.radioShadowS > r0;
      e.placeAt(contact.x, contact.z);
      e.advance(1);
      add('Radio: no contact in the planner’s shadow, contact outside it', inShadow && !s.radioShadow, 'shadow, then contact', `${inShadow ? 'shadow' : 'contact'}, then ${s.radioShadow ? 'shadow' : 'contact'}`);
    }
  }

  // 10. Fixed time step (E8): the same walk in one call or in 25 small ones ends in exactly the same place.
  {
    const p0 = { x: start.x + 25, z: start.z + 5 };
    const run = (chunks: number) => {
      e.placeAt(p0.x, p0.z);
      e.faceTo(p0.x + 100, p0.z - 40);
      e.setKey('w', true);
      for (let i = 0; i < chunks; i++) e.advance(5 / chunks);
      e.setKey('w', false);
      return { x: s.x, z: s.z };
    };
    const a = run(1);
    const b = run(25);
    add('Fixed ticks: one 5 s step = 25 small ones (m apart)', a.x === b.x && a.z === b.z && Math.hypot(a.x - p0.x, a.z - p0.z) > 1, '0', f3(Math.hypot(a.x - b.x, a.z - b.z)));
  }

  // 11. Eggs: the mast camera looks at the picture, and the board lies by the rover.
  const { percy, alien } = e.eggModels;
  if (percy && alien) {
    percy.group.updateMatrixWorld(true);
    alien.group.updateMatrixWorld(true);
    const head = percy.head.getWorldPosition(new THREE.Vector3());
    const look = percy.head.getWorldDirection(new THREE.Vector3()).negate(); // the cameras face the head's -z
    const to = alien.sign.getWorldPosition(new THREE.Vector3()).sub(head).normalize();
    const deg = (Math.acos(Math.min(1, look.dot(to))) * 180) / Math.PI;
    const far = Math.min(...stops.map((st) => Math.hypot(st.x - alien.group.position.x, st.z - alien.group.position.z)));
    add('Perseverance’s mast points at the cardboard Mars (°)', deg < 2, '< 2', deg.toFixed(2));
    add('The alien is off the plan: nearest stop (m)', far >= 90, '≥ 90', far.toFixed(0));
  } else add('Easter egg placed', false, 'Perseverance and the alien', 'missing');

  // E1: near the walker the drawn ground is the 1 m terrain; at the patch's edge it meets the 3 m mesh exactly.
  if (walk) {
    const p = { x: start.x + 40, z: start.z + 10 };
    e.placeAt(p.x, p.z);
    const under = Math.abs(e.groundY(p.x, p.z) - walk.groundAt(p.x, p.z));
    add('Under the walker the ground drawn is the 1 m terrain (m off)', under < 1e-6, '0', under.toExponential(1));
    const ring = [];
    for (let k = 0; k < 16; k++) {
      const a = (k / 16) * 2 * Math.PI;
      const r = 80 / Math.max(Math.abs(Math.cos(a)), Math.abs(Math.sin(a))); // on the square's edge
      const x = Math.round(p.x / 4) * 4 + Math.cos(a) * r;
      const z = Math.round(p.z / 4) * 4 + Math.sin(a) * r;
      // 1 cm inside vs 1 cm outside the edge: any step shows; the hillside's own slope adds well under 1 cm
      const inside = e.groundY(x - Math.cos(a) * 0.01, z - Math.sin(a) * 0.01);
      const outside = e.groundY(x + Math.cos(a) * 0.01, z + Math.sin(a) * 0.01);
      ring.push(Math.abs(inside - outside));
    }
    const step = Math.max(...ring);
    add('At the edge of the 1 m patch: step to the 3 m mesh (m, 16 points)', step < 0.01, '< 0.01', f3(step));
    const b0 = e.patchBuilds;
    e.placeAt(p.x + 40, p.z);
    add('Walking 40 m rebuilds the 1 m patch around the walker', e.patchBuilds > b0, 'rebuilt', e.patchBuilds > b0 ? 'rebuilt' : 'not rebuilt');
  }

  // 12. Sleep when idle (E10): paused, the loop stops drawing; resumed, it draws again.
  e.setPaused(true);
  await frames(6);
  const slept = e.sleeping;
  e.setPaused(false);
  await frames(2);
  add('Paused: the render loop sleeps; resumed: it wakes', slept && !e.sleeping, 'asleep, then awake', `${slept ? 'asleep' : 'awake'}, then ${e.sleeping ? 'asleep' : 'awake'}`);

  // 13. Shadows only redraw when something moved; ground tiles outside the view are skipped.
  const out0 = first ? Math.atan2(first.x - start.x, -(first.z - start.z)) : 0;
  e.placeAt(start.x + 14 * Math.sin(out0), start.z - 14 * Math.cos(out0));
  if (first) e.faceTo(first.x, first.z);
  if (!s.perf.on) e.togglePerf();
  const mini = () => (window as unknown as { __miniDraws?: number }).__miniDraws ?? 0;
  await sleep(1200);
  const hud0 = e.hudUpdates;
  const mini0 = mini();
  await sleep(2000);
  const still = s.perf;
  const hudStill = (e.hudUpdates - hud0) / 2;
  const miniStill = mini() - mini0;
  e.setTimeScale(20); // ~1 m/s for 2 s would not cross one minimap pixel (3 m at the default zoom)
  e.setKey('w', true);
  const hud1 = e.hudUpdates;
  const mini1 = mini();
  await sleep(2200);
  const walking = s.perf;
  const hudWalk = (e.hudUpdates - hud1) / 2.2;
  const miniWalk = mini() - mini1;
  e.setKey('w', false);
  e.setTimeScale(1);
  // E9: the HUD only gets a snapshot when something it shows changed (perf numbers change once a second while shown)
  add('Standing still: HUD updates per second (F stats on)', hudStill <= 1.5, '≤ 1 (the stats line, once a second)', hudStill.toFixed(1));
  add('Walking: HUD updates per second', hudWalk >= 3, '≥ 3 (every 150 ms when values change)', hudWalk.toFixed(1));
  add('Minimap redraws: standing still / walking 2 s at ×20', miniStill === 0 && miniWalk > 0, '0 / > 0', `${miniStill} / ${miniWalk}`);
  add('Standing still: shadow redraws per second', still.shadowUpdates <= 1, '0 (1 if the Sun crossed a 0.1° step)', String(still.shadowUpdates));
  add('Walking: shadow redraws per second', walking.shadowUpdates >= 20, '≥ 20 (each frame that moved)', String(walking.shadowUpdates));
  add('Ground tiles drawn (frustum culling)', still.chunksDrawn > 0 && still.chunksDrawn < still.chunks, `< ${still.chunks}`, String(still.chunksDrawn));
  add('Triangles drawn, with the 1 m patch and coarser far tiles (E1)', still.tris < 258_000, '< 258k (3 m everywhere, before E1)', `${(still.tris / 1000).toFixed(0)}k`);
  add('Frame rate on this machine (fps, frame ms)', still.fps > 0, 'reported', `${still.fps.toFixed(0)} fps, ${still.ms.toFixed(1)} ms, ${(still.tris / 1000).toFixed(0)}k triangles, ×${still.pixelRatio.toFixed(2)}`);
  e.togglePerf();
  return out;
}

/** Print the results as a console table and keep them on window.__simQA. */
export function report(results: QaResult[]): void {
  (window as unknown as { __simQA?: QaResult[] }).__simQA = results;
  console.table(results);
  console.info(`Simulator QA: ${results.filter((r) => r.ok).length} of ${results.length} checks pass.`);
}
