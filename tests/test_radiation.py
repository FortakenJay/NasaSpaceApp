"""Radiation at a Base: measured at Gale, scaled by surface pressure elsewhere (Guo et al. 2017)."""
import pytest

from marswalk.spaceweather import radiation as r


def test_reference_elevation_gives_gale_values():
    e = r.estimate(r.Z_REF_M)
    assert e["rad_gcr_dose_mgy_per_day"] == pytest.approx(0.21)
    assert e["rad_dose_equivalent_msv_per_day"] == pytest.approx(0.64)
    assert e["rad_estimate"]["pressure_pa"] == pytest.approx(r.P_REF_PA)


def test_higher_ground_has_less_air_and_more_dose():
    low, high = r.estimate(-6000.0), r.estimate(-2000.0)
    assert high["rad_gcr_dose_mgy_per_day"] > 0.21 > low["rad_gcr_dose_mgy_per_day"]
    assert high["rad_estimate"]["column_g_cm2"] < low["rad_estimate"]["column_g_cm2"]


def test_range_brackets_the_value_and_flags_extrapolation():
    e = r.estimate(-2569.0)              # the Jezero Base
    lo, hi = e["rad_estimate"]["gcr_range_mgy_per_day"]
    assert lo <= e["rad_gcr_dose_mgy_per_day"] <= hi
    assert not e["rad_estimate"]["extrapolated"]          # ~706 Pa: inside RAD's measured 700-950 Pa
    assert r.estimate(21000.0)["rad_estimate"]["extrapolated"]


def test_column_depth_matches_guo_2017():
    assert r.column_g_cm2(840.0) == pytest.approx(22.6, abs=0.05)     # Guo et al. 2017, section 2.3


def test_rates_from_site_config():
    assert r.rates({"rad_gcr_dose_mgy_per_day": 0.21, "rad_dose_equivalent_msv_per_day": 0.64})[:3] == (0.21, 0.64, False)
    gy, sv, est, note = r.rates({})
    assert (gy, sv, est) == (0.21, 0.64, True) and "Gale" in note
    e = r.estimate(-2569.0)
    gy, sv, est, note = r.rates(e)
    assert est and gy == e["rad_gcr_dose_mgy_per_day"] and "estimated" in note
