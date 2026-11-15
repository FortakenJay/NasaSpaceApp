"""The suit display: a navigation screen for a 7.5" e-ink panel (800 x 480, black and white).

It answers the questions a walker asks without stopping: where next, how far, how long the oxygen lasts, how
long the walk home takes, and when to turn back. Laid out like a car navigation screen:

    +--------------------------------------------------------------+
    | [arrow]  S3  140 m                               7 min        |   next stop, distance and time to it
    |          Monte Grande hollow, arrive at 1 h 36 min           |
    +-------------------------------------+------------------------+
    |                                     | Oxygen before reserve  |
    |   north-up map: route ahead (bold), | 3 h 30 min  [#####...] |
    |   route walked (thin), walk home    | Walk home   15 min     |
    |   (dashed), stops, you, off-limits  | Turn back by 5 h 21    |
    |   ground (hatched), scale, north    | To the rover 0.85 km   |
    |                                     | Radiation / weather    |
    +-------------------------------------+------------------------+
    | Mission time 1 h 12 min        Stop 2 of 5        Gale crater |
    +--------------------------------------------------------------+

Everything is drawn straight onto a 1-bit image (no anti-aliasing, so edges stay crisp on e-paper); only the relief
under the map is dithered. `to_bin` packs the image for an ESP32 (see firmware/suit_display): 1 bit per pixel,
rows top to bottom, most significant bit first, 1 = black.
"""
from __future__ import annotations

import datetime as dt
import itertools
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from marswalk.ask import hm, position_at
from marswalk.geo import ground_distance_m

W, H = 800, 480
BANNER_H = 112
FOOT_H = 34
MAP_W = 470
FONTS = Path(__file__).parent / "eink_fonts"
BLACK, WHITE = 0, 1


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _regular(size: int):
    return _font("Barlow-Regular.ttf", size)


def _bold(size: int):
    return _font("Barlow-SemiBold.ttf", size)


def _display(size: int):
    return _font("BarlowCondensed-SemiBold.ttf", size)


@dataclass
class Moment:
    """Everything the screen shows for one moment of the planned walk."""
    t_min: float                       # mission elapsed time (minutes since leaving the rover)
    lat: float
    lon: float
    where: str                         # "walking from S2 to S3", "working at S2", ...
    next_id: str                       # next stop id, or "H1"/the start id for the rover
    next_name: str
    next_lat: float
    next_lon: float
    next_arrive_min: float
    to_next_m: float                   # along the route
    at_stop: str | None                # id of the stop being worked at, if any
    work_left_min: float
    to_end_m: float                    # along the route, back to the rover
    end_min: float
    bearing_deg: float                 # heading of the route ahead, degrees from north
    stop_index: int                    # stops reached so far
    stop_count: int
    remaining_ids: list[str]
    usable_left_min: float             # oxygen time before the reserve
    reserve_min: float
    o2_total_min: float
    walk_home_min: float | None
    energy_pct: float
    dose_mgy: float
    walked_m: float | None = None                 # live mode: distance actually walked
    schedule_delta_min: float | None = None       # live mode: + behind the plan, - ahead of it


