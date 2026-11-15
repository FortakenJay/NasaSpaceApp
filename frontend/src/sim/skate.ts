// Easter egg: skateboarding on Mars. Off-plan and unofficial, but the physics is honest: what pulls you downhill is
// g sin(grade) with g = 3.71 m/s², what stops you is rolling resistance on regolith, and the thin air (about 0.02 kg/m³
// at Gale, under 2 % of Earth's) does almost nothing. The rolling-resistance numbers are MarsWalk's assumptions for
// small urethane wheels (see TODO.md: "Skateboard"); everything else is textbook mechanics.
//
// A push is a kick, not a motor. The back foot is on the ground for one slice of each push cycle (the same slice the
// animation draws), and that contact adds speed. Between kicks the board only coasts.

/** One push of the back foot, seconds: step off, kick, swing, step back on the tail. Shared with the animation. */
export const PUSH_S = 1.1;
/** Where in that cycle the foot is on the ground, kicking. Shared with pushFoot() in astronaut.ts. */
export const KICK_START = 0.18;
export const KICK_END = 0.55;

export interface SkateParams {
  crrBase: number; // rolling resistance coefficient on smooth, firm ground
  crrPerRoughM: number; // added per metre of the planner's 1 m roughness: small wheels hate rocks
  crrSand: number; // added on loose sand: wheels sink
  crrMax: number;
  kickMu: number; // boot friction on firm ground: the kick cannot push harder than μ × weight without slipping
  pushPowerW: number; // mechanical power while the foot is on the ground; the force falls as speed rises (P / v)
  cruiseMps: number; // kicks fade out approaching this, so pushing alone stays under the wobble; a downhill can still exceed it
  uphillKick: number; // on an uphill, extra push while the foot is down, as a multiple of the slope's pull
  brakeDecel: number; // foot drag, m/s² (friction-limited: mu * g = 0.6 * 3.71 = 2.2 at best)
  rhoAir: number; // kg/m³, Gale surface
  cdA: number; // drag area of an upright suited person, m²
  wipeoutMps: number; // speed wobbles past this: you come off
  roughWipeoutMps: number; // on off-limits (rocky or steep) ground, faster than this and you come off
  muscleEff: number; // mechanical to metabolic
  restW: number; // metabolic power at rest (same as the walking model's floor)
}

export const SKATE: SkateParams = {
  crrBase: 0.04,
  crrPerRoughM: 0.08,
  crrSand: 0.25,
  crrMax: 0.8,
  kickMu: 0.6,
  pushPowerW: 900,
  cruiseMps: 6.2,
  uphillKick: 1.5,
  brakeDecel: 1.5,
  rhoAir: 0.02,
  cdA: 0.8,
  wipeoutMps: 7,
  roughWipeoutMps: 1.2,
  muscleEff: 0.25,
  restW: 60,
};

/** Seconds of each push cycle the foot is actually pushing. */
export function kickContactS(): number {
  return (KICK_END - KICK_START) * PUSH_S;
}

export function rollingCoeff(roughM: number, sand: boolean, p: SkateParams = SKATE): number {
  return Math.min(p.crrBase + p.crrPerRoughM * Math.max(roughM, 0) + (sand ? p.crrSand : 0), p.crrMax);
}

export interface SkateStep {
  v: number; // new speed along the board, m/s (negative = rolling backwards)
  a: number; // acceleration this step, m/s²
  powerW: number; // metabolic power this step
}

/**
 * One time step of riding. v is signed speed along the heading; gradeDeg is the slope ahead (uphill positive);
 * pushS is how much of this slice the foot is on the ground (0 except during a kick); brake is the S key.
 * A kick pushes at min(μ × weight, P / v) for pushS seconds, then the board coasts.
 */
export function skateStep(
  v: number, dt: number, gradeDeg: number, roughM: number, sand: boolean, pushS: number, brake: boolean,
  g: number, massKg: number, p: SkateParams = SKATE,
): SkateStep {
  const th = (gradeDeg * Math.PI) / 180;
  const crr = rollingCoeff(roughM, sand, p);
  const slope = -g * Math.sin(th); // downhill speeds you up
  const rollMax = crr * g * Math.cos(th);
  const contact = Math.min(Math.max(pushS, 0), Math.max(dt, 0));
  const tractionN = p.kickMu * massKg * g;
  const room = Math.min(1, Math.max(0, p.cruiseMps - Math.max(v, 0)) / 1.2); // full kick until near the cruise speed
  // Grip is μ × weight, and weight is only 0.38 of Earth's, so a legal kick is a small shove. On an uphill that
  // shove barely beats the slope. The extra is a harder push past the slip limit, and only while climbing.
  const climbN = th > 0 ? p.uphillKick * massKg * g * Math.sin(th) : 0;
  const pushF = contact > 0 ? (Math.min(tractionN, p.pushPowerW / Math.max(Math.abs(v), 0.3)) + climbN) * room : 0;
  const pushA = dt > 0 ? (pushF / massKg) * (contact / dt) : 0;
  const drive = slope + pushA;
  const braking = brake ? p.brakeDecel : 0;
  // standing still: rolling resistance holds the board unless gravity and the kick beat it
  if (Math.abs(v) < 1e-3 && Math.abs(drive) <= rollMax + braking) {
    const mechJ = pushF * 0.3 * contact;
    return { v: 0, a: 0, powerW: p.restW + (dt > 0 ? mechJ / p.muscleEff / dt : 0) + (brake ? 30 : 0) };
  }
  const dir = Math.abs(v) < 1e-3 ? Math.sign(drive) : Math.sign(v);
  const drag = (0.5 * p.rhoAir * p.cdA * v * Math.abs(v)) / massKg;
  let a = drive - dir * (rollMax + braking) - drag;
  let nv = v + a * dt;
  // resistance and brakes stop the board; they never send it the other way
  if (dir !== 0 && Math.sign(nv) !== dir && Math.abs(drive) <= rollMax + braking) {
    nv = 0;
    a = dt > 0 ? -v / dt : 0;
  }
  const mechJ = pushF * Math.max(Math.abs(v), 0.3) * contact;
  return { v: nv, a, powerW: p.restW + (dt > 0 ? mechJ / p.muscleEff / dt : 0) + (brake ? 30 : 0) };
}

/** Top speed kicking on level ground: kick power, spread over the push cycle, meets rolling resistance and drag. */
export function flatTopSpeed(roughM: number, sand: boolean, g: number, massKg: number, p: SkateParams = SKATE): number {
  const roll = rollingCoeff(roughM, sand, p) * massKg * g;
  const traction = p.kickMu * massKg * g;
  const duty = KICK_END - KICK_START; // the foot is on the ground for this fraction of each push
  if (traction * duty <= roll) return 0;
  // duty * kick force = roll + 0.5 ρ CdA v²; the kick fades to nothing at cruiseMps
  let lo = 0.1;
  let hi = p.cruiseMps;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2;
    const room = Math.min(1, Math.max(0, p.cruiseMps - mid) / 1.2);
    const kick = Math.min(traction, p.pushPowerW / mid) * room;
    const f = duty * kick - roll - 0.5 * p.rhoAir * p.cdA * mid * mid;
    if (f > 0) lo = mid;
    else hi = mid;
  }
  return lo;
}
