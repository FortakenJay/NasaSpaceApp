import pytest
from fastapi.testclient import TestClient

from marswalk.api.app import create_app


@pytest.fixture
def client():
    # Fresh in-memory DB per test, seeded from the config files.
    return TestClient(create_app(db_url="sqlite://"))


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_site_payload(client):
    d = client.get("/api/site").json()
    assert d["site"]["id"] == "gale_boxwork"
    assert [s["id"] for s in d["stops"]] == ["H1", "S1", "S2", "S3", "S4", "S5"]
    assert "{z}" in d["site"]["basemap"]["url_template"]


def test_layers_empty_until_m2(client):
    assert client.get("/api/layers").json() == []
    assert client.get("/api/layers/nope.png").status_code == 404
    r = client.get("/api/layers/slope5.png")
    assert r.status_code == 501 and r.json()["milestone"] == "M2"


def test_plan_reports_milestone(client):
    r = client.post("/api/plan", json={"cost": "weighted", "order": "fixed"})
    assert r.status_code == 501 and r.json()["milestone"] == "M4"


def test_plan_validates_input(client):
    assert client.post("/api/plan", json={"cost": "teleport"}).status_code == 422


def test_status_reports_milestone(client):
    r = client.get("/api/status")
    assert r.status_code == 501 and r.json()["milestone"] == "M5"


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