def _route_xy(plan: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Route vertices (lat, lon) and cumulative distance (m) along them, in the profile's distance units."""
    coords = [c for f in plan["route"]["features"] for c in f["geometry"]["coordinates"]]
    lon = np.array([c[0] for c in coords], dtype=float)
    lat = np.array([c[1] for c in coords], dtype=float)
    step = np.hypot(np.diff(lat), np.diff(lon) * np.cos(np.radians(lat[:-1])))
    cum = np.concatenate([[0.0], np.cumsum(step)])
    prof_total = (plan.get("profile") or {}).get("dist_m") or [None]
    total = float(prof_total[-1] or 0.0) or float(plan["summary"]["distance_km"]) * 1000
    return lat, lon, cum / max(cum[-1], 1e-12) * total


def _dist_at(plan: dict, t_min: float) -> float:
    prof = plan.get("profile") or {}
    pts = [(t, d) for t, d in zip(prof.get("t_min") or [], prof.get("dist_m") or []) if t is not None and d is not None]
    if len(pts) < 2:
        return 0.0
    return float(np.interp(t_min, [p[0] for p in pts], [p[1] for p in pts]))


def _energy_at(plan: dict, t_min: float) -> float:
    prof = plan.get("profile") or {}
    pts = [(t, e) for t, e in zip(prof.get("t_min") or [], prof.get("energy_kj") or []) if t is not None and e is not None]
    if len(pts) < 2:
        return 0.0
    return float(np.interp(t_min, [p[0] for p in pts], [p[1] for p in pts]))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1)))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def moment(plan: dict, site, eva, t_min: float, walk_home_min: float | None = None) -> Moment:
    """Where the plan puts the crew at t_min, and what is left."""
    from marswalk.route.plan import usable_budgets
    tl = plan["timeline"]
    end = tl[-1]["arrive_min"]
    t = min(max(t_min, 0.0), end)
    lat, lon, where = position_at(plan, t) or (tl[0]["lat"], tl[0]["lon"], "at the rover")
    stops = [w for w in tl if w["kind"] == "stop"]
    at = next((w for w in stops if w["arrive_min"] <= t <= w["depart_min"]), None)
    nxt = next((w for w in tl[1:] if w["arrive_min"] > t), tl[-1])
    d_now = _dist_at(plan, t)
    d_next = _dist_at(plan, nxt["arrive_min"])
    d_end = _dist_at(plan, end)
    # heading of the route about 30 m ahead (or straight at the next stop when standing still)
    rlat, rlon, rcum = _route_xy(plan)
    ahead = min(d_now + 30.0, d_end)
    alat, alon = float(np.interp(ahead, rcum, rlat)), float(np.interp(ahead, rcum, rlon))
    if ground_distance_m(lat, lon, alat, alon, site.body["radius_m"]) < 3:
        alat, alon = nxt["lat"], nxt["lon"]
    b = usable_budgets(eva)
    reserve_frac = float(eva.eva["walkback_reserve_frac"])
    o2_total = float(eva.suit.get("o2_capacity_h", eva.eva["max_duration_h"])) * 60
    e_used = _energy_at(plan, t)
    rate = float(site.spaceweather.get("rad_gcr_dose_mgy_per_day", 0.21))
    return Moment(
        t_min=t, lat=lat, lon=lon, where=where,
        next_id=nxt["id"], next_name="the rover" if nxt["kind"] == "end" else nxt["name"],
        next_lat=nxt["lat"], next_lon=nxt["lon"], next_arrive_min=nxt["arrive_min"],
        to_next_m=max(d_next - d_now, 0.0), at_stop=at["id"] if at else None,
        work_left_min=(at["depart_min"] - t) if at else 0.0,
        to_end_m=max(d_end - d_now, 0.0), end_min=end, bearing_deg=_bearing(lat, lon, alat, alon),
        stop_index=sum(1 for w in stops if w["arrive_min"] <= t), stop_count=len(stops),
        remaining_ids=[w["id"] for w in stops if w["arrive_min"] > t],
        usable_left_min=b["time_s"] / 60 - t, reserve_min=o2_total * reserve_frac, o2_total_min=o2_total,
        walk_home_min=walk_home_min,
        energy_pct=100.0 * e_used / b["energy_kj"] if b["energy_kj"] else 0.0,
        dose_mgy=rate * t / 1440.0)


