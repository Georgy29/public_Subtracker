# Agent Notes (Codex / contributors)

This repository is intentionally a small, portfolio-style MVP. Prefer small, reviewable changes.

## Where to start
- Product/demo overview + interview flows: `README.md`

## Repo layout
- `backend/app.py` — Flask API entrypoint and routes
- `backend/models.py` — SQLAlchemy models
- `backend/detection.py` — subscription detection logic
- `backend/database.py` — DB engine/session configuration
- `backend/.env.example` — local config template
 - `backend/api_routes.py` — API routes and Swagger bindings
 - `backend/api_schemas.py` — request/response schemas (Marshmallow)

## Local run
From repo root:
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python app.py
```

## Demo assumptions
- Local SQLite is the default (`backend/demo.db`).
- Plaid is expected to be used in `sandbox` for demos.
- Textract is expected to be mocked by default (`MOCK_TEXTRACT=1`).

## Contribution guidelines
- Keep API behavior deterministic for demo flows (seed/reset should be stable).
- Do not add secrets or real credentials to the repo; keep `.env` out of git.
- Prefer adding/maintaining OpenAPI docs when changing endpoints (once Swagger is added).
- If adding tests, keep them fast and focused (detection + a few API smokes).
