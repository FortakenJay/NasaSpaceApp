"""Space-weather go/no-go for the EVA, from the MSL RAD surface baseline plus NASA DONKI.

What is checked (all from DONKI, the Space Weather Database Of Notifications, Knowledge, Information):
- WSA-ENLIL+Cone simulations: each run lists predicted CME shock arrivals by location, and "Mars" is one of
  the locations (checked against the live feed 2026-11-14: impactList entries are
  {location, arrivalTime, isGlancingBlow, isMinorImpact}, or impactList is null). This is the only Mars-specific signal here, so it drives the decision.
- SEP (solar energetic particle) events and solar flares (FLR): detected near Earth / L1 and by other
  spacecraft. Mars can be on the other side of the Sun, so these are a proxy and are labelled as such.

Rules (placeholders to review with a flight surgeon / space-weather officer, all in configurable windows):
  NO-GO   a CME shock (not a glancing blow) is predicted at Mars from 24 h ago to 48 h ahead,
          or an SEP event was detected in the last 48 h
  CAUTION a glancing blow at Mars in that window, any Mars arrival in the next 7 days,
          an SEP event in the last 7 days, an X-class flare in the last 24 h,
          or DONKI could not be reached (a quiet Sun cannot be confirmed)
  GO      otherwise
The GCR dose for the EVA at the RAD baseline rate is always reported for context (no terrain shielding credit).

DONKI notes: each request is capped at 60 days. api.nasa.gov needs a key (NASA_API_KEY in the environment or in
.env; DEMO_KEY works but is limited to about 30 requests/hour). Every request goes through
marswalk.sources.api_client.ApiClient: answers are cached per feed for 30 minutes, a saved copy up to 6 hours
old is used when NASA does not answer, slow feeds finish in the background, and failures back off.
The flare list is optional: its absence is noted but does not block a GO.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import asdict, dataclass, field, replace

from marswalk.sources.api_client import ApiClient, plain_error

CCMC_BASE = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get"
UTC = dt.timezone.utc


@dataclass(frozen=True)
class SpaceWeatherStatus:
    level: str                 # "GO" | "CAUTION" | "NO-GO"
    reason: str
    baseline_dose_mgy_per_day: float
    eva_dose_mgy: float
    recent_sep_events: int
    mars_arrivals: list = field(default_factory=list)     # [{"arrival": iso, "glancing": bool, "hours_from_now": float}]
    strongest_flare: str = ""                             # e.g. "X1.2" (last 3 days, Earth-facing proxy)
    checked_at: str = ""                                  # ISO UTC
    source: str = ""                                      # "DONKI", or why it is unavailable
    data_ok: bool = True                                  # False when a required feed gave no answer
    notes: list = field(default_factory=list)             # e.g. a saved copy was used, or the flare list is late

    def as_dict(self) -> dict:
        return asdict(self)


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


def parse_time(value) -> dt.datetime | None:
    """DONKI times look like 2024-09-04T14:00Z. Returns an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def mars_arrivals(simulations: list[dict], now: dt.datetime) -> list[dict]:
    """Predicted CME shock arrivals at Mars from WSA-ENLIL runs (deduplicated to the hour, newest run wins)."""
    found: dict[str, dict] = {}
    for sim in simulations:
        for imp in (sim.get("impactList") or []):
            if "mars" not in str(imp.get("location", "")).lower():
                continue
            t = parse_time(imp.get("arrivalTime"))
            if t is None:
                continue
            key = t.strftime("%Y-%m-%dT%H")
            found[key] = {"arrival": t.isoformat(),
                          "glancing": bool(imp.get("isGlancingBlow") or imp.get("isMinorImpact")),
                          "hours_from_now": round((t - now).total_seconds() / 3600.0, 1)}
    return sorted(found.values(), key=lambda x: x["arrival"])


def _flare_rank(cls: str) -> float:
    """"X1.2" -> 4.012-ish ordering value; unknown -> 0."""
    order = {"A": 0, "B": 1, "C": 2, "M": 3, "X": 4}
    cls = (cls or "").strip().upper()
    if not cls or cls[0] not in order:
        return 0.0
    try:
        return order[cls[0]] + min(float(cls[1:] or 0), 99.0) / 100.0
    except ValueError:
        return float(order[cls[0]])