def live_moment(plan: dict, site, eva, stack, back, lat: float, lon: float, t_min: float, walked_m: float,
                energy_kj: float, visited: list[str]) -> tuple[Moment, list[tuple[float, float]]]:
    """The screen for a walker at (lat, lon): the next planned stop not yet visited, the safest route there from
    here (A*), the rest of the plan after it, and how far ahead of or behind the plan they are.
    Returns the moment and the route ahead as (lat, lon) points."""
    from marswalk.cost.base import model_from_eva
    from marswalk.route.astar import astar, snap
    from marswalk.route.plan import usable_budgets
    tl = plan["timeline"]
    R = float(site.body["radius_m"])
    margin = float(eva.eva.get("time_margin_factor", 1.0))
    by_id = {w["id"]: w for w in tl if w["kind"] == "stop"}
    order = [w["id"] for w in tl if w["kind"] == "stop"]
    remaining = [i for i in order if i not in set(visited)]
    end = tl[-1]
    nxt = by_id[remaining[0]] if remaining else end
    legs = {(f["properties"]["from"], f["properties"]["to"]): f for f in plan["route"]["features"]}
    planned = {(a["id"], b["id"]): (b["arrive_min"] - a["depart_min"]) for a, b in itertools.pairwise(tl)}

    # here -> next: the safest route from where the walker actually is
    ahead: list[tuple[float, float]] = [(lat, lon)]
    a = snap(stack, stack.grid.latlon_to_rc(lat, lon), 25.0) if stack is not None else None
    b = snap(stack, stack.grid.latlon_to_rc(nxt["lat"], nxt["lon"]), 25.0) if stack is not None else None
    path = astar(stack, model_from_eva(eva, plan["summary"].get("cost_model")), a, b) if a and b and a != b else None
    if path is not None:
        la, lo = stack.grid.rc_to_latlon_many([c[0] for c in path.cells], [c[1] for c in path.cells])
        ahead += list(zip(map(float, la), map(float, lo)))
        to_next, t_next = path.distance_m, path.time_s * margin / 60.0
    else:
        to_next = ground_distance_m(lat, lon, nxt["lat"], nxt["lon"], R)
        t_next = to_next / 1.0 * margin / 60.0 if to_next > 1 else 0.0
    # next -> the remaining stops -> the rover, as planned where the plan has that leg
    seq = [nxt["id"]] + remaining[1:] + ([end["id"]] if remaining else [])
    rest_m, rest_min = 0.0, 0.0
    for i, (u, v) in enumerate(itertools.pairwise(seq)):
        f = legs.get((u, v))
        ua = by_id.get(u, end)
        vb = by_id.get(v, end) if i < len(seq) - 2 else end
        if f is not None:
            rest_m += float(f["properties"]["distance_m"])
            rest_min += planned.get((u, v), float(f["properties"]["distance_m"]) / 60.0)
            ahead += [(c[1], c[0]) for c in f["geometry"]["coordinates"]]
        else:                                   # stops visited out of plan order: straight line, a little longer
            d = ground_distance_m(ua["lat"], ua["lon"], vb["lat"], vb["lon"], R) * 1.15
            rest_m += d
            rest_min += d / 1.0 * margin / 60.0
            ahead += [(vb["lat"], vb["lon"])]
    work = sum(by_id[i]["depart_min"] - by_id[i]["arrive_min"] for i in remaining)
    arrive_next = t_min + t_next
    end_min = arrive_next + rest_min + work
    # heading: 30 m along the route ahead
    walked = 0.0
    alat, alon = nxt["lat"], nxt["lon"]
    for (p_lat, p_lon), (q_lat, q_lon) in itertools.pairwise(ahead):
        walked += ground_distance_m(p_lat, p_lon, q_lat, q_lon, R)
        if walked >= 30.0:
            alat, alon = q_lat, q_lon
            break
    b_ = usable_budgets(eva)
    o2_total = float(eva.suit.get("o2_capacity_h", eva.eva["max_duration_h"])) * 60
    rate = float(site.spaceweather.get("rad_gcr_dose_mgy_per_day", 0.21))
    at = nxt["id"] if remaining and to_next < 10.0 else None
    wh = None
    if back is not None and a is not None and back.reached(a):
        wh = float(back.time_s[a]) * margin / 60.0
    m = Moment(
        t_min=t_min, lat=lat, lon=lon, where="live",
        next_id=nxt["id"] if remaining else end["id"], next_name=nxt["name"] if remaining else "the rover",
        next_lat=nxt["lat"], next_lon=nxt["lon"], next_arrive_min=arrive_next, to_next_m=to_next,
        at_stop=at, work_left_min=(nxt["depart_min"] - nxt["arrive_min"]) if at else 0.0,
        to_end_m=to_next + rest_m, end_min=end_min, bearing_deg=_bearing(lat, lon, alat, alon),
        stop_index=len([v for v in visited if v in by_id]), stop_count=len(order), remaining_ids=remaining,
        usable_left_min=b_["time_s"] / 60 - t_min, reserve_min=o2_total * float(eva.eva["walkback_reserve_frac"]),
        o2_total_min=o2_total, walk_home_min=wh,
        energy_pct=100.0 * energy_kj / b_["energy_kj"] if b_["energy_kj"] else 0.0, dose_mgy=rate * t_min / 1440.0,
        walked_m=walked_m, schedule_delta_min=(arrive_next - nxt["arrive_min"]) if remaining else (end_min - end["arrive_min"]))
    return m, ahead


