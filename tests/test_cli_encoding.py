"""The CLI must not crash on a legacy Windows console code page (cp1252) when printing CO₂, m/s², ≤ etc."""
import io
import os
import subprocess
import sys

from marswalk.cli import _utf8_console

SAMPLE = "CO₂ m/s² ≤ 1.39 ± 0.12 → HiRISE"


def test_reconfigures_legacy_streams(monkeypatch):
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    _utf8_console()
    print(SAMPLE)                      # raised UnicodeEncodeError before the fix
    out.flush()
    assert out.buffer.getvalue().decode("utf-8").strip() == SAMPLE
    assert err.encoding.lower().replace("-", "") == "utf8"


def test_leaves_non_text_streams_alone(monkeypatch):
    s = io.StringIO()                  # no reconfigure(): must not raise
    monkeypatch.setattr(sys, "stdout", s)
    _utf8_console()
    print(SAMPLE)
    assert s.getvalue().strip() == SAMPLE


def test_real_process_with_cp1252_console():
    # Same conditions as a default Windows console: stdout encoded as cp1252, UTF-8 mode off.
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    code = f"from marswalk.cli import _utf8_console; _utf8_console(); print({SAMPLE!r})"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert r.stdout.decode("utf-8").strip() == SAMPLE
