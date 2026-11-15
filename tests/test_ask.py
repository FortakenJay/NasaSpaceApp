"""Ask MarsWalk: the question parser (on the real Gale stop names) and answers through the API (synthetic terrain)."""
import pytest
from fastapi.testclient import TestClient

from marswalk.api.app import create_app
from marswalk.ask import (
    AskContext,
    answer,
    find_mentions,
    normalize,
    resolve_here,
    spoken,
    topics_of,
)
from marswalk.config import load_eva, load_site

SITE = load_site("configs/sites/gale_boxwork.toml")
EVA = load_eva("configs/eva/artemis_default.toml")
STOPS = [{"id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon, "kind": s.kind, "science": s.science,
          "work_time_min": s.work_time_min, "dtm_z_m": s.dtm_z_m} for s in (SITE.start, *SITE.stops)]
STATUS = {"level": "GO", "reason": "No CME arrival predicted at Mars and no particle events in the last 7 days."}


def ctx(**kw) -> AskContext:
    return AskContext(site=SITE, eva=EVA, stops=STOPS, status=lambda: STATUS, **kw)


def ids(q: str, c: AskContext | None = None):
    c = c or ctx()
    return [(m.place.id if m.place else "here", m.origin) for m in find_mentions(normalize(q), c, resolve_here(c))]


@pytest.mark.parametrize("q", ["How far is S3 from here?", "how far is s 3 from here", "how far is s three from here",
                               "how far is stop three from here", "How far is S-3 from here", "how far is Monte Grande from here"])
def test_speech_spellings_of_a_stop(q):
    assert ids(q) == [("S3", False), ("here", True)]
    assert "distance" in topics_of(normalize(q))


def test_origins_ordinals_rover_and_soundalikes():
    assert ids("distance between S1 and S5") == [("S1", True), ("S5", False)]
    assert ids("how long to walk home from s for") == [("H1", False), ("S4", True)]
    assert ids("how far is the last stop from the rover") == [("S5", False), ("H1", True)]
    assert ids("how steep is the upper contact") == [("S5", False)]
    assert ids("is this far") == []                                 # "this" alone is not a place; "is" is not "S"
    assert ids("how far is the next stop", ctx(selected_stop_id="S2")) == [("S3", False)]
    assert ids("provide the path to S3 from my location") == [("S3", False), ("here", True)]
    assert "distance" in topics_of(normalize("provide the path to U1 from my location"))
    assert topics_of(normalize("go to S3")) == ["go"]


def test_topics():
    t = lambda q: topics_of(normalize(q))
    assert t("How much oxygen do we have left?") == ["oxygen"]
    assert t("how much exposure") == ["radiation"]
    assert set(t("how much radiation and energy")) == {"radiation", "energy"}
    assert "walk_home" in t("when must we turn back")
    assert t("is it safe to go out") == ["weather", "limits"]
    assert t("how much water") == ["untracked"]


def test_here_is_selected_stop_then_slider_position_then_rover():
    assert resolve_here(ctx()).label == "the rover"
    assert resolve_here(ctx(selected_stop_id="S2")).label.startswith("S2 (First boxwork ridge stop)")
    plan = {"timeline": [
        {"id": "H1", "kind": "start", "lat": 0.0, "lon": 0.0, "arrive_min": 0.0, "depart_min": 0.0},
        {"id": "S1", "kind": "stop", "lat": 0.0, "lon": 0.01, "arrive_min": 10.0, "depart_min": 40.0},
        {"id": "H1", "kind": "end", "lat": 0.0, "lon": 0.0, "arrive_min": 50.0, "depart_min": 50.0}]}
    here = resolve_here(ctx(plan=plan, elapsed_h=0.5))
    assert "working at S1" in here.label and here.lon == pytest.approx(0.01)
    here = resolve_here(ctx(plan=plan, elapsed_h=45 / 60))
    assert "walking from S1 to the rover" in here.label and 0 < here.lon < 0.01


