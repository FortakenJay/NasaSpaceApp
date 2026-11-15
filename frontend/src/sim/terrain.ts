// The walk area from GET /api/sim/terrain (frame) and /api/sim/terrain.bin (heights, off-limits cells) on a regular
// grid in local metres (origin at the rover, x east, z south, y up), and the conversion between local metres and lat/lon.
import * as THREE from 'three';
import type { SimFineMeta, SimTerrain, SimTerrainData } from '../api';

export class Terrain {
  readonly rows: number;
  readonly cols: number;
  readonly heights: Float32Array; // metres relative to the rover
  readonly nogo: Uint8Array; // 1 = off-limits
  readonly t: SimTerrain;

  constructor(t: SimTerrainData) {
    this.t = t;
    this.rows = t.rows;
    this.cols = t.cols;
    const n = t.rows * t.cols;
    if (t.heightsBin.byteLength !== 2 * n + ((n + 7) >> 3)) throw new Error(`terrain heights are ${t.heightsBin.byteLength} bytes, expected ${2 * n + ((n + 7) >> 3)}`);
    const dv = new DataView(t.heightsBin);
    this.heights = new Float32Array(n);
    for (let i = 0; i < n; i++) this.heights[i] = t.h0 + dv.getUint16(i * 2, true) / 100;
    const bits = new Uint8Array(t.heightsBin, 2 * n);
    this.nogo = new Uint8Array(n);
    for (let i = 0; i < n; i++) this.nogo[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1;
  }

  toLocal(lat: number, lon: number): { x: number; z: number } {
    return { x: (lon - this.t.lon0) * this.t.kx, z: -(lat - this.t.lat0) * this.t.kz };
  }

  toLatLon(x: number, z: number): { lat: number; lon: number } {
    return { lat: this.t.lat0 - z / this.t.kz, lon: this.t.lon0 + x / this.t.kx };
  }

  /** Grid coordinates (fractional) of a local point. */
  private cell(x: number, z: number): { c: number; r: number } {
    return { c: (x - this.t.x0) / this.t.dx, r: (z - this.t.z0) / this.t.dz };
  }

  bounds(): { minX: number; maxX: number; minZ: number; maxZ: number } {
    const xa = this.t.x0;
    const xb = this.t.x0 + (this.cols - 1) * this.t.dx;
    const za = this.t.z0;
    const zb = this.t.z0 + (this.rows - 1) * this.t.dz;
    return { minX: Math.min(xa, xb), maxX: Math.max(xa, xb), minZ: Math.min(za, zb), maxZ: Math.max(za, zb) };
  }

  /** Ground height at a local point (bilinear). */
  heightAt(x: number, z: number): number {
    const { c, r } = this.cell(x, z);
    const c0 = Math.min(Math.max(Math.floor(c), 0), this.cols - 2);
    const r0 = Math.min(Math.max(Math.floor(r), 0), this.rows - 2);
    const fc = Math.min(Math.max(c - c0, 0), 1);
    const fr = Math.min(Math.max(r - r0, 0), 1);
    const h = this.heights;
    const i = r0 * this.cols + c0;
    const top = h[i] * (1 - fc) + h[i + 1] * fc;
    const bot = h[i + this.cols] * (1 - fc) + h[i + this.cols + 1] * fc;
    return top * (1 - fr) + bot * fr;
  }

  isNoGo(x: number, z: number): boolean {
    const { c, r } = this.cell(x, z);
    const ci = Math.round(c);
    const ri = Math.round(r);
    if (ci < 0 || ri < 0 || ci >= this.cols || ri >= this.rows) return true;
    return this.nogo[ri * this.cols + ci] === 1;
  }

  /**
   * The ground as square tiles of `size` cells (sharing their edge vertices), so three.js can skip every tile outside
   * the view (frustum culling). Normals come from the whole grid by central differences, so tiles meet without seams.
   */
  chunks(size = 64): THREE.BufferGeometry[] {
    const { rows, cols } = this;
    const { dx, dz } = this.t;
    const nrm = new Float32Array(rows * cols * 3);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const hl = this.heights[r * cols + Math.max(c - 1, 0)];
        const hr = this.heights[r * cols + Math.min(c + 1, cols - 1)];
        const hu = this.heights[Math.max(r - 1, 0) * cols + c];
        const hd = this.heights[Math.min(r + 1, rows - 1) * cols + c];
        const sx = (hr - hl) / (dx * (Math.min(c + 1, cols - 1) - Math.max(c - 1, 0)));
        const sz = (hd - hu) / (dz * (Math.min(r + 1, rows - 1) - Math.max(r - 1, 0)));
        const len = Math.hypot(sx, 1, sz);
        const i = (r * cols + c) * 3;
        nrm[i] = -sx / len;
        nrm[i + 1] = 1 / len;
        nrm[i + 2] = -sz / len;
      }
    }
    const out: THREE.BufferGeometry[] = [];
    for (let r0 = 0; r0 < rows - 1; r0 += size) {
      for (let c0 = 0; c0 < cols - 1; c0 += size) {
        const r1 = Math.min(r0 + size, rows - 1);
        const c1 = Math.min(c0 + size, cols - 1);
        const nr = r1 - r0 + 1;
        const nc = c1 - c0 + 1;
        const pos = new Float32Array(nr * nc * 3);
        const uv = new Float32Array(nr * nc * 2);
        const nn = new Float32Array(nr * nc * 3);
        for (let r = 0; r < nr; r++) {
          for (let c = 0; c < nc; c++) {
            const gi = (r0 + r) * cols + (c0 + c);
            const li = r * nc + c;
            pos[li * 3] = this.t.x0 + (c0 + c) * dx;
            pos[li * 3 + 1] = this.heights[gi];
            pos[li * 3 + 2] = this.t.z0 + (r0 + r) * dz;
            uv[li * 2] = (c0 + c + 0.5) / cols;
            uv[li * 2 + 1] = 1 - (r0 + r + 0.5) / rows;
            nn[li * 3] = nrm[gi * 3];
            nn[li * 3 + 1] = nrm[gi * 3 + 1];
            nn[li * 3 + 2] = nrm[gi * 3 + 2];
          }
        }
        const idx = new Uint32Array((nr - 1) * (nc - 1) * 6);
        let k = 0;
        for (let r = 0; r < nr - 1; r++) {
          for (let c = 0; c < nc - 1; c++) {
            const a = r * nc + c;
            const d = a + nc;
            idx[k++] = a;
            idx[k++] = d;
            idx[k++] = a + 1;
            idx[k++] = a + 1;
            idx[k++] = d;
            idx[k++] = d + 1;
          }
        }
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
        g.setAttribute('normal', new THREE.BufferAttribute(nn, 3));
        g.setIndex(new THREE.BufferAttribute(idx, 1));
        g.computeBoundingSphere();
        out.push(g);
      }
    }
    return out;
  }

  /**
   * The ground as tiles of `size` cells at three levels of detail (E1): every 3 m, 6 m and 12 m (strides 1, 2, 4),
   * each with a 2 m skirt hanging from its edges so tiles at different levels meet without visible cracks.
   */
  lodTiles(size = 64): { center: THREE.Vector3; levels: THREE.BufferGeometry[] }[] {
    const { rows, cols } = this;
    const nrm = this.normals();
    const out: { center: THREE.Vector3; levels: THREE.BufferGeometry[] }[] = [];
    for (let r0 = 0; r0 < rows - 1; r0 += size) {
      for (let c0 = 0; c0 < cols - 1; c0 += size) {
        const r1 = Math.min(r0 + size, rows - 1);
        const c1 = Math.min(c0 + size, cols - 1);
        const levels = [1, 2, 4].map((k) => this.tile(r0, r1, c0, c1, k, nrm));
        out.push({ center: levels[0].boundingSphere?.center.clone() ?? new THREE.Vector3(), levels });
      }
    }
    return out;
  }

  private normals(): Float32Array {
    const { rows, cols } = this;
    const { dx, dz } = this.t;
    const nrm = new Float32Array(rows * cols * 3);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const hl = this.heights[r * cols + Math.max(c - 1, 0)];
        const hr = this.heights[r * cols + Math.min(c + 1, cols - 1)];
        const hu = this.heights[Math.max(r - 1, 0) * cols + c];
        const hd = this.heights[Math.min(r + 1, rows - 1) * cols + c];
        const sx = (hr - hl) / (dx * (Math.min(c + 1, cols - 1) - Math.max(c - 1, 0)));
        const sz = (hd - hu) / (dz * (Math.min(r + 1, rows - 1) - Math.max(r - 1, 0)));
        const len = Math.hypot(sx, 1, sz);
        const i = (r * cols + c) * 3;
        nrm[i] = -sx / len;
        nrm[i + 1] = 1 / len;
        nrm[i + 2] = -sz / len;
      }
    }
    return nrm;
  }

  private tile(r0: number, r1: number, c0: number, c1: number, k: number, nrm: Float32Array): THREE.BufferGeometry {
    const along = (a: number, b: number) => {
      const v: number[] = [];
      for (let i = a; i < b; i += k) v.push(i);
      v.push(b);
      return v;
    };
    const rs = along(r0, r1);
    const cs = along(c0, c1);
    const { cols } = this;
    const { dx, dz } = this.t;
    const ring = 2 * (rs.length + cs.length) - 4; // edge vertices, copied 2 m lower for the skirt
    const nv = rs.length * cs.length + ring;
    const pos = new Float32Array(nv * 3);
    const uv = new Float32Array(nv * 2);
    const nn = new Float32Array(nv * 3);
    const put = (li: number, r: number, c: number, drop: number) => {
      const gi = r * cols + c;
      pos[li * 3] = this.t.x0 + c * dx;
      pos[li * 3 + 1] = this.heights[gi] - drop;
      pos[li * 3 + 2] = this.t.z0 + r * dz;
      uv[li * 2] = (c + 0.5) / cols;
      uv[li * 2 + 1] = 1 - (r + 0.5) / this.rows;
      nn[li * 3] = nrm[gi * 3];
      nn[li * 3 + 1] = nrm[gi * 3 + 1];
      nn[li * 3 + 2] = nrm[gi * 3 + 2];
    };
    const nc = cs.length;
    for (let i = 0; i < rs.length; i++) for (let j = 0; j < nc; j++) put(i * nc + j, rs[i], cs[j], 0);
    const idx: number[] = [];
    for (let i = 0; i < rs.length - 1; i++) {
      for (let j = 0; j < nc - 1; j++) {
        const a = i * nc + j;
        const d = a + nc;
        idx.push(a, d, a + 1, a + 1, d, d + 1);
      }
    }
    // the skirt: walk the edge once round, each segment joined to its copy below (both windings: seen from either side)
    const edge: [number, number][] = [];
    for (let j = 0; j < nc; j++) edge.push([0, j]);
    for (let i = 1; i < rs.length; i++) edge.push([i, nc - 1]);
    for (let j = nc - 2; j >= 0; j--) edge.push([rs.length - 1, j]);
    for (let i = rs.length - 2; i > 0; i--) edge.push([i, 0]);
    const base = rs.length * nc;
    edge.forEach(([i, j], n) => put(base + n, rs[i], cs[j], 2));
    for (let n = 0; n < edge.length; n++) {
      const m = (n + 1) % edge.length;
      const a = edge[n][0] * nc + edge[n][1];
      const b = edge[m][0] * nc + edge[m][1];
      const a2 = base + n;
      const b2 = base + m;
      idx.push(a, a2, b, b, a2, b2, a, b, a2, b, b2, a2);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setAttribute('normal', new THREE.BufferAttribute(nn, 3));
    g.setIndex(idx);
    g.computeBoundingSphere();
    return g;
  }

  /** The ground as one mesh (kept for tools and tests; the engine draws `lodTiles()`). */
  geometry(): THREE.BufferGeometry {
    const { rows, cols } = this;
    const pos = new Float32Array(rows * cols * 3);
    const uv = new Float32Array(rows * cols * 2);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        pos[i * 3] = this.t.x0 + c * this.t.dx;
        pos[i * 3 + 1] = this.heights[i];
        pos[i * 3 + 2] = this.t.z0 + r * this.t.dz;
        uv[i * 2] = (c + 0.5) / cols;
        uv[i * 2 + 1] = 1 - (r + 0.5) / rows;
      }
    }
    const idx = new Uint32Array((rows - 1) * (cols - 1) * 6);
    let k = 0;
    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const a = r * cols + c;
        const b = a + 1;
        const d = a + cols;
        const e = d + 1;
        idx[k++] = a;
        idx[k++] = d;
        idx[k++] = b;
        idx[k++] = b;
        idx[k++] = d;
        idx[k++] = e;
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.computeVertexNormals();
    return g;
  }
}

