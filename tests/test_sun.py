"""The Sun model against NASA GISS's published Mars24 worked examples
(https://www.giss.nasa.gov/tools/mars24/help/algorithm.html)."""
import datetime as dt
import math

import pytest

from marswalk import sun

UTC = dt.UTC


def _centric(lat_g: float) -> float:
    return math.degrees(math.atan(math.tan(math.radians(lat_g)) / (sun.RE_KM / sun.RP_KM) ** 2))


@pytest.mark.parametrize(("millis", "lon_w", "lat_g", "want"), [
    # Example 1: 2000-01-06 00:00 UTC at 0 W, 0 N
    (947116800000, 0.0, 0.0, {"ls": 277.18758, "eot": -5.18774, "mst": 23.99425, "lmst": 23.99425, "ltst": 23.64840,
                              "subsol": 174.72600, "dec": -25.22825, "z": 154.26182, "az": 191.03905}),
    # Example 2: MER-A Spirit, local true midnight at 184.702 W, -14.640 N
    (1073137591000, 184.702, -14.640, {"ls": 327.32416, "eot": -12.77553, "mst": 13.16537, "lmst": 0.85190,
                                       "ltst": 0.00025, "subsol": 4.70500, "dec": -13.42065, "z": 151.93895,
                                       "az": 179.99383}),
])
def test_mars24_worked_examples(millis, lon_w, lat_g, want):
    t = dt.datetime.fromtimestamp(millis / 1000, UTC)
    s = sun.solar(t)
    lmst, ltst = sun.local_times(t, -lon_w)
    az, el = sun.sun_position(t, _centric(lat_g), -lon_w)
    assert s["ls_deg"] == pytest.approx(want["ls"], abs=1e-4)
    assert s["eot_deg"] == pytest.approx(want["eot"], abs=1e-4)
    assert s["mst_h"] == pytest.approx(want["mst"], abs=1e-4)
    assert s["subsolar_lon_w"] == pytest.approx(want["subsol"], abs=1e-4)
    assert lmst == pytest.approx(want["lmst"], abs=1e-4) and ltst == pytest.approx(want["ltst"], abs=1e-3)
    assert s["dec_deg"] == pytest.approx(want["dec"], abs=1e-3)
    assert 90 - el == pytest.approx(want["z"], abs=1e-3) and az == pytest.approx(want["az"], abs=1e-3)


def test_mars_sol_date_matches_the_first_worked_example():
    t = dt.datetime.fromtimestamp(947116800000 / 1000, UTC)       # 2000-01-06 00:00 UTC
    msd = sun.mars_sol_date(t)
    assert msd == pytest.approx(44795.99976, abs=1e-5)             # GISS C-2, from JD_TT = 2451549.500743
    assert (msd % 1.0) * 24 == pytest.approx(23.99425, abs=1e-4)    # its fraction is the example's MST
    assert sun.local_sol(t, 0.0) == 44795 and sun.local_sol(t, 137.38) == 44796   # Gale is already into the next sol


def test_walk_start_and_track_at_gale():
    lat, lon = -4.8, 137.38
    now = dt.datetime(2026, 11, 15, tzinfo=UTC)
    start = sun.next_lmst(now, lon, 9.0)
    assert now <= start < now + dt.timedelta(days=sun.SOL_DAYS)
    assert sun.local_times(start, lon)[0] == pytest.approx(9.0, abs=1e-6)
    tr = sun.track(start, lat, lon, 600.0)
    assert tr["sol"] == sun.local_sol(start, lon) == 54344                      # 09:00 at Gale on 2026-11-15
    els = [e for _, e in tr["az_el"]]
    # morning Sun in the east, climbing to local noon (3 h later) and setting before the 10 h track ends
    assert 0 < tr["az_el"][0][0] < 180 and els[0] > 0
    assert max(els) == pytest.approx(90 - abs(sun.planetographic_lat(lat) - sun.solar(start)["dec_deg"]), abs=0.5)
    assert els[-1] < 0
