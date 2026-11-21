"""
TrafficWatch Machine Learning Model Training & Multi-Horizon Evaluation Pipeline
- Trains and evaluates models for 15m, 30m, and 60m forecast horizons on cleaned historical dataset.
- Evaluates candidate algorithms (Persistence, Historical Average, Random Forest, HistGradientBoosting, Ridge).
- Rigorous 3-way chronological split (Train 60%, Validation 20%, Held-Out Test 20%) with strict embargo boundary gaps.
- Selects the best model independently for each horizon based on validation error.
- Evaluates all models and baselines on the exact same held-out test rows and per corridor.
- Produces persistent model artifacts with safe backup replacement and comprehensive model_metadata.json.
"""

import json
import hashlib
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.metrics import f1_score
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.data_prep import (
    FEATURE_COLUMNS,
    HORIZON_CONFIGS,
    load_dataset,
    inspect_dataset_stats,
    construct_prediction_pairs,
    chronological_train_test_split,
    chronological_train_val_test_split,
    load_verified_phase1_dataset,
)
from services.data_pipeline import CLEANED_CSV_FILE

MIN_HISTORY_DAYS = 14
MIN_COVERAGE = 0.80
POLL_INTERVAL_MINUTES = 15
QUALIFIED_SOURCES = {"tomtom", "verified_csv_import"}
QUALIFIED_QUALITY = {"validated", "gap_after_previous_observation"}


