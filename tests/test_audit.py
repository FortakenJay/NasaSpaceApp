"""`marswalk audit` recomputes the app's numbers by independent paths; on the synthetic site every check passes."""
from marswalk import audit
from marswalk.config import load_eva, load_site
from marswalk.layers.stack import build_stack

EVA = load_eva("configs/eva/artemis_default.toml")


def test_every_audit_check_passes_on_synthetic_terrain(synthetic_site):
    site = load_site(synthetic_site)
    checks = audit.run(site, EVA, build_stack(site, EVA, use_cache=False))
    failed = [(c.name, c.expected, c.got) for c in checks if not c.ok and c.group != "Constants"]
    assert not failed
    assert {c.group for c in checks} >= {"Constants", "Walking model", "Terrain", "Plan", "Safety", "Radiation"}
    md = audit.markdown(checks)
    assert md.startswith("# Audit results") and "| ✅ |" in md


def test_constants_match_their_sources():
    checks = audit.check_constants(load_site("configs/sites/gale_boxwork.toml"), EVA)
    assert all(c.ok for c in checks), [(c.name, c.got) for c in checks if not c.ok]
