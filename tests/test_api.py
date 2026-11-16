import pytest
from fastapi.testclient import TestClient

from marswalk.api.app import create_app


@pytest.fixture
def client():
    # Fresh in-memory DB per test, seeded from the config files.
    return TestClient(create_app(db_url="sqlite://"))


def test_hosted_database_is_not_in_the_checkout(monkeypatch):
    from marswalk.db import engine

    monkeypatch.delenv("MARSWALK_DATA", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(engine.os, "access", lambda *_a, **_k: False)
    assert engine.default_db_url() == "sqlite:////tmp/marswalk/marswalk.db"


def test_preview_plan_is_the_stored_gale_route():
    from marswalk.config import load_site
    from marswalk.db import repo
    from marswalk.db.engine import make_engine, make_session_factory

    site = load_site("configs/sites/gale_boxwork.toml")
    sessions = make_session_factory(make_engine("sqlite://"))
    with sessions() as s:
        repo.seed_site(s, site)
        assert repo.seed_preview_plan(s, site.id)
        plans = repo.list_plans(s, site.id)
        assert len(plans) == 1 and plans[0]["name"] == "Gale preview"
        assert plans[0]["stop_ids"] == ["S1", "S2", "S3", "S4", "S5"]
        assert plans[0]["result"]["summary"]["distance_km"] == 1.71
        assert repo.seed_preview_plan(s, site.id) is False


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_site_payload(client):
    d = client.get("/api/site").json()
    assert d["site"]["id"] == "gale_boxwork"
    assert [s["id"] for s in d["stops"]] == ["H1", "S1", "S2", "S3", "S4", "S5"]
    assert "{z}" in d["site"]["basemap"]["url_template"]
    assert d["api_version"] == client.get("/api/health").json()["version"] and d["eva"]["usable_h"] == 5.6


def test_terrain_routes_answer_409_until_fetched(client):
    # MARSWALK_DATA points at an empty temp folder (conftest), so no DTM is cached.
    assert client.get("/api/layers").json() == []
    assert client.get("/api/layers/nope.png").status_code == 404
    r = client.get("/api/layers/slope5.png")
    assert r.status_code == 409 and "marswalk fetch" in r.json()["detail"]
    r = client.post("/api/plan", json={"cost": "weighted", "order": "fixed"})
    assert r.status_code == 409 and "marswalk fetch" in r.json()["detail"]


def test_plan_layers_and_walkback_on_synthetic_terrain(synthetic_site):
    c = TestClient(create_app(site_path=str(synthetic_site), db_url="sqlite://"))
    layers = c.get("/api/layers").json()
    assert {l["key"] for l in layers} == {"hillshade", "slope5", "roughness", "ti", "nogo", "safezone", "radio", "shelter",
                                          "uncertain"}
    lon_min, lat_min, lon_max, lat_max = layers[0]["bounds"]
    assert lon_min < lon_max and lat_min < lat_max
    for key in ("slope5", "nogo", "radio", "shelter", "uncertain"):
        r = c.get(f"/api/layers/{key}.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get("/api/layers/safezone.png?elapsed_h=5.5").content[:4] == b"\x89PNG"

    r = c.post("/api/plan", json={"cost": "metabolic", "order": "fixed"})
    assert r.status_code == 200
    d = r.json()
    assert len(d["route"]["features"]) == 4 and d["summary"]["order"] == "A > B > C"
    saved = c.get("/api/plans").json()
    assert [p["id"] for p in saved] == [d["plan_id"]] and saved[0]["status"] == "computed"

    b = next(s for s in c.get("/api/site").json()["stops"] if s["id"] == "B")
    adhoc = c.post("/api/plan", json={"points": [{"lat": b["lat"], "lon": b["lon"], "name": "Clicked"}]}).json()
    assert adhoc["summary"]["order"] == "P1" and "plan_id" not in adhoc and len(c.get("/api/plans").json()) == 1
    assert c.post("/api/plan", json={"stop_ids": ["nope"]}).status_code == 422

    wb = c.get("/api/walkback", params={"lat": b["lat"], "lon": b["lon"]}).json()
    assert wb["reachable"] and wb["safe"] and wb["walkback_min"] > 0 and len(wb["route"]["geometry"]["coordinates"]) > 50
    late = c.get("/api/walkback", params={"lat": b["lat"], "lon": b["lon"], "elapsed_h": 5.59}).json()
    assert late["reachable"] and not late["safe"] and late["margin_min"] < 0


def test_plan_validates_input(client):
    assert client.post("/api/plan", json={"cost": "teleport"}).status_code == 422


def test_status_is_caution_when_donki_is_unreachable(client):
    d = client.get("/api/status").json()                      # conftest: the network is off
    assert d["level"] == "CAUTION" and d["data_ok"] is False and "DONKI" in d["reason"]
    assert d["eva_dose_mgy"] == pytest.approx(0.07) and d["baseline_dose_mgy_per_day"] == 0.21
    src = client.get("/api/sources").json()
    assert {f["name"]: f["state"] for f in src["feeds"]} == {"enlil": "missing", "sep": "missing", "flr": "missing"}
    assert src["key"] == "demo" and src["stats"]["failed"] == 3 and all(f["retry_in_s"] for f in src["feeds"])


def test_status_uses_mars_cme_arrivals_and_the_central_cache(client, monkeypatch):
    import datetime as dt
    import json
    from marswalk.sources import api_client
    soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=10)).strftime("%Y-%m-%dT%H:%MZ")
    feeds = {"SEP": [], "FLR": [{"classType": "M2.1", "peakTime": soon}],
             "WSAEnlilSimulations": [{"impactList": [{"location": "STEREO A", "arrivalTime": soon, "isGlancingBlow": False},
                                                     {"location": "Mars", "arrivalTime": soon, "isGlancingBlow": False}]},
                                     {"impactList": None}]}
    calls = []

    def nasa(url, timeout=0):
        calls.append(url)
        kind = url.split("/DONKI/")[1].split("?")[0]
        return json.dumps(feeds[kind]), {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": str(1000 - len(calls))}
    monkeypatch.setattr(api_client, "http_get", nasa)
    d = client.get("/api/status").json()
    assert d["level"] == "NO-GO" and "Mars" in d["reason"] and len(d["mars_arrivals"]) == 1
    assert d["mars_arrivals"][0]["glancing"] is False and d["data_ok"] is True and d["notes"] == []
    assert len(calls) == 3
    # a second look within 30 minutes asks NASA nothing
    assert client.get("/api/status").json()["level"] == "NO-GO" and len(calls) == 3
    src = client.get("/api/sources").json()
    assert src["stats"]["requests_sent"] == 3 and src["stats"]["served_from_cache"] == 3
    assert src["rate_limit"] == {"limit": 1000, "remaining": 997}
    assert all(f["state"] == "cached" and f["fresh_for_s"] > 1700 for f in src["feeds"])
    # "Ask NASA again" forces a fresh round
    r = client.post("/api/sources/refresh").json()
    assert len(calls) == 6 and r["status"]["level"] == "NO-GO" and r["sources"]["stats"]["requests_sent"] == 6


def test_a_late_flare_list_does_not_block_a_go(client, monkeypatch):
    from marswalk.sources import api_client

    def nasa(url, timeout=0):
        if "/FLR" in url:
            raise OSError("timed out")
        return "[]", {}
    monkeypatch.setattr(api_client, "http_get", nasa)
    d = client.get("/api/status").json()
    assert d["level"] == "GO" and d["data_ok"] is True
    assert len(d["notes"]) == 1 and "Solar flares" in d["notes"][0]


def test_site_stops_come_from_db(client):
    d = client.get("/api/site").json()
    s3 = next(s for s in d["stops"] if s["id"] == "S3")
    assert s3["lat"] == -4.807839 and s3["work_time_min"] == 30


def test_observations_roundtrip(client):
    assert client.get("/api/stops/S3/observations").json() == []
    r = client.post("/api/stops/S3/observations", json={"note": "  Ridge cement brighter than hollow floor ", "sample_id": "MW-S3-01"})
    assert r.status_code == 201
    o = r.json()
    assert o["note"] == "Ridge cement brighter than hollow floor" and o["sample_id"] == "MW-S3-01" and o["author"] == "crew"
    client.post("/api/stops/S3/observations", json={"note": "second"})
    notes = [x["note"] for x in client.get("/api/stops/S3/observations").json()]
    assert notes == ["second", "Ridge cement brighter than hollow floor"]  # newest first


def test_observation_validation_and_unknown_stop(client):
    assert client.post("/api/stops/S3/observations", json={"note": ""}).status_code == 422
    assert client.post("/api/stops/S9/observations", json={"note": "x"}).status_code == 404
    assert client.get("/api/stops/S9/observations").status_code == 404


def test_save_and_list_plans(client):
    r = client.post("/api/plans", json={"name": "Baseline", "cost": "metabolic", "order": "fixed",
                                        "stop_ids": ["S1", "S2", "S3", "S4", "S5"]})
    assert r.status_code == 201
    p = r.json()
    assert p["status"] == "requested" and p["result"] is None
    assert client.get(f"/api/plans/{p['id']}").json()["name"] == "Baseline"
    assert [x["id"] for x in client.get("/api/plans").json()] == [p["id"]]


def test_save_plan_rejects_unknown_stop(client):
    r = client.post("/api/plans", json={"cost": "weighted", "order": "fixed", "stop_ids": ["S1", "S9"]})
    assert r.status_code == 404
    assert client.get("/api/plans/nope").status_code == 404


def test_timestamps_are_utc_labelled(client):
    o = client.post("/api/stops/S1/observations", json={"note": "tz"}).json()
    assert o["created_at"].endswith("+00:00")
    p = client.get("/api/plans").json()
    assert all(x["created_at"].endswith("+00:00") for x in p)


def test_added_stops_are_saved_moved_planned_and_removed(synthetic_site):
    c = TestClient(create_app(site_path=str(synthetic_site), db_url="sqlite://"))
    stops = c.get("/api/site").json()["stops"]
    a, b = (next(s for s in stops if s["id"] == i) for i in ("A", "B"))
    mid = {"lat": (a["lat"] + stops[0]["lat"]) / 2, "lon": (a["lon"] + stops[0]["lon"]) / 2}

    r = c.post("/api/stops", json=mid)
    assert r.status_code == 201
    u1 = r.json()
    assert u1["id"] == "U1" and u1["kind"] == "user" and u1["name"] == "My stop 1" and u1["dtm_z_m"] is not None
    assert c.post("/api/stops", json={**mid, "name": "Ridge view"}).json()["id"] == "U2"
    assert [s["id"] for s in c.get("/api/site").json()["stops"]] == ["H1", "A", "B", "C", "U1", "U2"]   # saved, in order

    # a spot far off the mapped terrain is refused, with a reason
    far = c.post("/api/stops", json={"lat": mid["lat"] + 0.2, "lon": mid["lon"]})
    assert far.status_code == 422 and "off limits" in far.json()["detail"]

    # move and rename a saved stop; science stops are protected
    moved = c.patch("/api/stops/U1", json={"lat": b["lat"], "lon": b["lon"], "name": "Hollow floor"}).json()
    assert moved["lat"] == b["lat"] and moved["name"] == "Hollow floor"
    assert c.patch("/api/stops/A", json={"name": "x"}).status_code == 403
    assert c.delete("/api/stops/A").status_code == 403 and c.delete("/api/stops/U9").status_code == 404

    # the default plan now visits the added stops too, and a chosen subset works
    full = c.post("/api/plan", json={}).json()
    assert full["summary"]["order"] == "A > B > C > U1 > U2"
    sub = c.post("/api/plan", json={"stop_ids": ["U1", "A"]}).json()
    assert sub["summary"]["order"] == "U1 > A" and [w["id"] for w in sub["timeline"]] == ["H1", "U1", "A", "H1"]
    assert c.post("/api/plan", json={"stop_ids": []}).status_code == 422

    assert c.delete("/api/stops/U2").status_code == 200
    assert [s["id"] for s in c.get("/api/site").json()["stops"]] == ["H1", "A", "B", "C", "U1"]
    assert c.post("/api/stops", json=mid).json()["id"] == "U2"      # codes are reused only after the highest is gone
