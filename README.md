# Fantasy Art Automation

AI-powered fantasy art automation platform with Etsy API integration, OAuth token management, and autonomous engineering workflows.

## Status
- ✅ FastAPI app with `/health`
- ✅ Etsy OAuth token manager (expiry check, refresh, rotation, atomic file store) — tested with mocks
- ✅ Listing sync worker (retry with backoff, 429 `Retry-After`, alerts)
- ✅ Docker + docker-compose (PostgreSQL provisioned; not yet used by code)
- ✅ GitHub Actions CI
- ⏳ Real Etsy OAuth login flow, DB persistence, Devin integration

## Run locally
```bash
python -m venv .venv
.venv/Scripts/activate        # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --reload
```
Docs: http://127.0.0.1:8000/docs. Try `GET /auth/token/status`, `POST /auth/token/refresh` (mock mode by default).

## Test
```bash
python -m pytest -v
```

## Docker
```bash
cp .env.example .env   # set POSTGRES_PASSWORD
docker compose up --build
```

## Security
Never commit `.env`, API keys or tokens. Token files live in `.secrets/` (git-ignored). Set `ETSY_MOCK=false` and `ETSY_CLIENT_ID` for the real API.
