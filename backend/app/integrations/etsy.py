"""Etsy Open API v3 client (OAuth refresh + listings) with a mock for offline use."""
from __future__ import annotations

import httpx

ETSY_BASE_URL = "https://api.etsy.com/v3"
TOKEN_URL = f"{ETSY_BASE_URL}/public/oauth/token"


class EtsyAPIError(Exception):
    """Generic Etsy API failure."""


class EtsyAuthError(EtsyAPIError):
    """Refresh token / credentials rejected (HTTP 400/401/403)."""


class EtsyRateLimitError(EtsyAPIError):
    """HTTP 429. `retry_after` is in seconds."""

    def __init__(self, retry_after: float = 1.0):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        try:
            retry_after = float(resp.headers.get("Retry-After", "1"))
        except ValueError:
            retry_after = 1.0
        raise EtsyRateLimitError(retry_after)
    if resp.status_code in (400, 401, 403):
        raise EtsyAuthError(f"auth failed: HTTP {resp.status_code}")
    if resp.status_code >= 400:
        raise EtsyAPIError(f"Etsy API error: HTTP {resp.status_code}")


class EtsyClient:
    def __init__(self, client_id: str, http: httpx.Client | None = None):
        self.client_id = client_id
        self._http = http or httpx.Client(timeout=10.0)

    def refresh_token(self, refresh_token: str) -> dict:
        """Returns {access_token, refresh_token, expires_in}. Etsy rotates refresh tokens."""
        try:
            resp = self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise EtsyAPIError(f"network error: {exc}") from exc
        _raise_for_status(resp)
        return resp.json()

    def get_listings(self, access_token: str, shop_id: str) -> list[dict]:
        try:
            resp = self._http.get(
                f"{ETSY_BASE_URL}/application/shops/{shop_id}/listings",
                headers={"Authorization": f"Bearer {access_token}", "x-api-key": self.client_id},
            )
        except httpx.HTTPError as exc:
            raise EtsyAPIError(f"network error: {exc}") from exc
        _raise_for_status(resp)
        return resp.json().get("results", [])


class MockEtsyClient:
    """Offline stand-in. Set `fail_next` to an exception to simulate one failure."""

    def __init__(self):
        self.refresh_calls = 0
        self.fail_next: Exception | None = None

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc

    def refresh_token(self, refresh_token: str) -> dict:
        self._maybe_fail()
        self.refresh_calls += 1
        return {
            "access_token": f"mock-access-{self.refresh_calls}",
            "refresh_token": f"mock-refresh-{self.refresh_calls}",
            "expires_in": 3600,
        }

    def get_listings(self, access_token: str, shop_id: str) -> list[dict]:
        self._maybe_fail()
        return [{"listing_id": i, "title": f"Fantasy Art #{i}"} for i in range(1, 4)]
