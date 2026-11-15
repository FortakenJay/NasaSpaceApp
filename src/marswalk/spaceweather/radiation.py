"""Surface radiation (galactic cosmic rays) at a Base: measured at Gale, estimated by elevation elsewhere.

Measured (Gale): Hassler et al. 2014 (Science 343), Curiosity RAD on the surface: 0.21 +- 0.04 mGy/day absorbed dose,
0.64 +- 0.12 mSv/day dose equivalent. Measured at Bradbury Landing / Yellowknife Bay, about -4,501 m (MOLA areoid).

Elsewhere the dose changes with how much atmosphere is overhead. Guo et al. 2017 (JGR Planets 122: 329-341,
arXiv 1712.06987), section 3.2: RAD's dose rate falls as surface pressure rises, dD = kappa * dP, with
kappa = -0.13 +- 0.02 uGy/day/Pa (2013-14, weaker sun-quiet conditions) to -0.17 +- 0.03 uGy/day/Pa (2015-16), and
the HZETRN2015 model giving only 0.018-0.042 uGy/day/Pa. RAD only measured this between about 700 and 950 Pa
(column 18.9-25.7 g/cm2 at g = 3.72, section 2.3); the paper notes the trend may not extrapolate far beyond.

Model (an estimate, and labelled as one):
    P(z) = P_REF * exp(-(z - Z_REF) / H)                      hydrostatic, H = 11.1 km (NASA Mars fact sheet)
    D(z) = D_GALE + kappa * (P(z) - P_REF)                    kappa = -0.15 uGy/day/Pa (middle of the measured range)
The range spans the model's smallest |kappa| (0.018) to the largest measured (0.17). The dose equivalent is scaled by
the same ratio (an assumption: its quality factor also shifts with depth).
"""
from __future__ import annotations

import math

GALE_GCR_MGY_PER_DAY = 0.21            # Hassler et al. 2014
GALE_DOSE_EQ_MSV_PER_DAY = 0.64        # Hassler et al. 2014
Z_REF_M = -4501.0                      # Bradbury Landing, MOLA areoid
P_REF_PA = 840.0                       # typical Gale surface pressure; Guo et al. 2017 use 840 Pa as the example
G_MARS = 3.72                          # m/s2, as in Guo et al. 2017 section 2.3
SCALE_HEIGHT_M = 11_100.0              # Mars pressure scale height (NASA Mars fact sheet)
KAPPA_UGY_PER_DAY_PA = -0.15           # Guo et al. 2017, measured: -0.13 to -0.17
KAPPA_RANGE = (-0.018, -0.17)          # model low |kappa| .. measured high |kappa|
MEASURED_P_RANGE_PA = (700.0, 950.0)   # where RAD measured the trend
SOURCE = ("Scaled from Curiosity RAD at Gale (Hassler et al. 2014) by surface pressure (Guo et al. 2017, "
          "JGR Planets 122: 329)")


def pressure_pa(elevation_m: float) -> float:
    return P_REF_PA * math.exp(-(elevation_m - Z_REF_M) / SCALE_HEIGHT_M)


def column_g_cm2(pressure: float) -> float:
    return pressure / G_MARS / 10.0      # Pa / (m/s2) = kg/m2; /10 -> g/cm2


def estimate(elevation_m: float) -> dict:
    """Estimated GCR dose rates at a Base's elevation (metres above the MOLA areoid)."""
    p = pressure_pa(elevation_m)
    dp = p - P_REF_PA

    def dose(kappa: float) -> float:
        return max(GALE_GCR_MGY_PER_DAY + kappa * dp / 1000.0, 0.0)

    gy = dose(KAPPA_UGY_PER_DAY_PA)
    lo, hi = sorted((dose(KAPPA_RANGE[0]), dose(KAPPA_RANGE[1])))
    ratio = gy / GALE_GCR_MGY_PER_DAY
    lo_p, hi_p = MEASURED_P_RANGE_PA
    note = (f"estimated for {elevation_m:,.0f} m elevation (about {p:,.0f} Pa, {column_g_cm2(p):.1f} g/cm2 of air) "
            f"from Curiosity's measurement at Gale")
    if not lo_p <= p <= hi_p:
        note += f"; RAD only measured this trend between {lo_p:.0f} and {hi_p:.0f} Pa, so this is an extrapolation"
    return {"rad_gcr_dose_mgy_per_day": round(gy, 4), "rad_dose_equivalent_msv_per_day": round(GALE_DOSE_EQ_MSV_PER_DAY * ratio, 4),
            "rad_estimate": {"elevation_m": round(elevation_m, 1), "pressure_pa": round(p, 1),
                             "column_g_cm2": round(column_g_cm2(p), 2), "kappa_ugy_per_day_pa": KAPPA_UGY_PER_DAY_PA,
                             "gcr_range_mgy_per_day": [round(lo, 4), round(hi, 4)],
                             "extrapolated": not lo_p <= p <= hi_p, "note": note, "source": SOURCE}}


def rates(spaceweather: dict) -> tuple[float, float, bool, str]:
    """(GCR mGy/day, dose equivalent mSv/day, is_estimate, note) for a site's [spaceweather] table.
    Sites without values fall back to Gale's measurement, labelled as such."""
    gy = spaceweather.get("rad_gcr_dose_mgy_per_day")
    sv = spaceweather.get("rad_dose_equivalent_msv_per_day")
    est = spaceweather.get("rad_estimate")
    if gy is None:
        return GALE_GCR_MGY_PER_DAY, GALE_DOSE_EQ_MSV_PER_DAY, True, "Curiosity's measurement at Gale, not measured here"
    if sv is None:
        sv = GALE_DOSE_EQ_MSV_PER_DAY * float(gy) / GALE_GCR_MGY_PER_DAY
    if est:
        return float(gy), float(sv), True, str(est.get("note", "estimated"))
    return float(gy), float(sv), False, "measured on the ground by Curiosity's RAD instrument (Hassler et al. 2014)"
