// The walk simulator: a crew member on the real Gale terrain, walking at the speed and energy cost the planner
// assumes, under Mars gravity, in the light of the real Sun for the planned morning. Mouse: look and turn (captured with
// a click, freed by Esc, which pauses), wheel to zoom. Keyboard: W/S walk, A/D step sideways, arrows turn, Space jump,
// E work at a stop (or end at the rover), T time speed, V camera, H off-limits overlay.
import * as THREE from 'three';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import type { SimPhysics, SimSun } from '../api';
import { makeAstronaut, makeRover } from './astronaut';
import { makeAlien, makePerseverance, makeSkateboard } from './eggs';
import { KICK_END, KICK_START, PUSH_S, skateStep } from './skate';
import { G_EARTH, metabolicPower, terrainMultiplier, walkSpeed } from './physics';
import type { Terrain, WalkGrid } from './terrain';

export interface SimStop {
  id: string;
  name: string;
  kind: 'start' | 'stop' | 'user';
  x: number;
  z: number;
  workMin: number;
}

export interface SimStatus {
  tS: number; // mission time, seconds since leaving the rover
  walkedM: number;
  energyKj: number;
  x: number;
  z: number;
  lat: number;
  lon: number;
  headingDeg: number; // compass, 0 = north
  gradeDeg: number; // along the walking direction, on the planner's 1 m walk surface
  speedMps: number;
  tooSteep: boolean; // the slope ahead is steeper than a suited walker may take (max_grade_deg)
  terrainMult: number; // planner's slow-down on this ground: (1 + k * roughness) x sand penalty
  roughM: number; // roughness under the boots (m)
  sand: boolean; // loose sand under the boots
  sunAzDeg: number; // the Sun, clockwise from north
  sunElDeg: number; // the Sun above the horizon (negative = below)
  lmstH: number | null; // local mean solar time, hours
  ltstH: number | null; // local true solar time (sundial time), hours
  sol: number | null; // sol number at the rover (Mars Sol Date)
  radioShadow: boolean; // a ridge blocks the line of sight to the rover's antenna (layers/radio.py)
  radioShadowS: number; // seconds out of radio contact so far
  normals: boolean; // N: 1 m relief lit on the far ground (E5)
  // easter eggs (off-plan: they never change the plan, and the debrief says when they were used)
  eggsFound: string[]; // 'perseverance', 'skateboard'
  nearEgg: 'alien' | 'board' | null;
  skate: { has: boolean; riding: boolean; v: number; distM: number; wipeouts: number };
  message: string | null; // a line to show for a few seconds
  // engine performance (F to show)
  perf: { on: boolean; fps: number; ms: number; calls: number; tris: number; pixelRatio: number; shadowUpdates: number; chunksDrawn: number; chunks: number };
  powerW: number;
  inNoGo: boolean;
  noGoS: number; // seconds spent on off-limits ground
  near: SimStop | null; // stop within reach
  working: { id: string; leftS: number } | null;
  visited: string[];
  timeScale: number;
  reserveBreached: boolean;
  outOfOxygen: boolean;
  finished: boolean;
  camera: 'third' | 'first';
  hazard: boolean;
  paused: boolean;
  mouseLocked: boolean; // the browser has handed the mouse to the walk (pointer lock)
  lockNote: string | null; // why the mouse could not be captured, for the pause screen
}

export const TIME_SCALES = [1, 5, 20, 60];

// How finely the HUD shows each number: a step (e.g. 60 = one minute of seconds) or decimals. Anything else: 2 decimals.
const SHOWN: Record<string, { step?: number; dp?: number }> = {
  tS: { step: 60 }, leftS: { step: 60 }, noGoS: { step: 60 }, radioShadowS: { step: 60 },
  x: { dp: 0 }, z: { dp: 0 }, lat: { dp: 6 }, lon: { dp: 6 }, walkedM: { dp: 0 }, distM: { dp: 0 },
  energyKj: { dp: 0 }, powerW: { dp: 0 }, headingDeg: { dp: 0 }, gradeDeg: { dp: 0 },
  sunAzDeg: { dp: 0 }, sunElDeg: { dp: 0 }, fps: { dp: 0 }, ms: { dp: 1 }, tris: { step: 1000 },
};

/** The status as the HUD would draw it: numbers rounded to what is on screen. Equal keys = an identical HUD. */
function displayKey(s: SimStatus): string {
  return JSON.stringify(s, (k, v) => {
    if (typeof v !== 'number' || !Number.isFinite(v)) return v;
    const r = SHOWN[k];
    if (r?.step) return Math.floor(v / r.step);
    return Number(v.toFixed(r?.dp ?? 2));
  });
}
/** Real seconds per simulation tick: the simulation advances in fixed ticks, whatever the frame rate (E8). */
export const TICK_S = 1 / 60;
const REACH_M = 8;
// E1: the near-field patch of 1 m terrain (half size, blend band, how far the walker may drift before it is rebuilt)
const PATCH_HALF_M = 80;
const PATCH_BLEND_M = 8;
const PATCH_MOVE_M = 16;
// E1: the coarse tiles' level of detail by distance from the walker: every 3 m, then 6 m, then 12 m
const LOD_NEAR_M = 350;
const LOD_FAR_M = 800;
const JUMP_MPS = 1.6; // take-off speed of a suited hop: about 0.35 m high and 0.9 s in the air at 3.71 m/s²
const TURN_RAD_S = 1.6;
const LOOK_RAD_PER_COUNT = (0.0066 * 15 * Math.PI) / 180; // Overwatch's 0.0066° per mouse count at its default sensitivity, 15
const DRAG_RAD_PER_PX = 0.005; // touch and pen, which cannot capture the pointer: drag to look
const RELOCK_WAIT_MS = 1500; // Chrome refuses to capture the mouse again for 1.25 s after the user pressed Esc
const ROUTE_OUT = 0x3dd6e8; // the way out to a stop
const ROUTE_BACK = 0xff6a00; // the way back to the rover
const MAX_LEAN = 0.35; // rad, rider's roll into a turn
const AIM_LEAD_MAX = 1.7; // rad: on the board the camera may look this far ahead of where the board points
const wrapPi = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

export class SimEngine {
  readonly status: SimStatus;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private sun: THREE.DirectionalLight;
  private hemi: THREE.HemisphereLight;
  private skyMat: THREE.ShaderMaterial | null = null;
  private sunDisc: THREE.Mesh;
  private sunDir = new THREE.Vector3(0.5, 0.7, 0.3).normalize();
  private hazardMesh: THREE.Group | null = null;
  private groundChunks: THREE.Mesh[] = [];
  private tiles: { mesh: THREE.Mesh; hazard: THREE.Mesh | null; levels: THREE.BufferGeometry[]; center: THREE.Vector3; level: number }[] = [];
  // E1: the 1 m terrain drawn around the walker; the coarse tiles' materials cut a square hole under it
  private patch: { mesh: THREE.Mesh; hazard: THREE.Mesh | null; cx: number; cz: number } | null = null;
  private patchMat: THREE.MeshStandardMaterial | null = null;
  private patchHazardMat: THREE.MeshBasicMaterial | null = null;
  private hole = { value: new THREE.Vector3(0, 0, -1) }; // (centre x, centre z, half size); half < 0 = no hole
  private coarseMat: THREE.MeshStandardMaterial | null = null;
  private normalTex: THREE.DataTexture | null = null; // E5, built on first use
  // easter eggs
  percy: ReturnType<typeof makePerseverance> | null = null; // read by QA
  private alien: ReturnType<typeof makeAlien> | null = null;
  private alienSpot: { x: number; z: number } | null = null;
  private board = makeSkateboard();
  private boardSpot = { x: 0, z: 0 };
  private messageUntil = 0;
  private waveUntil = 0;
  // performance: adaptive resolution and shadows drawn only when something changed
  private frameMs: number[] = [];
  private lastAdapt = 0;
  private pixelRatio = 1;
  private maxPixelRatio = 1;
  private shadowKey = '';
  private shadowUpdates = 0;
  private perfT0 = performance.now();
  private perfFrames = 0;
  private tmpA = new THREE.Color();
  private tmpB = new THREE.Color();
  private tmpV = new THREE.Vector3();
  private frustum = new THREE.Frustum();
  private projView = new THREE.Matrix4();
  private beaconStops = new Map<string, SimStop>();
  private astro = makeAstronaut();
  private trail: Line2;
  private trailPts: number[] = [];
  private lineMats: LineMaterial[] = [];
  private beacons = new Map<string, THREE.Mesh>();
  private rings = new Map<string, Line2>();
  private keys = new Set<string>();
  private heading: number; // radians, 0 = north (-z), clockwise
  private y = 0;
  private vy = 0;
  private airborne = false;
  private phase = 0;
  private aimYaw = 0; // where the mouse points, same convention as heading; walking, heading follows it at once
  private lean = 0;
  private pushU: number | null = null; // 0..1 through the push you see, null when not pushing
  private kickLeft = 0; // seconds of foot-on-ground push not yet applied to the board
  private planLines: Line2[] = []; // the route on the ground: way out, then way back
  private guidePts: { x: number; z: number }[] | null = null;
  private guideAt = 0;
  private following = false; // walking that path after Go
  private skipMove = false;
  private unlockedAt = -Infinity;
  private lockByEvent = false; // older browsers report a refused capture only by the pointerlockerror event
  readonly lockSupported: boolean;
  private camPitch = 0.32;
  private camDist = 8;
  private raf = 0;
  private last = performance.now();
  private acc = 0; // real seconds not yet simulated
  private prev = { x: 0, z: 0, y: 0, heading: 0 }; // the walker at the previous tick
  private drawn = { x: 0, z: 0, y: 0, heading: 0 }; // where the walker is drawn: between the last two ticks
  private idleFrames = 0;
  private disposed = false;
  ticks = 0; // read by QA
  private onFootstep: (() => void) | null = null; // the sound of a step (sim/audio.ts)
  patchBuilds = 0; // read by QA
  private listeners: ((s: SimStatus) => void)[] = [];
  private lastEmit = 0;
  private hudKey = '';
  private hudSnap!: SimStatus;
  hudUpdates = 0; // snapshots handed to the HUD; read by QA
  private dragging = false;
  private mass: number;
  private usableS: number;
  private totalS: number;

