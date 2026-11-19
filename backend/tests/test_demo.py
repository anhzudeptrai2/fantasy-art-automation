import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


@pytest.mark.parametrize("name,ok,attempts", [
    ("ok", True, 1), ("expired_token", True, 1), ("server_error", True, 3),
    ("rate_limit", True, 3), ("outage", False, 4), ("revoked_token", False, 1),
])
def test_scenarios(name, ok, attempts):
    j = client.post(f"/demo/sync/{name}").json()
    assert j["ok"] is ok and j["attempts"] == attempts


def test_details():
    assert client.post("/demo/sync/expired_token").json()["token_refreshes"] == 1
    assert client.post("/demo/sync/rate_limit").json()["waits_seconds"] == [2, 2]
    assert len(client.post("/demo/sync/outage").json()["alerts"]) == 1


def test_page():
    assert "Fantasy Art Automation" in client.get("/demo").text


def test_trace_events():
    j = client.post("/demo/sync/server_error").json()
    kinds = [e["kind"] for e in j["events"]]
    assert kinds.count("bad") == 2 and kinds.count("wait") == 2 and kinds[-1] == "good"
    assert j["simulated_seconds"] == 1.5 and j["waits_seconds"] == [0.5, 1.0]
    r = client.post("/demo/sync/revoked_token").json()
    assert r["events"][-1]["kind"] == "alert" and r["attempts"] == 1


def test_unknown_scenario_404():
    assert client.post("/demo/sync/nope").status_code == 404
