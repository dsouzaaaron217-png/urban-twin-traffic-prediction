# Phase 1 data pipeline

## Collection and storage

The scheduled collector polls every 15 minutes in `Asia/Kolkata`. New Phase 1 records are stored in `data/phase1_ingestion.sqlite3`; timestamps are normalized to UTC. The SQLite store uses WAL mode and a unique `(corridor, timestamp_utc)` key, and records provider, quality, and ingestion-run ID. The existing raw CSV files are not rewritten by this pipeline.

TomTom is the scheduled source. Configure `TOMTOM_DAILY_REQUEST_BUDGET` to set its daily request cap (default: 500). Retries use exponential backoff; repeated failures open a five-minute circuit breaker. Google Routes spot checks are disabled by default and have a separate daily budget. Keep `store_enabled` false until Google's terms and storage policy are confirmed. `SyntheticSource` is demo-only and labels its output `synthetic_demo`.

## Readiness

The fixed resolution is 15 minutes. Supported horizons are 15, 30, and 60 minutes (1, 2, and 4 polling steps). A corridor is forecast-ready only after at least 14 days and at least 80% coverage in the most recent 14-day window. Missing intervals lower coverage; the pipeline does not fill them. The API is `GET /api/v1/data/readiness` and the UI page is `/readiness`.

## CSV import

Import into the Phase 1 store without modifying the source file:

```powershell
.\.venv\Scripts\python.exe scripts\import_phase1_csv.py path\to\traffic.csv
```

Required columns: `timestamp`, `city`, `area`, `latitude`, `longitude`, `current_speed_kmh`, `free_flow_speed_kmh`, and `congestion_percent`. Optional columns: `current_travel_time_seconds`, `free_flow_travel_time_seconds`, and `confidence`. Timestamps must include a timezone; naive timestamps are interpreted as Asia/Kolkata. Coordinates, speeds, congestion, and confidence are range-checked. Rows missing required values or containing malformed values are rejected and counted; duplicate corridor/timestamp rows are counted and ignored. CSV rows are labeled `csv_import`; preserve original source provenance in the CSV where known before importing. The import creates a run record and records row quality.

Run the import only on files you are authorized to use and whose traffic fields represent real measurements. Do not import simulated/demo data as real observations.
