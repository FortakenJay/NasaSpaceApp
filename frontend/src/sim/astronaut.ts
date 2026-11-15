// A suited crew member built from simple shapes (about 1.85 m tall), with a walk cycle and a skateboard stance.
import { KICK_END, KICK_START } from './skate';
// The legs have knees. On the board the feet are placed by two-bone IK, so they stay on the deck and the pushing foot
// reaches the ground.
import * as THREE from 'three';

/** The riding pose. Positions are in the board's frame: x right, y up from the deck, z back. */
export interface SkatePose {
  pushU: number | null; // 0..1 through one push of the back foot; null when not pushing
  braking: boolean; // back foot dragging on the ground
  lean: number; // roll into a turn, radians (negative = to the right)
  gradeRad: number; // slope along the board, uphill positive
}

export interface Astronaut {
  group: THREE.Group;
  /** phase: radians of the stride cycle; moving: walking or not; airborne: mid-jump; skate: the riding pose, or null on foot. */
  animate: (phase: number, moving: boolean, airborne: boolean, skate?: SkatePose | null) => void;
}

const HIP_Y = 0.9;
const THIGH = 0.42; // hip to knee
const SHIN = 0.4; // knee to ankle
const ANKLE_H = 0.09; // ankle above the sole
const DECK_H = 0.1; // the deck above the ground
// regular stance (left foot forward): ankles over the front bolts and on the tail
const FRONT_FOOT = new THREE.Vector3(0, ANKLE_H, -0.21);
const BACK_FOOT = new THREE.Vector3(0, ANKLE_H, 0.23);
// one push: the back foot steps off on the toe side, kicks back along the ground, swings up, steps back on the tail
const PLANT = new THREE.Vector3(0.2, ANKLE_H - DECK_H, -0.05);
const KICK_BACK = new THREE.Vector3(0.22, ANKLE_H - DECK_H, 0.42);
const SWING = new THREE.Vector3(0.12, ANKLE_H + 0.08, 0.32);
const DRAG = new THREE.Vector3(0.16, ANKLE_H - DECK_H, 0.48); // foot brake: the back foot on the ground behind
const SIDEWAYS = -Math.PI / 2; // body yaw riding: facing the toe side, right of travel
const PUSHING = -0.5; // body yaw mid-push: turned to face mostly forward, over the front foot

const smooth = (u: number) => u * u * (3 - 2 * u);
const clamp1 = (v: number) => Math.min(Math.max(v, -1), 1);

interface Leg {
  hip: THREE.Group;
  knee: THREE.Group;
  ankle: THREE.Group;
}

function makeLeg(x: number, suit: THREE.Material, trim: THREE.Material): Leg {
  const hip = new THREE.Group();
  hip.position.set(x, HIP_Y, 0);
  hip.rotation.order = 'ZXY'; // bend in the leg's own plane, then tilt that plane out to the side
  const thigh = new THREE.Mesh(new THREE.CapsuleGeometry(0.1, THIGH - 0.1, 4, 10), suit);
  thigh.position.y = -THIGH / 2;
  const knee = new THREE.Group();
  knee.position.y = -THIGH;
  const shin = new THREE.Mesh(new THREE.CapsuleGeometry(0.09, SHIN - 0.1, 4, 10), suit);
  shin.position.y = -SHIN / 2;
  const ankle = new THREE.Group();
  ankle.position.y = -SHIN;
  ankle.rotation.order = 'XZY'; // undoes the leg's bend and tilt, so the sole stays level
  const boot = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.1, 0.28), trim);
  boot.position.set(0, 0.05 - ANKLE_H, -0.05);
  ankle.add(boot);
  knee.add(shin, ankle);
  hip.add(thigh, knee);
  return { hip, knee, ankle };
}

/** Joint angles directly (the walk): thigh swing (+ = forward) and knee bend (+ = flexed), sole level. */
function pose(l: Leg, thigh: number, bend: number): void {
  l.hip.rotation.set(thigh, 0, 0);
  l.knee.rotation.x = -bend;
  l.ankle.rotation.set(bend - thigh, 0, 0);
}