def phase1_corridor_coverage(df: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> List[Dict[str, Any]]:
    """Compute 14-day polling coverage per city/corridor without filling missing slots."""
    if df.empty:
        return []
    now = now or pd.Timestamp.now(tz="Asia/Kolkata")
    now = now.tz_convert("Asia/Kolkata") if now.tzinfo else now.tz_localize("Asia/Kolkata")
    start = now - pd.Timedelta(days=MIN_HISTORY_DAYS)
    expected = MIN_HISTORY_DAYS * 24 * 60 / POLL_INTERVAL_MINUTES
    coverage_rows = []
    for (city, area), group in df.groupby(["city", "area"]):
        recent = group[(group["dt"] >= start) & (group["dt"] <= now)]
        first, last = group["dt"].min(), group["dt"].max()
        coverage = min(1.0, len(recent) / expected)
        history_days = max(0, (last.date() - first.date()).days + 1)
        ready = bool(
            first <= start
            and last >= now - pd.Timedelta(minutes=2 * POLL_INTERVAL_MINUTES)
            and coverage >= MIN_COVERAGE
        )
        coverage_rows.append({
            "city": str(city), "area": str(area), "observations_14d": int(len(recent)),
            "expected_observations_14d": int(expected), "coverage": round(coverage, 4),
            "history_days": history_days, "first_timestamp": first.isoformat(),
            "last_timestamp": last.isoformat(), "ready": ready,
        })
    return coverage_rows


def write_blocked_training_report(models_dir: Path, reason: str, row_count: int = 0,
                                  coverage: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Write an honest blocked report without touching active artifacts or metadata."""
    reports_dir = models_dir.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    coverage_rows = coverage or []
    report_lines = [
        "# Phase 2 Evaluation", "", "## Status: Training blocked", "",
        f"Reason: {reason}", "", f"Eligible verified observations: {row_count}",
        f"Required corridor history: at least {MIN_HISTORY_DAYS} days and {MIN_COVERAGE:.0%} polling coverage.",
        "No model artifacts or active model metadata were changed by this run.", "",
        "## Corridor readiness", "", "| City | Corridor | Rows in 14d | Coverage | History days | Ready |",
        "|---|---|---:|---:|---:|---|",
    ]
    if coverage_rows:
        report_lines.extend(
            f"| {r['city']} | {r['area']} | {r['observations_14d']} | {r['coverage']:.1%} | {r['history_days']} | {r['ready']} |"
            for r in coverage_rows
        )
    else:
        report_lines.append("| — | No provenance-qualified observations | 0 | 0% | 0 | False |")
    report_lines += [
        "", "## Data provenance and limitations", "",
        "The production training path uses provenance-qualified Phase 1 observations only. "
        "The legacy cleaned CSV is excluded because it has no row-level source/quality provenance. "
        "Metrics are unavailable; no synthetic observations or fabricated scores were used.", "",
    ]
    (reports_dir / "evaluation.md").write_text("\n".join(report_lines), encoding="utf-8")
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "MODEL_CARD.md").write_text(
        "# TrafficWatch model card\n\nStatus: no new model was trained.\n\n"
        f"Training is blocked: {reason}\n\n"
        "No production model was selected or replaced. The legacy CSV lacks row-level provenance, "
        "and forecasts remain subject to the Phase 1 corridor readiness gate.\n",
        encoding="utf-8",
    )
    return {"status": "blocked", "reason": reason, "eligible_data_rows": row_count,
            "corridor_readiness": coverage_rows, "report_path": str(reports_dir / "evaluation.md")}


class PersistencePredictor:
    """
    Predictor implementing the persistence baseline (delta = 0).
    Returns zero delta so future traffic retains current conditions,
    which is empirically optimal during steady-state traffic periods.
    """
    def __init__(self, horizon_minutes: int = 15):
        self.horizon_minutes = horizon_minutes
        self.model_name = "Persistence"

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        n = len(X) if hasattr(X, "__len__") else 1
        return np.zeros(n, dtype=float)


class HistoricalAveragePredictor:
    """Per-city, corridor, local-hour congestion average with a train-only fallback."""
    model_name = "HistoricalAvg"

    def __init__(self, averages: Dict[str, float], global_mean: float):
        self.averages = averages
        self.global_mean = float(global_mean)

    @staticmethod
    def _key(city: Optional[str], area: Optional[str], hour: float) -> str:
        return f"{(city or '').casefold()}|{(area or '').casefold()}|{int(hour) % 24}"

    def predict_for_location(self, city: Optional[str], area: Optional[str], hour: float) -> float:
        return float(self.averages.get(self._key(city, area, hour), self.global_mean))

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        if isinstance(X, pd.DataFrame):
            return np.asarray([self.predict_for_location(None, None, float(h)) for h in X["hour"]])
        return np.full(len(X), self.global_mean, dtype=float)


def compute_robust_mape(y_true: np.ndarray | pd.Series, y_pred: np.ndarray | pd.Series) -> float:
    """Computes Mean Absolute Percentage Error, protected against near-zero division."""
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    denom = np.maximum(y_t, 5.0)
    mape = np.mean(np.abs(y_t - y_p) / denom) * 100.0
    return round(float(mape), 2)


def congestion_class(values: np.ndarray | pd.Series) -> np.ndarray:
    """low <30%, moderate 30–<60%, heavy >=60%."""
    return np.digitize(np.asarray(values, dtype=float), bins=[30.0, 60.0], right=False)


def calculate_metrics(y_true: np.ndarray | pd.Series, y_pred: np.ndarray | pd.Series) -> Dict[str, float]:
    truth = np.asarray(y_true, dtype=float)
    prediction = np.asarray(y_pred, dtype=float)
    return {
        "mae_percent": round(float(mean_absolute_error(truth, prediction)), 3),
        "rmse_percent": round(float(root_mean_squared_error(truth, prediction)), 3),
        "mape": compute_robust_mape(truth, prediction),
        "congestion_macro_f1": round(float(f1_score(
            congestion_class(truth), congestion_class(prediction), labels=[0, 1, 2], average="macro", zero_division=0
        )), 4),
    }


def rolling_origin_evaluation(paired_df: pd.DataFrame, folds: int = 3) -> List[Dict[str, Any]]:
    """Expanding-window CV with target-time purging; every fold trains on the past only."""
    ordered = paired_df.sort_values("timestamp").copy()
    times = pd.Index(ordered["timestamp"].drop_duplicates().sort_values())
    if len(times) < 12:
        return []
    initial = max(8, int(len(times) * 0.5))
    block = max(1, (len(times) - initial) // folds)
    results: List[Dict[str, Any]] = []
    for fold in range(folds):
        start_index = initial + fold * block
        if start_index >= len(times):
            break
        end_index = min(len(times), start_index + block)
        validation_start = times[start_index]
        validation_end = times[end_index] if end_index < len(times) else None
        train = ordered[ordered["target_timestamp"] < validation_start]
        val_mask = ordered["timestamp"] >= validation_start
        if validation_end is not None:
            val_mask &= ordered["timestamp"] < validation_end
        validation = ordered[val_mask]
        if len(train) < 10 or validation.empty:
            continue
        X_train, X_val = train[FEATURE_COLUMNS], validation[FEATURE_COLUMNS]
        y_delta = train["target_congestion"] - train["current_congestion_percent"]
        learner = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", HistGradientBoostingRegressor(
                max_iter=60, max_depth=4, min_samples_leaf=15, l2_regularization=10.0, random_state=42
            )),
        ])
        learner.fit(X_train, y_delta)
        truth = validation["target_congestion"].to_numpy(dtype=float)
        persistence = validation["current_congestion_percent"].to_numpy(dtype=float)
        ml_prediction = np.clip(persistence + learner.predict(X_val), 0.0, 100.0)
        hist = train.groupby(["city", "area", "hour"])["target_congestion"].mean().to_dict()
        global_mean = float(train["target_congestion"].mean())
        historical = np.asarray([
            hist.get((row.city, row.area, row.hour), global_mean)
            for row in validation.itertuples()
        ], dtype=float)
        results.append({
            "fold": fold + 1,
            "train_samples": int(len(train)),
            "validation_samples": int(len(validation)),
            "train_target_end": train["target_timestamp"].max().isoformat(),
            "validation_start": validation["timestamp"].min().isoformat(),
            "validation_end": validation["timestamp"].max().isoformat(),
            "metrics": {
                "Persistence": calculate_metrics(truth, persistence),
                "HistoricalAvg": calculate_metrics(truth, historical),
                "HistGradientBoosting": calculate_metrics(truth, ml_prediction),
            },
        })
    return results


def atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def write_success_reports(models_dir: Path, metadata: Dict[str, Any]) -> None:
    reports_dir = models_dir.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 2 Evaluation", "", "Status: completed from provenance-qualified observations.",
        f"Model version: `{metadata['model_version']}`",
        f"Data source: `{metadata['dataset_path']}`",
        f"Training range: {metadata.get('training_range', ['unknown', 'unknown'])[0]} to {metadata.get('training_range', ['unknown', 'unknown'])[-1]}",
        f"Rows: {metadata.get('total_dataset_rows', 0)}", "",
    ]
    for horizon, result in metadata.get("evaluation_by_horizon", {}).items():
        lines.extend([f"## {horizon}", ""])
        if not result.get("supported"):
            lines.extend([f"Not supported: {result.get('reason', 'insufficient paired observations')}", ""])
            continue
        lines.extend([
            f"Selected model: **{result['selected_model_name']}**. {result.get('fallback_reason') or result.get('selection_rationale', '')}",
            f"Paired samples: {result['total_pairs']} (train {result['train_samples']}, validation {result['val_samples']}, test {result['test_samples']}).",
            f"Test metrics: MAE {result['model_metrics']['mae_percent']}%, RMSE {result['model_metrics']['rmse_percent']}%, MAPE {result['model_metrics']['mape']}%, congestion macro-F1 {result['model_metrics']['congestion_macro_f1']}.",
            f"Skill score vs best validation baseline: {result.get('skill_score_vs_best_baseline')}", "",
            "### Test metrics by corridor", "", "| City | Corridor | Samples | MAE | RMSE | MAPE | Macro-F1 | Skill vs baseline |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ])
        for row in result.get("per_corridor_metrics", []):
            m = row["selected"]
            lines.append(f"| {row['city']} | {row['area']} | {row['samples']} | {m['mae_percent']} | {m['rmse_percent']} | {m['mape']} | {m['congestion_macro_f1']} | {row['skill_score_vs_best_baseline']} |")
        lines.extend(["", "### Peak vs off-peak", "", "| Period | Samples | MAE | RMSE | MAPE | Macro-F1 | Skill vs baseline |", "|---|---:|---:|---:|---:|---:|---:|"])
        for period, item in result.get("peak_off_peak_metrics", {}).items():
            m = item["selected"]
            lines.append(f"| {period} | {item['samples']} | {m['mae_percent']} | {m['rmse_percent']} | {m['mape']} | {m['congestion_macro_f1']} | {item['skill_score_vs_best_baseline']} |")
        lines.extend(["", "### Rolling-origin cross-validation", ""])
        if result.get("rolling_origin_cv"):
            for fold in result["rolling_origin_cv"]:
                metrics = fold["metrics"]
                lines.append(f"- Fold {fold['fold']}: {fold['train_samples']} training and {fold['validation_samples']} validation pairs; HGB MAE {metrics['HistGradientBoosting']['mae_percent']}%, Persistence MAE {metrics['Persistence']['mae_percent']}%.")
        else:
            lines.append("Not available: too few distinct timestamps for three leakage-safe expanding folds.")
        lines.append("")
    lines.extend(["## Data and limitations", "", "Only provenance-qualified observations were used. No missing readings were filled. Forecast readiness is corridor-specific. GRU/LSTM/graph models were not selected because current verified data volume is not sufficient to justify them.", ""])
    (reports_dir / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    card = [
        "# TrafficWatch model card", "", f"Version: `{metadata['model_version']}`",
        f"Training data: `{metadata['dataset_path']}`", f"Training range: {metadata.get('training_range')}",
        f"Training cutoff: {metadata.get('training_data_cutoff_timestamp')}",
        f"Selected models: {metadata.get('selected_model_by_horizon')}",
        "", "## Intended use", "Short-horizon congestion forecasts for corridors that passed the verified-data readiness gate.",
        "", "## Limitations", *[f"- {item}" for item in metadata.get("limitations", [])],
        "", "See `reports/evaluation.md` for horizon, corridor, and peak/off-peak metrics.", "",
    ]
    (models_dir / "MODEL_CARD.md").write_text("\n".join(card), encoding="utf-8")


def check_feature_drift(reference: Dict[str, Dict[str, float]], current: pd.DataFrame, threshold: float = 0.5) -> Dict[str, Any]:
    """Simple standardized mean-shift monitor; returns unavailable when evidence is absent."""
    shifts = {}
    for feature, baseline in reference.items():
        if feature not in current:
            continue
        values = pd.to_numeric(current[feature], errors="coerce").dropna()
        if values.empty:
            continue
        scale = max(float(baseline.get("std", 0.0)), 1e-6)
        shifts[feature] = round(abs(float(values.mean()) - float(baseline.get("mean", 0.0))) / scale, 3)
    if not shifts:
        return {"status": "unavailable", "alert": False, "message": "No comparable recent feature observations."}
    maximum = max(shifts.values())
    return {
        "status": "alert" if maximum >= threshold else "clear",
        "alert": maximum >= threshold,
        "threshold_standard_deviations": threshold,
        "max_shift_standard_deviations": maximum,
        "shifted_features": {name: value for name, value in shifts.items() if value >= threshold},
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def get_drift_status(models_dir: str | Path = "models") -> Dict[str, Any]:
    """Compare the latest verified 15-minute feature windows with the active model reference."""
    models_dir = Path(models_dir)
    try:
        metadata = json.loads((models_dir / "model_metadata.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unavailable", "alert": False, "message": "No active model metadata."}
    reference = metadata.get("feature_reference") or {}
    if not reference:
        return {"status": "unavailable", "alert": False, "message": "This model version has no drift reference."}
    data = load_verified_phase1_dataset()
    if data.empty:
        return {"status": "unavailable", "alert": False, "message": "No verified observations are available for drift monitoring."}
    paired = construct_prediction_pairs(data, horizon_minutes=15)
    if paired.empty:
        return {"status": "unavailable", "alert": False, "message": "Not enough recent verified observations for drift monitoring."}
    recent_start = paired["timestamp"].max() - pd.Timedelta(days=1)
    recent = paired[paired["timestamp"] >= recent_start]
    status = check_feature_drift(reference, recent)
    status["model_version"] = metadata.get("model_version")
    status["recent_samples"] = int(len(recent))
    return status


def rollback_model_version(version: Optional[str] = None, models_dir: str | Path = "models") -> Dict[str, Any]:
    """Atomically activate a registered version, defaulting to the prior active version."""
    models_dir = Path(models_dir)
    registry_path = models_dir / "model_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError("No model registry is available for rollback.") from exc
    target = version or registry.get("previous_version")
    entry = next((item for item in registry.get("versions", []) if item.get("version") == target), None)
    if not entry:
        raise ValueError(f"Registered model version not found: {target}")
    metadata_path = models_dir / entry["metadata_file"]
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(f"Metadata for model version {target} is missing.") from exc
    for relative in metadata.get("model_files", {}).values():
        if not (models_dir / relative).is_file():
            raise FileNotFoundError(f"Artifact for model version {target} is missing: {relative}")
    prior_active = registry.get("active_version")
    atomic_write_json(models_dir / "model_metadata.json", metadata)
    registry["active_version"] = target
    registry["previous_version"] = prior_active
    atomic_write_json(registry_path, registry)
    return metadata


def train_horizon_model(
    df: pd.DataFrame,
    horizon_minutes: int,
    val_ratio: float = 0.20,
    test_ratio: float = 0.20,
) -> Dict[str, Any]:
    """
    Trains and rigorously evaluates candidate models for a single forecast horizon.
    Uses chronological validation for model selection and reserves a final held-out
    test set for unbiased evaluation.
    """
    paired_df = construct_prediction_pairs(df, horizon_minutes=horizon_minutes)
    if paired_df.empty or len(paired_df) < 15:
        return {
            "horizon_minutes": horizon_minutes,
            "supported": False,
            "reason": f"Insufficient paired observations ({len(paired_df)} found).",
            "model": None,
        }

    # Chronological 3-way split: Train (60%), Validation (20%), Held-Out Test (20%)
    train_df, val_df, test_df = chronological_train_val_test_split(
        paired_df, val_ratio=val_ratio, test_ratio=test_ratio
    )

    X_train = train_df[FEATURE_COLUMNS]
    y_train_delta = train_df["target_congestion"] - train_df["current_congestion_percent"]
    y_train_target = train_df["target_congestion"].values

    X_val = val_df[FEATURE_COLUMNS]
    y_val_target = val_df["target_congestion"].values
    val_cur_cong = val_df["current_congestion_percent"].values

    X_test = test_df[FEATURE_COLUMNS]
    y_test_target = test_df["target_congestion"].values
    test_cur_cong = test_df["current_congestion_percent"].values

    # Train Candidates:
    # 1. Historical Average baseline map from train
    hist_map = train_df.groupby(["city", "area", "hour"])["target_congestion"].mean().to_dict()
    historical_average = HistoricalAveragePredictor(
        {HistoricalAveragePredictor._key(c, a, h): float(value) for (c, a, h), value in hist_map.items()},
        float(train_df["target_congestion"].mean()),
    )
    global_mean = float(train_df["target_congestion"].mean())
    def hist_predict(df_sub):
        return df_sub.apply(
            lambda r: historical_average.predict_for_location(r["city"], r["area"], r["hour"]), axis=1
        ).values

    # 2. Random Forest Regressor
    rf = Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("model", RandomForestRegressor(
            n_estimators=100, max_depth=5, min_samples_split=6, min_samples_leaf=5, random_state=42
        )),
    ])
    rf.fit(X_train, y_train_delta)

    # 3. HistGradientBoostingRegressor
    hgb = Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("model", HistGradientBoostingRegressor(
            max_iter=60, max_depth=4, min_samples_leaf=15, l2_regularization=10.0, random_state=42
        )),
    ])
    hgb.fit(X_train, y_train_delta)

    # 4. Ridge Regression
    ridge = Pipeline([
        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("scaler", StandardScaler()),
        ("model", RidgeCV(alphas=np.logspace(-2, 4, 20))),
    ])
    ridge.fit(X_train, y_train_delta)

    # 5. Persistence Predictor
    persist_predictor = PersistencePredictor(horizon_minutes=horizon_minutes)

    # Candidate predictor definitions for production selection
    candidates = {
        "Persistence": {
            "model_obj": persist_predictor,
            "val_pred": val_cur_cong,
            "test_pred": test_cur_cong,
            "algorithm": "Persistence Baseline (maintains current conditions, delta = 0)",
        },
        "RandomForest": {
            "model_obj": rf,
            "val_pred": np.clip(val_cur_cong + rf.predict(X_val), 0.0, 100.0),
            "test_pred": np.clip(test_cur_cong + rf.predict(X_test), 0.0, 100.0),
            "algorithm": "RandomForestRegressor (residual delta formulation)",
        },
        "HistGradientBoosting": {
            "model_obj": hgb,
            "val_pred": np.clip(val_cur_cong + hgb.predict(X_val), 0.0, 100.0),
            "test_pred": np.clip(test_cur_cong + hgb.predict(X_test), 0.0, 100.0),
            "algorithm": "HistGradientBoostingRegressor (regularized boosting)",
        },
        "Ridge": {
            "model_obj": ridge,
            "val_pred": np.clip(val_cur_cong + ridge.predict(X_val), 0.0, 100.0),
            "test_pred": np.clip(test_cur_cong + ridge.predict(X_test), 0.0, 100.0),
            "algorithm": "RidgeCV (regularized linear delta formulation)",
        },
        "HistoricalAvg": {
            "model_obj": historical_average,
            "val_pred": hist_predict(val_df),
            "test_pred": hist_predict(test_df),
            "algorithm": "Train-only city/corridor/local-hour historical average",
        },
    }

    # Historical average is evaluated strictly as a baseline
    hist_val_pred = hist_predict(val_df)
    hist_test_pred = hist_predict(test_df)

    # Evaluate Validation Performance for Model Selection
    val_metrics = {
        name: calculate_metrics(y_val_target, cinfo["val_pred"])
        for name, cinfo in candidates.items()
    }

    # Evaluate Held-Out Test Performance (Unbiased Final Benchmark)
    test_metrics = {
        name: calculate_metrics(y_test_target, cinfo["test_pred"])
        for name, cinfo in candidates.items()
    }

    # ML is eligible for serving only when it beats the best baseline on validation.
    baseline_name = min(("Persistence", "HistoricalAvg"), key=lambda name: val_metrics[name]["mae_percent"])
    baseline_val_mae = val_metrics[baseline_name]["mae_percent"]
    ml_candidate_name = "HistGradientBoosting"
    ml_val_mae = val_metrics[ml_candidate_name]["mae_percent"]
    if ml_val_mae < baseline_val_mae:
        selected_name = ml_candidate_name
        fallback_reason = None
        selection_rationale = (
            f"HistGradientBoosting beat the best validation baseline ({baseline_name}) on MAE."
        )
    else:
        selected_name = baseline_name
        fallback_reason = (
            f"{baseline_name} served because HistGradientBoosting did not beat the best baseline on validation."
        )
        selection_rationale = fallback_reason

    selected_model_obj = candidates[selected_name]["model_obj"]

    # Feature importances if tree model selected
    feature_importances = {}
    selected_estimator = (
        selected_model_obj.named_steps.get("model")
        if isinstance(selected_model_obj, Pipeline)
        else selected_model_obj
    )
    if hasattr(selected_estimator, "feature_importances_"):
        feature_importances = {
            col: round(float(imp), 4)
            for col, imp in zip(FEATURE_COLUMNS, selected_estimator.feature_importances_)
        }
    elif hasattr(hgb.named_steps["model"], "feature_importances_"):
        feature_importances = {
            col: round(float(imp), 4)
            for col, imp in zip(FEATURE_COLUMNS, hgb.named_steps["model"].feature_importances_)
        }

    test_df_eval = test_df.copy()
    test_df_eval["y_true"] = y_test_target
    test_df_eval["sel_pred"] = candidates[selected_name]["test_pred"]
    per_corridor_metrics = []
    for (city, area), grp in test_df_eval.groupby(["city", "area"]):
        per_corridor_metrics.append({
            "city": str(city), "area": str(area), "samples": int(len(grp)),
            "selected": calculate_metrics(grp["y_true"], grp["sel_pred"]),
            "best_baseline": calculate_metrics(
                grp["y_true"], candidates[baseline_name]["test_pred"][grp.index]
            ),
            "skill_score_vs_best_baseline": round(1.0 - calculate_metrics(
                grp["y_true"], candidates[selected_name]["test_pred"][grp.index]
            )["mae_percent"] / max(calculate_metrics(
                grp["y_true"], candidates[baseline_name]["test_pred"][grp.index]
            )["mae_percent"], 1e-9), 4),
        })
    test_df_eval["period"] = np.where(
        test_df_eval["hour"].between(7, 10, inclusive="both") | test_df_eval["hour"].between(16, 19, inclusive="both"),
        "peak", "off_peak"
    )
    peak_off_peak_metrics = {}
    for period, grp in test_df_eval.groupby("period"):
        selected_period_metrics = calculate_metrics(grp["y_true"], grp["sel_pred"])
        baseline_period_metrics = calculate_metrics(
            grp["y_true"], candidates[baseline_name]["test_pred"][grp.index]
        )
        peak_off_peak_metrics[period] = {
            "samples": int(len(grp)),
            "selected": selected_period_metrics,
            "best_baseline": baseline_period_metrics,
            "skill_score_vs_best_baseline": round(
                1.0 - selected_period_metrics["mae_percent"] /
                max(baseline_period_metrics["mae_percent"], 1e-9), 4
            ),
        }
    corridor_evaluations = {
        f"{row['city']}:{row['area']}": {
            "city": row["city"], "area": row["area"], "test_samples": row["samples"],
            "selected_model_mae": row["selected"]["mae_percent"],
            "best_baseline_mae": row["best_baseline"]["mae_percent"],
            "best_on_corridor": selected_name if row["selected"]["mae_percent"] < row["best_baseline"]["mae_percent"] else baseline_name,
        }
        for row in per_corridor_metrics
    }
    selected_test_mae = test_metrics[selected_name]["mae_percent"]
    baseline_test_mae = test_metrics[baseline_name]["mae_percent"]
    skill_score = round(1.0 - selected_test_mae / max(baseline_test_mae, 1e-9), 4)
    rolling_cv = rolling_origin_evaluation(paired_df)

    # Location-level sample support for this horizon
    loc_counts = paired_df.groupby(["city", "area"]).size().to_dict()
    location_readiness = {}
    for (c, a), cnt in loc_counts.items():
        if cnt >= 25:
            tier = "established"
        elif cnt >= 8:
            tier = "experimental"
        else:
            tier = "insufficient"
        location_readiness[f"{c}:{a}"] = {
            "city": c,
            "area": a,
            "paired_samples": cnt,
            "tier": tier,
        }

    # Latest observation timestamp in train set (training cutoff)
    train_cutoff = train_df["timestamp"].max().isoformat() if not train_df.empty else None

    return {
        "horizon_minutes": horizon_minutes,
        "supported": True,
        "selected_model_name": selected_name,
        "selected_algorithm": candidates[selected_name]["algorithm"],
        "selection_rationale": selection_rationale,
        "fallback_reason": fallback_reason,
        "model": selected_model_obj,
        "total_pairs": len(paired_df),
        "train_samples": len(train_df),
        "val_samples": len(val_df),
        "test_samples": len(test_df),
        "train_time_range": [
            train_df["timestamp"].min().isoformat(),
            train_df["timestamp"].max().isoformat(),
        ],
        "val_time_range": [
            val_df["timestamp"].min().isoformat(),
            val_df["timestamp"].max().isoformat(),
        ],
        "test_time_range": [
            test_df["timestamp"].min().isoformat(),
            test_df["timestamp"].max().isoformat(),
        ],
        "training_data_cutoff_timestamp": train_cutoff,
        "validation_metrics": val_metrics,
        "test_metrics": test_metrics,
        "skill_score_vs_best_baseline": skill_score,
        "best_baseline_name": baseline_name,
        "per_corridor_metrics": per_corridor_metrics,
        "peak_off_peak_metrics": peak_off_peak_metrics,
        "rolling_origin_cv": rolling_cv,
        "model_metrics": test_metrics[selected_name],
        "persistence_baseline": test_metrics["Persistence"],
        "historical_avg_baseline": test_metrics["HistoricalAvg"],
        "random_forest_metrics": test_metrics["RandomForest"],
        "beats_baseline_mae": test_metrics[selected_name]["mae_percent"] < test_metrics[baseline_name]["mae_percent"],
        "beats_baseline_rmse": test_metrics[selected_name]["rmse_percent"] < test_metrics[baseline_name]["rmse_percent"],
        "feature_reference": {
            feature: {
                "mean": float(train_df[feature].mean()) if train_df[feature].notna().any() else 0.0,
                "std": float(train_df[feature].std(ddof=0)) if train_df[feature].notna().any() else 0.0,
            }
            for feature in FEATURE_COLUMNS
        },
        "feature_importances": feature_importances,
        "corridor_evaluations": corridor_evaluations,
        "location_support": location_readiness,
    }


def train_pipeline(
    csv_path: Optional[str | Path] = None,
    models_dir: str | Path = "models",
    val_ratio: float = 0.20,
    test_ratio: float = 0.20,
) -> Dict[str, Any]:
    """
    Executes the multi-horizon machine learning training, validation, and evaluation pipeline.
    Selects the best model independently for 15m, 30m, and 60m horizons.
    Safely creates backup versions of previous models before replacing them.
    """
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[{datetime.now().isoformat()}] Starting TrafficWatch Multi-Horizon ML Training Pipeline...")

    if csv_path is None:
        df = load_verified_phase1_dataset()
        dataset_label = "data/phase1_ingestion.sqlite3 (TomTom, validated rows)"
    else:
        df = load_dataset(csv_path)
        dataset_label = str(csv_path)
        if not {"source", "quality"}.issubset(df.columns):
            return write_blocked_training_report(
                models_dir,
                "Selected dataset has no row-level source and quality provenance; legacy rows are not eligible for production training.",
                row_count=0,
            )

    if df.empty:
        legacy_rows = 0
        try:
            legacy_rows = sum(1 for _ in open(CLEANED_CSV_FILE, encoding="utf-8")) - 1
        except OSError:
            pass
        return write_blocked_training_report(
            models_dir,
            f"No provenance-qualified Phase 1 observations are available. Legacy cleaned CSV rows ({max(legacy_rows, 0)}) are excluded because their source/quality cannot be verified.",
            row_count=0,
        )

    # Exclude synthetic/demo and unvalidated rows even if they are present in an import.
    df["source"] = df["source"].astype(str).str.casefold()
    df["quality"] = df["quality"].astype(str).str.casefold()
    df = df[df["source"].isin(QUALIFIED_SOURCES) & df["quality"].isin(QUALIFIED_QUALITY)].copy()
    if df.empty:
        return write_blocked_training_report(
            models_dir, "No rows have an approved real-data source and validated quality label.", row_count=0
        )

    coverage_rows = phase1_corridor_coverage(df)
    ready_keys = {(row["city"], row["area"]) for row in coverage_rows if row["ready"]}
    if not ready_keys:
        return write_blocked_training_report(
            models_dir,
            "No corridor meets the Phase 1 14-day history and 80% coverage gate.",
            row_count=len(df), coverage=coverage_rows,
        )
    df = df[df.apply(lambda row: (str(row["city"]), str(row["area"])) in ready_keys, axis=1)].copy()

    stats = inspect_dataset_stats(df)
    print(f"Cleaned Dataset: {stats['total_rows']} rows across {stats['unique_roads']} areas")
    print(f"Time span: {stats['earliest_timestamp']} to {stats['latest_timestamp']} ({stats['time_span_hours']}h)")

    horizons = [15, 30, 60]
    horizon_results: Dict[str, Any] = {}
    supported_horizons: List[int] = []
    selected_models: Dict[str, str] = {}
    pending_models: Dict[int, Any] = {}

    for h in horizons:
        print(f"\n--- Training & Evaluating {h}-Minute Horizon ---")
        res = train_horizon_model(df, horizon_minutes=h, val_ratio=val_ratio, test_ratio=test_ratio)
        if res["supported"]:
            pending_models[h] = res.pop("model")

            supported_horizons.append(h)
            selected_models[f"{h}m"] = res["selected_model_name"]

            sel_m = res["model_metrics"]
            p_m = res["persistence_baseline"]
            rf_m = res["random_forest_metrics"]
            print(f"  Selected Model:      {res['selected_model_name']} ({res['selected_algorithm']})")
            print(f"  Selected Test Error: MAE = {sel_m['mae_percent']:.3f}%, RMSE = {sel_m['rmse_percent']:.3f}%, MAPE = {sel_m['mape']:.2f}%")
            print(f"  Persistence Base:    MAE = {p_m['mae_percent']:.3f}%, RMSE = {p_m['rmse_percent']:.3f}%, MAPE = {p_m['mape']:.2f}%")
            print(f"  Random Forest:       MAE = {rf_m['mae_percent']:.3f}%, RMSE = {rf_m['rmse_percent']:.3f}%, MAPE = {rf_m['mape']:.2f}%")
            print(f"  Selection Rationale: {res['selection_rationale']}")

            horizon_results[f"{h}m"] = res
        else:
            print(f"  Horizon {h}m unsupported: {res['reason']}")
            horizon_results[f"{h}m"] = res

    if not pending_models:
        return write_blocked_training_report(
            models_dir, "No horizon has enough valid time-paired observations for chronological evaluation.",
            row_count=len(df), coverage=coverage_rows,
        )

    # Global training cutoff (latest timestamp in train partitions)
    cutoff_ts = max(
        (r.get("training_data_cutoff_timestamp") for r in horizon_results.values() if r.get("training_data_cutoff_timestamp")),
        default=datetime.now(timezone.utc).isoformat(),
    )

    # Primary model name
    primary_model_name = selected_models.get("15m", "Persistence")

    # Generate metadata
    metadata = {
        "model_name": primary_model_name,
        "status": "ready",
        "model_version": "pending",
        "data_provenance_status": "verified",
        "training_sources": sorted(df["source"].dropna().astype(str).unique().tolist()),
        "previous_version": None,
        "model_files": {},
        "selected_model_by_horizon": selected_models,
        "supported_horizons": supported_horizons,
        "target": "congestion_percent_delta",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data_cutoff_timestamp": cutoff_ts,
        "training_range": [min((r.get("train_time_range", [None, None])[0] for r in horizon_results.values() if r.get("supported")), default=None), max((r.get("train_time_range", [None, None])[1] for r in horizon_results.values() if r.get("supported")), default=None)],
        "dataset_path": dataset_label,
        "total_dataset_rows": stats["total_rows"],
        "feature_columns": FEATURE_COLUMNS,
        "evaluation_by_horizon": horizon_results,
        "feature_reference": horizon_results.get("15m", {}).get("feature_reference", {}),
        "drift": {"status": "pending_first_check", "alert": False},
        "metrics": {
            "horizon_15m": horizon_results.get("15m", {}).get("model_metrics"),
            "model_mae_kmh": horizon_results.get("15m", {}).get("model_metrics", {}).get("mae_percent"),
            "model_rmse_kmh": horizon_results.get("15m", {}).get("model_metrics", {}).get("rmse_percent"),
            "comparison": (
                "Models evaluated using 3-way chronological validation (Train 60%, Val 20%, Test 20%) "
                "with embargo boundary gaps preventing any future leakage. "
                "Candidates evaluated: Persistence, Historical Average, Random Forest, HistGradientBoosting, and Ridge. "
                "The served model is selected per horizon only when it beats the best baseline on chronological validation; rolling-origin folds are also reported."
            ),
        },
        "coverage_summary": {
            "monitored_roads": list(stats["road_counts"].keys()),
            "roads_with_repeated_observations": stats["roads_with_repeated_observations"],
            "sufficient_history": stats["has_sufficient_history"],
        },
        "limitations": [
            "Trained for 15, 30, and 60 minute congestion forecasts on monitored road segments.",
            "Requires at least 15 historical readings for high-confidence predictions on a specific road.",
            "Predictions apply to road segments with known speed and free-flow speed.",
            "Unmonitored roads without traffic observations cannot produce genuine ML predictions.",
            "If severe incident data or road closure is not present in TomTom flow, model predicts recurring patterns.",
        ],
    }

    # Write immutable version artifacts first. Active metadata is switched only after
    # every selected horizon and its metadata are safely staged.
    model_version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    versions_dir = models_dir / "versions"
    version_dir = versions_dir / model_version
    version_dir.mkdir(parents=True, exist_ok=False)
    model_files = {}
    for h, model in pending_models.items():
        final_path = version_dir / f"traffic_model_{h}m.joblib"
        temporary = final_path.with_suffix(final_path.suffix + ".tmp")
        joblib.dump(model, temporary)
        os.replace(temporary, final_path)
        model_files[str(h)] = str(final_path.relative_to(models_dir).as_posix())
    metadata["model_version"] = model_version
    metadata["model_files"] = model_files
    meta_path = models_dir / "model_metadata.json"
    registry_path = models_dir / "model_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {"versions": []}
    except (OSError, json.JSONDecodeError):
        registry = {"versions": []}
    prior_version = registry.get("active_version")
    metadata["previous_version"] = prior_version
    atomic_write_json(version_dir / "metadata.json", metadata)
    versions = registry.setdefault("versions", [])
    versions.append({
        "version": model_version,
        "previous_version": prior_version,
        "trained_at": metadata["trained_at"],
        "training_range": metadata["training_range"],
        "metrics": {h: result.get("model_metrics") for h, result in horizon_results.items() if result.get("supported")},
        "model_files": model_files,
        "metadata_file": str((version_dir / "metadata.json").relative_to(models_dir).as_posix()),
    })
    registry["active_version"] = model_version
    registry["previous_version"] = prior_version
    metadata["registry_summary"] = {"active_version": model_version, "previous_version": prior_version, "registered_versions": len(versions)}
    atomic_write_json(version_dir / "metadata.json", metadata)
    # Persist registry then atomically activate this version for serving.
    atomic_write_json(registry_path, registry)
    atomic_write_json(meta_path, metadata)
    write_success_reports(models_dir, metadata)
    print(f"\\nActivated model version {model_version}; metadata saved to {meta_path}")
    return metadata


if __name__ == "__main__":
    train_pipeline()
