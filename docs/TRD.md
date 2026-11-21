# Technical Requirements Document

## Architecture

- **Frontend:** React 19, TypeScript, TanStack Start file routes, Vite, Tailwind, Leaflet/React-Leaflet, and Recharts. Typed HTTP access is centralized in `fronted/src/services/api.ts`.
- **Backend:** FastAPI application in `main.py`, Pydantic request/response schemas, request ID/error/rate-limit/cache middleware in `phase3_http.py`, and service modules under `services/`.
- **Data:** CSV files are raw/imported and derived datasets are separate. Phase 1 SQLite stores ingestion runs, validated observations, budgets, and forecast records; PostgreSQL is configurable through `DATABASE_URL` and Alembic migrations.
- **ML:** `ml/data_prep.py`, `ml/train.py`, and `ml/predict.py` build features, evaluate chronological splits, register versions, and serve forecast/baseline states. Readiness gates predictions.

## Security and configuration

- Provider keys and admin key are read by the backend from environment variables or a local ignored `.env`; frontend bundles must never contain them.
- `ENABLE_TOMTOM_SCHEDULER` and `ENABLE_MODEL_RETRAINING` default to false. Compose also forces both off.
- Admin write operations require a non-empty `API_KEY` and `X-API-Key`; no demo password is used as a production fallback.
- CORS is allow-listed. Inputs are bounded and validated by FastAPI/Pydantic query and body models.
- Request logs record request ID, route, status, and duration, not request bodies, query parameters, or authorization headers.

## Quality gates

`.github/workflows/quality.yml` runs backend tests with a 70% coverage floor, `pip-audit`, frontend ESLint, TypeScript, Vitest, Vite production build, and `bun audit` for pushes and pull requests.

The repository has unit/component tests, mocked provider API tests, and a Playwright browser flow covering alerts, model evaluation, readiness empty states, and browser errors. That E2E flow passes locally. Docker Compose has not been executed because Docker is unavailable in the current environment.

## Run-time topology

`docker compose up --build` starts the backend on port 8000 and frontend on port 8080, waits for health checks, and persists the SQLite database in the `trafficwatch-db` volume. The Compose frontend runs Vite's development server; it is a local demonstration topology, not a hardened production deployment.

## Known technical limitations

- Public Nominatim autocomplete is disabled because its published usage policy prohibits autocomplete. Place suggestions require the backend TomTom integration; map tile requests remain browser-driven with visible OSM attribution.
- Route-level horizon ETA and best-departure estimation remain unavailable until a validated route model exists.
- The frontend linter currently reports legacy `any` and Fast Refresh warnings. `tsc` is a separate hard gate.
- Automated Playwright checks cover 390×844 and 1920×1080 with no horizontal overflow, plus the mocked route planner, alerts, model evaluation, and readiness flows. A manual visual/accessibility review and real-provider checks remain outstanding.
