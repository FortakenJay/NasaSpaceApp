"""Ask MarsWalk: questions in plain words, answered from the plan, the terrain and the space-weather check.

    "How far is S3 from here?"      "How much oxygen does this walk use?"     "How much radiation?"
    "When must we turn back?"       "How steep is S2?"                        "Is it safe to go out?"

No language model and no network: a small keyword parser finds the topics a question asks about (one question may
ask about several) and the places it names (stop codes, distinctive words of stop names, "the rover", "here",
"the next stop"). Every number in an answer comes from the same code that builds the plan. Speech-to-text often
writes "S3" as "s 3", "s three", "stop three" or "s-3"; all of those are understood.

"Here" is, in this order: the stop selected on the map; the planned position at the time chosen on the step 4
slider; the rover. Every answer that uses it says which one it was.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from marswalk.config import EVAConfig, SiteConfig
from marswalk.geo import ground_distance_m

KJ_PER_KCAL = 4.184
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12}
# How speech-to-text spells a digit after the letter "s" ("s for" = S4). Only used right after s/es/ess.
SOUNDALIKE = {"to": 2, "too": 2, "for": 4, "fore": 4, "won": 1, "tree": 3, "free": 3, "ate": 8}
ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4, "sixth": 5, "last": -1, "final": -1}
# Words of stop names that never identify one stop on their own.
NAME_STOPWORDS = {"first", "second", "third", "final", "last", "next", "stop", "stops", "site", "ridge", "ridges",
                  "hollow", "drill", "phase", "start", "point", "place", "parking", "pressurized", "rover", "boxwork",
                  "where", "there", "about", "which", "after", "before"}
NUM = "|".join([r"\d{1,2}", *NUMBERS])

TOPICS: list[tuple[str, str]] = [
    ("help", r"\b(help|what can (you|i) (ask|say|do)|how does this work)\b"),
    ("distance", (r"\b(how far|distance|far (is|are|from|away|to)|how many (meters|metres|kilometers|kilometres)"
                  r"|path to|route to|way to|directions to|where is|where'?s)\b")),
    ("go", r"\b((go|head|walk|get|take me|navigate) to)\b"),
    ("travel_time", (r"\b(how long (does it take |will it take |would it take |is it )?(to|until) (walk|get|go|reach|hike)"
                    r"|time to (walk|get|reach)|how many minutes (to|until))\b")),
    ("walk_home", (r"\b(walk(ing)? (home|back)|get(ting)? (home|back)|make it (home|back)|head(ing)? (home|back)"
                  r"|return(ing)? (home|to the rover)|turn (back|around)|back to (the )?(rover|base|habitat))\b")),
    ("oxygen", r"\b(oxygen|o2|o 2|o two|breath(e|ing)?|air (left|supply))\b"),
    ("radiation", r"\b(radiation|exposure|exposed|doses?|sieverts?|millisieverts?|grays?|milligrays?|cosmic rays?)\b"),
    ("energy", r"\b(energy|calories?|kilocalories?|kilojoules?|kj|effort|tired|metabolic|burn)\b"),
    ("weather", (r"\b(space weather|solar|sun|flares?|storms?|cme|eruptions?|particles?|go or no go|go no go"
                r"|safe to go( out(side)?)?)\b")),
    ("terrain", (r"\b(steep|steepness|slopes?|rough|roughness|rocks?|rocky|sand|sandy|terrain|ground|elevation|altitude"
                r"|height|ledges?)\b")),
    ("time", (r"\b(how long|how much time|duration|time (outside|left|remaining|budget)|spare|margin"
             r"|when (do|will|must|should|can|would) (we|i)|deadline|back by|what time)\b")),
    ("stops", (r"\b(next stop|order|which stops|what stops|how many stops|itinerary|schedule|timeline"
              r"|where (do|are|will) (we|i) (go|going|stop))\b")),
    ("limits", (r"\b(limits?|violations?|problems?|warnings?|issues?|risks?|is it safe"
               r"|is (the|this|my|our) (plan|walk|route|eva) (safe|ok|okay|fine|good))\b")),
    ("untracked", (r"\b(water|drink|thirst|thirsty|food|eat|battery|batteries|temperature|cold|heat|hot|co2"
                  r"|carbon dioxide|suit pressure|cooling)\b")),
]
ROUTE_TOPICS = {"distance", "travel_time", "go"}
STAY_WORDS = re.compile(r"\b(stay|spend|remain|last|left|keep)\b")


# --- what a question names ------------------------------------------------------------------------

@dataclass
class Place:
    id: str | None              # stop code, or None for a position along the plan
    name: str
    lat: float
    lon: float
    kind: str                   # "start" | "stop" | "user" | "position"
    label: str                  # how answers name it the first time ("S3 (Monte Grande hollow ...)")
    short: str = ""             # and afterwards ("S3", "the rover")
    arrive_min: float | None = None    # planned clock time here (minutes since leaving the rover), when known
    depart_min: float | None = None
    is_here: bool = False       # this is "here" (the selected stop, the slider position or the rover)


@dataclass
class Mention:
    place: Place | None         # None = "here"
    start: int
    end: int
    origin: bool = False        # named after "from" / "leaving" (or first of "between X and Y")


@dataclass
class AskContext:
    site: SiteConfig
    eva: EVAConfig
    stops: list[dict]                                  # the site's stops as the API lists them (DB)
    plan: dict | None = None                           # plan payload (export.payload.plan_payload) or None
    cost: str | None = None                            # cost model of that plan
    selected_stop_id: str | None = None
    elapsed_h: float = 0.0
    live: tuple[float, float] | None = None           # (lat, lon) of a walker, e.g. in the simulator: that is "here"
    visited: list[str] | None = None                  # stops already done (live mode): "the next stop" skips them
    stack: Callable[[], object] | None = None          # -> LayerStack, or None when the terrain is not fetched
    walkback: Callable[[object], object] | None = None   # stack -> reverse Field from the rover (cached by the API)
    status: Callable[[], dict] | None = None           # -> space-weather status dict
    _stack_cache: list = field(default_factory=list)

    def terrain(self):
        if not self._stack_cache:
            try:
                self._stack_cache.append(self.stack() if self.stack else None)
            except Exception:  # noqa: BLE001 - e.g. the terrain is not fetched yet: answer without it
                self._stack_cache.append(None)
        return self._stack_cache[0]


def normalize(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9.'\s-]", " ", t)
    t = re.sub(r"(?<=[a-z])-(?=\d)|(?<=\d)-(?=[a-z])", " ", t)     # "s-3" -> "s 3"
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)                         # keep decimal points only
    return re.sub(r"\s+", " ", t).strip()


def _number(word: str, soundalike: bool = False) -> int | None:
    if word.isdigit():
        return int(word)
    return NUMBERS.get(word) or (SOUNDALIKE.get(word) if soundalike else None)


def topics_of(q: str) -> list[str]:
    return [name for name, pat in TOPICS if re.search(pat, q)]


def _distinct_words(stops: list[dict]) -> dict[str, str]:
    """Words (5+ letters) that appear in exactly one stop's name -> that stop's id."""
    seen: dict[str, set[str]] = {}
    for s in stops:
        for w in set(re.findall(r"[a-z]{5,}", normalize(s["name"]))):
            if w not in NAME_STOPWORDS:
                seen.setdefault(w, set()).add(s["id"])
    return {w: next(iter(ids)) for w, ids in seen.items() if len(ids) == 1}


def find_mentions(q: str, ctx: AskContext, here: Place) -> list[Mention]:
    """Places named in the (normalized) question, in order of appearance."""
    by_id = {s["id"].upper(): s for s in ctx.stops}
    places = {sid: _stop_place(s, ctx.plan) for sid, s in by_id.items()}
    start_id = next((s["id"] for s in ctx.stops if s["kind"] == "start"), None)
    found: list[Mention] = []

    def add(place: Place | None, m: re.Match) -> None:
        if any(not (m.end() <= x.start or m.start() >= x.end) for x in found):
            return                                                       # overlaps an earlier, longer match
        found.append(Mention(place, m.start(), m.end()))

    for m in re.finditer(r"\b(?:the )?(" + "|".join(ORDINALS) + r"|next|previous) stop\b", q):
        p = _ordinal_stop(m.group(1), ctx, here, places)
        if p is not None:
            add(p, m)
    for m in re.finditer(r"\b(s|es|ess|stop|station|site)\s?(" + NUM + "|" + "|".join(SOUNDALIKE) + r")\b", q):
        n = _number(m.group(2), soundalike=m.group(1) in ("s", "es", "ess"))
        if n is not None and f"S{n}" in places:
            add(places[f"S{n}"], m)
    for m in re.finditer(r"\b(?:u\s?|my stop\s?|added stop\s?)(" + NUM + r")\b", q):
        n = _number(m.group(1))
        if n is not None and f"U{n}" in places:
            add(places[f"U{n}"], m)
    if start_id:
        for m in re.finditer(r"\b(h\s?1|h one|(the )?(rover|home|base|habitat|airlock|vehicle|starting point))\b", q):
            add(places[start_id.upper()], m)
    for m in re.finditer(r"\b(here|this (point|spot|part|place|location)|where (i am|we are|i'm)"
                         r"|(my|our) (position|location)|current (position|location))\b", q):
        add(None, m)
    for word, sid in _distinct_words(ctx.stops).items():
        for m in re.finditer(rf"\b{word}\b", q):
            add(places[sid.upper()], m)
    found.sort(key=lambda x: x.start)
    merged: list[Mention] = []
    for x in found:            # "monte grande", "nevado sajama": two words of one name are one mention
        prev = merged[-1] if merged else None
        if (prev and prev.place and x.place and prev.place.id == x.place.id
                and re.fullmatch(r"[\s+]*|\s(and|y)\s|\s\+\s", q[prev.end:x.start] or " ")):
            prev.end = x.end
        else:
            merged.append(x)
    found = merged
    for x in found:
        before = q[max(0, x.start - 14):x.start]
        x.origin = bool(re.search(r"\b(from|leaving|starting at)( the)?\s*$", before))
    if re.search(r"\bbetween\b", q) and len(found) >= 2 and not any(x.origin for x in found):
        found[0].origin = True
    return found


def _stop_place(s: dict, plan: dict | None) -> Place:
    label = "the rover" if s["kind"] == "start" else f"{s['id']} ({s['name']})"
    short = "the rover" if s["kind"] == "start" else s["id"]
    arrive = depart = None
    if plan:
        w = next((w for w in plan.get("timeline", []) if w["id"] == s["id"] and w["kind"] == "stop"), None)
        if w is not None:
            arrive, depart = w["arrive_min"], w["depart_min"]
    return Place(s["id"], s["name"], s["lat"], s["lon"], s["kind"], label, short, arrive, depart)


def _plan_stops(ctx: AskContext) -> list[str]:
    if ctx.plan:
        return [w["id"] for w in ctx.plan.get("timeline", []) if w["kind"] == "stop"]
    return [s["id"] for s in ctx.stops if s["kind"] != "start"]


def _ordinal_stop(word: str, ctx: AskContext, here: Place, places: dict[str, Place]) -> Place | None:
    order = _plan_stops(ctx)
    if not order:
        return None
    if word in ORDINALS:
        i = ORDINALS[word]
        return places.get(order[i].upper()) if -len(order) <= i < len(order) else None
    # next / previous, relative to "here"
    if ctx.visited is not None and word == "next":
        left = [i for i in order if i not in set(ctx.visited)]
        return places.get(left[0].upper()) if left else next((p for p in places.values() if p.kind == "start"), None)
    tl = [w for w in (ctx.plan or {}).get("timeline", []) if w["kind"] == "stop"]
    if here.id and here.id in order:
        i = order.index(here.id) + (1 if word == "next" else -1)
    elif tl and here.arrive_min is not None:
        later = [k for k, w in enumerate(tl) if w["arrive_min"] > here.arrive_min]
        i = (later[0] if later else len(tl)) - (0 if word == "next" else 1)
    else:
        i = 0 if word == "next" else -1
    return places.get(order[i].upper()) if 0 <= i < len(order) else None


# --- "here" ---------------------------------------------------------------------------------------

def resolve_here(ctx: AskContext) -> Place:
    """The selected stop, else the planned position at the slider time, else the rover."""
    by_id = {s["id"]: s for s in ctx.stops}
    if ctx.live is not None:
        t = ctx.elapsed_h * 60.0
        return Place(None, "position", ctx.live[0], ctx.live[1], "position", f"your position, {hm(t)} into the walk",
                     "your position", arrive_min=t, depart_min=t, is_here=True)
    if ctx.selected_stop_id and ctx.selected_stop_id in by_id:
        p = _stop_place(by_id[ctx.selected_stop_id], ctx.plan)
        p.label = f"{p.label}, the stop selected on the map" if p.kind != "start" else "the rover (selected on the map)"
        p.is_here = True
        return p
    start = next(s for s in ctx.stops if s["kind"] == "start")
    t = ctx.elapsed_h * 60.0
    if ctx.plan and t > 0:
        pos = position_at(ctx.plan, t)
        if pos is not None:
            lat, lon, where = pos
            return Place(None, "position", lat, lon, "position", f"your planned position {hm(t)} into the walk ({where})",
                         f"your position at {hm(t)} ({where})", arrive_min=t, depart_min=t, is_here=True)
    p = _stop_place(start, ctx.plan)
    p.arrive_min = p.depart_min = 0.0 if ctx.plan else None
    p.is_here = True
    return p


def position_at(plan: dict, t_min: float) -> tuple[float, float, str] | None:
    """Where the plan puts the crew at t_min (lat, lon, plain description), from the timeline and route."""
    tl = plan.get("timeline") or []
    if not tl:
        return None
    for i, w in enumerate(tl):
        if w["arrive_min"] <= t_min <= w["depart_min"]:
            return w["lat"], w["lon"], ("at the rover" if w["kind"] in ("start", "end") else f"working at {w['id']}")
        nxt = tl[i + 1] if i + 1 < len(tl) else None
        if nxt and w["depart_min"] < t_min < nxt["arrive_min"]:
            to = "the rover" if nxt["kind"] == "end" else nxt["id"]
            frm = "the rover" if w["kind"] == "start" else w["id"]
            ll = _along_route(plan, t_min)
            if ll is None:      # no profile: assume an even pace on this leg
                f = (t_min - w["depart_min"]) / max(nxt["arrive_min"] - w["depart_min"], 1e-6)
                ll = (w["lat"] + f * (nxt["lat"] - w["lat"]), w["lon"] + f * (nxt["lon"] - w["lon"]))
            return ll[0], ll[1], f"walking from {frm} to {to}"
    last = tl[-1]
    return last["lat"], last["lon"], "back at the rover"


def _along_route(plan: dict, t_min: float) -> tuple[float, float] | None:
    prof = plan.get("profile") or {}
    t, d = prof.get("t_min"), prof.get("dist_m")
    feats = (plan.get("route") or {}).get("features") or []
    if not t or not d or not feats:
        return None
    pts = [(tt, dd) for tt, dd in zip(t, d) if tt is not None and dd is not None]
    if len(pts) < 2:
        return None
    dist = float(np.interp(t_min, [p[0] for p in pts], [p[1] for p in pts]))
    coords = [c for f in feats for c in f["geometry"]["coordinates"]]
    lon, lat = np.array([c[0] for c in coords]), np.array([c[1] for c in coords])
    step = np.hypot(np.diff(lat), np.diff(lon) * np.cos(np.radians(lat[:-1])))
    cum = np.concatenate([[0.0], np.cumsum(step)])
    if cum[-1] <= 0:
        return float(lat[0]), float(lon[0])
    s = dist / max(d[-1] or 1.0, 1e-6) * cum[-1]          # profile distance -> share of the drawn route
    return float(np.interp(s, cum, lat)), float(np.interp(s, cum, lon))


# --- formatting -----------------------------------------------------------------------------------

def hm(minutes: float) -> str:
    m = max(round(minutes), 0)
    h, mm = divmod(m, 60)
    return f"{h} h {mm:02d} min" if h else f"{mm} min"


def dist_text(m: float) -> str:
    return f"{m / 1000:.2f} km" if m >= 1000 else f"{max(round(m, -1), 10):.0f} m"


def spoken(text: str) -> str:
    """The answer as text-to-speech should read it (units spelled out, symbols dropped)."""
    s = re.sub(r"(\d+) h 0?(\d+) min", lambda m: f"{m[1]} hour{'' if m[1] == '1' else 's'} {m[2]} minutes", text)
    s = re.sub(r"(\d+) min\b", r"\1 minutes", s)
    for pat, rep in [(r"(\d) km\b", r"\1 kilometres"), (r"(\d) m\b", r"\1 metres"), (r"°", " degrees"),
                     (r"\bmGy\b", "milligray"), (r"\bmSv\b", "millisieverts"), (r"\bkJ\b", "kilojoules"),
                     (r"\bkcal\b", "kilocalories"), (r"(\d) kg\b", r"\1 kilograms"), (r"%", " percent"),
                     (r"−", "minus "), (r"\bO2\b", "oxygen"), (r"\bEVA\b", "E V A")]:
        s = re.sub(pat, rep, s)
    return s


# --- answers --------------------------------------------------------------------------------------

def _budgets(ctx: AskContext) -> dict:
    from marswalk.route.plan import usable_budgets
    b = usable_budgets(ctx.eva)
    return {"usable_min": b["time_s"] / 60.0, "energy_kj": b["energy_kj"],
            "o2_h": float(ctx.eva.suit.get("o2_capacity_h", ctx.eva.eva["max_duration_h"])),
            "reserve": float(ctx.eva.eva["walkback_reserve_frac"]),
            "margin": float(ctx.eva.eva.get("time_margin_factor", 1.0))}


def _point(lat: float, lon: float, role: str, label: str) -> dict:
    return {"type": "Feature", "properties": {"role": role, "label": label},
            "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}}


def _line(stack, cells, role: str) -> dict:
    lats, lons = stack.grid.rc_to_latlon_many([c[0] for c in cells], [c[1] for c in cells])
    return {"type": "Feature", "properties": {"role": role},
            "geometry": {"type": "LineString", "coordinates": [[round(float(lo), 7), round(float(la), 7)]
                                                                for la, lo in zip(lats, lons)]}}


def _cell(stack, p: Place):
    from marswalk.route.astar import snap
    return snap(stack, stack.grid.latlon_to_rc(p.lat, p.lon))


def answer_route(ctx: AskContext, origin: Place, target: Place, out: list) -> str:
    if origin.id is not None and origin.id == target.id:
        return f"You are already at {target.short}."
    straight = ground_distance_m(origin.lat, origin.lon, target.lat, target.lon, ctx.site.body["radius_m"])
    head = f"{_cap(target.label)} is {dist_text(straight)} from {origin.short} in a straight line."
    stack = ctx.terrain()
    if stack is None:
        return head + " The walking route needs the terrain data (run marswalk fetch)."
    from marswalk.cost.base import model_from_eva
    from marswalk.route.astar import astar
    a, b = _cell(stack, origin), _cell(stack, target)
    if a is None or b is None:
        off = origin if a is None else target
        return head + f" {_cap(off.short)} is outside the ground where walks can be planned, so there is no walking route."
    path = astar(stack, model_from_eva(ctx.eva, ctx.cost), a, b)
    if path is None:
        return head + " There is no walkable route between them inside the slope and roughness limits."
    m = _budgets(ctx)["margin"]
    out.append(_line(stack, path.cells, "route"))
    _append_return(ctx, stack, target, out)
    out += [_point(origin.lat, origin.lon, "here" if origin.is_here else "from", origin.short),
            _point(target.lat, target.lon, "to", target.short)]
    climb = f", climbing {path.climb_m:.0f} m and descending {path.descent_m:.0f} m" if path.climb_m + path.descent_m >= 5 else ""
    return (head + f" On foot, the safest route is {dist_text(path.distance_m)}: about {hm(path.time_s / 60 * m)} "
            f"with the {round((m - 1) * 100)}% time margin{climb}.")


def _append_return(ctx: AskContext, stack, target: Place, out: list) -> None:
    """The walk back from the target to the rover, so a 'go there' has a way out and a way home."""
    if ctx.walkback is None:
        return
    rc = _cell(stack, target)
    back = ctx.walkback(stack)
    if rc is None or not back.reached(rc):
        return
    cells = back.trace(rc)
    if len(cells) > 1:
        out.append(_line(stack, cells, "back"))


def answer_walk_home(ctx: AskContext, origin: Place, out: list) -> str:
    b = _budgets(ctx)
    if origin.kind == "start":
        return "You are at the rover." + (f" {_time_left_sentence(ctx, origin, 0.0)}" if ctx.plan else "")
    stack = ctx.terrain()
    if stack is None or ctx.walkback is None:
        return "The walk home needs the terrain data (run marswalk fetch)."
    rc = _cell(stack, origin)
    back = ctx.walkback(stack)
    if rc is None or not back.reached(rc):
        return f"There is no walkable route from {origin.short} back to the rover inside the slope and roughness limits."
    cells = back.trace(rc)
    steps = np.diff(np.array(cells, dtype=float), axis=0)
    dist = float(np.hypot(steps[:, 0], steps[:, 1]).sum()) * stack.grid.pixel_m
    walk = float(back.time_s[rc]) * b["margin"] / 60.0
    out += [_line(stack, cells, "home"), _point(origin.lat, origin.lon, "here" if origin.is_here else "from", origin.short)]
    first = origin.label if origin.kind in ("stop", "user") and "selected" not in origin.label else origin.short
    text = (f"From {first} the walk back to the rover is {dist_text(dist)}, about {hm(walk)} "
            f"with the {round((b['margin'] - 1) * 100)}% time margin.")
    return text + " " + _time_left_sentence(ctx, origin, walk)


def _time_left_sentence(ctx: AskContext, p: Place, walk_home_min: float) -> str:
    b = _budgets(ctx)
    t = p.depart_min if p.depart_min is not None else (ctx.elapsed_h * 60.0 if ctx.elapsed_h > 0 else None)
    if t is None:
        return (f"With full suits there are {hm(b['usable_min'])} of usable oxygen time, so you could stay out up to "
                f"{hm(b['usable_min'] - walk_home_min)} before starting back.")
    left = b["usable_min"] - t
    when = "when you leave it" if p.kind in ("stop", "user") and p.depart_min is not None else "at that point"
    if left - walk_home_min < 0:
        return (f"At {hm(t)} into the walk ({when}) only {hm(max(left, 0))} of usable oxygen time is left: "
                f"that is {hm(walk_home_min - left)} too little to get home with the reserve intact.")
    turn = "" if walk_home_min <= 0 else f", so you must start back within {hm(left - walk_home_min)}"
    return f"At {hm(t)} into the walk ({when}) {hm(left)} of usable oxygen time is left{turn}."


def answer_oxygen(ctx: AskContext, place: Place | None) -> str:
    from marswalk.route.plan import KJ_PER_KG_O2
    b = _budgets(ctx)
    base = (f"Each suit carries {b['o2_h']:g} h of oxygen. MarsWalk keeps {round(b['reserve'] * 100)}% in reserve for "
            f"the walk home, which leaves {hm(b['usable_min'])} to use.")
    if not ctx.plan:
        return base + " Plan a walk to see how much of it this one uses."
    s = ctx.plan["summary"]
    dur = float(s["duration_h"]) * 60
    text = (base + f" This walk is out {hm(dur)}, {round(100 * dur / b['usable_min'])}% of that, and each crew member "
            f"breathes about {float(s['energy_kj']) / KJ_PER_KG_O2:.2f} kg of oxygen (from {int(s['energy_kj']):,} kJ of "
            f"effort). The tightest moment still leaves {hm(float(s['min_walkback_margin_min']))} to spare.")
    if place is not None and place.kind != "start" and place.depart_min is not None:
        w = next((w for w in ctx.plan["timeline"] if w["id"] == place.id), None)
        used = f", about {w['energy_used_kj'] / KJ_PER_KG_O2:.2f} kg breathed so far" if w else ""
        text += f" At {place.short}: {hm(b['usable_min'] - place.depart_min)} of usable oxygen time left when you leave{used}."
    return text


def answer_radiation(ctx: AskContext) -> str:
    from marswalk.spaceweather import radiation
    gy, sv, estimated, note = radiation.rates(ctx.site.spaceweather)
    dur_h = float(ctx.plan["summary"]["duration_h"]) if ctx.plan else float(ctx.eva.eva["max_duration_h"])
    what = "this" if ctx.plan else f"a full {dur_h:g} h"
    dose = gy * dur_h / 24
    where = (f"the rate {note} ({gy:.3g} mGy, {sv:.3g} mSv per day)" if estimated else
             f"the rate Curiosity's RAD instrument measures on the ground in Gale crater ({gy:g} mGy, {sv:g} mSv per day)")
    text = (f"Over {what} {hm(dur_h * 60)} walk each crew member gets about {dose:.3f} mGy ({sv * dur_h / 24:.3f} mSv) "
            f"from cosmic rays, at {where}. A solar storm would add to that.")
    return text + " " + answer_weather(ctx, short=True)


def answer_weather(ctx: AskContext, short: bool = False) -> str:
    if ctx.status is None:
        return "The space-weather check is not available."
    try:
        st = ctx.status()
    except Exception:  # noqa: BLE001
        return "The space-weather check did not answer."
    head = {"GO": "Clear to go outside", "CAUTION": "Go with caution", "NO-GO": "Stay inside"}.get(st["level"], st["level"])
    return f"Space weather now: {head}. {st['reason']}" if short else f"{head}. {st['reason']} (NASA DONKI)."


def answer_energy(ctx: AskContext, place: Place | None) -> str:
    b = _budgets(ctx)
    if not ctx.plan:
        return f"The usable effort budget is {b['energy_kj']:,.0f} kJ per crew member. Plan a walk to see how much it takes."
    s = ctx.plan["summary"]
    kj = float(s["energy_kj"])
    text = (f"This walk takes about {kj:,.0f} kJ per crew member (about {kj / KJ_PER_KCAL:,.0f} kcal): "
            f"{s['energy_budget_used_pct']}% of the usable effort budget of {b['energy_kj']:,.0f} kJ.")
    if place is not None and place.depart_min is not None and place.kind != "start":
        w = next((w for w in ctx.plan["timeline"] if w["id"] == place.id), None)
        if w:
            text += f" By the time you leave {place.id}, {w['energy_used_kj']:,.0f} kJ has been used."
    return text


def answer_time(ctx: AskContext, place: Place | None) -> str:
    b = _budgets(ctx)
    if not ctx.plan:
        return f"No walk is planned yet. With the reserve kept, the suits allow {hm(b['usable_min'])} outside."
    s = ctx.plan["summary"]
    dur, walk = float(s["duration_h"]) * 60, float(s["walking_h"]) * 60
    text = (f"The walk takes {hm(dur)}: {hm(walk)} walking and {hm(dur - walk)} at the stops, back at the rover "
            f"{hm(dur)} after leaving. The smallest spare time to still walk home is {hm(float(s['min_walkback_margin_min']))}.")
    if place is not None and place.kind != "start" and place.depart_min is not None:
        w = next((w for w in ctx.plan["timeline"] if w["id"] == place.id), None)
        home = w["walkback_min"] if w else 0.0
        text += " " + _time_left_sentence(ctx, place, home)
    return text


def answer_terrain(ctx: AskContext, place: Place) -> str:
    stack = ctx.terrain()
    if stack is None:
        return "The ground layers need the terrain data (run marswalk fetch)."
    r, c = stack.grid.latlon_to_rc(place.lat, place.lon)
    h, w = stack.shape
    if not (0 <= r < h and 0 <= c < w) or not np.isfinite(stack.elevation_m[r, c]):
        return f"{_cap(place.short)} is outside the terrain data."
    box = (slice(max(r - 12, 0), r + 13), slice(max(c - 12, 0), c + 13))
    with np.errstate(invalid="ignore"):
        slope = float(np.nanmean(stack.slope_5m_deg[box]))
        rough = float(np.nanmean(stack.roughness_m[box]))
        ti = float(np.nanmean(stack.ti[box])) if np.isfinite(stack.ti[box]).any() else math.nan
    coarse = stack.coarse is not None and bool(stack.coarse[r, c])
    walk = ("no trusted 1 m terrain here, so no route is planned through it" if coarse
            else "off limits (too steep or too rough)" if stack.nogo[r, c] else "walkable")
    ground = "" if not math.isfinite(ti) else (f" Firm ground (thermal inertia {ti:.0f})." if not stack.sand[r, c]
                                               else f" Likely loose sand (thermal inertia {ti:.0f}).")
    return (f"Around {place.label} the ground slopes about {slope:.0f}° (over 5 m) with {rough:.2f} m of roughness "
            f"(rocks and ledges); elevation {float(stack.elevation_m[r, c]):,.0f} m. {_cap(walk)}.{ground}").replace(" -", " −")


def answer_stops(ctx: AskContext, here: Place) -> str:
    if not ctx.plan:
        ids = _plan_stops(ctx)
        return f"No walk is planned yet. The ticked stops are {', '.join(ids)}." if ids else "No stops are chosen yet."
    tl = [w for w in ctx.plan["timeline"] if w["kind"] == "stop"]
    end = ctx.plan["timeline"][-1]
    parts = ", ".join(f"{w['id']} at {hm(w['arrive_min'])}" for w in tl)
    text = f"The plan visits {parts}, and is back at the rover at {hm(end['arrive_min'])}."
    t = here.depart_min
    if t is not None and here.kind != "start":
        nxt = next((w for w in tl if w["arrive_min"] > t), None)
        text += (f" From {here.short} the next stop is {nxt['id']}, at {hm(nxt['arrive_min'])}." if nxt
                 else f" After {here.short} the next stop is the rover.")
    return text


def answer_limits(ctx: AskContext) -> str:
    if not ctx.plan:
        return "No walk is planned yet, so there is nothing to check."
    v = ctx.plan.get("violations") or []
    s = ctx.plan["summary"]
    if not v:
        return (f"This walk stays inside every limit: {s['distance_km']} km, {hm(float(s['duration_h']) * 60)} outside, "
                f"{s['energy_budget_used_pct']}% of the effort budget, and never steeper than {s['max_grade_deg']}° underfoot.")
    hard = [x for x in v if x["severity"] == "no-go"]
    lead = "This walk breaks a hard limit" if hard else "This walk needs care"
    return lead + ": " + "; ".join(f"{x['where']}: {x['detail']}" if x["where"] else x["detail"] for x in v[:4]) + "."


UNTRACKED = {"water": "water", "drink": "water", "thirst": "water", "thirsty": "water", "food": "food", "eat": "food",
             "battery": "suit battery", "batteries": "suit battery", "temperature": "temperature", "cold": "temperature",
             "heat": "temperature", "hot": "temperature", "co2": "carbon dioxide", "carbon": "carbon dioxide",
             "pressure": "suit pressure", "cooling": "cooling water"}
HELP = ("You can ask: “How far is S3 from here?”, “Path to U1 from here”, “Go to S3”, “How long to walk home from S5?”, "
        "“How much oxygen does this walk use?”, “How much radiation?”, “How steep is S2?”, “When must we turn back?”, "
        "“Is it safe to go out?” Here means the stop you selected, else the time on the step 4 slider, else the rover. "
        "Go, or press Go, to make that place the next stop.")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# --- entry point ----------------------------------------------------------------------------------

def answer(question: str, ctx: AskContext) -> dict:
    q = normalize(question)
    here = resolve_here(ctx)
    topics = topics_of(q)
    mentions = find_mentions(q, ctx, here)
    named = [m for m in mentions if m.place is not None]
    origin_m = next((m for m in mentions if m.origin), None)
    origin = (origin_m.place or here) if origin_m else here
    targets = [m.place or here for m in mentions if m is not origin_m]
    start = next((m.place for m in named if m.place.kind == "start"), None)
    place = next((m.place for m in named if not m.origin and m.place.kind != "start"), None) or (
        origin if origin_m else None) or here

    # "How long ... S3" asks how long it takes to get there; "how long can we stay at S3" asks about the time budget.
    if "time" in topics and targets and not STAY_WORDS.search(q) and "walk_home" not in topics:
        topics = ["travel_time" if t == "time" else t for t in topics]
    route = bool(ROUTE_TOPICS & set(topics))
    if route and targets and all(t.kind == "start" for t in targets):
        topics, route = ["walk_home" if t in ROUTE_TOPICS else t for t in topics], False   # "how far is the rover"
    if "walk_home" in topics:          # the walk-home answer already covers the time left
        route = False
        topics = [t for t in topics if t not in ROUTE_TOPICS and t != "time"]
    if route and re.search(r"\b(" + "|".join(ORDINALS) + r"|next|previous) stop\b", q):
        topics = [t for t in topics if t != "stops"]      # "how far is the next stop" names a place, not the schedule
    topics = list(dict.fromkeys(topics))

    texts: list[str] = []
    feats: list[dict] = []
    done: set[str] = set()
    used: list[Place] = []          # the places the answer is about, to say whether "here" was used
    go_to: dict | None = None       # a stop the crew can make the next stop on the walk
    for t in topics:
        if t in done or len(texts) >= 3:
            continue
        done.add(t)
        if t in ROUTE_TOPICS:
            done |= ROUTE_TOPICS
            target = next((x for x in targets if x is not origin), None)
            if target is None:
                texts.append("Which place? Name a stop, for example “How far is S3 from here?”")
            else:
                before = len(feats)
                texts.append(answer_route(ctx, origin, target, feats))
                used += [origin, target]
                routed = any(f.get("properties", {}).get("role") == "route" for f in feats[before:])
                if routed and target.id and target.kind in ("stop", "user"):
                    go_to = {"id": target.id, "label": target.short}
                    texts[-1] += f" Press Go to head to {target.short}."
        elif t == "walk_home":
            frm = origin if origin_m else next((m.place for m in named if m.place.kind != "start"), None) or here
            texts.append(answer_walk_home(ctx, frm, feats))
            used.append(frm)
        elif t == "oxygen":
            texts.append(answer_oxygen(ctx, place if place.id else None))
            used.append(place)
        elif t == "radiation":
            texts.append(answer_radiation(ctx))
            done.add("weather")
        elif t == "weather":
            texts.append(answer_weather(ctx))
        elif t == "energy":
            texts.append(answer_energy(ctx, place if place.id else None))
            used.append(place)
        elif t == "terrain":
            texts.append(answer_terrain(ctx, place if place is not here or not start else start))
            used.append(place if place is not here or not start else start)
        elif t == "time":
            texts.append(answer_time(ctx, place))
            used.append(place)
        elif t == "stops":
            texts.append(answer_stops(ctx, here))
            used.append(here)
        elif t == "limits":
            texts.append(answer_limits(ctx))
        elif t == "untracked":
            words = sorted({UNTRACKED[w] for w in re.findall(r"[a-z0-9]+", q) if w in UNTRACKED})
            texts.append(f"MarsWalk does not track {' or '.join(words) or 'that'} yet. It knows distances, walking time, "
                         "oxygen time, effort, radiation, the ground and space weather.")
        elif t == "help":
            texts.append(HELP)
    if not texts:
        texts.append("I did not catch a question I can answer. " + HELP)
        topics = ["help"]
    text = " ".join(texts)
    return {"question": question, "answer": text, "speech": spoken(text), "topics": [t for t in topics if t in done] or topics,
            "here": {"label": here.label, "lat": round(here.lat, 7), "lon": round(here.lon, 7),
                     "used": any(p is not None and p.is_here for p in used)},
            "highlight": {"type": "FeatureCollection", "features": feats} if feats else None,
            "go_to": go_to}