def test_answers_without_plan_or_terrain():
    c = ctx()
    a = answer("how much oxygen", c)
    assert "8 h of oxygen" in a["answer"] and "5 h 36 min" in a["answer"] and "Plan a walk" in a["answer"]
    r = answer("how much radiation exposure", c)["answer"]
    assert "0.070 mGy" in r and "0.213 mSv" in r and "Clear to go outside" in r         # full 8 h at 0.21 / 0.64 per day
    d = answer("how far is S3 from S1", c)
    assert "in a straight line" in d["answer"] and "marswalk fetch" in d["answer"] and d["highlight"] is None
    assert "does not track water" in answer("how much water is left", c)["answer"]
    assert "You can ask" in answer("blah", c)["answer"]


def test_spoken_spells_out_units():
    s = spoken("About 3 h 05 min, 1.72 km, 450 m, 12°, 0.031 mGy (0.098 mSv), 2,950 kJ, 0.20 kg, 35%.")
    assert s == ("About 3 hours 5 minutes, 1.72 kilometres, 450 metres, 12 degrees, 0.031 milligray "
                 "(0.098 millisieverts), 2,950 kilojoules, 0.20 kilograms, 35 percent.")


def test_ask_api_on_synthetic_terrain(synthetic_site, monkeypatch):
    c = TestClient(create_app(site_path=str(synthetic_site), db_url="sqlite://"))
    site = c.get("/api/site").json()
    b = next(s for s in site["stops"] if s["id"] == "B")
    u = c.post("/api/stops", json={"lat": b["lat"], "lon": b["lon"], "name": "Gully"}).json()
    plan = c.post("/api/plan", json={"cost": "metabolic", "order": "fixed", "stop_ids": ["A", "B", u["id"]]}).json()

    r = c.post("/api/ask", json={"question": "How far is U1 from here?", "plan_id": plan["plan_id"]}).json()
    assert r["here"]["label"] == "the rover" and r["here"]["used"] and "On foot, the safest route is" in r["answer"]
    assert [f["properties"]["role"] for f in r["highlight"]["features"]] == ["route", "back", "here", "to"]
    assert r["go_to"]["id"] == "U1" and "Press Go to head to U1." in r["answer"]
    commanded = c.post("/api/ask", json={"question": "provide the path to U1 from my location",
                                         "plan_id": plan["plan_id"]}).json()
    assert "On foot, the safest route is" in commanded["answer"] and commanded["go_to"]["id"] == u["id"]
    assert commanded["here"]["used"]
    line = next(f for f in r["highlight"]["features"] if f["geometry"]["type"] == "LineString")
    assert len(line["geometry"]["coordinates"]) > 50 and "kilometres" not in r["answer"] and "metres" in r["speech"]

    r = c.post("/api/ask", json={"question": "how long to walk home from the north stop", "plan_id": plan["plan_id"]}).json()
    assert r["topics"] == ["walk_home"] and r["answer"].startswith("From A (North stop) the walk back to the rover is")
    assert "must start back within" in r["answer"] and not r["here"]["used"]
    assert [f["properties"]["role"] for f in r["highlight"]["features"]] == ["home", "from"]

    r = c.post("/api/ask", json={"question": "how much oxygen and energy", "plan_id": plan["plan_id"],
                                 "selected_stop_id": "A"}).json()
    assert set(r["topics"]) == {"oxygen", "energy"} and "kg of oxygen" in r["answer"] and "kcal" in r["answer"]
    assert "left when you leave" in r["answer"]

    r = c.post("/api/ask", json={"question": "how steep is it here", "selected_stop_id": "B"}).json()
    assert "slopes about" in r["answer"] and "Walkable" in r["answer"]
    r = c.post("/api/ask", json={"question": "is the plan safe", "plan_id": plan["plan_id"]}).json()
    # the wall hides B from the rover's antenna: the only caution on this site
    assert r["answer"].startswith("This walk needs care: ") and "out of radio contact" in r["answer"]
    assert ": :" not in r["answer"]
    r = c.post("/api/ask", json={"question": "where do we go", "plan_id": plan["plan_id"], "elapsed_h": 0.3}).json()
    assert "The plan visits A at" in r["answer"] and "into the walk" in r["here"]["label"]
    assert c.post("/api/ask", json={"question": ""}).status_code == 422


