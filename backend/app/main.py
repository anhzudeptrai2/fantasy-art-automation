import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from backend.app.demo import router as demo_router
from backend.app.integrations.etsy import EtsyAPIError, EtsyClient, MockEtsyClient
from backend.app.services.token_manager import FileTokenStore, InMemoryTokenStore, Token, TokenManager

app = FastAPI(
    title="Fantasy Art Automation API",
    version="0.1.0",
    description="Automation backend for fantasy art commerce.",
)


def build_token_manager() -> TokenManager:
    """ETSY_MOCK=true (default) uses a mock Etsy and an in-memory demo token."""
    if os.getenv("ETSY_MOCK", "true").lower() == "true":
        store = InMemoryTokenStore(Token("mock-access-0", "mock-refresh-0", time.time() + 3600))
        return TokenManager(MockEtsyClient(), store)
    client = EtsyClient(os.environ["ETSY_CLIENT_ID"])
    return TokenManager(client, FileTokenStore(os.getenv("ETSY_TOKEN_FILE", ".secrets/etsy_token.json")))


app.state.token_manager = build_token_manager()
app.include_router(demo_router)


@app.get("/")
def root():
    return {"project": "Fantasy Art Automation", "version": "0.1.0", "status": "development", "demo": "/demo"}


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/auth/token/status")
def token_status():
    return app.state.token_manager.status()


@app.post("/auth/token/refresh")
def token_refresh():
    try:
        app.state.token_manager.refresh()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except EtsyAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return app.state.token_manager.status()
