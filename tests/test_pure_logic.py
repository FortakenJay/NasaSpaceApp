import datetime as dt

import numpy as np
import pytest

from marswalk.config import load_eva
from marswalk.constraints.eva import check_distance_from_rover, check_duration
from marswalk.cost import get_cost_model
from marswalk.layers.stack import nogo_mask
from marswalk.route.sequence import order_stops, tour_cost
from marswalk.spaceweather.status import eva_dose_mgy, go_no_go, mars_arrivals, parse_time, split_range

EVA = load_eva("configs/eva/artemis_default.toml")


def test_fixed_order_unchanged():
    assert order_stops(["S1", "S2", "S3"], "H1", lambda a, b: 1.0) == ["S1", "S2", "S3"]


def test_optimize_order_finds_cheaper_tour():
    pos = {"H1": 0, "A": 3, "B": 1, "C": 2}
    cost = lambda a, b: abs(pos[a] - pos[b])
    fixed = ["A", "B", "C"]
    best = order_stops(fixed, "H1", cost, mode="optimize")
    assert tour_cost(best, "H1", cost) < tour_cost(fixed, "H1", cost)
    assert tour_cost(best, "H1", cost) == 6


def test_nogo_mask():
    z = np.array([[0.0, np.nan], [0.0, 0.0]])
    s1 = np.array([[10.0, 10.0], [40.0, 10.0]])
    s5 = np.array([[10.0, 10.0], [10.0, 30.0]])
    rough = np.zeros((2, 2))
    m = nogo_mask(s1, s5, rough, z, EVA.hazards)
    assert m.tolist() == [[False, True], [True, True]]


def test_constraints_scalar_checks():
    assert check_duration(4 * 3600, EVA) == []
    assert check_duration(9 * 3600, EVA)[0].severity == "no-go"
    assert check_distance_from_rover({"S5": 655.0}, EVA) == []
    assert check_distance_from_rover({"X": 2500.0}, EVA)[0].where == "X"


def test_spaceweather_helpers():
    assert eva_dose_mgy(8, 0.21) == pytest.approx(0.07)
    chunks = split_range(dt.date(2025, 7, 1), dt.date(2026, 2, 28), 60)
    assert all((b - a).days <= 59 for a, b in chunks)
    assert chunks[0][0] == dt.date(2025, 7, 1) and chunks[-1][1] == dt.date(2026, 2, 28)


@pytest.mark.parametrize("name", ["metabolic", "weighted"])
def test_cost_models_switchable(name):
    m = get_cost_model(name, EVA.cost[name])
    assert m.name == name
    assert m.params.dtype == np.float64 and m.params.ndim == 1  # numba-ready


def test_unknown_cost_model():
    with pytest.raises(ValueError):
        get_cost_model("teleport", {})


def test_go_no_go_rules():
    now = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.timezone.utc)
    iso = lambda hours: (now + dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%MZ")   # noqa: E731
    sim = lambda hours, glancing: {"impactList": [{"location": "Mars", "arrivalTime": iso(hours), "isGlancingBlow": glancing}]}  # noqa: E731
    assert parse_time("2024-09-04T14:00Z") == dt.datetime(2024, 9, 4, 14, 0, tzinfo=dt.timezone.utc)
    assert parse_time("") is None and parse_time("nonsense") is None
    assert go_no_go([], now, 8, 0.21).level == "GO"
    assert go_no_go([{"eventTime": iso(-30)}], now, 8, 0.21).level == "NO-GO"            # SEP in the last 48 h
    assert go_no_go([{"eventTime": iso(-100)}], now, 8, 0.21).level == "CAUTION"         # SEP in the last 7 days
    assert go_no_go([{"eventTime": iso(-300)}], now, 8, 0.21).level == "GO"              # older than 7 days
    assert go_no_go([], now, 8, 0.21, simulations=[sim(20, False)]).level == "NO-GO"     # direct hit in the window
    assert go_no_go([], now, 8, 0.21, simulations=[sim(20, True)]).level == "CAUTION"    # glancing blow
    assert go_no_go([], now, 8, 0.21, simulations=[sim(100, False)]).level == "CAUTION"  # arrival later this week
    assert go_no_go([], now, 8, 0.21, simulations=[sim(-200, False)]).level == "GO"      # long past
    assert go_no_go([], now, 8, 0.21, flares=[{"classType": "X1.2", "peakTime": iso(-5)}]).level == "CAUTION"
    assert go_no_go([], now, 8, 0.21, flares=[{"classType": "M9.9", "peakTime": iso(-5)}]).strongest_flare == "M9.9"
    assert go_no_go([], now, 8, 0.21, data_ok=False).level == "CAUTION"
    earth_only = [{"impactList": [{"location": "STEREO A", "arrivalTime": iso(5), "isGlancingBlow": False}]}]
    assert mars_arrivals(earth_only, now) == [] and go_no_go([], now, 8, 0.21, simulations=earth_only).level == "GO"