def test_suit_display_png_and_packed_bits(synthetic_site):
    import io

    import numpy as np
    from PIL import Image
    c = TestClient(create_app(site_path=str(synthetic_site), db_url="sqlite://"))
    assert c.get("/api/eink.png").status_code == 404                      # nothing planned yet
    plan = c.post("/api/plan", json={"cost": "metabolic", "order": "fixed"}).json()
    end_h = plan["timeline"][-1]["arrive_min"] / 60
    for h in (0.0, plan["timeline"][1]["arrive_min"] / 60 + 0.01, end_h / 2, end_h + 1):
        r = c.get("/api/eink.png", params={"elapsed_h": h, "plan_id": plan["plan_id"]})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        img = Image.open(io.BytesIO(r.content))
        assert img.size == (800, 480) and img.mode == "1"
    b = c.get("/api/eink.bin", params={"elapsed_h": end_h / 2})               # latest plan when no id is given
    assert b.status_code == 200 and len(b.content) == 800 * 480 // 8 and b.headers["x-width"] == "800"
    bits = np.unpackbits(np.frombuffer(b.content, dtype=np.uint8)).reshape(480, 800)
    assert bits[0, :].all() and 0.15 < bits.mean() < 0.6                   # black banner on top; mostly white below


def test_suit_display_moment_arithmetic(synthetic_site):
    from marswalk import eink
    from marswalk.export.payload import plan_payload
    from marswalk.layers.stack import build_stack
    from marswalk.route.plan import build_plan
    site = load_site(synthetic_site)
    st = build_stack(site, EVA, use_cache=False)
    p = plan_payload(build_plan(site, EVA, st, "metabolic"), st)
    tl = p["timeline"]
    a = tl[1]
    m = eink.moment(p, site, EVA, (a["arrive_min"] + a["depart_min"]) / 2)       # working at the first stop
    assert m.at_stop == a["id"] and m.next_id == tl[2]["id"] and m.stop_index == 1
    assert m.usable_left_min == pytest.approx(336 - m.t_min)
    assert m.to_end_m == pytest.approx(p["profile"]["dist_m"][-1] - eink._dist_at(p, m.t_min))
    start = eink.moment(p, site, EVA, 0.0)
    assert start.to_end_m == pytest.approx(p["profile"]["dist_m"][-1], rel=1e-6) and start.next_id == a["id"]
    done = eink.moment(p, site, EVA, 10_000)
    assert done.to_end_m == pytest.approx(0, abs=1e-6) and done.remaining_ids == []


