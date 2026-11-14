"""Space-weather status panel data.

Implemented: EVA dose estimate from the RAD baseline, and splitting date ranges for DONKI.
TODO(M5): fetch_sep_events() and go_no_go() (rules below).

Notes:
- DONKI (api.nasa.gov/DONKI/SEP) caps each request at 60 days. DEMO_KEY works but is rate-limited,
  so set NASA_API_KEY. Tested 2026-11-13: 11 SEP entries for Jul-Aug 2025.
- DONKI reports Earth/L1-centric SEP detections. At this stage they are a proxy for Mars risk.
  Mars-side confirmation (MAVEN SEP, RAD time series on PDS PPI) is a later upgrade.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class SpaceWeatherStatus:
    level: str                 # "GO" | "CAUTION" | "NO-GO"
    reason: str
    baseline_dose_mgy_per_day: float
    eva_dose_mgy: float
    recent_sep_events: int


def eva_dose_mgy(duration_h: float, baseline_mgy_per_day: float) -> float:
    """GCR dose over the EVA at the surface baseline rate (no terrain shielding credit yet)."""
    return baseline_mgy_per_day * duration_h / 24.0


def split_range(start: dt.date, end: dt.date, max_days: int = 60) -> list[tuple[dt.date, dt.date]]:
    """Split [start, end] into inclusive chunks of at most max_days, for DONKI's limit."""
    out, cur = [], start
    while cur <= end:
        nxt = min(cur + dt.timedelta(days=max_days - 1), end)
        out.append((cur, nxt))
        cur = nxt + dt.timedelta(days=1)
    return out


def fetch_sep_events(start: dt.date, end: dt.date, base_url: str, api_key: str) -> list[dict]:
    """TODO(M5): GET {base_url}/SEP?startDate=..&endDate=..&api_key=.. for each split_range() chunk."""
    raise NotImplementedError("M5: DONKI SEP fetch")


def go_no_go(events: list[dict], now: dt.datetime, duration_h: float, baseline_mgy_per_day: float) -> SpaceWeatherStatus:
    """TODO(M5) rules (placeholders to review):
    NO-GO   if any SEP event in the last 48 h, or a >=M5 flare in the last 24 h (DONKI FLR)
    CAUTION if any SEP event in the last 7 days
    GO      otherwise. Always report eva_dose_mgy() for context.
    """
    raise NotImplementedError("M5: go/no-go rules")
