"""Demo router: simulate Etsy failures and trace the real recovery logic (mock Etsy, no credentials)."""
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from backend.app.integrations.etsy import EtsyAPIError, EtsyAuthError, EtsyRateLimitError, MockEtsyClient
from backend.app.services.token_manager import InMemoryTokenStore, Token, TokenManager
from backend.app.workers.listing_sync import sync_listings

router = APIRouter(prefix="/demo", tags=["demo"])
PAGE = Path(__file__).parent / "static" / "demo.html"

SCENARIOS = {
    "ok": {"title": "Healthy", "desc": "Token valid, Etsy answers"},
    "expired_token": {"title": "Expired token", "desc": "Refreshed automatically, then sync"},
    "server_error": {"title": "Etsy error (5xx)", "desc": "Two failures, then recovery with backoff"},
    "rate_limit": {"title": "Rate limited (429)", "desc": "Waits as long as Etsy asks"},
    "outage": {"title": "Full outage", "desc": "Gives up after 4 attempts and alerts"},
    "revoked_token": {"title": "Revoked login", "desc": "No pointless retries, alerts at once"},
}

FAILURES = {
    "server_error": lambda: [EtsyAPIError("HTTP 503")] * 2,
    "rate_limit": lambda: [EtsyRateLimitError(2)] * 2,
    "outage": lambda: [EtsyAPIError("HTTP 500")] * 99,
}


@router.get("/scenarios")
def scenarios():
    return SCENARIOS


@router.post("/sync/{scenario}")
def run(scenario: str):
    if scenario not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario, choose one of {list(SCENARIOS)}")

    clock = [0.0]  # simulated seconds, so the demo never actually sleeps
    events: list[dict] = []

    def log(kind: str, text: str):
        events.append({"t": round(clock[0], 2), "kind": kind, "text": text})

    now = time.time()
    expired = scenario in ("expired_token", "revoked_token")
    client = MockEtsyClient()
    tm = TokenManager(client, InMemoryTokenStore(
        Token("old-access", "old-refresh", now - 10 if expired else now + 3600)))
    if scenario == "revoked_token":
        client.fail_next = EtsyAuthError("refresh token revoked")

    # Wrap the mock so every call shows up in the trace; the worker logic itself is untouched.
    real_refresh, real_listings = client.refresh_token, client.get_listings
    pending = FAILURES.get(scenario, list)()
    attempt = [0]

    def refresh(rt):
        log("info", "access token expired, refreshing")
        try:
            data = real_refresh(rt)
        except EtsyAuthError as exc:
            log("bad", f"refresh rejected: {exc}")
            raise
        log("good", "new token saved (refresh token rotated)")
        return data

    def listings(token, shop):
        attempt[0] += 1
        log("info", f"attempt {attempt[0]}: GET /shops/{shop}/listings")
        if pending:
            exc = pending.pop()
            log("bad", f"Etsy 429 Too Many Requests (Retry-After {exc.retry_after:g}s)"
                if isinstance(exc, EtsyRateLimitError) else f"Etsy {exc}")
            raise exc
        result = real_listings(token, shop)
        log("good", f"received {len(result)} listings")
        return result

    client.refresh_token, client.get_listings = refresh, listings

    def sleep(seconds: float):
        log("wait", f"waiting {seconds:g}s before retry")
        clock[0] += seconds

    def alert(message: str):
        log("alert", f"ALERT sent to operator: {message}")

    res = sync_listings(client, tm, "demo-shop", sleep=sleep, alert=alert)
    return {
        "scenario": scenario,
        "ok": res.ok,
        "attempts": res.attempts,
        "token_refreshes": client.refresh_calls,
        "waits_seconds": [float(e["text"].split()[1].rstrip("s")) for e in events if e["kind"] == "wait"],
        "alerts": [e["text"] for e in events if e["kind"] == "alert"],
        "simulated_seconds": round(clock[0], 2),
        "events": events,
        "listings": res.listings,
        "error": res.error,
    }


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def page():
    return PAGE.read_text(encoding="utf-8")