def test_simulator_terrain_texture_live_eink_and_live_ask(synthetic_site):
    import gzip
    import io

    import numpy as np
    from PIL import Image
    c = TestClient(create_app(site_path=str(synthetic_site), db_url="sqlite://"))
    t = c.get("/api/sim/terrain", params={"step": 2}).json()
    # binary URLs carry the layout version and the data stamp, so a browser never decodes a stale copy
    assert "heights_cm" not in t and t["heights"]["url"].startswith("/api/sim/terrain.bin?step=2&v=2-")
    assert t["fine"]["url"].startswith("/api/sim/fine.bin?v=2-")
    hb = c.get(t["heights"]["url"]).content
    hb = gzip.decompress(hb) if hb[:2] == b"\x1f\x8b" else hb
    n3 = t["rows"] * t["cols"]
    assert len(hb) == 2 * n3 + (n3 + 7) // 8
    h = np.frombuffer(hb[: 2 * n3], dtype="<u2").reshape(t["rows"], t["cols"])
    nogo = np.unpackbits(np.frombuffer(hb[2 * n3:], dtype=np.uint8))[:n3]
    assert h.shape == (t["rows"], t["cols"]) and nogo.size == h.size and t["physics"]["gravity_mps2"] == pytest.approx(3.71)
    assert h.min() == 0 and nogo.any()
    site = c.get("/api/site").json()
    start = next(s for s in site["stops"] if s["kind"] == "start")
    b = next(s for s in site["stops"] if s["id"] == "B")
    # the frame: the rover is the origin, B is where its lat/lon says (x east, z south)
    bx, bz = (b["lon"] - t["lon0"]) * t["kx"], -(b["lat"] - t["lat0"]) * t["kz"]
    assert t["lat0"] == start["lat"] and bz > 0                                # B is south of the rover
    ci, ri = round((bx - t["x0"]) / t["dx"]), round((bz - t["z0"]) / t["dz"])
    assert 0 <= ci < t["cols"] and 0 <= ri < t["rows"]
    tex = Image.open(io.BytesIO(c.get("/api/sim/texture.png", params={"step": 2}).content))
    assert abs(tex.size[0] / tex.size[1] - t["cols"] / t["rows"]) < 0.02
    assert c.get("/api/sim/texture.png", params={"kind": "hazard", "step": 2}).status_code == 200

    # the 1 m physics grid: same cells, same rough/sand/off-limits as the stack the route search uses
    f = t["fine"]
    raw = c.get(f["url"]).content
    raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    n = f["rows"] * f["cols"]
    nb = (n + 7) // 8
    assert len(raw) == 5 * n + 3 * nb
    walk = np.frombuffer(raw[: 2 * n], dtype="<u2").reshape(f["rows"], f["cols"])
    dtm = np.frombuffer(raw[2 * n: 4 * n], dtype="<u2").reshape(f["rows"], f["cols"])
    rough = np.frombuffer(raw[4 * n: 5 * n], dtype=np.uint8)
    fine_nogo = np.unpackbits(np.frombuffer(raw[5 * n + nb: 5 * n + 2 * nb], dtype=np.uint8))[:n]
    shadow = np.unpackbits(np.frombuffer(raw[5 * n + 2 * nb:], dtype=np.uint8))[:n].reshape(f["rows"], f["cols"])
    assert walk.max() > 0 and rough.max() > 0 and fine_nogo.sum() >= 0
    assert min(int(walk.min()), int(dtm.min())) == 0 and dtm.max() > walk.max() - 100    # one zero for both
    assert shadow.any() and not shadow.all()
    ph = t["physics"]
    assert ph["roughness_penalty_per_m"] == pytest.approx(2.0) and ph["sand_penalty"] == pytest.approx(1.2)
    # one fine cell per stack pixel, and B lands inside the fine grid too
    assert f["dx"] * 2 == pytest.approx(t["dx"], rel=0.02) and f["dz"] * 2 == pytest.approx(t["dz"], rel=0.02)
    bi, bj = round((bz - f["z0"]) / f["dz"]), round((bx - f["x0"]) / f["dx"])
    assert 0 <= bj < f["cols"] and 0 <= bi < f["rows"]
    assert shadow[bi, bj] == 1                                                 # the wall hides B from the rover

    s = c.get("/api/sim/sun").json()
    assert s["lmst_h"] == pytest.approx(9.0, abs=1e-3) and len(s["az_el"]) == 301 and 0 < s["az_el"][0][0] < 180

    plan = c.post("/api/plan", json={"cost": "metabolic", "order": "fixed"}).json()
    a = plan["timeline"][1]
    live = {"lat": (start["lat"] + a["lat"]) / 2, "lon": (start["lon"] + a["lon"]) / 2, "walked_m": 25.0,
            "energy_kj": 40.0, "elapsed_h": 0.1}
    r = c.get("/api/eink.png", params=live)
    assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (800, 480)
    r = c.get("/api/eink.png", params={**live, "visited": a["id"]})
    assert r.status_code == 200

    q = c.post("/api/ask", json={"question": "how far is the next stop", "plan_id": plan["plan_id"], "elapsed_h": 0.1,
                                 "here_lat": live["lat"], "here_lon": live["lon"], "visited": []}).json()
    assert q["here"]["label"].startswith("your position") and q["answer"].startswith(f"{a['id']} (")
    q = c.post("/api/ask", json={"question": "how far is the next stop", "plan_id": plan["plan_id"], "elapsed_h": 0.1,
                                 "here_lat": live["lat"], "here_lon": live["lon"], "visited": [a["id"]]}).json()
    assert q["answer"].startswith(f"{plan['timeline'][2]['id']} (")


