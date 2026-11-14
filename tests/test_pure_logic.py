import datetime as dt

import numpy as np
import pytest

from marswalk.config import load_eva
from marswalk.constraints.eva import check_distance_from_rover, check_duration
from marswalk.cost import get_cost_model
from marswalk.layers.stack import nogo_mask
from marswalk.route.sequence import order_stops, tour_cost
from marswalk.spaceweather.status import eva_dose_mgy, split_range

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