# --- drawing --------------------------------------------------------------------------------------

def _arrow(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, bearing: float, fill: int) -> None:
    """A navigation arrow pointing along `bearing` (0 = up/north, clockwise)."""
    pts = [(0, -1.0), (0.62, 0.55), (0.0, 0.22), (-0.62, 0.55)]
    a = math.radians(bearing)
    d.polygon([(cx + size * (x * math.cos(a) - y * math.sin(a)), cy + size * (x * math.sin(a) + y * math.cos(a)))
               for x, y in pts], fill=fill)


def _compass(bearing: float) -> str:
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int((bearing + 22.5) // 45) % 8]


def _dist(m: float) -> str:
    return f"{m / 1000:.2f} km" if m >= 1000 else f"{max(round(m, -1), 10):.0f} m"


def _thin(pts: list, min_px: float = 2.0) -> list:
    """Drop polyline points closer than min_px to the last kept one (1 m route points are sub-pixel when zoomed out)."""
    out = pts[:1]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_px:
            out.append(p)
    if len(pts) > 1 and out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _text(d, xy, s, font, fill=BLACK, anchor="la", halo: int = 0):
    if halo:
        d.text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=halo, stroke_fill=1 - fill)
    else:
        d.text(xy, s, font=font, fill=fill, anchor=anchor)


def _dither_relief(z: np.ndarray, px_m: float) -> Image.Image:
    """Faint dithered hillshade for the map background (light, so the route stays the strongest thing)."""
    from matplotlib.colors import LightSource
    fill = np.where(np.isfinite(z), z, np.nanmean(z) if np.isfinite(z).any() else 0.0)
    hs = LightSource(315, 40).hillshade(fill, vert_exag=2.5, dx=px_m, dy=px_m)
    gray = (212 + 43 * np.clip(hs, 0, 1)).astype(np.uint8)        # 212..255: a light texture
    gray[~np.isfinite(z)] = 255
    return Image.fromarray(gray, "L").convert("1")                # Floyd-Steinberg


def _map(img: Image.Image, plan: dict, m: Moment, stack, back_cells, box: tuple[int, int, int, int], site,
         ahead: list[tuple[float, float]] | None = None) -> None:
    """Draw the map into its own image (so nothing spills over the panels), then paste it into the box."""
    bx0, by0, bx1, by1 = box
    canvas = Image.new("1", (bx1 - bx0, by1 - by0), WHITE)
    _map_canvas(canvas, plan, m, stack, back_cells, site, ahead)
    img.paste(canvas, (bx0, by0))
    ImageDraw.Draw(img).rectangle(box, outline=BLACK, width=2)


