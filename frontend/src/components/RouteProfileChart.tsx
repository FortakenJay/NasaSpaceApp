import type { RouteProfile } from '../api';

const W = 320;
const H = 84;
const BAND = 8; // slope strip under the elevation line

function slopeColor(deg: number | null): string {
  if (deg === null) return '#cfd4cf';
  if (deg < 10) return '#1f8a4c';
  if (deg < 15) return '#d9a514';
  return '#c2372b';
}

/** Elevation along the route, with a strip coloured by 5 m slope (green < 10°, yellow < 15°, red above). */
export function RouteProfileChart({ profile }: { profile: Partial<RouteProfile> }) {
  const dist = profile.dist_m ?? [];
  const elev = profile.elev_m ?? [];
  const slope = profile.slope_deg ?? [];
  const pts = dist.flatMap((d, i) => {
    const z = elev[i];
    return d === null || z === null || z === undefined ? [] : [{ d, z, s: slope[i] ?? null }];
  });
  if (pts.length < 2) return null;
  const dMax = pts[pts.length - 1].d || 1;
  const zs = pts.map((p) => p.z);
  const zMin = Math.min(...zs);
  const zMax = Math.max(...zs);
  const x = (d: number) => (d / dMax) * W;
  const y = (z: number) => 4 + (1 - (z - zMin) / Math.max(zMax - zMin, 1e-6)) * (H - BAND - 10);
  const line = pts.map((p) => `${x(p.d).toFixed(1)},${y(p.z).toFixed(1)}`).join(' ');
  return (
    <figure className="profile">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Elevation and slope along the route">
        <polyline points={line} fill="none" stroke="#17212b" strokeWidth="1.5" />
        {pts.slice(0, -1).map((p, i) => (
          <rect
            key={p.d}
            x={x(p.d)}
            y={H - BAND}
            width={Math.max(x(pts[i + 1].d) - x(p.d), 0.5)}
            height={BAND}
            fill={slopeColor(p.s)}
          />
        ))}
      </svg>
      <figcaption>
        Height along the route, from {zMin.toFixed(0)} m to {zMax.toFixed(0)} m. The strip underneath shows how steep the
        ground is: green under 10°, yellow under 15°, red above.
      </figcaption>
    </figure>
  );
}