/**
 * The planner's own 1 m walking grid (GET /api/sim/fine.bin): the walk surface the route search takes its grades
 * from, roughness, loose sand and off-limits cells. The 3-D mesh is for the eyes; the physics reads this.
 */
export class WalkGrid {
  readonly rows: number;
  readonly cols: number;
  private h: Uint16Array; // walk surface, centimetres above m.h0 (height_unit_m)
  private g: Uint16Array; // the 1 m terrain itself (drawn near the walker), same zero
  private rough: Uint8Array; // centimetres
  private sandBits: Uint8Array;
  private nogoBits: Uint8Array;
  private radioBits: Uint8Array;

  constructor(
    readonly m: SimFineMeta,
    buf: ArrayBuffer,
  ) {
    this.rows = m.rows;
    this.cols = m.cols;
    const n = m.rows * m.cols;
    const nb = (n + 7) >> 3;
    if (buf.byteLength !== 5 * n + 3 * nb) throw new Error(`walking grid is ${buf.byteLength} bytes, expected ${5 * n + 3 * nb}`);
    // keep the 16-bit heights as they came (3 MB each instead of 6 MB float copies); copy only on a big-endian machine
    const littleEndian = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;
    const u16 = (offset: number): Uint16Array => {
      if (littleEndian) return new Uint16Array(buf, offset, n);
      const dv = new DataView(buf);
      const a = new Uint16Array(n);
      for (let i = 0; i < n; i++) a[i] = dv.getUint16(offset + i * 2, true);
      return a;
    };
    this.h = u16(0);
    this.g = u16(2 * n);
    this.rough = new Uint8Array(buf, 4 * n, n);
    this.sandBits = new Uint8Array(buf, 5 * n, nb);
    this.nogoBits = new Uint8Array(buf, 5 * n + nb, nb);
    this.radioBits = new Uint8Array(buf, 5 * n + 2 * nb, nb);
  }

