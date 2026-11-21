import sqlite3

import pytest

from services import phase1_pipeline as pipeline


@pytest.fixture
def phase1_db(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "DB_PATH", tmp_path / "phase1.sqlite3")
    return tmp_path / "phase1.sqlite3"


def sample(timestamp="2026-11-01T10:00:00+05:30"):
    return {
        "timestamp": timestamp, "city": "Mangaluru", "area": "Hampankatta",
        "latitude": 12.86784, "longitude": 74.842333,
        "current_speed_kmh": 24, "free_flow_speed_kmh": 40,
        "congestion_percent": 40, "confidence": 0.9,
    }


def test_observations_are_utc_idempotent_and_keep_provenance(phase1_db):
    run_id = pipeline.start_run("tomtom")
    row = sample()
    assert pipeline.record_observation(row, "tomtom", run_id)
    assert not pipeline.record_observation(row, "tomtom", run_id)
    with sqlite3.connect(phase1_db) as db:
        saved = db.execute("SELECT timestamp_utc,city,source,quality,run_id FROM observations").fetchone()
    assert saved == ("2026-11-01T04:30:00+00:00", "Mangaluru", "tomtom", "validated", run_id)


@pytest.mark.parametrize("changes", [
    {"current_speed_kmh": float("nan")},
    {"congestion_percent": 101},
    {"congestion_percent": None},
    {"city": ""},
])
def test_invalid_values_are_rejected_without_filling(changes, phase1_db):
    reading = sample()
    reading.update(changes)
    with pytest.raises(ValueError):
        pipeline.record_observation(reading, "tomtom", pipeline.start_run("tomtom"))


def test_google_spot_check_is_disabled_without_consuming_budget(phase1_db):
    called = False

    def request(*_args, **_kwargs):
        nonlocal called
        called = True

    source = pipeline.GoogleRoutesSource(request=request)
    with pytest.raises(RuntimeError, match="disabled"):
        source.fetch_spot_check("origin", "destination")
    assert not called
    with sqlite3.connect(phase1_db) as db:
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='daily_budget'").fetchone()[0] == 0


def test_google_spot_check_uses_budget_and_does_not_store_by_default(phase1_db):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"routes": [{"duration": "300s", "distanceMeters": 1200}]}

    calls = []
    source = pipeline.GoogleRoutesSource(
        api_key="mock-key", request=lambda *args, **kwargs: (calls.append((args, kwargs)) or Response()), enabled=True
    )
    result = source.fetch_spot_check({"latitude": 12.8, "longitude": 74.8}, {"latitude": 12.9, "longitude": 74.9})
    assert result["store"] is False
    assert result["source"] == "google_routes"
    assert len(calls) == 1
    with sqlite3.connect(phase1_db) as db:
        assert db.execute("SELECT used FROM daily_budget WHERE provider='google_routes'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_restart_marks_open_runs_interrupted(phase1_db):
    run_id = pipeline.start_run("tomtom")
    assert pipeline.recover_interrupted_runs() == 1
    with sqlite3.connect(phase1_db) as db:
        assert db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "interrupted"


def test_readiness_reports_collecting_state_for_sparse_history(phase1_db):
    run_id = pipeline.start_run("csv_import")
    pipeline.record_observation(sample("2026-10-15T10:00:00+05:30"), "csv_import", run_id)
    result = pipeline.readiness()
    assert len(result["corridors"]) == 1
    assert result["corridors"][0]["ready"] is False
    assert result["corridors"][0]["message"].startswith("Collecting data:")
