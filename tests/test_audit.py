"""`marswalk audit` recomputes the app's numbers by independent paths; on the synthetic site every check passes."""
import dataclasses

from marswalk import audit
from marswalk.config import load_eva, load_site
from marswalk.layers.stack import build_stack

EVA = load_eva("configs/eva/artemis_default.toml")


def test_every_audit_check_passes_on_synthetic_terrain(synthetic_site):
    site = load_site(synthetic_site)
    checks = audit.run(site, EVA, build_stack(site, EVA, use_cache=False))
    failed = [(c.name, c.expected, c.got) for c in checks if not c.ok and not c.finding and c.group != "Constants"]
    assert not failed
    assert {c.group for c in checks} >= {"Constants", "Walking model", "Terrain", "Plan", "Safety", "Radiation", "Operations"}
    md = audit.markdown(checks)
    assert md.startswith("# Audit results") and "| ✅ |" in md


def test_constants_match_their_sources():
    checks = audit.check_constants(load_site("configs/sites/gale_boxwork.toml"), EVA)
    assert all(c.ok for c in checks if not c.finding), [(c.name, c.got) for c in checks if not c.ok and not c.finding]


def test_the_gait_finding_flags_the_uncapped_curve_and_clears_with_the_limit():
    site = load_site("configs/sites/gale_boxwork.toml")
    find = lambda e: next(c for c in audit.check_constants(site, e) if c.finding)   # noqa: E731
    off = find(EVA)
    assert not off.ok and off.got == 1.6 and "⚠️" in off.row()
    on = dataclasses.replace(EVA, cost={**EVA.cost, "metabolic": {**EVA.cost["metabolic"], "walk_run_froude": 0.56}})
    assert find(on).ok and find(on).got == 1.36
