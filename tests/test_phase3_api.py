from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from services import phase1_pipeline as pipeline
from phase3_http import invalidate_read_cache, reset_http_state

client = TestClient(main.app)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_phase1_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(pipeline, "DB_PATH", tmp_path / "phase1.sqlite3")
    reset_http_state()
    invalidate_read_cache()
    yield
    invalidate_read_cache()


def _observation(timestamp: str, city="Pune", area="Test Road"):
    return {
        "timestamp": timestamp, "city": city, "area": area,
        "latitude": 18.52, "longitude": 73.85,
        "current_speed_kmh": 30, "free_flow_speed_kmh": 50,
        "current_travel_time_seconds": 120, "free_flow_travel_time_seconds": 72,
        "confidence": 0.9, "congestion_percent": 40,
    }


def test_phase3_current_state_is_paginated_and_provider_free(isolated_phase1_store):
    run_id = pipeline.start_run("test_fixture")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    assert pipeline.record_observation(_observation(now.isoformat()), "tomtom", run_id)
    response = client.get("/api/v1/traffic/current?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1 and data["limit"] == 1 and data["offset"] == 0
    assert data["items"][0]["city"] == "Pune"
    assert data["items"][0]["source"] == "tomtom"


def test_forecast_actuals_join_only_same_corridor_observations(isolated_phase1_store):
    origin = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=15)
    target = origin + timedelta(minutes=15)
    pipeline.record_forecast("Pune", "Test Road", 15, origin.isoformat(), target.isoformat(),
                             origin.isoformat(), 38.0, "test-version", "tomtom", "validated")
    run_id = pipeline.start_run("test_fixture")
    pipeline.record_observation(_observation(target.isoformat()), "tomtom", run_id)
    result = pipeline.forecast_actual_history(city="Pune", area="Test Road")
    assert result["total"] == 1
    assert result["items"][0]["actual_congestion_percent"] == 40.0
    assert result["items"][0]["model_version"] == "test-version"


def test_phase3_forecast_actuals_api_paginates(isolated_phase1_store):
    response = client.get("/api/v1/forecasts/actuals?limit=5&offset=0")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 5, "offset": 0}


def test_forecast_response_always_has_quality_version_and_time(isolated_phase1_store):
    response = client.get("/api/v1/forecasts/UnsupportedCity/UnknownRoad?horizon_minutes=15")
    assert response.status_code == 200
    data = response.json()
    assert data["forecast_available"] is False
    assert data["data_quality"]
    assert "model_version" in data
    assert data["generated_at"].endswith("Z") or data["generated_at"].endswith("+00:00")


def test_model_metrics_and_alerts_contract(isolated_phase1_store):
    metrics = client.get("/api/v1/model/metrics")
    assert metrics.status_code == 200
    assert "model_version" in metrics.json()
    alerts = client.get("/api/v1/alerts?limit=2&offset=0")
    assert alerts.status_code == 200
    assert alerts.json()["limit"] == 2


def test_route_eta_reports_current_and_unavailable_future_without_guessing(isolated_phase1_store, monkeypatch):
    monkeypatch.setattr(main, "plan_routes", lambda request: {
        "provider": "mock-route-provider",
        "routes": [{"travel_time_seconds": 900, "distance_km": 8.2}],
    })
    payload = {
        "source": {"latitude": 18.52, "longitude": 73.85, "name": "A"},
        "destination": {"latitude": 18.59, "longitude": 73.74, "name": "B"},
        "preference": "fastest", "alternatives": False,
    }
    response = client.post("/api/v1/routes/eta", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["current"]["seconds"] == 900
    assert data["best_time_to_leave"] is None
    for horizon in ("15m", "30m", "60m"):
        assert data["horizons"][horizon]["available"] is False
        assert "data_quality" in data["horizons"][horizon]
        assert "model_version" in data["horizons"][horizon]
        assert "generated_at" in data["horizons"][horizon]


def test_error_responses_use_common_shape(isolated_phase1_store):
    response = client.get("/api/traffic/history?limit=0")
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert payload["message"] == "Request validation failed."
    assert payload["detail"] == payload["message"]
    assert payload["timestamp"].endswith("Z")


def test_rate_limit_returns_standard_429(isolated_phase1_store, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    client.get("/api/v1/data/readiness")
    response = client.get("/api/v1/data/readiness")
    assert response.status_code == 429
    assert response.json()["error"] == "rate_limit_exceeded"
    assert response.headers["retry-after"] == "60"


def test_metrics_health_and_request_id_contract(isolated_phase1_store):
    response = client.get("/health", headers={"X-Request-ID": "phase3-test-1"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "phase3-test-1"
    assert response.json()["live"] is True
    metrics = client.get("/metrics").json()
    assert metrics["requests_total"] >= 1
    assert "responses_by_status" in metrics


def test_request_logs_do_not_include_auth_header(isolated_phase1_store, caplog):
    secret = "do-not-log-this-admin-token"
    client.get("/health", headers={"X-API-Key": secret})
    assert secret not in caplog.text


def test_cors_only_allows_configured_origins(isolated_phase1_store):
    allowed = client.options("/api/v1/data/readiness", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
    })
    denied = client.options("/api/v1/data/readiness", headers={
        "Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET",
    })
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert denied.headers.get("access-control-allow-origin") is None


def test_settings_normalizes_postgres_scheme(monkeypatch):
    from settings import settings
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/traffic")
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_phase1_schema_compiles_for_postgresql():
    from sqlalchemy import create_mock_engine
    from services.db_schema import metadata
    statements = []
    engine = create_mock_engine("postgresql+psycopg://user:pass@localhost/db", lambda sql, *a, **k: statements.append(str(sql.compile(dialect=engine.dialect))))
    metadata.create_all(engine)
    rendered = "\n".join(statements)
    assert "CREATE TABLE observations" in rendered
    assert "CREATE TABLE forecast_records" in rendered


@pytest.mark.parametrize("existing", [False, True])
def test_alembic_upgrade_fresh_and_existing_sqlite_preserves_observations(tmp_path, monkeypatch, existing):
    db_path = tmp_path / ("existing.sqlite3" if existing else "fresh.sqlite3")
    if existing:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(pipeline, "DB_PATH", db_path)
        run_id = pipeline.start_run("migration-fixture")
        pipeline.record_observation(_observation(datetime.now(timezone.utc).isoformat()), "tomtom", run_id)

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.resolve().as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(db_path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"observations", "forecast_records", "alembic_version"}.issubset(tables)
        count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == (1 if existing else 0)