def _map_canvas(img: Image.Image, plan: dict, m: Moment, stack, back_cells, site,
                ahead: list[tuple[float, float]] | None = None) -> None:
    x0, y0 = 0, 0
    w, h = img.size
    x1, y1 = w, h
    box = (0, 0, w, h)
    R = float(site.body["radius_m"])
    m_per_deg = 2 * math.pi * R / 360
    coslat = math.cos(math.radians(m.lat))
    # scale: fit you, the next stop and 60 m around them; snap to a tidy value
    need = max(abs(m.next_lat - m.lat) * m_per_deg, abs(m.next_lon - m.lon) * m_per_deg * coslat, 60.0) * 2 + 120
    scale = next((s for s in (0.5, 1, 1.5, 2, 3, 4, 6, 8, 12) if s * min(w, h) >= need), 16.0)   # metres per pixel
    cx, cy = (m.lon + m.next_lon) / 2, (m.lat + m.next_lat) / 2

    def xy(lat, lon):
        return (x0 + w / 2 + (lon - cx) * m_per_deg * coslat / scale, y0 + h / 2 - (lat - cy) * m_per_deg / scale)

    d = ImageDraw.Draw(img)
    if stack is not None:
        jj, ii = np.meshgrid(np.arange(w), np.arange(h))
        lats = cy - (ii - h / 2) * scale / m_per_deg
        lons = cx + (jj - w / 2) * scale / (m_per_deg * coslat)
        rows, cols = stack.grid.latlon_to_rc_many(lats.ravel(), lons.ravel())
        rows, cols = rows.reshape(h, w), cols.reshape(h, w)
        inside = (rows >= 0) & (rows < stack.shape[0]) & (cols >= 0) & (cols < stack.shape[1])
        rr, cc = np.clip(rows, 0, stack.shape[0] - 1), np.clip(cols, 0, stack.shape[1] - 1)
        z = np.where(inside, stack.elevation_m[rr, cc], np.nan).astype(np.float32)
        img.paste(_dither_relief(z, scale), (x0, y0))
        nogo = inside & stack.nogo[rr, cc]
        hatch = ((ii + jj) % 7 == 0) | ((ii - jj) % 7 == 0)               # cross-hatching: off-limits ground
        arr = np.array(img.crop(box), dtype=bool)
        arr[nogo & hatch] = False
        arr[nogo & ~hatch] = True                                         # off-limits: hatched on white, no relief
        img.paste(Image.fromarray(arr), (x0, y0))
        d = ImageDraw.Draw(img)

    # route: walked part thin, the rest bold with a white casing
    rlat, rlon, rcum = _route_xy(plan)
    d_now = _dist_at(plan, m.t_min)
    pts = [xy(a, b) for a, b in zip(rlat, rlon)]
    if ahead is None:
        done = _thin([p for p, c in zip(pts, rcum) if c <= d_now] + [xy(m.lat, m.lon)])
        todo = _thin([xy(m.lat, m.lon)] + [p for p, c in zip(pts, rcum) if c > d_now])
    else:                                          # live: the whole plan thin, the route from here bold
        done = _thin(pts)
        todo = _thin([xy(a, b) for a, b in ahead])
    if len(done) > 1:
        d.line(done, fill=BLACK, width=2)
    if back_cells is not None and len(back_cells) > 1:
        bl, bo = stack.grid.rc_to_latlon_many([c[0] for c in back_cells], [c[1] for c in back_cells])
        bp = _thin([xy(a, b) for a, b in zip(bl, bo)], 3.0)
        for i in range(0, len(bp) - 1, 2):                               # dashed: the walk home
            d.line(bp[i:i + 2], fill=BLACK, width=2)
    if len(todo) > 1:
        d.line(todo, fill=WHITE, width=11, joint="curve")
        d.line(todo, fill=BLACK, width=6, joint="curve")
    # stops and the rover
    f = _bold(15)
    start = plan["timeline"][0]
    for wpt in plan["timeline"]:
        if wpt["kind"] == "end":
            continue
        px, py = xy(wpt["lat"], wpt["lon"])
        if not (x0 - 20 < px < x1 + 20 and y0 - 20 < py < y1 + 20):
            continue
        if wpt["kind"] == "start":
            d.rectangle([px - 8, py - 8, px + 8, py + 8], fill=BLACK, outline=WHITE, width=2)
        else:
            nxt = wpt["id"] == m.next_id
            d.ellipse([px - 8, py - 8, px + 8, py + 8], fill=BLACK if nxt else WHITE, outline=BLACK, width=3)
        _text(d, (px + 12, py - 9), "Rover" if wpt["id"] == start["id"] else wpt["id"], f, halo=2)
    # you: an arrow on the move; a double ring around the stop while working there
    px, py = xy(m.lat, m.lon)
    if m.at_stop or m.t_min <= 0:
        d.ellipse([px - 17, py - 17, px + 17, py + 17], outline=BLACK, width=3)
        d.ellipse([px - 13, py - 13, px + 13, py + 13], outline=WHITE, width=2)
    else:
        d.ellipse([px - 15, py - 15, px + 15, py + 15], fill=WHITE)
        _arrow(d, px, py, 13, m.bearing_deg, BLACK)
    # north arrow, scale bar
    _arrow(d, x0 + 22, y0 + 26, 11, 0, BLACK)
    _text(d, (x0 + 22, y0 + 42), "N", _bold(14), anchor="mt", halo=2)
    bar_m = next(v for v in (10, 20, 50, 100, 200, 500, 1000, 2000) if v / scale >= 60)
    bx, by = x0 + 14, y1 - 16
    d.rectangle([bx - 4, by - 24, bx + bar_m / scale + 8, by + 6], fill=WHITE)
    d.line([(bx, by), (bx + bar_m / scale, by)], fill=BLACK, width=3)
    d.line([(bx, by - 5), (bx, by + 3)], fill=BLACK, width=2)
    d.line([(bx + bar_m / scale, by - 5), (bx + bar_m / scale, by + 3)], fill=BLACK, width=2)
    _text(d, (bx, by - 8), _dist(bar_m), _regular(14), anchor="lb")


