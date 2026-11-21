# Phase 2: Machine Learning

## Data eligibility and current status

Production training reads the Phase 1 SQLite observations with approved source and quality labels (`tomtom` or explicitly verified `verified_csv_import`). Rows from the legacy cleaned CSV are excluded when row-level provenance is missing. Synthetic/demo rows are never accepted as real training data. Pre-Phase-2 model files that lack row-level verified provenance are retained on disk but not served and their metrics are hidden. The readiness gate is corridor-specific: at least 14 days of observations, at least 80% coverage at the 15-minute polling resolution, a fresh latest observation, and valid future pairs for each forecast horizon. A CSV defaults to unqualified `csv_import`; use `--source verified_csv_import` only after independently confirming its origin and license. No missing readings are filled.

The checkout reviewed for this implementation currently has **zero observations** in `data/phase1_ingestion.sqlite3`; training is therefore blocked and no model artifacts should be replaced. `reports/evaluation.md` will explain the block. It will contain real metrics only after eligible data is imported and evaluated.

## Features and evaluation

Features are constructed as of each observation timestamp: current readings, 15/30/60-minute lags, rolling speed/congestion statistics, local Asia/Kolkata time cycles, weekend and fixed national-holiday flags, corridor coordinates, and same-city nearby corridor summaries. Unknown or stale lag values remain missing and are imputed inside a scikit-learn pipeline fitted on training rows only. Chronological train/validation/test partitions use target-time embargoes; expanding rolling-origin folds train only on earlier targets. Results include MAE, RMSE, robust MAPE, congestion macro-F1, baseline skill score, corridor results, and peak (07:00–10:59 and 16:00–19:59 local time) versus off-peak results.

The served candidate is selected per horizon only if HistGradientBoosting beats both persistence and historical-average baselines on validation MAE. Otherwise the better validation baseline is served and the API/UI return the fallback reason. GRU/LSTM and graph models remain disabled until verified data volume justifies them. Prediction intervals are not shown because coverage has not been measured. The UI's sensor/history score is labeled heuristic and uncalibrated; it is not presented as measured predictive probability.

## Registry, rollback, drift, and scheduling

Successful training writes immutable model files under `models/versions/<version>/`, a registry at `models/model_registry.json`, and atomically switches `models/model_metadata.json` only after the new artifacts are staged. The rollback route is `POST /api/model/rollback` (optionally pass `?version=<registered-version>`). Drift status compares recent verified feature means with the active model's train-only reference; the status is available from `GET /api/model/status`. This standardized mean-shift monitor is an alert, not a claim of accuracy degradation.

Scheduled retraining is off by default. Set `ENABLE_MODEL_RETRAINING=true` and optionally `MODEL_RETRAIN_INTERVAL_HOURS=24` to enable it. This job only reads local verified data and does not call TomTom or other external APIs. TomTom collection remains controlled separately by `ENABLE_TOMTOM_SCHEDULER`.

## Run and verify

```powershell
.\.venv\Scripts\python.exe -m ml.train
.\.venv\Scripts\python.exe -m pytest -q
```

A blocked training run is an expected result until valid data passes the corridor gate. Do not label that state as a trained model or report model accuracy.

CSV import example after source/license verification:

```powershell
.\.venv\Scripts\python.exe scripts\import_phase1_csv.py path\to\traffic.csv --source verified_csv_import
```

Without that explicit flag, CSV-imported rows remain unqualified for production model training.
