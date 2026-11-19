"""Demo router: simulate Etsy failures and watch the recovery logic (mock only, no real Etsy calls)."""
import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.app.integrations.etsy import EtsyAPIError, EtsyAuthError, EtsyRateLimitError, MockEtsyClient
from backend.app.services.token_manager import InMemoryTokenStore, Token, TokenManager
from backend.app.workers.listing_sync import sync_listings

router = APIRouter(prefix="/demo", tags=["demo"])

SCENARIOS = {
    "ok": "Everything works",
    "expired_token": "Access token expired -> auto refresh -> sync",
    "server_error": "Etsy returns 5xx twice, then recovers (exponential backoff)",
    "rate_limit": "Etsy returns 429 twice (honors Retry-After), then recovers",
    "outage": "Etsy down for all attempts -> alert raised",
    "revoked_token": "Refresh token revoked -> no retry, alert raised",
}


@router.get("/scenarios")
def scenarios():
    return SCENARIOS


@router.post("/sync/{scenario}")
def run(scenario: str):
    if scenario not in SCENARIOS:
        return {"error": f"unknown scenario, choose one of {list(SCENARIOS)}"}
    now = time.time()
    client = MockEtsyClient()
    expired = scenario in ("expired_token", "revoked_token")
    store = InMemoryTokenStore(Token("old-access", "old-refresh", now - 10 if expired else now + 3600))
    tm = TokenManager(client, store)

    failures = {
        "server_error": [EtsyAPIError("HTTP 503")] * 2,
        "rate_limit": [EtsyRateLimitError(2)] * 2,
        "outage": [EtsyAPIError("HTTP 500")] * 99,
        "revoked_token": [EtsyAuthError("refresh token revoked")],
    }.get(scenario, [])
    real = client.get_listings if scenario != "revoked_token" else None
    pending = list(failures)

    if scenario == "revoked_token":
        client.fail_next = pending.pop()
    else:
        def flaky(token, shop):
            if pending:
                raise pending.pop()
            return real(token, shop)
        client.get_listings = flaky

    delays, alerts = [], []
    res = sync_listings(client, tm, "demo-shop", sleep=delays.append, alert=alerts.append)
    return {
        "scenario": scenario,
        "ok": res.ok,
        "attempts": res.attempts,
        "token_refreshes": client.refresh_calls,
        "waits_seconds": delays,
        "alerts": alerts,
        "listings": res.listings,
        "error": res.error,
    }


PAGE = """<!doctype html><meta charset=utf-8><title>Fantasy Art Automation demo</title>
<style>body{font-family:system-ui;max-width:760px;margin:2rem auto;padding:0 1rem}
button{display:block;width:100%;text-align:left;margin:.4rem 0;padding:.7rem;cursor:pointer}
pre{background:#111;color:#8f8;padding:1rem;overflow:auto}</style>
<h1>Fantasy Art Automation</h1><p>Etsy token refresh &amp; listing-sync recovery (mock Etsy).</p>
<div id=b></div><pre id=o>Pick a scenario...</pre>
<script>
fetch('/demo/scenarios').then(r=>r.json()).then(s=>{for(const k in s){
const e=document.createElement('button');e.textContent=k+' - '+s[k];
e.onclick=()=>fetch('/demo/sync/'+k,{method:'POST'}).then(r=>r.json()).then(j=>o.textContent=JSON.stringify(j,null,2));
b.appendChild(e)}})
</script>"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def page():
    return PAGE
