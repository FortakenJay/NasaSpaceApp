// The planner's walking models, line for line (src/marswalk/cost/physics.py), so the simulator walks at the
// speed and costs the energy the plan assumed. Sources: Johnson et al. 2010 (Marquez speed curve, Table 1) and
// Santee et al. 2001 (metabolic rate, Table 2), with the level term scaled by g/g_earth (MarsWalk's assumption).
// Optional gait limit: speed capped at the walk-run transition sqrt(Fr g L) (Kram et al. 1997), off unless configured.

export const G_EARTH = 9.81;
export const MIN_POWER_W = 60;

/** Comfortable suited walking speed (m/s) on a grade in degrees (uphill positive), at most `capMps`. */
export function walkSpeed(gradeDeg: number, capMps = Infinity): number {
  const a = gradeDeg;
  let v: number;
  if (a < -20) v = 0.05;
  else if (a < -10) v = 0.095 * a + 1.95;
  else if (a < 0) v = 0.06 * a + 1.6;
  else if (a < 6) v = -0.2 * a + 1.6;
  else if (a < 15) v = -0.039 * a + 0.634;
  else v = 0.05;
  return Math.min(v, capMps);
}

/** Metabolic power (W) walking at v (m/s) on a grade, for crew + suit mass m (kg) under gravity g. */
export function metabolicPower(massKg: number, g: number, gradeDeg: number, v: number): number {
  const a = (gradeDeg * Math.PI) / 180;
  const level = (3.28 * massKg * (g / G_EARTH) + 71.1) * (0.661 * v * Math.cos(a) + 0.115);
  const slope =
    gradeDeg >= 0
      ? 3.5 * massKg * g * v * Math.sin(a)
      : 2.4 * massKg * g * v * Math.sin(a) * Math.pow(0.3, Math.abs(gradeDeg) / 7.65);
  return Math.max(level + slope, MIN_POWER_W);
}

/** The planner's terrain multiplier on walking time: rough ground and loose sand slow you down (physics.py). */
export function terrainMultiplier(roughM: number, sand: boolean, roughPenaltyPerM: number, sandPenalty: number): number {
  return (1 + roughPenaltyPerM * Math.max(roughM, 0)) * (sand ? sandPenalty : 1);
}

/**
 * Time (s) and energy (kJ) to walk one step of run `runM` and climb `dzM`, exactly as the route search prices a grid
 * edge (physics.py edge_time_energy): Infinity past the steepest grade a suited walker may take.
 */
export function edgeTimeEnergy(
  g: number, massKg: number, roughPen: number, sandPen: number, maxGradeDeg: number,
  dzM: number, runM: number, roughM: number, sand: boolean, vCapMps = Infinity,
): { timeS: number; energyKj: number } {
  const grade = (Math.atan2(dzM, runM) * 180) / Math.PI;
  if (Math.abs(grade) > maxGradeDeg) return { timeS: Infinity, energyKj: Infinity };
  const v = walkSpeed(grade, vCapMps);
  const t = (Math.hypot(runM, dzM) / v) * terrainMultiplier(roughM, sand, roughPen, sandPen);
  return { timeS: t, energyKj: (metabolicPower(massKg, g, grade, v) * t) / 1000 };
}
