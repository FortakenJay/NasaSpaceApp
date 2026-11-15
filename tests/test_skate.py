"""Skateboard kicks: one burst of speed each time the foot meets the ground, enough to climb a hill."""
import json
import shutil
import subprocess

import pytest

from marswalk.config import PROJECT_ROOT

NODE = shutil.which("node")
SKATE_TS = (PROJECT_ROOT / "frontend" / "src" / "sim" / "skate.ts").as_posix()

# Mirrors the engine: the push cycle runs in real time, and the kick is applied only while the foot is down.
RIDE = r"""
import { skateStep, flatTopSpeed, KICK_START, KICK_END, PUSH_S } from %s;
const g = 3.71, m = 143;
const contact = (KICK_END - KICK_START) * PUSH_S;
const dt = 1 / 60;
function ride(grade, seconds, rough, sand, kick) {
  let v = 0, t = 0, dist = 0, kicks = 0, pushLeft = 0, u = null, prevDown = false, vmax = 0;
  while (t < seconds - 1e-9) {
    if (kick) {
      if (u === null) u = 0;
      else { u += dt / PUSH_S; if (u >= 1) u -= 1; }
    }
    const down = u !== null && u >= KICK_START && u < KICK_END;
    if (down && !prevDown) { pushLeft += contact; kicks += 1; }
    prevDown = down;
    const pushS = Math.min(dt, pushLeft);
    pushLeft -= pushS;
    const r = skateStep(v, dt, grade, rough, sand, kick ? pushS : 0, false, g, m);
    dist += r.v * dt;
    v = r.v;
    vmax = Math.max(vmax, v);
    t += dt;
  }
  return { v, dist, kicks, vmax };
}
const one = skateStep(0, contact, 0, 0, false, contact, false, g, m);
const out = {
  oneKick: one.v,
  flat4: ride(0, 4, 0, false, true),
  up8: ride(8, 8, 0, false, true),
  down10coast: ride(-10, 4, 0, false, false),
  down10kick: ride(-10, 4, 0, false, true),
  sand: ride(0, 3, 0, true, true),
  topSmooth: flatTopSpeed(0, false, g, m),
  topRough: flatTopSpeed(0.17, false, g, m),
  topSand: flatTopSpeed(0, true, g, m),
};
process.stdout.write(JSON.stringify(out));
""" % json.dumps("file://" + SKATE_TS)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_kick_adds_speed_and_hills_are_climbable():
    out = json.loads(subprocess.run(
        [NODE, "--input-type=module", "-e", RIDE], capture_output=True, text=True, timeout=60, check=True,
    ).stdout)
    # one contact at the traction limit (0.6 × 143 kg × 3.71 m/s²), minus smooth rolling resistance
    assert out["oneKick"] == pytest.approx(0.845, abs=0.02)
    assert out["flat4"]["kicks"] >= 3
    assert out["flat4"]["v"] > 2.0          # the old steady 60 N was still under 1 m/s here
    assert out["up8"]["v"] > 0.5            # an 8° hill is climbable by kicking
    assert out["up8"]["dist"] > 2
    assert out["down10coast"]["v"] > 1.5    # a 10° downhill builds speed with no kick at all
    assert out["down10kick"]["v"] > out["down10coast"]["v"]
    # a kick can shove the board on sand, but the sand stops it again before the next kick
    assert out["sand"]["vmax"] < 0.6
    assert out["sand"]["v"] < 0.5
    assert out["sand"]["dist"] < 1
    assert 5 < out["topSmooth"] < 7         # under the 7 m/s wobble, so a downhill can still throw you
    assert out["topRough"] > 1
    assert out["topSand"] == 0