def test_live_moment_counts_progress_and_schedule(synthetic_site):
    from marswalk import eink
    from marswalk.export.payload import plan_payload
    from marswalk.layers.stack import build_stack
    from marswalk.route.plan import build_plan
    site = load_site(synthetic_site)
    st = build_stack(site, EVA, use_cache=False)
    p = plan_payload(build_plan(site, EVA, st, "metabolic"), st)
    tl = p["timeline"]
    a = tl[1]
    m, ahead = eink.live_moment(p, site, EVA, st, None, a["lat"], a["lon"], a["arrive_min"], 100.0, 50.0, [])
    assert m.at_stop == a["id"] and m.to_next_m < 10 and abs(m.schedule_delta_min) < 1     # on plan at the stop
    assert m.to_end_m == pytest.approx(p["profile"]["dist_m"][-1] - eink._dist_at(p, a["arrive_min"]), rel=0.05)
    late, _ = eink.live_moment(p, site, EVA, st, None, a["lat"], a["lon"], a["arrive_min"] + 20, 100.0, 50.0, [])
    assert late.schedule_delta_min == pytest.approx(20, abs=1)
    done, _ = eink.live_moment(p, site, EVA, st, None, a["lat"], a["lon"], a["depart_min"], 100.0, 50.0, [a["id"]])
    assert done.next_id == tl[2]["id"] and done.stop_index == 1 and len(ahead) > 2


def test_simulator_walking_grid_is_the_planners_own(synthetic_site):
    """The simulator's physics reads the route search's own layers, cell for cell."""
    import numpy as np

    from marswalk import sim
    from marswalk.layers.stack import build_stack
    site = load_site(synthetic_site)
    st = build_stack(site, EVA, use_cache=False)
    stops, start = list(site.stops), site.start
    pts = [(s.lat, s.lon) for s in stops]
    meta = sim.fine_meta(site, st, start.lat, start.lon, pts)
    raw = sim.fine_bytes(st, start.lat, start.lon, pts)
    n, nb = meta["rows"] * meta["cols"], (meta["rows"] * meta["cols"] + 7) // 8
    rough = np.frombuffer(raw[4 * n: 5 * n], dtype=np.uint8).reshape(meta["rows"], meta["cols"])
    nogo = np.unpackbits(np.frombuffer(raw[5 * n + nb: 5 * n + 2 * nb], dtype=np.uint8))[:n].reshape(meta["rows"], meta["cols"])
    walk = np.frombuffer(raw[: 2 * n], dtype="<u2").reshape(meta["rows"], meta["cols"]).astype(float) / 100
    r0, _, c0, _ = sim.area(st, [(start.lat, start.lon), *pts])
    fr = sim.frame(site, start.lat, start.lon)
    for s in stops:
        r, c = st.grid.latlon_to_rc(s.lat, s.lon)
        # the same cell, found the browser's way: lat/lon -> local metres -> grid index
        x, z = (s.lon - fr["lon0"]) * fr["kx"], -(s.lat - fr["lat0"]) * fr["kz"]
        ci, ri = round((x - meta["x0"]) / meta["dx"]), round((z - meta["z0"]) / meta["dz"])
        assert (ri, ci) == (r - r0, c - c0)
        assert rough[ri, ci] == round(min(float(st.roughness_m[r, c]) * 100, 255))
        assert bool(nogo[ri, ci]) == bool(st.nogo[r, c])
        # walk heights keep the planner's grades: the same climb to the next cell east
        ref = st.walk_elev_m if st.walk_elev_m is not None else st.elevation_m
        assert walk[ri, ci + 1] - walk[ri, ci] == pytest.approx(float(ref[r, c + 1] - ref[r, c]), abs=0.011)
