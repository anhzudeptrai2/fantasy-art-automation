"""Token lifecycle: expiry check, refresh, safe persistence."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol


@dataclass
class Token:
    access_token: str
    refresh_token: str
    expires_at: float  # unix seconds

    def is_expired(self, now: float, skew: float = 0.0) -> bool:
        return now >= self.expires_at - skew


class TokenStore(Protocol):
    def load(self) -> Token | None: ...
    def save(self, token: Token) -> None: ...


class InMemoryTokenStore:
    def __init__(self, token: Token | None = None):
        self._token = token

    def load(self) -> Token | None:
        return self._token

    def save(self, token: Token) -> None:
        self._token = token


class FileTokenStore:
    """JSON file, atomically written, owner-only permissions. Keep it out of git."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        return Token(**json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(token)), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)


class TokenManager:
    def __init__(self, client, store: TokenStore, skew: float = 60.0,
                 now: Callable[[], float] = time.time):
        self.client = client
        self.store = store
        self.skew = skew
        self._now = now
        self._lock = threading.Lock()

    def status(self) -> dict:
        """Safe to expose: never includes token values."""
        token = self.store.load()
        if token is None:
            return {"has_token": False, "expired": None, "expires_in": None}
        remaining = token.expires_at - self._now()
        return {
            "has_token": True,
            "expired": token.is_expired(self._now(), self.skew),
            "expires_in": max(0, int(remaining)),
        }

    def refresh(self) -> Token:
        with self._lock:
            return self._refresh_locked()

    def _refresh_locked(self) -> Token:
        current = self.store.load()
        if current is None:
            raise RuntimeError("no token stored; complete the OAuth flow first")
        data = self.client.refresh_token(current.refresh_token)  # errors propagate
        new = Token(
            access_token=data["access_token"],
            # Etsy rotates refresh tokens; fall back to the old one if absent.
            refresh_token=data.get("refresh_token", current.refresh_token),
            expires_at=self._now() + float(data["expires_in"]),
        )
        self.store.save(new)
        return new

    def get_valid_token(self) -> Token:
        with self._lock:
            token = self.store.load()
            if token is None:
                raise RuntimeError("no token stored; complete the OAuth flow first")
            if token.is_expired(self._now(), self.skew):
                return self._refresh_locked()
            return token
