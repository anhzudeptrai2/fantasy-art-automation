import httpx
import pytest

from backend.app.integrations.etsy import (
    EtsyAPIError, EtsyAuthError, EtsyClient, EtsyRateLimitError, MockEtsyClient,
)
from backend.app.services.token_manager import FileTokenStore, InMemoryTokenStore, Token, TokenManager
from backend.app.workers.listing_sync import sync_listings


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(expires_at, clock=None):
    clock = clock or Clock()
    client = MockEtsyClient()
    store = InMemoryTokenStore(Token("a0", "r0", expires_at))
    return TokenManager(client, store, skew=60, now=clock), client, store, clock


def test_valid_token_not_refreshed():
    tm, client, _, _ = make(expires_at=5000)
    assert tm.get_valid_token().access_token == "a0"
    assert client.refresh_calls == 0


def test_expired_token_refreshed_and_rotated():
    tm, client, store, _ = make(expires_at=900)
    tok = tm.get_valid_token()
    assert tok.access_token == "mock-access-1"
    assert store.load().refresh_token == "mock-refresh-1"
    assert tok.expires_at == 1000 + 3600


def test_token_within_skew_is_refreshed():
    tm, client, _, _ = make(expires_at=1030)  # 30s left < 60s skew
    tm.get_valid_token()
    assert client.refresh_calls == 1


def test_refresh_failure_keeps_old_token():
    tm, client, store, _ = make(expires_at=900)
    client.fail_next = EtsyAuthError("bad refresh token")
    with pytest.raises(EtsyAuthError):
        tm.get_valid_token()
    assert store.load().access_token == "a0"


def test_status_has_no_secrets():
    tm, *_ = make(expires_at=5000)
    assert set(tm.status()) == {"has_token", "expired", "expires_in"}


def test_file_store_roundtrip(tmp_path):
    store = FileTokenStore(tmp_path / "sub" / "t.json")
    assert store.load() is None
    store.save(Token("a", "r", 1.0))
    assert store.load() == Token("a", "r", 1.0)


def test_http_client_refresh_success_and_errors():
    def handler(request: httpx.Request):
        body = request.content.decode()
        assert "grant_type=refresh_token" in body
        if "refresh_token=good" in body:
            return httpx.Response(200, json={"access_token": "n", "refresh_token": "n2", "expires_in": 3600})
        if "refresh_token=slow" in body:
            return httpx.Response(429, headers={"Retry-After": "7"})
        if "refresh_token=boom" in body:
            return httpx.Response(500)
        return httpx.Response(401)

    c = EtsyClient("key", httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.refresh_token("good")["access_token"] == "n"
    with pytest.raises(EtsyAuthError):
        c.refresh_token("bad")
    with pytest.raises(EtsyRateLimitError) as e:
        c.refresh_token("slow")
    assert e.value.retry_after == 7
    with pytest.raises(EtsyAPIError):
        c.refresh_token("boom")


# --- listing sync worker ---

def test_sync_retries_then_succeeds():
    tm, client, _, _ = make(expires_at=5000)
    sleeps, alerts = [], []
    client.fail_next = EtsyAPIError("HTTP 503")
    res = sync_listings(client, tm, "shop", sleep=sleeps.append, alert=alerts.append)
    assert res.ok and res.attempts == 2 and len(res.listings) == 3
    assert sleeps == [0.5] and alerts == []


def test_sync_honors_rate_limit_retry_after():
    tm, client, _, _ = make(expires_at=5000)
    sleeps = []
    client.fail_next = EtsyRateLimitError(retry_after=9)
    res = sync_listings(client, tm, "shop", sleep=sleeps.append, alert=lambda m: None)
    assert res.ok and sleeps == [9]


def test_sync_gives_up_and_alerts():
    tm, client, _, _ = make(expires_at=5000)
    alerts = []

    def always_fail(*a):
        raise EtsyAPIError("HTTP 500")

    client.get_listings = always_fail
    res = sync_listings(client, tm, "shop", max_attempts=3, sleep=lambda s: None, alert=alerts.append)
    assert not res.ok and res.attempts == 3 and len(alerts) == 1


def test_sync_auth_error_not_retried():
    tm, client, _, _ = make(expires_at=900)  # forces refresh
    client.fail_next = EtsyAuthError("revoked")
    alerts = []
    res = sync_listings(client, tm, "shop", sleep=lambda s: None, alert=alerts.append)
    assert not res.ok and res.attempts == 1 and len(alerts) == 1
