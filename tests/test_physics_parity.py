"""The simulator's walking physics (frontend/src/sim/physics.ts) must equal the planner's (cost/physics.py).

Node runs the TypeScript file directly (type stripping, Node >= 22.18), so this needs no browser and no build."""
import json
import math
import shutil
import subprocess

import pytest

from marswalk.config import PROJECT_ROOT
from marswalk.cost.physics import PHYSICS_DEFAULTS, edge_time_energy, metabolic_power_w, walk_speed_cap, walk_speed_mps

NODE = shutil.which("node")
PHYSICS_TS = (PROJECT_ROOT / "frontend" / "src" / "sim" / "physics.ts").as_posix()

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

RUNNER = """
import * as p from %s;
const cases = JSON.parse(await new Promise(r => { let s = ''; process.stdin.on('data', d => s += d); process.stdin.on('end', () => r(s)); }));
const out = cases.map(([fn, args]) => {
  const r = p[fn](...args);
  return typeof r === 'number' ? [r] : [r.timeS, r.energyKj];
});
process.stdout.write(JSON.stringify(out, (k, v) => (v === Infinity ? 'inf' : v)));
"""


def run_ts(cases: list) -> list:
    proc = subprocess.run([NODE, "--input-type=module", "-e", RUNNER % json.dumps("file://" + PHYSICS_TS)],
                          input=json.dumps(cases), capture_output=True, text=True, timeout=60, check=True)
    return [[math.inf if v == "inf" else v for v in row] for row in json.loads(proc.stdout)]


def close(a: float, b: float) -> bool:
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


D = PHYSICS_DEFAULTS
MASS = D["body_mass_kg"] + D["suit_mass_kg"]
GRADES = [g / 2 for g in range(-50, 51)]
CAP = walk_speed_cap({"walk_run_froude": 0.56})          # the gait limit switched on (Kram et al. 1997, 0.4 g)


def test_walk_speed_and_power_match():
    cases, want = [], []
    for g in GRADES:
        v = walk_speed_mps(g)
        cases.append(["walkSpeed", [g]])
        want.append([v])
        cases.append(["walkSpeed", [g, CAP]])
        want.append([min(v, CAP)])
        cases.append(["metabolicPower", [MASS, D["gravity_mps2"], g, v]])
        want.append([metabolic_power_w(MASS, D["gravity_mps2"], D["earth_gravity_mps2"], g, v)])
    got = run_ts(cases)
    bad = [(c, w, g) for c, w, g in zip(cases, want, got) if not all(close(a, b) for a, b in zip(w, g))]
    assert not bad, bad[:5]


def test_edge_time_energy_matches_on_every_kind_of_step():
    cases, want = [], []
    for g in GRADES:
        for run in (1.0, math.sqrt(2.0)):
            dz = run * math.tan(math.radians(g))
            for rough in (0.0, 0.17, 0.8):
                for sand in (False, True):
                    for cap in (None, CAP):
                        args = [D["gravity_mps2"], MASS, D["roughness_penalty_per_m"], D["sand_penalty"],
                                D["max_grade_deg"], dz, run, rough, sand]
                        cases.append(["edgeTimeEnergy", args if cap is None else [*args, cap]])
                        want.append(list(edge_time_energy(D["gravity_mps2"], D["earth_gravity_mps2"], MASS,
                                                          D["roughness_penalty_per_m"], D["sand_penalty"],
                                                          D["max_grade_deg"], dz, run, rough, 1.0 if sand else 0.0,
                                                          math.inf if cap is None else cap)))
    got = run_ts(cases)
    assert len(got) == len(cases) > 2000
    bad = [(c, w, g) for c, w, g in zip(cases, want, got) if not all(close(a, b) for a, b in zip(w, g))]
    assert not bad, bad[:5]
    assert sum(math.isinf(w[0]) for w in want) > 0          # the 20 deg refusal is part of what is compared