/** Two-bone IK: the ankle at `t` (body frame), knee forward, sole level. Out of reach, the leg points at it. */
function reach(l: Leg, t: THREE.Vector3): void {
  const dx = t.x - l.hip.position.x;
  const dy = t.y - l.hip.position.y;
  const dz = t.z - l.hip.position.z;
  const side = Math.atan2(dx, -dy);
  const down = Math.hypot(dx, dy);
  const d = Math.min(Math.max(Math.hypot(dz, down), 0.15), THIGH + SHIN - 1e-3);
  const toward = Math.atan2(-dz, down);
  const atHip = Math.acos(clamp1((THIGH * THIGH + d * d - SHIN * SHIN) / (2 * THIGH * d)));
  const bend = Math.PI - Math.acos(clamp1((THIGH * THIGH + SHIN * SHIN - d * d) / (2 * THIGH * SHIN)));
  const thigh = toward + atHip;
  l.hip.rotation.set(thigh, 0, side);
  l.knee.rotation.x = -bend;
  l.ankle.rotation.set(bend - thigh, 0, -side);
}

/** The back foot at u through a push (board frame, into `out`); returns how far the body has turned forward, 0..1. */
function pushFoot(u: number, out: THREE.Vector3): number {
  if (u < KICK_START) {
    const a = smooth(u / KICK_START);
    out.lerpVectors(BACK_FOOT, PLANT, a);
    out.y += 0.12 * Math.sin(Math.PI * a);
    return a;
  }
  if (u < KICK_END) {
    out.lerpVectors(PLANT, KICK_BACK, (u - KICK_START) / (KICK_END - KICK_START));
    return 1;
  }
  if (u < 0.8) {
    const a = smooth((u - KICK_END) / (0.8 - KICK_END));
    out.lerpVectors(KICK_BACK, SWING, a);
    out.y += 0.08 * Math.sin(Math.PI * a);
    return 1;
  }
  const a = smooth((u - 0.8) / 0.2);
  out.lerpVectors(SWING, BACK_FOOT, a);
  return 1 - a;
}

