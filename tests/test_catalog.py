"""HiRISE catalog: parsing, footprints, choosing terrain for a Base (fixture: real index rows, no network)."""
from pathlib import Path

import pytest

from marswalk.sources import catalog

FIX = Path(__file__).parent / "fixtures" / "catalog"


@pytest.fixture(scope="module")
def entries():
    with open(FIX / "DTMCUMINDEX.TAB", encoding="latin-1", newline="") as f:
        return catalog.parse((FIX / "DTMCUMINDEX.LBL").read_text(encoding="latin-1"), f)


def by_id(entries, prefix):
    return next(e for e in entries if e.product_id.startswith(prefix))


def test_label_has_34_columns():
    names = catalog.column_names((FIX / "DTMCUMINDEX.LBL").read_text(encoding="latin-1"))
    assert len(names) == 34 and names[1] == "FILE_NAME_SPECIFICATION" and names[-1] == "CORNER4_LONGITUDE"


def test_parse_groups_orthos_with_their_dtm(entries):
    gale = by_id(entries, "DTEEC_019698_1750_019988_1750")
    assert gale.url.endswith("DTEEC_019698_1750_019988_1750_U01.IMG")
    assert gale.orthos["RED_C"].endswith("ESP_019698_1750_RED_C_01_ORTHO.JP2")
    assert gale.projection == "EQUIRECTANGULAR" and gale.scale_m < 1.1
    assert all(-180 <= c[1] <= 180 for e in entries for c in e.corners)


def test_supported_reasons(entries):
    assert catalog.supported(by_id(entries, "DTEEC_019698"))[0]
    reasons = {catalog.supported(e)[1] for e in entries if not catalog.supported(e)[0]}
    assert any("polar" in r for r in reasons)
    assert any("too coarse" in r for r in reasons)
    assert any("no 1 m photo" in r for r in reasons)


def test_choose_gale_and_jezero(entries):
    gale = catalog.choose(entries, -4.7982118, 137.3847004)
    assert gale and gale[0].entry.product_id.startswith("DTEEC_019698_1750_019988_1750")
    jez = catalog.choose(entries, 18.44, 77.45)
    assert jez and jez[0].entry.product_id.startswith("DTEEC_045994_1985")
    assert jez[0].edge_m > 1500
    assert catalog.choose(entries, 40.0, -150.0) == []


def test_contains_works_across_the_seams():
    # a footprint straddling 0/360 longitude, given in 0-360 like the index (normalised by parse)
    e = catalog.DtmEntry("X", "u", "f", 1.0, "EQUIRECTANGULAR",
                         [[1.0, catalog._wrap(359.95)], [1.0, catalog._wrap(0.05)], [-1.0, catalog._wrap(0.05)], [-1.0, catalog._wrap(359.95)]])
    assert catalog.contains(e, 0.0, 0.0)
    assert catalog.contains(e, 0.0, 359.99)
    assert catalog.contains(e, 0.0, -0.01)
    assert not catalog.contains(e, 0.0, 0.2)
    # the east-of-180 fixture strip is found from both longitude conventions
    ent = catalog.DtmEntry("Y", "u", "f", 1.0, "EQUIRECTANGULAR", [[1, 179.9], [1, -179.9], [-1, -179.9], [-1, 179.9]])
    assert catalog.contains(ent, 0, 180.0) and catalog.contains(ent, 0, -180.0)
    assert not catalog.supported(ent)[0]     # crosses the antimeridian


@pytest.mark.parametrize("lat,lon,tile", [(-4.8, 137.38, "30S120E"), (18.44, 77.45, "00N060E"), (0.0, 0.0, "00N000E"),
                                          (-0.1, -80.0, "30S240E"), (45.0, 359.9, "30N300E"), (-45.0, 10.0, "60S000E"),
                                          (61.0, 10.0, None), (-61.0, 10.0, None)])
def test_ti_tile_names(lat, lon, tile):
    assert catalog.ti_tile(lat, lon) == tile


def test_base_bbox_is_3_km_and_clipped(entries):
    b = catalog.base_bbox(18.44, 77.45)
    assert b["lat_max"] - b["lat_min"] == pytest.approx(2 * 3000 / 59274.7, rel=1e-3)
    gale = by_id(entries, "DTEEC_019698")
    clipped = catalog.base_bbox(-4.735, 137.3847, gale)       # near the strip's north edge
    assert clipped["lat_max"] <= max(c[0] for c in gale.corners) + 1e-9
    assert catalog.estimate_bytes(b, 1.0) > 1e8


def test_footprints_geojson(entries):
    gj = catalog.footprints_geojson(entries)
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) == len(entries)
    f = gj["features"][0]
    ring = f["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5
    assert {"supported", "reason", "product_id", "scale_m"} <= set(f["properties"])
