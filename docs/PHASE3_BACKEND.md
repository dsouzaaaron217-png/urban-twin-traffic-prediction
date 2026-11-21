# Phase 3 Backend

## Configuration

Copy `.env.example` to `.env`, configure a private `API_KEY`, and never commit `.env`. Without `API_KEY`, admin-only actions return `503`; anonymous requests are read-only viewers. Invalid supplied keys return `401`.

`DATABASE_URL` defaults to the existing Phase 1 SQLite file (`data/phase1_ingestion.sqlite3`). PostgreSQL uses `postgresql+psycopg://user:password@host:5432/database`. `CORS_ALLOWED_ORIGINS` is a comma-separated explicit allowlist. `RATE_LIMIT_PER_MINUTE` controls the process-local per-IP limit; use a shared gateway/limiter for multi-worker deployments.

Install dependencies and run migrations from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
```

The baseline migration creates only missing tables and preserves existing Phase 1 observations. Its downgrade intentionally does not drop operational tables. SQLite and PostgreSQL use the same SQLAlchemy metadata; PostgreSQL requires a reachable server and valid credentials.

## API

- `GET /health` reports process liveness and Phase 1 store readiness.
- `GET /metrics` returns request totals by HTTP status.
- `GET /api/v1/traffic/current?city=&area=&limit=&offset=` returns the latest stored observation for each corridor, with source and quality.
- `GET /api/v1/forecasts/{city}/{area}?horizon_minutes=15|30|60` wraps the existing Phase 2 predictor. Every response carries `data_quality`, `model_version`, and UTC `generated_at`; insufficient history returns an unavailable state.
- `GET /api/v1/forecasts/actuals?city=&area=&limit=&offset=` lists persisted forecasts and joins an actual observation only for the same city/area within one 15-minute poll step of the target time.
- `GET /api/traffic/history` supports city/area/date filters and bounded `limit`/`offset`; response includes `items`, `total`, `limit`, and `offset`.
- `POST /api/v1/routes/eta` returns provider ETA now. Horizon ETAs and best-time-to-leave remain explicitly unavailable until route-level verified forecasts exist.
- `GET /api/v1/alerts?limit=&offset=` reports current model-drift and collector-health signals; no alerts are fabricated.
- `GET /api/v1/data/readiness` preserves the Phase 1 14-day/80%-coverage gate.
- `GET /api/v1/model/metrics` exposes active model version, training range, per-horizon evaluation, fallback reasons, provenance, and drift.

The existing `/api/saved-locations` response retains `locations` and adds page metadata/`items` for compatibility. All errors use `error`, `message`, `details`, and UTC `timestamp`, with a `detail` compatibility alias.

## Limitations

The checked-in Phase 1 database currently has no verified observations. Forecasts therefore remain unavailable until validated observations meet the existing readiness gate. Route-level future ETAs are not modeled yet; the API returns a reason rather than guessing. The rate limiter is in-memory and PostgreSQL has not been integration-tested unless a live test database is configured separately.
