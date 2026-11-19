from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_root():
    assert client.get("/").json()["project"] == "Fantasy Art Automation"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert "timestamp" in r.json()


def test_token_status_and_refresh_endpoints_hide_secrets():
    s = client.get("/auth/token/status").json()
    assert s["has_token"] is True and "access_token" not in s
    r = client.post("/auth/token/refresh")
    assert r.status_code == 200 and "refresh_token" not in r.json()
