"""Where the Sun is in the sky at a place on Mars: the Mars24 algorithm (Allison & McEwen 2000, as published by
NASA GISS with worked examples: https://www.giss.nasa.gov/tools/mars24/help/algorithm.html).

Coordinates: latitudes and longitudes in MarsWalk are planetocentric, east-positive (Mars 2000 sphere). Mars24 takes
planetographic latitude and west longitude; `sun_position` converts. Azimuth is clockwise from north.
"""
from __future__ import annotations

import datetime as dt
import math

UTC = dt.UTC
SOL_DAYS = 1.0274912517            # Mars solar day in Earth days (C-2)
RE_KM, RP_KM = 3396.19, 3376.20     # IAU Mars ellipsoid, for planetocentric -> planetographic latitude

# TAI - UTC from the IERS leap-second table (dates after 1999); TT - UTC = TAI - UTC + 32.184 s (A-4).
_LEAP = [(dt.datetime(2017, 1, 1, tzinfo=UTC), 37), (dt.datetime(2015, 7, 1, tzinfo=UTC), 36),
         (dt.datetime(2012, 7, 1, tzinfo=UTC), 35), (dt.datetime(2009, 1, 1, tzinfo=UTC), 34),
         (dt.datetime(2006, 1, 1, tzinfo=UTC), 33), (dt.datetime(1999, 1, 1, tzinfo=UTC), 32)]


def tt_minus_utc(t: dt.datetime) -> float:
    for since, tai in _LEAP:
        if t >= since:
            return tai + 32.184
    return 32 + 32.184


def _sin(d: float) -> float:
    return math.sin(math.radians(d))


def _cos(d: float) -> float:
    return math.cos(math.radians(d))


def jd_tt(t: dt.datetime) -> float:
    t = t if t.tzinfo else t.replace(tzinfo=UTC)
    jd_ut = 2440587.5 + t.timestamp() / 86400.0                                     # A-2
    return jd_ut + tt_minus_utc(t) / 86400.0                                       # A-5


def solar(t: dt.datetime) -> dict:
    """Mars-wide solar quantities at UTC time t (steps A to D-1)."""
    jtt = jd_tt(t)
    d = jtt - 2451545.0                                                            # A-6
    m = (19.3871 + 0.52402073 * d) % 360.0                                         # B-1
    a_fms = (270.3871 + 0.524038496 * d) % 360.0                                   # B-2
    pbs = sum(a * _cos(0.985626 * d / tau + phi) for a, tau, phi in (               # B-3
        (0.0071, 2.2353, 49.409), (0.0057, 2.7543, 168.173), (0.0039, 1.1177, 191.837),
        (0.0037, 15.7866, 21.736), (0.0021, 2.1354, 15.704), (0.0020, 2.4694, 95.528),
        (0.0018, 32.8493, 49.095)))
    nu_m = ((10.691 + 3.0e-7 * d) * _sin(m) + 0.623 * _sin(2 * m) + 0.050 * _sin(3 * m)  # B-4
            + 0.005 * _sin(4 * m) + 0.0005 * _sin(5 * m) + pbs)
    ls = (a_fms + nu_m) % 360.0                                                    # B-5
    eot = 2.861 * _sin(2 * ls) - 0.071 * _sin(4 * ls) + 0.002 * _sin(6 * ls) - nu_m  # C-1, degrees
    mst = (24.0 * ((jtt - 2451549.5) / SOL_DAYS + 44796.0 - 0.0009626)) % 24.0       # C-2, hours
    sub_lon_w = (mst * 15.0 + eot + 180.0) % 360.0                                 # C-5, subsolar west longitude
    dec = math.degrees(math.asin(0.42565 * _sin(ls))) + 0.25 * _sin(ls)            # D-1
    return {"jd_tt": jtt, "ls_deg": ls, "eot_deg": eot, "mst_h": mst, "subsolar_lon_w": sub_lon_w, "dec_deg": dec}


def mars_sol_date(t: dt.datetime) -> float:
    """Mars Sol Date (C-2): sols since 1873-12-29 at Mars's prime meridian; its fraction x 24 is the mean solar time."""
    return (jd_tt(t) - 2451549.5) / SOL_DAYS + 44796.0 - 0.0009626


def local_sol(t: dt.datetime, lon_e: float) -> int:
    """The sol number at east longitude lon_e: the Mars Sol Date counted in local mean solar time."""
    return math.floor(mars_sol_date(t) + lon_e / 360.0)


def planetographic_lat(lat_c: float) -> float:
    return math.degrees(math.atan(math.tan(math.radians(lat_c)) * (RE_KM / RP_KM) ** 2))


def local_times(t: dt.datetime, lon_e: float) -> tuple[float, float]:
    """(LMST, LTST) in hours at east longitude lon_e (C-3, C-4)."""
    s = solar(t)
    lmst = (s["mst_h"] + lon_e / 15.0) % 24.0                                      # west longitude = -lon_e
    return lmst, (lmst + s["eot_deg"] / 15.0) % 24.0


def sun_position(t: dt.datetime, lat_c: float, lon_e: float) -> tuple[float, float]:
    """(azimuth clockwise from north, elevation) of the Sun in degrees, seen from (lat_c, lon_e) (D-5, D-6)."""
    s = solar(t)
    phi = planetographic_lat(lat_c)
    h = ((-lon_e) % 360.0) - s["subsolar_lon_w"]                                   # H = west longitude - subsolar
    dec = s["dec_deg"]
    cos_z = _sin(dec) * _sin(phi) + _cos(dec) * _cos(phi) * _cos(h)
    z = math.degrees(math.acos(max(-1.0, min(1.0, cos_z))))
    az = math.degrees(math.atan2(_sin(h), _cos(phi) * math.tan(math.radians(dec)) - _sin(phi) * _cos(h))) % 360.0
    return az, 90.0 - z


def next_lmst(now: dt.datetime, lon_e: float, lmst_h: float) -> dt.datetime:
    """The first UTC moment at or after `now` when the local mean solar time at lon_e is lmst_h."""
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    cur, _ = local_times(now, lon_e)
    wait_h = (lmst_h - cur) % 24.0                                                 # Mars hours (1/24 sol)
    return now + dt.timedelta(days=wait_h / 24.0 * SOL_DAYS)


def track(start: dt.datetime, lat_c: float, lon_e: float, minutes: float, step_min: float = 2.0) -> dict:
    """The Sun through a walk: azimuth and elevation every `step_min` minutes from `start` (UTC)."""
    n = math.ceil(minutes / step_min) + 1
    pts = []
    for i in range(n):
        az, el = sun_position(start + dt.timedelta(minutes=i * step_min), lat_c, lon_e)
        pts.append([round(az, 3), round(el, 3)])
    lmst, ltst = local_times(start, lon_e)
    return {"start_utc": start.astimezone(UTC).isoformat(timespec="seconds"), "ls_deg": round(solar(start)["ls_deg"], 2),
            "lmst_h": round(lmst, 4), "ltst_h": round(ltst, 4), "sol": local_sol(start, lon_e),
            "step_min": step_min, "az_el": pts}
