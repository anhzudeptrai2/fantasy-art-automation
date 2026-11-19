"""Listing sync worker: retry with backoff, rate-limit awareness, logging, alerting."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from backend.app.integrations.etsy import EtsyAPIError, EtsyAuthError, EtsyRateLimitError

log = logging.getLogger("listing_sync")


@dataclass
class SyncResult:
    ok: bool
    listings: list[dict] = field(default_factory=list)
    attempts: int = 0
    error: str | None = None


def default_alert(message: str) -> None:
    log.error("ALERT: %s", message)  # swap for Slack/email later


def sync_listings(
    client,
    token_manager,
    shop_id: str,
    max_attempts: int = 4,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    alert: Callable[[str], None] = default_alert,
) -> SyncResult:
    last_error = "unknown"
    for attempt in range(1, max_attempts + 1):
        try:
            token = token_manager.get_valid_token()
            listings = client.get_listings(token.access_token, shop_id)
            log.info("synced %d listings (attempt %d)", len(listings), attempt)
            return SyncResult(True, listings, attempt)
        except EtsyAuthError as exc:
            # Not retryable: credentials are bad. Alert a human.
            alert(f"Etsy auth failure, manual action needed: {exc}")
            return SyncResult(False, attempts=attempt, error=str(exc))
        except EtsyRateLimitError as exc:
            last_error = str(exc)
            delay = exc.retry_after
        except EtsyAPIError as exc:
            last_error = str(exc)
            delay = base_delay * 2 ** (attempt - 1)
        log.warning("attempt %d/%d failed: %s", attempt, max_attempts, last_error)
        if attempt < max_attempts:
            sleep(delay)
    alert(f"listing sync failed after {max_attempts} attempts: {last_error}")
    return SyncResult(False, attempts=max_attempts, error=last_error)
