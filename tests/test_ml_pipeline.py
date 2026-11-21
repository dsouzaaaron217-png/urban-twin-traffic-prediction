import pandas as pd
import numpy as np
import pytest

from ml.data_prep import (
    load_verified_phase1_dataset,
    load_raw_dataset,
    inspect_dataset_stats,
    construct_prediction_pairs,
    chronological_train_test_split,
    FEATURE_COLUMNS,
    build_as_of_features,
)
from ml.predict import TrafficPredictor
from ml.train import HistoricalAveragePredictor, check_feature_drift, phase1_corridor_coverage, rolling_origin_evaluation, rollback_model_version, train_horizon_model, train_pipeline


@pytest.fixture
def sample_traffic_df():
    """Generates synthetic multi-day traffic observations for 2 roads."""
    records = []
    base_time = pd.Timestamp("2026-10-15 08:00:00+05:30")
    for road in ["Central Pune", "Hinjawadi"]:
        base_ff = 50.0 if road == "Central Pune" else 60.0
        for i in range(40):
            t = base_time + pd.Timedelta(minutes=5 * i)
            # Speed varies realistically
            speed = base_ff - 10.0 + (5.0 if i % 2 == 0 else -5.0)
            congestion = round(max(0.0, 100.0 * (1.0 - speed / base_ff)), 1)
            records.append(
                {
                    "timestamp": t.isoformat(),
                    "city": "Pune",
                    "area": road,
                    "latitude": 18.5204 if road == "Central Pune" else 18.5913,
                    "longitude": 73.8567 if road == "Central Pune" else 73.7389,
                    "current_speed_kmh": speed,
                    "free_flow_speed_kmh": base_ff,
                    "current_travel_time_seconds": 300,
                    "free_flow_travel_time_seconds": 250,
                    "confidence": 0.9,
                    "congestion_percent": congestion,
                }
            )
    return pd.DataFrame(records)