  /** The 1 m terrain height (bilinear), metres relative to the rover: what is drawn near the walker. */
  groundAt(x: number, z: number): number {
    return this.bilinear(this.g, x, z) * this.m.height_unit_m + this.m.h0;
  }

  /** True where a ridge blocks the line of sight from the suit radio to the rover's antenna (layers/radio.py). */
  inRadioShadow(x: number, z: number): boolean {
    const i = this.nearest(x, z);
    return i >= 0 && this.bit(this.radioBits, i);
  }

  /**
   * The drawn height of the near-field patch at (x, z) (E1): the 1 m terrain inside, blending over the outer `blend`
   * metres into the coarse mesh, which it equals at the patch edge, so the two meet without a step.
   */
  patchHeight(x: number, z: number, cx: number, cz: number, half: number, blend: number, coarse: Terrain): number {
    const w = Math.min(Math.max((half - Math.max(Math.abs(x - cx), Math.abs(z - cz))) / blend, 0), 1);
    const c = coarse.heightAt(x, z);
    return w > 0 ? c + w * (this.groundAt(x, z) - c) : c;
  }

  /**
   * A tangent-space normal map of the 1 m terrain over the coarse mesh's texture (E5): 1 m relief lit on the 3 m mesh.
   * One texel per metre; u runs east, v north, as the ground's UVs do.
   */
  normalMap(coarse: Terrain): THREE.DataTexture {
    const t = coarse.t;
    const w = Math.round(t.cols * t.dx);
    const h = Math.round(t.rows * t.dz);
    const u0 = t.x0 - t.dx / 2;
    const v0 = t.z0 - t.dz / 2;
    const data = new Uint8Array(w * h * 4);
    for (let j = 0; j < h; j++) {
      const z = v0 + (1 - (j + 0.5) / h) * t.rows * t.dz;
      for (let i = 0; i < w; i++) {
        const x = u0 + ((i + 0.5) / w) * t.cols * t.dx;
        const hx = (this.groundAt(x + 1, z) - this.groundAt(x - 1, z)) / 2;
        const hz = (this.groundAt(x, z + 1) - this.groundAt(x, z - 1)) / 2;
        // world normal (-hx, 1, -hz); tangent = +x (u), bitangent = -z (v grows northward)
        const len = Math.hypot(hx, hz, 1);
        const k = (j * w + i) * 4;
        data[k] = Math.round(((-hx / len) * 0.5 + 0.5) * 255);
        data[k + 1] = Math.round(((hz / len) * 0.5 + 0.5) * 255);
        data[k + 2] = Math.round(((1 / len) * 0.5 + 0.5) * 255);
        data[k + 3] = 255;
      }
    }
    const tex = new THREE.DataTexture(data, w, h, THREE.RGBAFormat);
    tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.generateMipmaps = true;
    tex.needsUpdate = true;
    return tex;
  }