def go_no_go(sep_events: list[dict], now: dt.datetime, duration_h: float, baseline_mgy_per_day: float,
             simulations: list[dict] | None = None, flares: list[dict] | None = None,
             data_ok: bool = True, source: str = "DONKI") -> SpaceWeatherStatus:
    """Apply the rules in the module docstring. `now` must be timezone-aware."""
    h = lambda t: (now - t).total_seconds() / 3600.0          # noqa: E731  hours ago (negative = future)
    sep_times = [t for t in (parse_time(e.get("eventTime")) for e in sep_events) if t is not None]
    sep_48h = [t for t in sep_times if 0 <= h(t) <= 48]
    sep_7d = [t for t in sep_times if 0 <= h(t) <= 7 * 24]
    arrivals = mars_arrivals(simulations or [], now)
    window = [a for a in arrivals if -24 <= a["hours_from_now"] <= 48]
    ahead = [a for a in arrivals if 48 < a["hours_from_now"] <= 7 * 24]
    recent_flares = [f for f in (flares or []) if (t := parse_time(f.get("peakTime") or f.get("beginTime"))) and 0 <= h(t) <= 72]
    strongest = max((str(f.get("classType", "")) for f in recent_flares), key=_flare_rank, default="")
    x_24h = [f for f in recent_flares if str(f.get("classType", "")).upper().startswith("X")
             and h(parse_time(f.get("peakTime") or f.get("beginTime"))) <= 24]

    no_go, caution = [], []
    direct = [a for a in window if not a["glancing"]]
    if direct:
        no_go.append(f"CME shock predicted at Mars ({direct[0]['arrival'][:16]}Z)")
    if sep_48h:
        no_go.append(f"{len(sep_48h)} solar energetic particle event(s) in the last 48 h (detected near Earth)")
    glancing = [a for a in window if a["glancing"]]
    if glancing:
        caution.append(f"glancing CME blow predicted at Mars ({glancing[0]['arrival'][:16]}Z)")
    if ahead:
        caution.append(f"CME arrival at Mars predicted in {ahead[0]['hours_from_now'] / 24:.1f} days")
    if sep_7d and not sep_48h:
        caution.append(f"{len(sep_7d)} solar energetic particle event(s) in the last 7 days (detected near Earth)")
    if x_24h:
        caution.append(f"{strongest} flare in the last 24 h (Earth-facing view)")
    if not data_ok:
        caution.append("NASA DONKI did not answer in full, so a quiet Sun is not confirmed")

    if no_go:
        level, reason = "NO-GO", "; ".join(no_go + caution)
    elif caution:
        level, reason = "CAUTION", "; ".join(caution)
    else:
        level, reason = "GO", "No CME arrival predicted at Mars and no particle events in the last 7 days"
    return SpaceWeatherStatus(level=level, reason=reason[0].upper() + reason[1:] + ".",
                              baseline_dose_mgy_per_day=baseline_mgy_per_day,
                              eva_dose_mgy=round(eva_dose_mgy(duration_h, baseline_mgy_per_day), 4),
                              recent_sep_events=len(sep_7d), mars_arrivals=window + ahead, strongest_flare=strongest,
                              checked_at=now.isoformat(timespec="seconds"), source=source, data_ok=data_ok)


# Feeds asked from DONKI. "required" feeds decide whether a quiet Sun can be confirmed; flares are only a hint
# (what matters at Mars arrives as a CME or as particles, which the other two feeds cover).
FEEDS = {
    "enlil": {"kind": "WSAEnlilSimulations", "days": 7, "required": True, "label": "Eruptions predicted to reach Mars"},
    "sep": {"kind": "SEP", "days": 7, "required": True, "label": "Particle storms"},
    "flr": {"kind": "FLR", "days": 3, "required": False, "label": "Solar flares", "timeout_s": 30.0},
}
FEED_TTL_S = 30 * 60        # how long an answer counts as current
FEED_STALE_S = 6 * 3600     # how old a saved copy may be and still be used when NASA does not answer
FEED_TIMEOUT_S = 12.0       # per request; slow answers finish in the background
STATUS_DEADLINE_S = 10.0    # how long the panel waits before answering with what it has


def feed_requests(base_url: str, api_key: str, today: dt.date) -> dict[str, dict]:
    out = {}
    for name, f in FEEDS.items():
        q = {"startDate": (today - dt.timedelta(days=f["days"])).isoformat(), "endDate": today.isoformat()}
        out[name] = {"urls": [f"{base_url.rstrip('/')}/{f['kind']}?{urllib.parse.urlencode({**q, 'api_key': api_key})}",
                              f"{CCMC_BASE}/{f['kind']}?{urllib.parse.urlencode(q)}"],
                     "ttl_s": FEED_TTL_S, "timeout_s": f.get("timeout_s", FEED_TIMEOUT_S), "stale_s": FEED_STALE_S}
    return out


def current_status(spaceweather_cfg: dict, duration_h: float, api_key: str, now: dt.datetime | None = None,
                   client: ApiClient | None = None, force: bool = False) -> SpaceWeatherStatus:
    """Ask DONKI through the central ApiClient (cache, stale copies, back-off) and apply the rules.
    Never raises on network trouble and never waits longer than STATUS_DEADLINE_S."""
    now = now or dt.datetime.now(UTC)
    client = client or ApiClient()
    from marswalk.spaceweather.radiation import rates
    rate = rates(spaceweather_cfg)[0]
    base = spaceweather_cfg.get("donki_base_url", "https://api.nasa.gov/DONKI")
    got = client.get_many(feed_requests(base, api_key, now.date()), deadline_s=STATUS_DEADLINE_S, force=force)

    notes, missing_required = [], []
    for name, f in FEEDS.items():
        r = got[name]
        if r.state == "missing":
            (missing_required if f["required"] else notes).append(
                f["label"] if f["required"] else
                f"{f['label']}: no answer yet. {plain_error(r.error)} Flares are seen from Earth, so this list is only a hint "
                "for Mars and does not change the go/no-go.")
        elif r.state == "stale":
            at = dt.datetime.fromtimestamp(r.fetched_at, UTC).strftime("%H:%M UTC")
            notes.append(f"{f['label']}: NASA did not answer just now, using the copy saved at {at}.")
    source = "NASA DONKI" if not missing_required else f"NASA DONKI (no answer for: {', '.join(missing_required)})"
    st = go_no_go(got["sep"].data or [], now, duration_h, rate, simulations=got["enlil"].data or [],
                  flares=got["flr"].data or [], data_ok=not missing_required, source=source)
    return replace(st, notes=notes)