def test_inspect_dataset_stats(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    stats = inspect_dataset_stats(sample_traffic_df)
    assert stats["total_rows"] == 80
    assert stats["unique_roads"] == 2
    assert stats["roads_with_repeated_observations"] == 2
    assert stats["has_sufficient_history"] is True


def test_target_construction_and_no_future_leakage(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    pairs = construct_prediction_pairs(sample_traffic_df, target_horizon_min=15)
    assert not pairs.empty
    assert len(pairs) > 30

    # Verify no future leakage: for every sample, target timestamp is strictly after current timestamp
    for _, row in pairs.iterrows():
        assert row["target_timestamp"] > row["timestamp"]
        diff_min = (row["target_timestamp"] - row["timestamp"]).total_seconds() / 60.0
        assert 10.0 <= diff_min <= 25.0
        # Target speed is physically valid
        assert row["target_speed_15m"] > 0


def test_as_of_features_ignore_future_observations(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    target = sample_traffic_df.iloc[10]
    before = build_as_of_features(sample_traffic_df, target)

    changed_future = sample_traffic_df.copy()
    future_mask = changed_future["dt"] > target["dt"]
    changed_future.loc[future_mask, "congestion_percent"] = 99.0
    changed_future.loc[future_mask, "current_speed_kmh"] = 1.0
    after = build_as_of_features(changed_future, target)

    for feature in FEATURE_COLUMNS:
        left, right = before[feature], after[feature]
        if pd.isna(left):
            assert pd.isna(right), feature
        else:
            assert left == right, feature


def test_chronological_split_prevents_temporal_leakage(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    pairs = construct_prediction_pairs(sample_traffic_df, target_horizon_min=15)
    train_df, test_df = chronological_train_test_split(pairs, test_ratio=0.25)

    assert len(train_df) > 0
    assert len(test_df) > 0
    # Total samples may be less than pairs due to purging boundary overlap (embargo gap)
    assert len(train_df) + len(test_df) <= len(pairs)

    # Maximum timestamp in train must be <= minimum timestamp in test
    assert train_df["timestamp"].max() <= test_df["timestamp"].min()

    # Embargo boundary verification: training targets must never leak into the test evaluation period
    assert train_df["target_timestamp"].max() <= test_df["timestamp"].min()


def test_predictor_segment_inference():
    predictor = TrafficPredictor()
    res = predictor.predict_segment(
        current_speed_kmh=35.0,
        free_flow_speed_kmh=50.0,
        congestion_percent=30.0,
        road_id="Test Road",
        city="Pune",
        area="Central Pune",
        historical_sample_count=30,
    )
    assert "predicted_speed_kmh" in res
    assert "predicted_congestion_percent" in res
    assert res["horizon_minutes"] == 15
    assert res["predicted_speed_kmh"] is not None
    assert 0 <= res["predicted_congestion_percent"] <= 100


def test_predictor_missing_inputs():
    predictor = TrafficPredictor()
    res = predictor.predict_segment(
        current_speed_kmh=None,
        free_flow_speed_kmh=None,
    )
    assert res["model_status"] == "invalid_input"
    assert res["predicted_speed_kmh"] is None



def test_neighbor_features_never_cross_city_or_area(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    observation = sample_traffic_df[sample_traffic_df["area"] == "Central Pune"].iloc[10]
    before = build_as_of_features(sample_traffic_df, observation)
    foreign = sample_traffic_df.copy()
    foreign["city"] = "Mangaluru"
    foreign["congestion_percent"] = 100.0
    after = build_as_of_features(pd.concat([sample_traffic_df, foreign]), observation)
    if pd.isna(before["neighbor_mean_congestion"]):
        assert pd.isna(after["neighbor_mean_congestion"])
    else:
        assert before["neighbor_mean_congestion"] == after["neighbor_mean_congestion"]


def test_rolling_origin_cv_purges_future_targets(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    pairs = construct_prediction_pairs(sample_traffic_df, horizon_minutes=15)
    folds = rolling_origin_evaluation(pairs)
    assert folds
    for fold in folds:
        assert fold["train_target_end"] < fold["validation_start"]
        assert fold["validation_samples"] > 0
        assert "congestion_macro_f1" in fold["metrics"]["HistGradientBoosting"]


def test_historical_average_predictor_serves_absolute_congestion(tmp_path):
    predictor = TrafficPredictor(models_dir=tmp_path, meta_path=tmp_path / "metadata.json")
    predictor.metadata = {
        "selected_model_by_horizon": {"15m": "HistoricalAvg"},
        "evaluation_by_horizon": {"15m": {"supported": True, "location_support": {}}},
    }
    predictor.models[15] = HistoricalAveragePredictor(
        {HistoricalAveragePredictor._key("Pune", "Central Pune", 8): 65.0}, 40.0
    )
    result = predictor.predict_segment(
        current_speed_kmh=40.0, free_flow_speed_kmh=50.0, congestion_percent=20.0,
        city="Pune", area="Central Pune", horizon_minutes=15, historical_sample_count=30,
        dt=__import__("datetime").datetime(2026, 11, 21, 8, 0, tzinfo=__import__("datetime").timezone(__import__("datetime").timedelta(hours=5, minutes=30))),
    )
    assert result["predicted_congestion_percent"] == 65.0
    assert result["model_status"] == "baseline_prediction"


def test_feature_drift_alert_uses_standardized_shift():
    reference = {"hour": {"mean": 8.0, "std": 2.0}}
    alert = check_feature_drift(reference, pd.DataFrame({"hour": [10.0, 10.0]}), threshold=0.5)
    assert alert["status"] == "alert"
    assert alert["alert"] is True


def test_model_registry_rolls_back_to_requested_version(tmp_path):
    version_dir = tmp_path / "versions" / "v1"
    version_dir.mkdir(parents=True)
    artifact = version_dir / "traffic_model_15m.joblib"
    artifact.write_bytes(b"model")
    metadata = {"model_version": "v1", "model_files": {"15": "versions/v1/traffic_model_15m.joblib"}}
    (version_dir / "metadata.json").write_text(__import__("json").dumps(metadata), encoding="utf-8")
    (tmp_path / "model_registry.json").write_text(__import__("json").dumps({
        "active_version": "v2", "previous_version": "v1", "versions": [
            {"version": "v1", "metadata_file": "versions/v1/metadata.json"}
        ]
    }), encoding="utf-8")
    activated = rollback_model_version(models_dir=tmp_path)
    assert activated["model_version"] == "v1"
    registry = __import__("json").loads((tmp_path / "model_registry.json").read_text(encoding="utf-8"))
    assert registry["active_version"] == "v1"



def test_horizon_report_has_corridor_period_metrics_and_skill_score(sample_traffic_df):
    sample_traffic_df["dt"] = pd.to_datetime(sample_traffic_df["timestamp"])
    result = train_horizon_model(sample_traffic_df, horizon_minutes=15)
    assert result["supported"] is True
    assert set(result["model_metrics"]) == {"mae_percent", "rmse_percent", "mape", "congestion_macro_f1"}
    assert result["per_corridor_metrics"]
    assert result["peak_off_peak_metrics"]
    assert "skill_score_vs_best_baseline" in result
    assert "fallback_reason" in result


def test_phase1_coverage_gate_requires_14_days_and_80_percent():
    now = pd.Timestamp("2026-11-21T12:00:00+05:30")
    times = pd.date_range(end=now, periods=14 * 24 * 4 + 1, freq="15min")
    rows = pd.DataFrame({
        "city": "Pune", "area": "Corridor A", "dt": times,
        "timestamp": times.astype(str),
    })
    ready = phase1_corridor_coverage(rows, now=now)[0]
    assert ready["ready"] is True
    sparse = rows.iloc[::2].copy()
    blocked = phase1_corridor_coverage(sparse, now=now)[0]
    assert blocked["ready"] is False
    assert blocked["coverage"] < 0.8


def test_blocked_training_preserves_active_artifacts(tmp_path, monkeypatch):
    import json
    import ml.train as training
    models = tmp_path / "models"
    models.mkdir()
    active_metadata = models / "model_metadata.json"
    active_metadata.write_text('{"model_version":"keep-me"}', encoding="utf-8")
    active_model = models / "traffic_model_15m.joblib"
    active_model.write_bytes(b"existing")
    monkeypatch.setattr(training, "load_verified_phase1_dataset", lambda: pd.DataFrame())
    result = train_pipeline(models_dir=models)
    assert result["status"] == "blocked"
    assert json.loads(active_metadata.read_text(encoding="utf-8"))["model_version"] == "keep-me"
    assert active_model.read_bytes() == b"existing"
    assert "Metrics are unavailable" in (tmp_path / "reports" / "evaluation.md").read_text(encoding="utf-8")



def test_unmonitored_route_segment_does_not_count_as_forecast_coverage():
    predictor = TrafficPredictor()
    result = predictor.predict_route(
        [{"id": "unknown", "current_speed_kmh": 20.0, "free_flow_speed_kmh": 40.0}],
        route_distance_km=1.0,
        route_travel_time_seconds=180,
    )
    assert result["coverage_percent"] == 0.0
    assert result["route_prediction_available"] is False
    assert result["segment_predictions"][0]["model_status"] == "insufficient_data"



def test_verified_loader_keeps_only_verified_provenance(tmp_path, monkeypatch):
    from contextlib import closing
    import sqlite3
    import services.phase1_pipeline as phase1
    database = tmp_path / "observations.sqlite3"
    monkeypatch.setattr(phase1, "DB_PATH", database)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("""CREATE TABLE observations (
            timestamp_utc TEXT, city TEXT, area TEXT, latitude REAL, longitude REAL,
            current_speed_kmh REAL, free_flow_speed_kmh REAL,
            current_travel_time_seconds REAL, free_flow_travel_time_seconds REAL,
            confidence REAL, congestion_percent REAL, source TEXT, quality TEXT, run_id TEXT
        )""")
        base = ("2026-11-21T08:00:00+00:00", "Pune", "Road A", 18.5, 73.8, 20, 40, 100, 50, 0.9, 50)
        rows = [
            (*base, "tomtom", "validated", "r1"),
            (*base, "verified_csv_import", "validated", "r2"),
            (*base, "csv_import", "validated", "r3"),
            (*base, "synthetic_demo", "synthetic_demo", "r4"),
            (*base, "tomtom", "invalid", "r5"),
        ]
        connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    eligible = load_verified_phase1_dataset()
    assert set(eligible["source"]) == {"tomtom", "verified_csv_import"}
    assert len(eligible) == 2



def test_unverified_legacy_models_are_not_loaded_or_reported(tmp_path):
    import json
    (tmp_path / "traffic_model_15m.joblib").write_bytes(b"unverified-placeholder")
    metadata = {
        "model_name": "LegacyModel", "supported_horizons": [15],
        "evaluation_by_horizon": {"15m": {"model_metrics": {"mae_percent": 1.0}}},
    }
    meta_path = tmp_path / "model_metadata.json"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    predictor = TrafficPredictor(models_dir=tmp_path, meta_path=meta_path)
    assert predictor.models == {}
    assert predictor.metadata["status"] == "legacy_unverified"
    assert predictor.metadata["evaluation_by_horizon"] == {}



def test_prediction_support_does_not_match_same_area_in_another_city(tmp_path):
    predictor = TrafficPredictor(models_dir=tmp_path, meta_path=tmp_path / "metadata.json")
    predictor.metadata = {
        "evaluation_by_horizon": {"15m": {"supported": True, "location_support": {
            "Mumbai:Central Road": {"city": "Mumbai", "area": "Central Road", "paired_samples": 50, "tier": "established"}
        }}},
    }
    result = predictor.predict_segment(
        current_speed_kmh=20.0, free_flow_speed_kmh=40.0, congestion_percent=50.0,
        city="Pune", area="Central Road", horizon_minutes=15,
    )
    assert result["model_status"] == "insufficient_data"
    assert result["predicted_congestion_percent"] is None



def test_successful_training_activates_a_version_without_touching_legacy_paths(tmp_path, monkeypatch):
    import ml.train as training
    from datetime import timezone
    now = pd.Timestamp.now(tz="Asia/Kolkata").floor("15min")
    times = pd.date_range(end=now, periods=14 * 24 * 4 + 1, freq="15min")
    rows = []
    for index, timestamp in enumerate(times):
        local_hour = timestamp.hour + timestamp.minute / 60.0
        speed = 32.0 + 7.0 * np.sin(2 * np.pi * index / 96.0) + 2.0 * np.sin(index / 11.0)
        free_flow = 50.0
        rows.append({
            "timestamp": timestamp.isoformat(), "dt": timestamp,
            "city": "Pune", "area": "Test Corridor",
            "latitude": 18.52, "longitude": 73.85,
            "current_speed_kmh": speed, "free_flow_speed_kmh": free_flow,
            "current_travel_time_seconds": 100.0, "free_flow_travel_time_seconds": 70.0,
            "confidence": 0.9,
            "congestion_percent": max(0.0, min(100.0, (1.0 - speed / free_flow) * 100.0)),
            "source": "tomtom", "quality": "validated", "run_id": "unit-test-run",
        })
    monkeypatch.setattr(training, "load_verified_phase1_dataset", lambda: pd.DataFrame(rows))
    models = tmp_path / "models"
    legacy = models / "traffic_model_15m.joblib"
    models.mkdir()
    legacy.write_bytes(b"keep-legacy-artifact")
    metadata = train_pipeline(models_dir=models)
    assert metadata["status"] == "ready"
    assert metadata["data_provenance_status"] == "verified"
    assert set(metadata["supported_horizons"]) == {15, 30, 60}
    assert all((models / value).is_file() for value in metadata["model_files"].values())
    assert legacy.read_bytes() == b"keep-legacy-artifact"
    assert (models / "model_registry.json").is_file()
    assert (tmp_path / "reports" / "evaluation.md").is_file()
    from ml.predict import TrafficPredictor
    predictor = TrafficPredictor(models_dir=models, meta_path=models / "model_metadata.json")
    assert predictor.is_available is True
    assert set(predictor.models) == {15, 30, 60}