  /** The 1 m terrain as a mesh, `half` metres around (cx, cz), with the coarse mesh's texture coordinates (E1). */
  patch(cx: number, cz: number, half: number, blend: number, coarse: Terrain): THREE.BufferGeometry {
    const { x0, dx, z0, dz } = this.m;
    const ca = Math.max(Math.ceil((cx - half - x0) / dx), 0);
    const cb = Math.min(Math.floor((cx + half - x0) / dx), this.cols - 1);
    const ra = Math.max(Math.ceil((cz - half - z0) / dz), 0);
    const rb = Math.min(Math.floor((cz + half - z0) / dz), this.rows - 1);
    const nc = cb - ca + 1;
    const nr = rb - ra + 1;
    const t = coarse.t;
    const u0 = t.x0 - t.dx / 2;
    const v0 = t.z0 - t.dz / 2;
    const pos = new Float32Array(nr * nc * 3);
    const uv = new Float32Array(nr * nc * 2);
    const hs = new Float32Array(nr * nc);
    for (let r = 0; r < nr; r++) {
      for (let c = 0; c < nc; c++) {
        const x = x0 + (ca + c) * dx;
        const z = z0 + (ra + r) * dz;
        const i = r * nc + c;
        hs[i] = this.patchHeight(x, z, cx, cz, half, blend, coarse);
        pos[i * 3] = x;
        pos[i * 3 + 1] = hs[i];
        pos[i * 3 + 2] = z;
        uv[i * 2] = (x - u0) / (t.cols * t.dx);
        uv[i * 2 + 1] = 1 - (z - v0) / (t.rows * t.dz);
      }
    }
    const nn = new Float32Array(nr * nc * 3);
    for (let r = 0; r < nr; r++) {
      for (let c = 0; c < nc; c++) {
        const cl = Math.max(c - 1, 0);
        const cr = Math.min(c + 1, nc - 1);
        const ru = Math.max(r - 1, 0);
        const rd = Math.min(r + 1, nr - 1);
        const sx = (hs[r * nc + cr] - hs[r * nc + cl]) / (dx * (cr - cl));
        const sz = (hs[rd * nc + c] - hs[ru * nc + c]) / (dz * (rd - ru));
        const len = Math.hypot(sx, 1, sz);
        const i = (r * nc + c) * 3;
        nn[i] = -sx / len;
        nn[i + 1] = 1 / len;
        nn[i + 2] = -sz / len;
      }
    }
    const idx = new Uint32Array((nr - 1) * (nc - 1) * 6);
    let k = 0;
    for (let r = 0; r < nr - 1; r++) {
      for (let c = 0; c < nc - 1; c++) {
        const a = r * nc + c;
        const d = a + nc;
        idx[k++] = a;
        idx[k++] = d;
        idx[k++] = a + 1;
        idx[k++] = a + 1;
        idx[k++] = d;
        idx[k++] = d + 1;
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setAttribute('normal', new THREE.BufferAttribute(nn, 3));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.computeBoundingSphere();
    return g;
  }

  private bilinear(a: Uint16Array, x: number, z: number): number {
    const c = (x - this.m.x0) / this.m.dx;
    const r = (z - this.m.z0) / this.m.dz;
    const c0 = Math.min(Math.max(Math.floor(c), 0), this.cols - 2);
    const r0 = Math.min(Math.max(Math.floor(r), 0), this.rows - 2);
    const fc = Math.min(Math.max(c - c0, 0), 1);
    const fr = Math.min(Math.max(r - r0, 0), 1);
    const i = r0 * this.cols + c0;
    const top = a[i] * (1 - fc) + a[i + 1] * fc;
    const bot = a[i + this.cols] * (1 - fc) + a[i + this.cols + 1] * fc;
    return top * (1 - fr) + bot * fr;
  }

  private nearest(x: number, z: number): number {
    const c = Math.round((x - this.m.x0) / this.m.dx);
    const r = Math.round((z - this.m.z0) / this.m.dz);
    if (c < 0 || r < 0 || c >= this.cols || r >= this.rows) return -1;
    return r * this.cols + c;
  }

  private bit(bits: Uint8Array, i: number): boolean {
    return ((bits[i >> 3] >> (7 - (i & 7))) & 1) === 1;
  }

  /** Walk-surface height (bilinear), metres relative to the rover. */
  heightAt(x: number, z: number): number {
    return this.bilinear(this.h, x, z) * this.m.height_unit_m + this.m.h0;
  }

  /** Grade in degrees from (x, z) one metre along the unit direction (dirX, dirZ); uphill positive. */
  gradeDeg(x: number, z: number, dirX: number, dirZ: number): number {
    return (Math.atan2(this.heightAt(x + dirX, z + dirZ) - this.heightAt(x, z), 1) * 180) / Math.PI;
  }

  roughnessM(x: number, z: number): number {
    const i = this.nearest(x, z);
    return i < 0 ? 0 : this.rough[i] * this.m.rough_unit_m;
  }

  isSand(x: number, z: number): boolean {
    const i = this.nearest(x, z);
    return i >= 0 && this.bit(this.sandBits, i);
  }

  isNoGo(x: number, z: number): boolean {
    const i = this.nearest(x, z);
    return i < 0 || this.bit(this.nogoBits, i);
  }

  /**
   * The flattest walkable spot on a ring `rMin`..`rMax` metres from `from`, at least `clear` metres from every point in
   * `avoid` (stops, the route). Deterministic: the same ground always gives the same spot.
   */
  findQuietSpot(from: { x: number; z: number }, rMin: number, rMax: number, avoid: { x: number; z: number }[], clear: number): { x: number; z: number } | null {
    let best: { x: number; z: number } | null = null;
    let bestScore = Infinity;
    for (let r = 0; r < this.rows; r += 4) {
      for (let c = 0; c < this.cols; c += 4) {
        const x = this.m.x0 + c * this.m.dx;
        const z = this.m.z0 + r * this.m.dz;
        const d = Math.hypot(x - from.x, z - from.z);
        if (d < rMin || d > rMax) continue;
        let ok = true;
        for (let dz = -8; dz <= 8 && ok; dz += 4) for (let dx = -8; dx <= 8 && ok; dx += 4) if (this.isNoGo(x + dx, z + dz)) ok = false;
        if (!ok) continue;
        let near = Infinity;
        for (const a of avoid) near = Math.min(near, Math.hypot(a.x - x, a.z - z));
        if (near < clear) continue;
        const slope = Math.abs(this.heightAt(x + 4, z) - this.heightAt(x - 4, z)) + Math.abs(this.heightAt(x, z + 4) - this.heightAt(x, z - 4));
        const score = slope + this.roughnessM(x, z);
        if (score < bestScore) {
          bestScore = score;
          best = { x, z };
        }
      }
    }
    return best;
  }

  /** For QA: a point inside walkable ground where the walk surface is steeper than `deg`, and the uphill direction. */
  findSteep(deg: number, near: { x: number; z: number }, maxDist = 400): { x: number; z: number; dirX: number; dirZ: number } | null {
    let best: { x: number; z: number; dirX: number; dirZ: number } | null = null;
    let bestD = Infinity;
    for (let r = 1; r < this.rows - 1; r += 2) {
      for (let c = 1; c < this.cols - 1; c += 2) {
        const x = this.m.x0 + c * this.m.dx;
        const z = this.m.z0 + r * this.m.dz;
        const d = Math.hypot(x - near.x, z - near.z);
        if (d > maxDist || d >= bestD || this.isNoGo(x, z)) continue;
        const gx = (this.heightAt(x + 0.5, z) - this.heightAt(x - 0.5, z));
        const gz = (this.heightAt(x, z + 0.5) - this.heightAt(x, z - 0.5));
        const g = Math.hypot(gx, gz);
        if (g === 0) continue;
        const dirX = gx / g;
        const dirZ = gz / g;
        if (this.gradeDeg(x, z, dirX, dirZ) > deg && !this.isNoGo(x + dirX, z + dirZ)) {
          best = { x, z, dirX, dirZ };
          bestD = d;
        }
      }
    }
    return best;
  }
}