  constructor(
    private host: HTMLElement,
    private terrain: Terrain,
    private physics: SimPhysics,
    private stops: SimStop[],
    route: { x: number; z: number }[],
    routeBack: { x: number; z: number }[],
    photo: THREE.Texture,
    hazard: THREE.Texture | null,
    private walk: WalkGrid | null = null,
    private sunTrack: SimSun | null = null,
  ) {
    this.mass = physics.body_mass_kg + physics.suit_mass_kg;
    this.totalS = physics.o2_capacity_h * 3600;
    this.usableS = this.totalS * (1 - physics.walkback_reserve_frac);
    const start = stops.find((s) => s.kind === 'start') ?? { x: 0, z: 0 };
    const first = stops.find((s) => s.kind !== 'start') ?? { x: 0, z: -10 };
    this.heading = Math.atan2(first.x - start.x, -(first.z - start.z));
    this.aimYaw = this.heading;
    const px = start.x + 14 * Math.sin(this.heading); // a few steps out of the rover, facing the first stop
    const pz = start.z - 14 * Math.cos(this.heading);
    const ll = terrain.toLatLon(px, pz);
    this.status = {
      tS: 0, walkedM: 0, energyKj: 0, x: px, z: pz, lat: ll.lat, lon: ll.lon, headingDeg: 0, gradeDeg: 0, speedMps: 0,
      tooSteep: false, terrainMult: 1, roughM: 0, sand: false, sunAzDeg: 90, sunElDeg: 45, lmstH: sunTrack?.lmst_h ?? null,
      ltstH: sunTrack?.ltst_h ?? null, sol: sunTrack?.sol ?? null, radioShadow: false, radioShadowS: 0, normals: false,
      eggsFound: [], nearEgg: null, skate: { has: false, riding: false, v: 0, distM: 0, wipeouts: 0 }, message: null,
      perf: { on: false, fps: 0, ms: 0, calls: 0, tris: 0, pixelRatio: 1, shadowUpdates: 0, chunksDrawn: 0, chunks: 0 },
      powerW: 0, inNoGo: false, noGoS: 0, near: null, working: null, visited: [], timeScale: 1, reserveBreached: false,
      outOfOxygen: false, finished: false, camera: 'third', hazard: false, paused: false, mouseLocked: false, lockNote: null,
    };
    this.y = terrain.heightAt(px, pz);
    this.status.radioShadow = walk?.inRadioShadow(px, pz) ?? false;
    this.hudSnap = { ...this.status };
    this.hudKey = displayKey(this.status);

    // renderer, camera
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.maxPixelRatio = Math.min(window.devicePixelRatio, 2);
    this.pixelRatio = this.maxPixelRatio;
    this.renderer.setPixelRatio(this.pixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.autoUpdate = false; // redrawn only when the walker, the board or the Sun moved
    this.renderer.info.autoReset = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(this.renderer.domElement);
    this.lockSupported = typeof this.renderer.domElement.requestPointerLock === 'function';
    this.camera = new THREE.PerspectiveCamera(60, 1, 0.3, 9000);

    // Mars: butterscotch sky, dust haze, a small pale Sun (0.35° across, two-thirds of Earth's) with a bluish halo
    // that shows when it is low. Where the Sun is comes from the Mars24 track for the planned morning.
    const sky = new THREE.Color(0xd9b38c);
    this.scene.background = sky;
    this.scene.fog = new THREE.FogExp2(0xd6b08a, 0.00042);
    this.scene.add(this.skyDome());
    this.hemi = new THREE.HemisphereLight(0xf0cfa5, 0x5a3a26, 1.1);
    this.scene.add(this.hemi);
    const discR = 7000 * Math.tan(((0.35 / 2) * Math.PI) / 180);
    this.sunDisc = new THREE.Mesh(new THREE.CircleGeometry(discR, 32), new THREE.MeshBasicMaterial({ color: 0xfff6e8, fog: false, depthWrite: false }));
    this.sunDisc.renderOrder = -1;
    this.scene.add(this.sunDisc);
    this.sun = new THREE.DirectionalLight(0xfff1de, 2.4);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera;
    sc.left = -40;
    sc.right = 40;
    sc.top = 40;
    sc.bottom = -40;
    sc.near = 1;
    sc.far = 400;
    this.scene.add(this.sun, this.sun.target);

    // ground
    photo.colorSpace = THREE.SRGBColorSpace;
    photo.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    // The ground (E1): 64 x 64-cell tiles of the 3 m mesh at three levels of detail by distance, outside the view not
    // drawn at all (frustum culling), and near the walker the 1 m terrain itself as a patch that follows them. The
    // coarse tiles skip their pixels under the patch, so the two never draw over each other.
    const groundMat = this.holed(new THREE.MeshStandardMaterial({ map: photo, roughness: 0.96, metalness: 0 }));
    this.coarseMat = groundMat;
    const hazardMat = hazard
      ? this.holed(new THREE.MeshBasicMaterial({ map: hazard, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }))
      : null;
    if (hazardMat) {
      this.hazardMesh = new THREE.Group();
      this.hazardMesh.visible = false;
      this.scene.add(this.hazardMesh);
    }
    for (const t of terrain.lodTiles(64)) {
      const ground = new THREE.Mesh(t.levels[0], groundMat);
      ground.receiveShadow = true;
      this.groundChunks.push(ground);
      this.scene.add(ground);
      const hz = hazardMat && this.hazardMesh ? new THREE.Mesh(t.levels[0], hazardMat) : null;
      if (hz && this.hazardMesh) this.hazardMesh.add(hz);
      this.tiles.push({ mesh: ground, hazard: hz, levels: t.levels, center: t.center, level: 0 });
    }
    this.status.perf.chunks = this.groundChunks.length;
    if (walk) {
      this.patchMat = new THREE.MeshStandardMaterial({ map: photo, roughness: 0.96, metalness: 0 });
      this.patchHazardMat = hazard
        ? new THREE.MeshBasicMaterial({ map: hazard, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 })
        : null;
      this.updatePatch(px, pz);
      this.y = this.groundY(px, pz);
    }

    // the planned route, draped on the ground: cyan on the way out, orange on the way back. The trail walked so far is white.
    this.drape(route, ROUTE_OUT);
    this.drape(routeBack, ROUTE_BACK);
    this.trailPts = [px, this.y + 0.15, pz, px, this.y + 0.15, pz];
    this.trail = this.line(this.trailPts, 0xffffff, 2.5, 0.9);
    this.scene.add(this.trail);

    // stops: light pillars you can see from far away; the rover at the start
    for (const s of stops) {
      const h = this.fineGround(s.x, s.z);
      if (s.kind === 'start') {
        const rover = makeRover();
        rover.position.set(s.x, h, s.z);
        rover.rotation.y = -this.heading;
        this.scene.add(rover);
        continue;
      }
      const pillar = new THREE.Mesh(
        new THREE.CylinderGeometry(0.6, 0.6, 70, 20, 1, true),
        new THREE.MeshBasicMaterial({ color: 0xffb030, transparent: true, opacity: 0.3, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide }),
      );
      pillar.position.set(s.x, h + 35, s.z);
      this.scene.add(pillar);
      this.beacons.set(s.id, pillar);
      this.beaconStops.set(s.id, s);
      // the reach ring, draped on the ground (a flat disc would cut through a slope)
      const ringPts: number[] = [];
      for (let i = 0; i <= 64; i++) {
        const a = (i / 64) * Math.PI * 2;
        const rx = s.x + REACH_M * Math.cos(a);
        const rz = s.z + REACH_M * Math.sin(a);
        ringPts.push(rx, this.aboveBoth(rx, rz) + 0.15, rz);
      }
      const ring = this.line(ringPts, 0xffd257, 3, 0.85);
      this.rings.set(s.id, ring);
      this.scene.add(ring);
      this.scene.add(this.label(s.id, s.x, h + 12, s.z));
    }

    this.astro.group.position.set(px, this.y, pz);
    this.scene.add(this.astro.group);
    this.placeEggs(start, [...route, ...routeBack]);
    this.keepPrev();
    this.interpolate(1);

    this.bindInput();
    this.resize();
    this.raf = requestAnimationFrame(this.loop);
  }

  onStatus(fn: (s: SimStatus) => void): void {
    this.listeners.push(fn);
  }

  setTimeScale(v: number): void {
    this.status.timeScale = v;
    this.emit(true);
  }

  cycleTimeScale(): void {
    const i = TIME_SCALES.indexOf(this.status.timeScale);
    this.setTimeScale(TIME_SCALES[(i + 1) % TIME_SCALES.length]);
  }

  toggleHazard(): void {
    if (this.hazardMesh) this.hazardMesh.visible = !this.hazardMesh.visible;
    this.status.hazard = !!this.hazardMesh?.visible;
    this.emit(true);
  }

  toggleCamera(): void {
    this.status.camera = this.status.camera === 'third' ? 'first' : 'third';
    this.astro.group.visible = this.status.camera === 'third';
    this.emit(true);
  }

  setPaused(p: boolean): void {
    this.status.paused = p;
    this.keys.clear();
    if (p) this.releaseMouse();
    this.emit(true);
  }

  /** Resume from the pause screen: capture the mouse first; the clock starts once the browser hands it over. */
  resume(): void {
    const s = this.status;
    if (s.finished || s.outOfOxygen) return;
    if (this.lockSupported) this.captureMouse();
    else this.setPaused(false);
  }

  /** Esc, when the browser lets the page see it (the mouse is not captured): pause; resume only without pointer lock. */
  escape(): void {
    const s = this.status;
    if (s.finished || s.outOfOxygen) return;
    if (!s.paused) this.setPaused(true);
    else if (!this.lockSupported) this.setPaused(false);
  }

  /** Ask the browser for the mouse (needs a click or key press). Raw counts when it offers them, as games use. */
  captureMouse(): void {
    if (!this.lockSupported || this.status.mouseLocked) return;
    const el = this.renderer.domElement;
    try {
      const p = el.requestPointerLock({ unadjustedMovement: true }) as Promise<void> | undefined;
      this.lockByEvent = !p;
      p?.catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'NotSupportedError') {
          (el.requestPointerLock() as Promise<void> | undefined)?.catch(this.lockRefused);
        } else this.lockRefused();
      });
    } catch {
      this.lockRefused();
    }
  }

  private releaseMouse(): void {
    if (document.pointerLockElement === this.renderer.domElement) document.exitPointerLock();
  }

  /** Right after Esc the browser says no: say so and stay paused. Otherwise it never will: play on, drag to look. */
  private lockRefused = (): void => {
    const s = this.status;
    if (performance.now() - this.unlockedAt < RELOCK_WAIT_MS) {
      s.lockNote = 'The browser waits a second after Esc before it hands the mouse back. Click Resume again.';
    } else {
      s.lockNote = null;
      if (s.paused && !s.finished && !s.outOfOxygen) this.setPaused(false);
    }
    this.emit(true);
  };

  /** E: start work at the stop in reach, or end the walk at the rover. */
  act(): void {
    const s = this.status;
    if (s.working || s.finished || s.outOfOxygen) return;
    if (s.nearEgg === 'alien') {
      if (!s.eggsFound.includes('perseverance')) s.eggsFound = [...s.eggsFound, 'perseverance'];
      this.waveUntil = performance.now() + 4000;
      this.say('The alien lowers the cardboard Mars and waves. Perseverance keeps shooting. (It is officially near Jezero crater, about 3,800 km from here.)', 9000);
      this.emit(true);
      return;
    }
    if (s.nearEgg === 'board' && !s.skate.has) {
      s.skate = { ...s.skate, has: true };
      if (!s.eggsFound.includes('skateboard')) s.eggsFound = [...s.eggsFound, 'skateboard'];
      this.say('You found a skateboard. Press B to ride, B again to step off. It is not in the plan.', 7000);
      this.emit(true);
      return;
    }
    if (!s.near) return;
    if (s.near.kind === 'start') {
      if (s.visited.length > 0) {
        s.finished = true;
        s.paused = true;
        this.releaseMouse();
      }
    } else if (!s.visited.includes(s.near.id)) {
      s.working = { id: s.near.id, leftS: s.near.workMin * 60 };
      if (s.skate.riding) s.skate = { ...s.skate, riding: false, v: 0 }; // step off to work
    }
    this.emit(true);
  }

  jump(): void {
    if (!this.airborne && !this.status.working) {
      this.airborne = true;
      this.vy = JUMP_MPS;
      // energy of the hop: lifting crew + suit, at 25 % muscle efficiency
      const h = (JUMP_MPS * JUMP_MPS) / (2 * this.physics.gravity_mps2);
      this.status.energyKj += (this.mass * this.physics.gravity_mps2 * h) / 0.25 / 1000;
    }
  }

  /** B: step on or off the skateboard (once you have it). */
  toggleSkate(): void {
    const s = this.status;
    if (!s.skate.has || s.working || s.finished || s.outOfOxygen) return;
    s.skate = { ...s.skate, riding: !s.skate.riding, v: 0 };
    this.emit(true);
  }

  /**
   * N: light the 3 m mesh with 1 m relief from a normal map (E5), gently (strength 0.6), because the HiRISE photo
   * already carries the shading of the moment it was taken. Built on first use (about a tenth of a second).
   */
  toggleNormals(): void {
    if (!this.walk || !this.coarseMat) return;
    if (!this.normalTex) this.normalTex = this.walk.normalMap(this.terrain);
    const on = this.coarseMat.normalMap === null;
    this.coarseMat.normalMap = on ? this.normalTex : null;
    this.coarseMat.normalScale.set(0.6, 0.6);
    this.coarseMat.needsUpdate = true;
    this.status.normals = on;
    this.emit(true);
  }

  togglePerf(): void {
    this.status.perf = { ...this.status.perf, on: !this.status.perf.on };
    this.emit(true);
  }

  private say(text: string, ms: number): void {
    this.status.message = text;
    this.messageUntil = performance.now() + ms;
  }

  /** Teleport for testing and for "skip to the next stop" in a demo. */
  placeAt(x: number, z: number): void {
    this.status.x = x;
    this.status.z = z;
    this.updatePatch(x, z);
    this.y = this.groundY(x, z);
    this.keepPrev(); // a jump, not a walk: nothing to draw in between
    this.interpolate(1);
    this.emit(true);
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.releaseMouse();
    document.removeEventListener('pointerlockchange', this.onLockChange);
    document.removeEventListener('pointerlockerror', this.onLockError);
    window.removeEventListener('keydown', this.onKeyDown);
    window.removeEventListener('keyup', this.onKeyUp);
    window.removeEventListener('resize', this.onResize);
    this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown);
    window.removeEventListener('pointerup', this.onPointerUp);
    window.removeEventListener('pointermove', this.onPointerMove);
    this.renderer.domElement.removeEventListener('wheel', this.onWheel);
    this.scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        const m = o.material as THREE.Material | THREE.Material[];
        (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
      }
    });
    for (const t of this.tiles) t.levels.forEach((g) => g.dispose()); // the levels not on screen
    this.normalTex?.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  // --- simulation -------------------------------------------------------------------------------

  private step(dtReal: number): void {
    const s = this.status;
    const p = this.physics;
    if (s.paused || s.finished || s.outOfOxygen) return;
    let left = dtReal * s.timeScale;
    if (this.following && (this.keys.has('s') || this.keys.has('a') || this.keys.has('d') || this.keys.has('arrowleft') || this.keys.has('arrowright') || this.keys.has('arrowdown'))) {
      this.following = false;
      this.keys.delete('w');
    } else if (this.following) {
      const next = this.nextOnGuide();
      if (!next) {
        this.following = false;
        this.keys.delete('w');
        this.say('You are there.', 5000);
      } else this.keys.add('w');
    }
    // turning and jumping happen in real time; walking, work and the clock in mission time
    const fwd = (this.keys.has('w') || this.keys.has('arrowup') ? 1 : 0) - (this.keys.has('s') || this.keys.has('arrowdown') ? 1 : 0);
    const side = (this.keys.has('d') ? 1 : 0) - (this.keys.has('a') ? 1 : 0);
    const arrows = (this.keys.has('arrowright') ? 1 : 0) - (this.keys.has('arrowleft') ? 1 : 0);
    const headingBefore = this.heading;
    if (s.skate.riding) {
      // A/D lean the board; it carves toward where you look, no faster than the lean turns it
      this.aimYaw += Math.max(-1, Math.min(1, side + arrows)) * TURN_RAD_S * dtReal;
      const most = TURN_RAD_S * dtReal;
      this.heading += Math.max(-most, Math.min(most, wrapPi(this.aimYaw - this.heading)));
      const lead = wrapPi(this.aimYaw - this.heading);
      if (Math.abs(lead) > AIM_LEAD_MAX) this.aimYaw = this.heading + Math.sign(lead) * AIM_LEAD_MAX;
    } else {
      this.aimYaw += arrows * TURN_RAD_S * dtReal;
      this.heading = this.aimYaw;
    }
    if (this.following) {
      const next = this.nextOnGuide();
      if (next) {
        this.heading = Math.atan2(next.x - s.x, -(next.z - s.z));
        this.aimYaw = this.heading;
      }
    }
    const strafe = s.skate.riding ? 0 : side; // on foot, A/D step sideways
    this.syncKick(dtReal, fwd);
    let moved = false;
    while (left > 1e-6) {
      const dt = Math.min(left, 0.5);
      left -= dt;
      s.tS += dt;
      // the ground under the boots, whatever you are doing
      s.roughM = this.walk ? this.walk.roughnessM(s.x, s.z) : 0;
      s.sand = this.walk ? this.walk.isSand(s.x, s.z) : false;
      s.terrainMult = terrainMultiplier(s.roughM, s.sand, p.roughness_penalty_per_m ?? 0, p.sand_penalty ?? 1);
      s.radioShadow = this.walk ? this.walk.inRadioShadow(s.x, s.z) : false;
      if (s.radioShadow) s.radioShadowS += dt;
      // time on off-limits ground counts whatever you do there: walking, standing, working or riding
      if ((this.walk ?? this.terrain).isNoGo(s.x, s.z)) s.noGoS += dt;
      if (s.working) {
        s.gradeDeg = 0;
        s.tooSteep = false;
        s.working.leftS -= dt;
        s.energyKj += (p.work_power_w * dt) / 1000;
        s.powerW = p.work_power_w;
        s.speedMps = 0;
        if (s.working.leftS <= 0) {
          s.visited = [...s.visited, s.working.id];
          const b = this.beacons.get(s.working.id);
          if (b) (b.material as THREE.MeshBasicMaterial).color.set(0x3ad07c);
          s.working = null;
        }
        continue;
      }
      if (s.skate.riding) {
        moved = this.skateStepOnce(dt, fwd) || moved;
        continue;
      }
      if (fwd === 0 && strafe === 0) {
        s.speedMps = 0;
        s.gradeDeg = 0;
        s.tooSteep = false;
        s.powerW = metabolicPower(this.mass, p.gravity_mps2, 0, 0);
        s.energyKj += (s.powerW * dt) / 1000;
        continue;
      }
      // the planner's model, step for step (cost/physics.py edge_time_energy): the grade comes from the 1 m walk
      // surface the route search uses; speed from the grade; rough ground and loose sand stretch the time by the
      // planner's multiplier at the same power; grades past max_grade_deg cannot be walked at all.
      const ang = this.heading + Math.atan2(strafe, fwd); // forward, back, sideways or diagonal
      const dirX = Math.sin(ang);
      const dirZ = -Math.cos(ang);
      const surf = this.walk ?? this.terrain;
      const h0 = surf.heightAt(s.x, s.z);
      const grade = (Math.atan2(surf.heightAt(s.x + dirX, s.z + dirZ) - h0, 1) * 180) / Math.PI;
      s.gradeDeg = grade;
      s.tooSteep = Math.abs(grade) > p.max_grade_deg;
      if (s.tooSteep) {
        // too steep to take: you stand there, breathing at rest
        s.speedMps = 0;
        s.powerW = metabolicPower(this.mass, p.gravity_mps2, 0, 0);
        s.energyKj += (s.powerW * dt) / 1000;
        continue;
      }
      const vModel = walkSpeed(grade, p.walk_speed_cap_mps ?? Infinity) * (fwd > 0 ? 1 : 0.5); // backwards or sideways: half speed
      let v = vModel / s.terrainMult; // along the slope, as the plan times it: hypot(run, climb) / v
      const across = v * Math.cos((grade * Math.PI) / 180); // the part of it that covers ground on the map
      const nx = s.x + dirX * across * dt;
      const nz = s.z + dirZ * across * dt;
      const b = this.terrain.bounds();
      if (nx < b.minX + 2 || nx > b.maxX - 2 || nz < b.minZ + 2 || nz > b.maxZ - 2) {
        v = 0; // edge of the mapped ground
      } else {
        const d = Math.hypot(nx - s.x, nz - s.z, surf.heightAt(nx, nz) - h0); // along the walk surface, like the plan
        s.x = nx;
        s.z = nz;
        s.walkedM += d;
        const before = Math.floor(this.phase / Math.PI);
        this.phase += (d / 1.4) * Math.PI;
        if (Math.floor(this.phase / Math.PI) !== before) this.onFootstep?.(); // a foot comes down every half stride
        moved = true;
      }
      s.speedMps = v;
      s.powerW = v > 0 ? metabolicPower(this.mass, p.gravity_mps2, grade, vModel) : metabolicPower(this.mass, p.gravity_mps2, 0, 0);
      s.energyKj += (s.powerW * dt) / 1000;
      s.inNoGo = (this.walk ?? this.terrain).isNoGo(s.x, s.z);
    }
    if (fwd === 0 && strafe === 0 && !s.working && !s.skate.riding) {
      s.inNoGo = (this.walk ?? this.terrain).isNoGo(s.x, s.z);
      s.tooSteep = false;
    }
    this.checkEggs();
    // vertical: Mars gravity, real time
    const ground = this.groundY(s.x, s.z);
    if (this.airborne) {
      this.vy -= p.gravity_mps2 * dtReal;
      this.y += this.vy * dtReal;
      if (this.y <= ground) {
        this.y = ground;
        this.airborne = false;
        this.vy = 0;
      }
    } else {
      this.y = ground;
    }
    if (moved && this.trailEnd() > 2) {
      this.trailPts.push(s.x, ground + 0.15, s.z);
      (this.trail.geometry as LineGeometry).setPositions(this.trailPts);
    }
    // reach, oxygen
    s.near = null;
    let best = Infinity;
    for (const st of this.stops) {
      const d = Math.hypot(st.x - s.x, st.z - s.z);
      if (d <= (st.kind === 'start' ? 12 : REACH_M) && d < best) {
        best = d;
        s.near = st;
      }
    }
    s.reserveBreached = s.tS > this.usableS;
    if (s.tS >= this.totalS) {
      s.outOfOxygen = true;
      s.paused = true;
      this.releaseMouse();
    }
    const ll = this.terrain.toLatLon(s.x, s.z);
    s.lat = ll.lat;
    s.lon = ll.lon;
    s.headingDeg = ((((this.heading * 180) / Math.PI) % 360) + 360) % 360;
    this.animateRider(dtReal, headingBefore, fwd, moved);
  }

  /** Advance the push cycle and, the moment the foot meets the ground, bank one kick of push time. */
  private syncKick(dtReal: number, fwd: number): void {
    const riding = this.status.skate.riding;
    const pushing = riding && fwd > 0 && !this.airborne;
    const prev = this.pushU;
    if (!riding) this.pushU = null;
    else if (this.pushU === null) this.pushU = pushing ? 0 : null;
    else {
      this.pushU += dtReal / PUSH_S;
      if (this.pushU >= 1) this.pushU = pushing ? this.pushU - 1 : null;
    }
    const down = this.pushU !== null && this.pushU >= KICK_START && this.pushU < KICK_END;
    const prevDown = prev !== null && prev >= KICK_START && prev < KICK_END;
    const wrapped = prev !== null && this.pushU !== null && this.pushU < prev;
    if (down && !this.airborne && (!prevDown || wrapped)) this.kickLeft += (KICK_END - KICK_START) * PUSH_S;
    if (!riding || this.airborne) this.kickLeft = 0;
  }

  /** The walker you see. On the board: the push cycle from syncKick, the foot brake on S, and a roll into turns. */
  private animateRider(dtReal: number, headingBefore: number, fwd: number, moved: boolean): void {
    const s = this.status;
    const riding = s.skate.riding;
    // the lean that balances a turn: tan(lean) = v ω / g
    const w = dtReal > 0 ? wrapPi(this.heading - headingBefore) / dtReal : 0;
    const target = riding ? Math.max(-MAX_LEAN, Math.min(MAX_LEAN, -Math.atan((Math.abs(s.skate.v) * w) / this.physics.gravity_mps2))) : 0;
    this.lean += (target - this.lean) * Math.min(1, dtReal * 6);
    const pose = riding
      ? { pushU: this.pushU, braking: fwd < 0 && Math.abs(s.skate.v) > 0.1, lean: this.lean, gradeRad: (s.gradeDeg * Math.PI) / 180 }
      : null;
    this.astro.animate(this.phase, moved, this.airborne, pose);
  }

  /** One mission-time slice on the board: skate.ts physics on the planner's 1 m ground. Returns whether it moved. */
  private skateStepOnce(dt: number, fwd: number): boolean {
    const s = this.status;
    const p = this.physics;
    const sk = s.skate;
    const dirX = Math.sin(this.heading);
    const dirZ = -Math.cos(this.heading);
    const surf = this.walk ?? this.terrain;
    const h0 = surf.heightAt(s.x, s.z);
    const grade = (Math.atan2(surf.heightAt(s.x + dirX, s.z + dirZ) - h0, 1) * 180) / Math.PI;
    const pushS = Math.min(dt, this.kickLeft);
    this.kickLeft -= pushS;
    const r = skateStep(sk.v, dt, grade, s.roughM, s.sand, pushS, fwd < 0, p.gravity_mps2, this.mass + 3);
    s.gradeDeg = grade;
    s.tooSteep = false;
    s.speedMps = Math.abs(r.v);
    s.powerW = r.powerW;
    s.energyKj += (r.powerW * dt) / 1000;
    let v = r.v;
    const across = v * Math.cos((grade * Math.PI) / 180);
    const nx = s.x + dirX * across * dt;
    const nz = s.z + dirZ * across * dt;
    const b = this.terrain.bounds();
    let moved = false;
    if (nx < b.minX + 2 || nx > b.maxX - 2 || nz < b.minZ + 2 || nz > b.maxZ - 2) {
      v = 0;
    } else if (v !== 0) {
      const d = Math.hypot(nx - s.x, nz - s.z, surf.heightAt(nx, nz) - h0);
      s.x = nx;
      s.z = nz;
      s.walkedM += d;
      sk.distM += d;
      this.phase += d * 0.5;
      moved = true;
    }
    s.inNoGo = surf.isNoGo(s.x, s.z);
    // wipeouts: speed wobbles, or rocks and ledges at speed
    const wob = Math.abs(v) > 7;
    const rocks = s.inNoGo && Math.abs(v) > 1.2;
    if (wob || rocks) {
      s.skate = { ...sk, riding: false, v: 0, wipeouts: sk.wipeouts + 1 };
      s.speedMps = 0;
      this.say(wob ? `Wiped out: speed wobbles at ${Math.abs(v).toFixed(1)} m/s. In a suit, a fall is how gloves and visors crack.` : 'Wiped out on rocky ground. Small wheels and Mars rocks do not mix.', 7000);
      return moved;
    }
    s.skate = { ...sk, v, distM: sk.distM };
    return moved;
  }

  /** Put the eggs out: the board by the rover, Perseverance and the alien on quiet flat ground off the route. */
  private placeEggs(start: { x: number; z: number }, route: { x: number; z: number }[]): void {
    const side = this.heading + Math.PI / 2; // to the right of the way out, a few steps from the rover
    this.boardSpot = { x: start.x + Math.sin(side) * 6, z: start.z - Math.cos(side) * 6 };
    this.board.position.set(this.boardSpot.x, this.fineGround(this.boardSpot.x, this.boardSpot.z), this.boardSpot.z);
    this.board.rotation.y = 0.7;
    this.scene.add(this.board);
    if (!this.walk) return;
    const avoid = [...this.stops, ...route.filter((_, i) => i % 10 === 0)];
    const spot = this.walk.findQuietSpot(start, 150, 320, avoid, 90);
    if (!spot) return;
    this.alienSpot = spot;
    const percy = makePerseverance();
    const alien = makeAlien();
    const yaw = Math.atan2(0.5, -1); // any fixed bearing works: the pair faces each other
    const px = spot.x + Math.sin(yaw) * 4.5;
    const pz = spot.z - Math.cos(yaw) * 4.5;
    percy.group.position.set(px, this.fineGround(px, pz), pz);
    percy.group.rotation.y = -yaw + Math.PI; // front (-z) toward the alien
    alien.group.position.set(spot.x, this.fineGround(spot.x, spot.z), spot.z);
    alien.group.rotation.y = -yaw; // sign (-z) toward the rover
    this.scene.add(percy.group, alien.group);
    this.scene.updateMatrixWorld(true);
    // the mast camera looks at the picture
    const target = alien.sign.getWorldPosition(this.tmpV.clone());
    percy.head.lookAt(target);
    percy.head.rotateY(Math.PI); // the head's cameras face its -z
    this.percy = percy;
    this.alien = alien;
  }

  /** What egg is in reach, and the alien's little animation. */
  private checkEggs(): void {
    const s = this.status;
    let near: 'alien' | 'board' | null = null;
    if (!s.skate.has && Math.hypot(s.x - this.boardSpot.x, s.z - this.boardSpot.z) < 2.5) near = 'board';
    if (this.alienSpot && Math.hypot(s.x - this.alienSpot.x, s.z - this.alienSpot.z) < 12) near = 'alien';
    s.nearEgg = near;
    if (s.message && performance.now() > this.messageUntil) s.message = null;
  }

  /** The cardboard-Mars alien: antennae bob; it peeks over the sign when you come close; it waves when greeted. */
  private animateEggs(now: number): void {
    const s = this.status;
    this.board.visible = !s.skate.has || s.skate.riding;
    if (s.skate.riding) {
      // pitched with the slope, rolled on its trucks into the turn
      this.board.position.set(this.drawn.x, this.drawn.y, this.drawn.z);
      this.board.rotation.set((s.gradeDeg * Math.PI) / 180, -this.drawn.heading, this.lean * 0.5, 'YXZ');
    }
    if (!this.alien || !this.alienSpot) return;
    const d = Math.hypot(s.x - this.alienSpot.x, s.z - this.alienSpot.z);
    const peek = d < 30 ? 1 : 0;
    const a = this.alien;
    a.head.position.y += ((1.62 + peek * 0.33) - a.head.position.y) * 0.08;
    a.head.rotation.z = Math.sin(now / 600) * 0.06;
    if (peek) {
      // turn to look at you
      const dx = s.x - this.alienSpot.x;
      const dz = s.z - this.alienSpot.z;
      const target = -Math.atan2(dx, -dz) - a.group.rotation.y; // local yaw that points the face (-z) at the walker
      const delta = Math.atan2(Math.sin(target - a.head.rotation.y), Math.cos(target - a.head.rotation.y));
      a.head.rotation.y += delta * 0.05;
    } else a.head.rotation.y *= 0.95;
    const waving = now < this.waveUntil;
    a.armR.rotation.z = waving ? -1.9 + Math.sin(now / 120) * 0.4 : -0.24;
    a.armR.rotation.x = waving ? 0 : -0.55;
    a.sign.position.y = waving ? 1.1 : 1.42;
  }

  private trailEnd(): number {
    const n = this.trailPts.length;
    return Math.hypot(this.trailPts[n - 3] - this.status.x, this.trailPts[n - 1] - this.status.z);
  }

  /**
   * One frame: run as many fixed ticks as real time asks for (at most a quarter second's worth after a stall), then
   * draw. While paused or finished it draws once more and then sleeps (no frames at all) until something calls wake().
   */
  private loop = (): void => {
    this.raf = 0;
    if (this.disposed) return;
    const now = performance.now();
    const frame = now - this.last;
    this.frameMs.push(frame);
    if (this.frameMs.length > 60) this.frameMs.shift();
    this.last = now;
    this.acc = Math.min(this.acc + frame / 1000, 0.25);
    while (this.acc >= TICK_S) {
      this.tick();
      this.acc -= TICK_S;
    }
    this.interpolate(this.acc / TICK_S);
    this.draw(now);
    this.emit(false);
    const s = this.status;
    this.idleFrames = s.paused || s.finished || s.outOfOxygen ? this.idleFrames + 1 : 0;
    if (this.idleFrames < 3 && this.raf === 0) this.raf = requestAnimationFrame(this.loop);
  };

  private tick(): void {
    this.keepPrev();
    this.step(TICK_S);
    this.ticks++;
  }

  private keepPrev(): void {
    const p = this.prev;
    p.x = this.status.x;
    p.z = this.status.z;
    p.y = this.y;
    p.heading = this.heading;
  }

  /** Draw the walker `a` (0..1) of the way from the previous tick to the latest one. */
  private interpolate(a: number): void {
    const p = this.prev;
    const d = this.drawn;
    d.x = p.x + (this.status.x - p.x) * a;
    d.z = p.z + (this.status.z - p.z) * a;
    d.y = p.y + (this.y - p.y) * a;
    d.heading = p.heading + (this.heading - p.heading) * a;
  }

  /** A ground material that skips its pixels under the near-field patch (E1): a square hole that moves with it. */
  private holed<M extends THREE.Material>(m: M): M {
    m.onBeforeCompile = (sh) => {
      sh.uniforms.uHole = this.hole;
      sh.vertexShader = sh.vertexShader
        .replace('#include <common>', '#include <common>\nvarying vec2 vHoleXZ;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvHoleXZ = (modelMatrix * vec4(transformed, 1.0)).xz;');
      sh.fragmentShader = sh.fragmentShader
        .replace('#include <common>', '#include <common>\nuniform vec3 uHole;\nvarying vec2 vHoleXZ;')
        .replace('void main() {', 'void main() {\n  if (uHole.z > 0.0 && abs(vHoleXZ.x - uHole.x) < uHole.z && abs(vHoleXZ.y - uHole.y) < uHole.z) discard;');
    };
    m.customProgramCacheKey = () => 'marswalk-holed';
    return m;
  }

  /** Rebuild the 1 m patch around (x, z) once the walker has drifted PATCH_MOVE_M from its centre (about 3 ms). */
  private updatePatch(x: number, z: number): void {
    if (!this.walk || !this.patchMat) return;
    if (this.patch && Math.max(Math.abs(x - this.patch.cx), Math.abs(z - this.patch.cz)) < PATCH_MOVE_M) return;
    const cx = Math.round(x / 4) * 4;
    const cz = Math.round(z / 4) * 4;
    const geo = this.walk.patch(cx, cz, PATCH_HALF_M, PATCH_BLEND_M, this.terrain);
    if (this.patch) {
      this.patch.mesh.geometry.dispose();
      this.patch.mesh.geometry = geo;
      if (this.patch.hazard) this.patch.hazard.geometry = geo;
      this.patch.cx = cx;
      this.patch.cz = cz;
    } else {
      this.patchMat.polygonOffset = true; // wins the 1 m overlap with the coarse tiles at its edge
      this.patchMat.polygonOffsetFactor = -1;
      this.patchMat.polygonOffsetUnits = -1;
      const mesh = new THREE.Mesh(geo, this.patchMat);
      mesh.receiveShadow = true;
      this.scene.add(mesh);
      const hazard = this.patchHazardMat && this.hazardMesh ? new THREE.Mesh(geo, this.patchHazardMat) : null;
      if (hazard) this.hazardMesh?.add(hazard);
      this.patch = { mesh, hazard, cx, cz };
    }
    this.hole.value.set(cx, cz, PATCH_HALF_M - 1);
    this.patchBuilds++;
  }

  /** Each coarse tile at the level of detail its distance from (x, z) calls for. */
  private updateLod(x: number, z: number): void {
    for (const t of this.tiles) {
      const r = t.levels[0].boundingSphere?.radius ?? 0;
      const d = Math.max(Math.hypot(t.center.x - x, t.center.z - z) - r, 0);
      const level = d < LOD_NEAR_M ? 0 : d < LOD_FAR_M ? 1 : 2;
      if (level === t.level) continue;
      t.level = level;
      t.mesh.geometry = t.levels[level];
      if (t.hazard) t.hazard.geometry = t.levels[level];
    }
  }

  /** The height of the ground as drawn at (x, z): the 1 m patch near the walker, the 3 m mesh elsewhere. */
  groundY(x: number, z: number): number {
    if (this.patch && this.walk) return this.walk.patchHeight(x, z, this.patch.cx, this.patch.cz, PATCH_HALF_M, PATCH_BLEND_M, this.terrain);
    return this.terrain.heightAt(x, z);
  }

  /** The 1 m terrain where there is one: for things that stand still (the rover, the eggs), seen up close. */
  private fineGround(x: number, z: number): number {
    return this.walk ? this.walk.groundAt(x, z) : this.terrain.heightAt(x, z);
  }

  /** Above both surfaces: for lines drawn once (the route, the reach rings), which must show on either mesh. */
  private aboveBoth(x: number, z: number): number {
    return Math.max(this.terrain.heightAt(x, z), this.fineGround(x, z));
  }

  private draw(now: number): void {
    this.updatePatch(this.drawn.x, this.drawn.z);
    this.updateLod(this.drawn.x, this.drawn.z);
    this.place();
    this.animateEggs(now);
    this.updateShadows();
    this.renderer.render(this.scene, this.camera);
    this.measure(now);
  }

  /** Start drawing again after the loop went to sleep (pause, debrief), e.g. on a key, a resize or a setting. */
  wake(): void {
    if (this.raf !== 0 || this.disposed) return;
    this.idleFrames = 0;
    this.last = performance.now();
    this.raf = requestAnimationFrame(this.loop);
  }

  /** True while the render loop is asleep (nothing is drawn). Read by QA. */
  get sleeping(): boolean {
    return this.raf === 0 && !this.disposed;
  }

  /** Call `fn` each time a foot comes down (null: stop). */
  setFootstep(fn: (() => void) | null): void {
    this.onFootstep = fn;
  }

  /** Mid-hop. Read by QA. */
  get inAir(): boolean {
    return this.airborne;
  }

  /** Replace the route on the ground: cyan toward the place, orange back to the rover. */
  setLiveRoute(going: { x: number; z: number }[], back: { x: number; z: number }[]): void {
    for (const line of this.planLines) {
      this.scene.remove(line);
      line.geometry.dispose();
    }
    this.planLines = [];
    this.following = false;
    this.drape(going, ROUTE_OUT);
    this.drape(back, ROUTE_BACK);
    this.guidePts = going.length > 1 ? going : null;
    this.guideAt = 0;
  }

  /** A chain of 1 m steps, smoothed, laid on the ground. */
  private drape(leg: { x: number; z: number }[], color: number): void {
    if (leg.length < 2) return;
    const pts: number[] = [];
    const k = 3;
    for (let i = 0; i < leg.length; i++) {
      let sx = 0;
      let sz = 0;
      let n = 0;
      for (let j = Math.max(0, i - k); j <= Math.min(leg.length - 1, i + k); j++) {
        sx += leg[j].x;
        sz += leg[j].z;
        n++;
      }
      const x = i === 0 || i === leg.length - 1 ? leg[i].x : sx / n;
      const z = i === 0 || i === leg.length - 1 ? leg[i].z : sz / n;
      pts.push(x, this.aboveBoth(x, z) + 0.25, z);
    }
    const line = this.line(pts, color, 3.5, 0.95);
    this.planLines.push(line);
    this.scene.add(line);
  }

  /** Walk or ride the way-out path. Steer or brake to stop. Staying on the board keeps kicking along it. */
  goAlongPath(): boolean {
    if (!this.guidePts || this.guidePts.length < 2) return false;
    this.following = true;
    this.guideAt = 0;
    this.setPaused(false);
    this.keys.add('w');
    this.say('Heading there. Steer or brake to stop.', 6000);
    return true;
  }

  private nextOnGuide(): { x: number; z: number } | null {
    const pts = this.guidePts;
    if (!pts) return null;
    const s = this.status;
    while (this.guideAt < pts.length && Math.hypot(pts[this.guideAt].x - s.x, pts[this.guideAt].z - s.z) < 4) this.guideAt++;
    return this.guideAt < pts.length ? pts[this.guideAt] : null;
  }

  /** Turn to face a point (QA, and "face the next stop" in a demo). */
  faceTo(x: number, z: number): void {
    this.heading = Math.atan2(x - this.status.x, -(z - this.status.z));
    this.aimYaw = this.heading;
    this.keepPrev();
    this.interpolate(1);
  }

  /** The easter-egg models, for QA. */
  get eggModels(): { percy: ReturnType<typeof makePerseverance> | null; alien: ReturnType<typeof makeAlien> | null } {
    return { percy: this.percy, alien: this.alien };
  }

  /**
   * Run the simulation for `realS` seconds of real time in fixed ticks, as the loop would, without drawing. For QA and
   * tests: the result is the same whatever the frame rate, because the loop runs the same ticks.
   */
  advance(realS: number): void {
    const n = Math.round(realS / TICK_S);
    for (let i = 0; i < n; i++) this.tick();
    this.interpolate(1);
    this.updatePatch(this.status.x, this.status.z);
    this.emit(true);
  }

  /**
   * Shadows: redraw the shadow map only when the walker, the board or the Sun has moved (or the alien is animating).
   * The Sun counts in 0.1° steps: it moves about 0.004° a second, and a smaller shift does not change a shadow.
   */
  private updateShadows(): void {
    const s = this.status;
    const alienNear = this.alienSpot ? Math.hypot(s.x - this.alienSpot.x, s.z - this.alienSpot.z) < 60 : false;
    const key = `${s.x.toFixed(2)},${s.z.toFixed(2)},${this.y.toFixed(2)},${this.heading.toFixed(3)},${s.sunAzDeg.toFixed(1)},${s.sunElDeg.toFixed(1)},${this.phase.toFixed(2)}`;
    if (key !== this.shadowKey || alienNear) {
      this.shadowKey = key;
      this.renderer.shadowMap.needsUpdate = true;
      this.shadowUpdates++;
    }
  }

  /** Frame statistics, and adaptive resolution: drop the pixel ratio when frames run slow, raise it when there is room. */
  private measure(now: number): void {
    const info = this.renderer.info.render;
    this.perfFrames++;
    let drawn = 0;
    // frustum test the same way the renderer does, for the overlay
    if (this.status.perf.on) {
      this.frustum.setFromProjectionMatrix(this.projView.multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse));
      for (const m of this.groundChunks) if (m.geometry.boundingSphere && this.frustum.intersectsSphere(m.geometry.boundingSphere)) drawn++;
    }
    if (now - this.perfT0 >= 1000) {
      const avg = this.frameMs.reduce((a, b) => a + b, 0) / Math.max(this.frameMs.length, 1);
      this.status.perf = {
        ...this.status.perf,
        fps: (this.perfFrames * 1000) / (now - this.perfT0),
        ms: avg,
        calls: info.calls,
        tris: info.triangles,
        pixelRatio: this.pixelRatio,
        shadowUpdates: this.shadowUpdates,
        chunksDrawn: this.status.perf.on ? drawn : this.status.perf.chunksDrawn,
      };
      this.perfFrames = 0;
      this.shadowUpdates = 0;
      this.perfT0 = now;
      if (now - this.lastAdapt > 2000 && this.frameMs.length >= 30) {
        let pr = this.pixelRatio;
        if (avg > 24 && pr > 0.6) pr = Math.max(0.6, pr - 0.15); // under ~40 fps: render fewer pixels
        else if (avg < 14 && pr < this.maxPixelRatio) pr = Math.min(this.maxPixelRatio, pr + 0.1); // over ~70 fps: sharpen
        if (pr !== this.pixelRatio) {
          this.pixelRatio = pr;
          this.renderer.setPixelRatio(pr);
          this.resize();
          this.lastAdapt = now;
        }
      }
    }
  }

  private place(): void {
    const s = this.status;
    const { x, z, y } = this.drawn; // between the last two ticks (E8): smooth motion at any frame rate
    this.astro.group.position.set(x, y + (s.skate.riding ? 0.1 : 0), z);
    this.astro.group.rotation.y = -this.drawn.heading;
    // the camera looks where the mouse points, from behind the walker; on the board it rides low and close, as in
    // skate games
    const yaw = this.aimYaw;
    const riding = s.skate.riding;
    if (s.camera === 'first') {
      const eye = y + (riding ? 1.65 : 1.7);
      this.camera.position.set(x, eye, z);
      this.camera.lookAt(this.tmpV.set(x + Math.sin(yaw) * 10, eye - Math.tan(this.camPitch - 0.32) * 10, z - Math.cos(yaw) * 10));
    } else {
      const d = this.camDist * (riding ? 0.7 : 1);
      const lookY = y + (riding ? 1.0 : 1.4);
      const cx = x - Math.sin(yaw) * d * Math.cos(this.camPitch);
      const cz = z + Math.cos(yaw) * d * Math.cos(this.camPitch);
      const cy = Math.max(lookY - 0.2 + Math.sin(this.camPitch) * d, this.groundY(cx, cz) + (riding ? 0.6 : 1.2));
      this.camera.position.set(cx, cy, cz);
      this.camera.lookAt(x, lookY, z);
    }
    // a light pillar fades as you walk up to it, so it marks the stop without blinding you
    for (const [id, pillar] of this.beacons) {
      const st = this.beaconStops.get(id);
      if (!st) continue;
      // a stop you have already worked stays as a dimmer green marker
      const done = s.visited.includes(id) ? 0.5 : 1;
      const ring = this.rings.get(id);
      if (ring) (ring.material as LineMaterial).opacity = done < 1 ? 0.3 : 0.85;
      const d = Math.hypot(st.x - s.x, st.z - s.z);
      (pillar.material as THREE.MeshBasicMaterial).opacity = 0.3 * done * Math.min(Math.max((d - 6) / 60, 0.06), 1);
    }
    this.light();
    this.sun.position.set(x + this.sunDir.x * 200, y + this.sunDir.y * 200, z + this.sunDir.z * 200);
    this.sun.target.position.set(x, y, z);
  }

  /** The Sun at mission time tS, from the Mars24 track (interpolated), as (azimuth, elevation) in degrees. */
  sunAt(tS: number): { az: number; el: number } | null {
    const tr = this.sunTrack;
    if (!tr || tr.az_el.length === 0) return null;
    const f = tS / 60 / tr.step_min;
    const i = Math.min(Math.max(Math.floor(f), 0), tr.az_el.length - 1);
    const j = Math.min(i + 1, tr.az_el.length - 1);
    const w = Math.min(Math.max(f - i, 0), 1);
    const [a0, e0] = tr.az_el[i];
    const [a1, e1] = tr.az_el[j];
    const da = ((((a1 - a0) % 360) + 540) % 360) - 180; // shortest way round
    return { az: (((a0 + da * w) % 360) + 360) % 360, el: e0 + (e1 - e0) * w };
  }

  /** Point the sunlight, the sky and the haze at the Sun's real position for this moment of the walk. */
  private light(): void {
    const s = this.status;
    const sp = this.sunAt(s.tS);
    if (sp) {
      s.sunAzDeg = sp.az;
      s.sunElDeg = sp.el;
      const tr = this.sunTrack;
      if (tr) {
        const marsH = (s.tS / 3600) * (24 / 24.6597); // Mars hours per Earth hour
        s.lmstH = (tr.lmst_h + marsH) % 24;
        s.ltstH = (tr.ltst_h + marsH) % 24; // the equation of time barely moves in a few hours
        if (tr.sol !== undefined) s.sol = tr.sol + Math.floor((tr.lmst_h + marsH) / 24);
      }
    }
    const az = (s.sunAzDeg * Math.PI) / 180;
    const el = (s.sunElDeg * Math.PI) / 180;
    this.sunDir.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
    const smooth = (a: number, b: number, x: number) => {
      const u = Math.min(Math.max((x - a) / (b - a), 0), 1);
      return u * u * (3 - 2 * u);
    };
    const day = smooth(-6, 15, s.sunElDeg); // twilight lasts long on Mars: dust scatters light past sunset
    this.sun.intensity = 2.6 * smooth(-0.5, 6, s.sunElDeg);
    this.sun.color.setRGB(1, 0.86 + 0.08 * day, 0.74 + 0.13 * day);
    this.hemi.intensity = 0.12 + 1.0 * day;
    (this.scene.background as THREE.Color).copy(this.tmpA.setHex(0x1e1a24).lerp(this.tmpB.setHex(0xd9b38c), day));
    (this.scene.fog as THREE.FogExp2).color.copy(this.tmpA.setHex(0x1c1820).lerp(this.tmpB.setHex(0xd6b08a), day));
    if (this.skyMat) {
      this.skyMat.uniforms.sunDir.value.copy(this.sunDir);
      this.skyMat.uniforms.day.value = day;
    }
    this.sunDisc.position.copy(this.camera.position).addScaledVector(this.sunDir, 7000);
    this.sunDisc.lookAt(this.camera.position);
    this.sunDisc.visible = s.sunElDeg > -0.5;
  }

  /**
   * Hand the HUD a new snapshot, at most every 150 ms and only if something it shows changed at the precision it
   * shows it (E9): standing still, the HUD redraws about once a minute instead of seven times a second.
   */
  private emit(force: boolean): void {
    if (force) this.wake();
    const now = performance.now();
    if (!force && now - this.lastEmit < 150) return;
    this.lastEmit = now;
    const key = displayKey(this.status);
    if (key === this.hudKey && !force) return;
    this.hudKey = key;
    this.hudSnap = { ...this.status };
    this.hudUpdates++;
    for (const fn of this.listeners) fn(this.hudSnap);
  }

  /** useSyncExternalStore: subscribe to HUD snapshots. */
  subscribe = (fn: () => void): (() => void) => {
    const l = () => fn();
    this.listeners.push(l);
    return () => {
      this.listeners = this.listeners.filter((x) => x !== l);
    };
  };

  /** useSyncExternalStore: the latest HUD snapshot (the same object until something shown changes). */
  getSnapshot = (): SimStatus => this.hudSnap;

  // --- scenery helpers ---------------------------------------------------------------------------

  private line(pts: number[], color: number, width: number, opacity: number): Line2 {
    const g = new LineGeometry();
    g.setPositions(pts);
    const m = new LineMaterial({ color, linewidth: width, transparent: opacity < 1, opacity, worldUnits: false });
    this.lineMats.push(m);
    return new Line2(g, m);
  }

  private label(text: string, x: number, y: number, z: number): THREE.Sprite {
    const c = document.createElement('canvas');
    c.width = 128;
    c.height = 64;
    const ctx = c.getContext('2d') as CanvasRenderingContext2D;
    ctx.font = '600 44px Barlow, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineWidth = 8;
    ctx.strokeStyle = 'rgba(20,14,10,0.85)';
    ctx.strokeText(text, 64, 34);
    ctx.fillStyle = '#ffe2a8';
    ctx.fillText(text, 64, 34);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false, transparent: true }));
    sp.position.set(x, y, z);
    sp.scale.set(8, 4, 1);
    return sp;
  }

  private skyDome(): THREE.Mesh {
    const m = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        top: { value: new THREE.Color(0xa8714a) },
        horizon: { value: new THREE.Color(0xe8c9a2) },
        night: { value: new THREE.Color(0x15121a) },
        sunDir: { value: this.sunDir.clone() },
        day: { value: 1 },
      },
      vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      // butterscotch by day; around a low Sun the dust scatters blue (the Martian sunset); dark after twilight
      fragmentShader:
        'uniform vec3 top; uniform vec3 horizon; uniform vec3 night; uniform vec3 sunDir; uniform float day; varying vec3 vP;' +
        'void main(){ float t = clamp(vP.y*1.6, 0.0, 1.0); vec3 c = mix(horizon, top, t);' +
        ' float g = pow(max(dot(normalize(vP), sunDir), 0.0), 18.0);' +
        ' float low = 1.0 - smoothstep(0.0, 0.35, sunDir.y);' +
        ' c = mix(c, vec3(0.62, 0.74, 0.86), g * low * 0.85) + vec3(1.0, 0.95, 0.85) * pow(max(dot(normalize(vP), sunDir), 0.0), 400.0) * 0.6;' +
        ' gl_FragColor = vec4(mix(night + vec3(0.25, 0.32, 0.45) * g * 0.6, c, day), 1.0); }',
    });
    this.skyMat = m;
    const dome = new THREE.Mesh(new THREE.SphereGeometry(8000, 32, 16), m);
    dome.onBeforeRender = () => dome.position.copy(this.camera.position);
    return dome;
  }

  // --- input -------------------------------------------------------------------------------------

  private typing(e: Event): boolean {
    const t = e.target as HTMLElement | null;
    return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
  }

  private onKeyDown = (e: KeyboardEvent): void => {
    if (this.typing(e)) return;
    const k = e.key.toLowerCase();
    if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(k)) {
      this.keys.add(k);
      e.preventDefault();
    } else if (k === ' ') {
      this.jump();
      e.preventDefault();
    } else if (k === 'e') this.act();
    else if (k === 't') this.cycleTimeScale();
    else if (k === 'v') this.toggleCamera();
    else if (k === 'h') this.toggleHazard();
    else if (k === 'b') this.toggleSkate();
    else if (k === 'f') this.togglePerf();
    else if (k === 'n') this.toggleNormals();
  };

  private onKeyUp = (e: KeyboardEvent): void => {
    this.keys.delete(e.key.toLowerCase());
  };

  /** A click on the scene captures the mouse; touch and pen drag to look instead. */
  private onPointerDown = (e: PointerEvent): void => {
    const s = this.status;
    this.dragging = true;
    if (e.pointerType === 'mouse' && this.lockSupported) {
      if (!s.mouseLocked && !s.paused && !s.finished && !s.outOfOxygen) this.captureMouse();
    } else (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  private onPointerUp = (): void => {
    this.dragging = false;
  };

  private onPointerMove = (e: PointerEvent): void => {
    if (this.status.mouseLocked) {
      if (this.skipMove) {
        this.skipMove = false; // the first movement after capture can carry the jump to the lock point
        return;
      }
      this.look(e.movementX * LOOK_RAD_PER_COUNT, e.movementY * LOOK_RAD_PER_COUNT);
    } else if (this.dragging) this.look(e.movementX * DRAG_RAD_PER_PX, e.movementY * DRAG_RAD_PER_PX * 0.8);
  };

  /** Turn (mouse left/right) and look up or down (mouse forward/back), as in a shooter. */
  private look(dYaw: number, dPitch: number): void {
    const s = this.status;
    if (s.paused || s.finished || s.outOfOxygen) return;
    this.aimYaw += dYaw;
    this.camPitch = Math.min(Math.max(this.camPitch + dPitch, -0.2), 1.35);
  }

  /** The mouse was captured or freed. Freed during play (Esc, or the window lost focus) pauses the walk. */
  private onLockChange = (): void => {
    const s = this.status;
    const locked = document.pointerLockElement === this.renderer.domElement;
    s.mouseLocked = locked;
    if (locked) {
      s.lockNote = null;
      this.skipMove = true;
      if (s.paused && !s.finished && !s.outOfOxygen) this.setPaused(false);
    } else {
      this.unlockedAt = performance.now();
      if (!s.paused && !s.finished && !s.outOfOxygen) this.setPaused(true);
    }
    this.emit(true);
  };

  private onLockError = (): void => {
    if (this.lockByEvent) this.lockRefused();
  };

  private onWheel = (e: WheelEvent): void => {
    this.camDist = Math.min(Math.max(this.camDist * (e.deltaY > 0 ? 1.12 : 0.89), 3), 120);
    e.preventDefault();
  };

  private onResize = (): void => this.resize();

  private resize(): void {
    const w = this.host.clientWidth || window.innerWidth;
    const h = this.host.clientHeight || window.innerHeight;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    for (const m of this.lineMats) m.resolution.set(w, h);
  }

  private bindInput(): void {
    window.addEventListener('keydown', this.onKeyDown);
    window.addEventListener('keyup', this.onKeyUp);
    window.addEventListener('resize', this.onResize);
    this.renderer.domElement.addEventListener('pointerdown', this.onPointerDown);
    window.addEventListener('pointerup', this.onPointerUp);
    window.addEventListener('pointermove', this.onPointerMove);
    this.renderer.domElement.addEventListener('wheel', this.onWheel, { passive: false });
    document.addEventListener('pointerlockchange', this.onLockChange);
    document.addEventListener('pointerlockerror', this.onLockError);
  }

  /** Press or release a movement key from on-screen controls (and in tests). */
  setKey(key: string, down: boolean): void {
    if (down) this.keys.add(key);
    else this.keys.delete(key);
  }

  /** G_EARTH re-exported for the HUD's "0.38 g". */
  static readonly gEarth = G_EARTH;
}
