from marswalk.config import load_eva, load_site


def test_site_loads_with_start_and_five_stops():
    site = load_site("configs/sites/gale_boxwork.toml")
    assert site.start.id == "H1"
    assert [s.id for s in site.stops] == ["S1", "S2", "S3", "S4", "S5"]


def test_all_points_inside_bbox():
    site = load_site("configs/sites/gale_boxwork.toml")
    b = site.bbox
    for s in (site.start, *site.stops):
        assert b["lat_min"] <= s.lat <= b["lat_max"], s.id
        assert b["lon_min"] <= s.lon <= b["lon_max"], s.id


def test_required_products_present():
    site = load_site("configs/sites/gale_boxwork.toml")
    for key in ("dtm", "ortho_1m", "thermal_inertia", "basemap_tiles"):
        assert key in site.products


def test_eva_defaults():
    eva = load_eva("configs/eva/artemis_default.toml")
    assert eva.cost_model in ("metabolic", "weighted")
    assert eva.route["stop_order"] in ("fixed", "optimize")
    assert 0 < eva.eva["walkback_reserve_frac"] < 1