export function makeAstronaut(): Astronaut {
  const suit = new THREE.MeshStandardMaterial({ color: 0xf2efe8, roughness: 0.85 });
  const trim = new THREE.MeshStandardMaterial({ color: 0xb4b7bb, roughness: 0.6, metalness: 0.15 });
  const stripe = new THREE.MeshStandardMaterial({ color: 0xd2562f, roughness: 0.7 });
  const visor = new THREE.MeshStandardMaterial({ color: 0xc9902a, roughness: 0.15, metalness: 0.9 });
  const group = new THREE.Group();
  const rig = new THREE.Group(); // leans into turns on the board
  const body = new THREE.Group();
  group.add(rig);
  rig.add(body);

  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.27, 0.45, 6, 12), suit);
  torso.position.y = 1.22;
  body.add(torso);
  const band = new THREE.Mesh(new THREE.CylinderGeometry(0.285, 0.285, 0.07, 16), stripe);
  band.position.y = 1.05;
  body.add(band);
  const pack = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.62, 0.26), trim);
  pack.position.set(0, 1.28, 0.27);
  body.add(pack);
  const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.2, 20, 16), suit);
  helmet.position.y = 1.7;
  body.add(helmet);
  const face = new THREE.Mesh(new THREE.SphereGeometry(0.17, 20, 12, Math.PI * 0.6, Math.PI * 0.8, Math.PI * 0.3, Math.PI * 0.4), visor);
  face.position.set(0, 1.71, -0.04);
  body.add(face);

  const limb = (r: number, len: number, mat: THREE.Material) => {
    const pivot = new THREE.Group();
    const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 4, 10), mat);
    m.position.y = -len / 2 - r;
    pivot.add(m);
    return pivot;
  };
  const legL = makeLeg(-0.13, suit, trim);
  const legR = makeLeg(0.13, suit, trim);
  const armL = limb(0.075, 0.5, suit);
  const armR = limb(0.075, 0.5, suit);
  armL.position.set(-0.36, 1.5, 0);
  armR.position.set(0.36, 1.5, 0);
  body.add(legL.hip, legR.hip, armL, armR);
  group.traverse((o) => {
    if (o instanceof THREE.Mesh) o.castShadow = true;
  });

  const toBody = new THREE.Matrix4();
  const front = new THREE.Vector3();
  const back = new THREE.Vector3();
  let brakeW = 0; // eases the foot brake in and out

  return {
    group,
    animate(phase, moving, airborne, skate = null) {
      if (skate) {
        brakeW += ((skate.braking ? 1 : 0) - brakeW) * 0.15;
        let turn = 0;
        if (skate.pushU !== null) turn = pushFoot(skate.pushU, back);
        else back.copy(BACK_FOOT);
        if (brakeW > 0.01) {
          back.lerp(DRAG, brakeW);
          turn = Math.max(turn, 0.6 * brakeW);
        }
        front.copy(FRONT_FOOT);
        // the deck pitches with the slope; the ground under the pushing foot slopes the same way
        const tilt = Math.tan(skate.gradeRad);
        front.y -= front.z * tilt;
        back.y -= back.z * tilt;
        // sideways with knees bent; through a push the body turns to face forward and drops over the front foot
        const tuck = airborne ? 0.12 : 0;
        rig.rotation.z = skate.lean;
        body.rotation.set(0, SIDEWAYS + (PUSHING - SIDEWAYS) * turn, 0);
        body.position.set(0.06 * turn, -0.04 - 0.21 * turn - tuck, 0.01 - 0.13 * turn);
        rig.updateMatrix();
        body.updateMatrix();
        toBody.multiplyMatrices(rig.matrix, body.matrix).invert();
        reach(legL, front.applyMatrix4(toBody));
        reach(legR, back.applyMatrix4(toBody));
        // arms out along the board for balance; through a push they come in and swing against the kicking leg
        const kick = skate.pushU !== null && skate.pushU >= KICK_START && skate.pushU < KICK_END ? (skate.pushU - KICK_START) / (KICK_END - KICK_START) : 0;
        armL.rotation.set(-0.3 * turn, 0, -0.9 + 0.55 * turn + Math.sin(phase) * 0.05);
        armR.rotation.set((0.2 + 0.5 * kick) * turn, 0, 0.9 - 0.6 * turn - Math.sin(phase) * 0.05);
        return;
      }
      brakeW = 0;
      rig.rotation.z = 0;
      body.rotation.set(0, 0, 0);
      armL.rotation.z = 0;
      armR.rotation.z = 0;
      const swing = airborne ? 0.35 : moving ? Math.sin(phase) * 0.5 : 0;
      // the knee bends while the leg swings forward, so the boot clears the ground
      pose(legL, swing, airborne ? 0.4 : moving ? Math.max(0, Math.cos(phase)) * 0.6 : 0);
      pose(legR, airborne ? -0.2 : -swing, airborne ? 0.4 : moving ? Math.max(0, -Math.cos(phase)) * 0.6 : 0);
      armL.rotation.x = -swing * 0.7;
      armR.rotation.x = airborne ? -0.6 : swing * 0.7;
      body.position.set(0, moving && !airborne ? Math.abs(Math.cos(phase)) * 0.05 : 0, 0); // the low-gravity lope
    },
  };
}

/** The pressurized rover: the start and finish of every walk. */
export function makeRover(): THREE.Group {
  const g = new THREE.Group();
  const white = new THREE.MeshStandardMaterial({ color: 0xe9e6df, roughness: 0.6 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x2c2f33, roughness: 0.9 });
  const glass = new THREE.MeshStandardMaterial({ color: 0x23364a, roughness: 0.1, metalness: 0.6 });
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(3.2, 1.7, 5.2), white);
  cabin.position.y = 1.65;
  g.add(cabin);
  const nose = new THREE.Mesh(new THREE.BoxGeometry(2.9, 1.0, 0.5), glass);
  nose.position.set(0, 1.95, -2.7);
  g.add(nose);
  for (const x of [-1.75, 1.75]) {
    for (const z of [-1.8, 0, 1.8]) {
      const w = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.55, 0.45, 18), dark);
      w.rotation.z = Math.PI / 2;
      w.position.set(x, 0.55, z);
      g.add(w);
    }
  }
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.6, 8), dark);
  mast.position.set(1.1, 3.3, 1.6);
  g.add(mast);
  const dish = new THREE.Mesh(new THREE.CircleGeometry(0.45, 20), white);
  dish.position.set(1.1, 4.1, 1.6);
  dish.rotation.x = -Math.PI / 3;
  g.add(dish);
  g.traverse((o) => {
    if (o instanceof THREE.Mesh) o.castShadow = true;
  });
  return g;
}
