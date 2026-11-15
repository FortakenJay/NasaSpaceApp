"""The simulator's sound through Mars air (frontend/src/sim/audio.ts) follows Perseverance's measured absorption."""
import json
import math
import shutil
import subprocess

import pytest

from marswalk.config import PROJECT_ROOT

NODE = shutil.which("node")
AUDIO_TS = (PROJECT_ROOT / "frontend" / "src" / "sim" / "audio.ts").as_posix()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_air_absorption_cutoff():
    js = f"import {{ cutoffHz }} from {json.dumps('file://' + AUDIO_TS)};" \
         "process.stdout.write(JSON.stringify([2, 8, 30, 100, 300].map(cutoffHz)));"
    out = json.loads(subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True,
                                    timeout=60, check=True).stdout)
    near, eight, thirty, hundred, far = out
    assert near == 20000                                   # 2 m: absorption needs > 13 kHz for -20 dB: nothing lost
    # 8 m: e^(-a d) = 0.1 at a = ln 10 / 8 = 0.288 per m, between 0.21 (4.5 kHz) and 0.34 (8.5 kHz)
    assert eight == pytest.approx(4500 + (math.log(10) / 8 - 0.21) / 0.13 * 4000, rel=1e-9)
    assert thirty == pytest.approx(math.log(10) / 30 / 0.21 * 4500, rel=1e-9)   # extrapolated below 2 kHz
    assert eight > thirty > hundred > far > 0