def _clock(site, eva, t_min: float, start_utc: dt.datetime | None) -> tuple[int, float]:
    """(sol, local true solar time in hours) at the rover, t_min into a walk that starts at start_utc (default: the
    next eva.start_lmst_h, as the simulator assumes)."""
    from marswalk import sun
    lon = float(site.start.lon)
    start = start_utc or sun.next_lmst(dt.datetime.now(dt.UTC), lon, float(eva.eva.get("start_lmst_h", 9.0)))
    t = start + dt.timedelta(minutes=t_min)
    return sun.local_sol(t, lon), sun.local_times(t, lon)[1]


def _hhmm(h: float) -> str:
    m = int(round((h % 24.0) * 60)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def render(plan: dict, site, eva, t_min: float, stack=None, walkback=None, weather: dict | None = None,
           live: dict | None = None, start_utc: dt.datetime | None = None) -> Image.Image:
    """The suit display at t_min minutes into the planned walk, as a 1-bit 800 x 480 image.

    With `live` = {lat, lon, walked_m, energy_kj, visited}, the screen follows a walker's actual position (the
    simulator, or a real position source) instead of where the plan says they would be at t_min."""
    from marswalk import consumables
    back_cells, walk_home, ahead = None, None, None
    tl = plan["timeline"]
    margin = float(eva.eva.get("time_margin_factor", 1.0))
    if live is not None:
        back = None
        if stack is not None and walkback is not None:
            try:
                back = walkback(stack)
            except Exception:  # noqa: BLE001
                back = None
        m, ahead = live_moment(plan, site, eva, stack, back, float(live["lat"]), float(live["lon"]), t_min,
                               float(live.get("walked_m", 0.0)), float(live.get("energy_kj", 0.0)), list(live.get("visited", [])))
        if back is not None and stack is not None:
            from marswalk.route.astar import snap
            rc = snap(stack, stack.grid.latlon_to_rc(m.lat, m.lon), 25.0)
            if rc is not None and back.reached(rc):
                back_cells = back.trace(rc)
    elif stack is not None and walkback is not None:
        from marswalk.route.astar import snap
        lat, lon, _ = position_at(plan, min(max(t_min, 0), tl[-1]["arrive_min"])) or (tl[0]["lat"], tl[0]["lon"], "")
        rc = snap(stack, stack.grid.latlon_to_rc(lat, lon), 25.0)
        try:
            back = walkback(stack)
        except Exception:  # noqa: BLE001 - the screen still works without the walk-home field
            back = None
        if back is not None and rc is not None and back.reached(rc):
            walk_home = float(back.time_s[rc]) * margin / 60
            back_cells = back.trace(rc)
    if live is None:
        m = moment(plan, site, eva, t_min, walk_home)

    img = Image.new("1", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # --- banner: the next thing to do
    d.rectangle([0, 0, W, BANNER_H], fill=BLACK)
    if live is None and m.t_min >= m.end_min - 0.01 or (live is not None and not m.remaining_ids and m.to_next_m < 10):
        title, sub, right = "Back at the rover", f"Walk finished after {hm(m.end_min)}", ""
        d.rectangle([34, 28, 90, 84], outline=WHITE, width=5)
    elif m.at_stop:
        title = f"At {m.at_stop}"
        sub = f"Work time left {hm(m.work_left_min)}, then {_dist(m.to_next_m)} to {m.next_id if m.next_name != 'the rover' else 'the rover'}"
        right = hm(m.work_left_min)
        d.ellipse([30, 24, 94, 88], outline=WHITE, width=5)
        d.ellipse([52, 46, 72, 66], fill=WHITE)
    else:
        target = "Rover" if m.next_name == "the rover" else m.next_id
        title = f"{target}   {_dist(m.to_next_m)}"
        name = "back to the rover" if m.next_name == "the rover" else m.next_name
        sub = f"Head {_compass(m.bearing_deg)} · {name}"
        right = hm(m.next_arrive_min - m.t_min)
        _arrow(d, 62, 58, 40, m.bearing_deg, WHITE)
    _text(d, (122, 14), title, _display(58), fill=WHITE)
    _text(d, (124, 84), _fit(d, sub, _regular(22), W - 124 - (150 if right else 20)), _regular(22), fill=WHITE)
    if right:
        _text(d, (W - 22, 30), right, _display(44), fill=WHITE, anchor="ra")
        _text(d, (W - 22, 84), "to go" if not m.at_stop else "left here", _regular(18), fill=WHITE, anchor="ra")

    # --- map
    _map(img, plan, m, stack, back_cells, (10, BANNER_H + 10, MAP_W, H - FOOT_H - 8), site, ahead)
    d = ImageDraw.Draw(img)

    # --- readouts: the consumable that runs out first (oxygen unless the config tracks something tighter)
    x, y = MAP_W + 22, BANNER_H + 12
    rw = W - x - 16
    summ = plan.get("summary") or {}
    mean_kw = float(summ.get("energy_kj", 0)) / max(float(summ.get("duration_h", 0)) * 3600.0, 1.0)
    e_now = float(live.get("energy_kj", 0.0)) if live is not None else _energy_at(plan, m.t_min)
    first = consumables.time_left(eva, m.t_min * 60.0, e_now, mean_kw)[0]
    _text(d, (x, y), f"{first['label']} before reserve", _regular(18))
    left = max(m.usable_left_min if first["name"] == "oxygen" else first["minutes_left"], 0)
    _text(d, (x, y + 20), hm(left), _display(44))
    gy = y + 72
    used_w = rw * min(m.t_min / m.o2_total_min, 1)
    res_w = rw * m.reserve_min / m.o2_total_min
    d.rectangle([x, gy, x + rw, gy + 14], outline=BLACK, width=2)
    d.rectangle([x, gy, x + used_w, gy + 14], fill=BLACK)
    for hx in range(int(x + rw - res_w), int(x + rw), 5):                # the reserve, hatched: never planned into
        d.line([(hx, gy + 14), (min(hx + 7, x + rw), gy)], fill=BLACK, width=1)
    d.line([(x + rw - res_w, gy - 4), (x + rw - res_w, gy + 18)], fill=BLACK, width=2)
    _text(d, (x, gy + 20), f"{m.o2_total_min / 60:g} h tank, {hm(m.reserve_min)} kept for the walk home", _regular(15))

    y = gy + 44
    d.line([(x, y), (x + rw, y)], fill=BLACK, width=1)
    y += 6
    if m.walk_home_min is not None:
        turn = left - m.walk_home_min
        tight = turn < 30
        if tight:
            d.rectangle([x - 6, y - 2, x + rw + 4, y + 70], fill=BLACK)
        fg = WHITE if tight else BLACK
        _text(d, (x, y), "Walk home", _regular(17), fill=fg)
        _text(d, (x, y + 18), hm(m.walk_home_min), _display(38), fill=fg)
        _text(d, (x + rw, y), "Turn back within" if turn >= 0 else "Turn back now", _regular(17), fill=fg, anchor="ra")
        _text(d, (x + rw, y + 18), hm(max(turn, 0)) if turn >= 0 else "late", _display(38), fill=fg, anchor="ra")
        y += 72
        d.line([(x, y), (x + rw, y)], fill=BLACK, width=1)
        y += 6
    via = ("To the rover via " + ", ".join(m.remaining_ids)) if m.remaining_ids else "To the rover"
    _text(d, (x, y), _fit(d, via, _regular(17), rw), _regular(17))
    _text(d, (x, y + 18), f"{_dist(m.to_end_m)}", _display(38))
    _text(d, (x + rw, y + 18), hm(m.end_min - m.t_min), _display(38), anchor="ra")
    y += 70
    d.line([(x, y), (x + rw, y)], fill=BLACK, width=1)
    lvl = (weather or {}).get("level")
    sw = {"GO": "Sun quiet", "CAUTION": "Sun: caution", "NO-GO": "Sun: go inside"}.get(lvl or "", "Sun: no data")
    _text(d, (x, y + 7), f"Dose {m.dose_mgy:.3f} mGy", _regular(15))
    _text(d, (x + rw / 2 + 8, y + 7), f"Effort {m.energy_pct:.0f}%", _regular(15), anchor="ma")
    _text(d, (x + rw, y + 7), sw, _bold(15), anchor="ra")

    # --- footer
    d.rectangle([0, H - FOOT_H, W, H], fill=BLACK)
    _text(d, (16, H - FOOT_H / 2), f"Mission time {hm(m.t_min)}", _bold(17), fill=WHITE, anchor="lm")
    centre = f"Stop {m.stop_index} of {m.stop_count}"
    if m.schedule_delta_min is not None and abs(m.schedule_delta_min) >= 1:
        centre += f"   {hm(abs(m.schedule_delta_min))} {'behind' if m.schedule_delta_min > 0 else 'ahead of'} plan"
    elif m.schedule_delta_min is not None:
        centre += "   on plan"
    _text(d, (W / 2, H - FOOT_H / 2), centre, _regular(17), fill=WHITE, anchor="mm")
    sol, ltst = _clock(site, eva, m.t_min, start_utc)
    right = (f"{_hhmm(ltst)} local · walked {_dist(m.walked_m)}" if m.walked_m is not None
             else f"Sol {sol} · {_hhmm(ltst)} local")
    _text(d, (W - 16, H - FOOT_H / 2), right, _regular(17), fill=WHITE, anchor="rm")
    return img


def _fit(d: ImageDraw.ImageDraw, s: str, font, width: float) -> str:
    """Shorten s with an ellipsis until it fits in width pixels."""
    if d.textlength(s, font=font) <= width:
        return s
    while s and d.textlength(s + "…", font=font) > width:
        s = s[:-1]
    return s.rstrip() + "…"


def to_bin(img: Image.Image) -> bytes:
    """Pack for an e-paper driver: 1 bit per pixel, row-major, MSB first, 1 = black (GxEPD2 drawBitmap)."""
    a = np.array(img.convert("1"), dtype=bool)          # True = white
    return np.packbits(~a, axis=1).tobytes()


def to_png(img: Image.Image) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
