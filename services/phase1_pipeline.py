"""Phase 1 collection metadata, idempotency, quota, and readiness helpers."""
from __future__ import annotations

import csv
import hashlib
import math
import os
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from typing import Callable
from zoneinfo import ZoneInfo

from services.data_pipeline import validate_reading_fields

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "phase1_ingestion.sqlite3"
POLL_MINUTES = 15
HORIZONS_MINUTES = (15, 30, 60)
MIN_HISTORY_DAYS = 14
MIN_COVERAGE = 0.80
LOCAL_TZ = ZoneInfo("Asia/Kolkata")
GOOGLE_ROUTES_STORE_ENABLED = False


class TomTomSource:
    name = "tomtom"

    def __init__(self, api_key: str, request: Callable[..., Any], daily_budget: int = 500):
        self.api_key = api_key
        self.request = request
        self.daily_budget = daily_budget

    def fetch(self, latitude: float, longitude: float) -> dict:
        url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
        def send():
            reserve_daily_request(self.name, self.daily_budget)
            return self.request("traffic_flow", url, params={"point": f"{latitude},{longitude}", "key": self.api_key}, timeout=15)
        response = resilient_call(self.name, send)
        response.raise_for_status()
        return response.json().get("flowSegmentData", {})


class GoogleRoutesSource:
    name = "google_routes"

    def __init__(self, api_key: str | None = None, request: Callable[..., Any] | None = None, daily_budget: int = 50, enabled: bool | None = None, store_enabled: bool = GOOGLE_ROUTES_STORE_ENABLED):
        self.request = request
        self.api_key = api_key
        self.daily_budget = daily_budget
        self.enabled = (os.getenv("ENABLE_GOOGLE_ROUTES_SPOT_CHECKS", "false").lower() == "true") if enabled is None else enabled
        self.store_enabled = store_enabled

    def fetch_spot_check(self, origin: dict, destination: dict, travel_mode: str = "DRIVE"):
        if not self.enabled:
            raise RuntimeError("Google Routes spot checks are disabled")
        if not self.api_key or self.request is None:
            raise RuntimeError("Google Routes credentials or HTTP transport are not configured")
        reserve_daily_request(self.name, self.daily_budget)
        response = self.request(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": "routes.duration,routes.staticDuration,routes.distanceMeters"},
            json={"origin": {"location": {"latLng": origin}}, "destination": {"location": {"latLng": destination}}, "travelMode": travel_mode},
            timeout=10,
        )
        response.raise_for_status()
        routes = response.json().get("routes", [])
        if not routes:
            raise ValueError("Google Routes returned no route")
        return {"source": self.name, "quality": "spot_check", "store": self.store_enabled, "result": routes[0]}


class SyntheticSource:
    name = "synthetic_demo"

    def fetch(self, location: dict) -> dict:
        # Explicitly demo-only values; never silently used by the live collector.
        return {"source": self.name, "quality": "synthetic_demo", "location": location,
                "timestamp": utc_timestamp(), "city": location["city"], "area": location["area"],
                "latitude": location["latitude"], "longitude": location["longitude"],
                "current_speed_kmh": 24.0, "free_flow_speed_kmh": 40.0,
                "congestion_percent": 40.0}


def resilient_call(provider: str, operation: Callable[[], Any], attempts: int = 3):
    now = datetime.now(timezone.utc)
    with connect() as db:
        row = db.execute("SELECT failures,open_until FROM breaker WHERE provider=?", (provider,)).fetchone()
    if row and row[1] and datetime.fromisoformat(row[1]) > now:
        raise RuntimeError(f"{provider} circuit breaker is open")
    for attempt in range(attempts):
        try:
            result = operation()
            with connect() as db:
                db.execute("INSERT INTO breaker(provider,failures,open_until) VALUES(?,0,NULL) ON CONFLICT(provider) DO UPDATE SET failures=0,open_until=NULL", (provider,))
            return result
        except Exception:
            failures = (row[0] if row else 0) + 1
            until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat() if failures >= 5 else None
            with connect() as db:
                db.execute("INSERT INTO breaker(provider,failures,open_until) VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET failures=excluded.failures,open_until=excluded.open_until", (provider, failures, until))
            if attempt + 1 == attempts:
                raise
            time.sleep(0.5 * (2 ** attempt))
            row = (failures, until)


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    configured_url = os.getenv("DATABASE_URL")
    if configured_url and not configured_url.startswith("sqlite:"):
        return _connect_postgres(configured_url)
    sqlite_path = DB_PATH
    if configured_url and configured_url.startswith("sqlite:"):
        raw_path = configured_url.removeprefix("sqlite:///").removeprefix("sqlite://")
        sqlite_path = Path(raw_path)
        if not sqlite_path.is_absolute():
            sqlite_path = Path(__file__).resolve().parents[1] / sqlite_path
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(sqlite_path, timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=20000")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started_at TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running');
      CREATE TABLE IF NOT EXISTS observations(
        corridor TEXT NOT NULL, timestamp_utc TEXT NOT NULL, city TEXT NOT NULL, area TEXT NOT NULL,
        latitude REAL NOT NULL, longitude REAL NOT NULL, current_speed_kmh REAL NOT NULL,
        free_flow_speed_kmh REAL NOT NULL, current_travel_time_seconds REAL,
        free_flow_travel_time_seconds REAL, confidence REAL, congestion_percent REAL NOT NULL,
        source TEXT NOT NULL, quality TEXT NOT NULL, run_id TEXT NOT NULL,
        PRIMARY KEY(corridor,timestamp_utc));
      CREATE TABLE IF NOT EXISTS daily_budget(day TEXT NOT NULL, provider TEXT NOT NULL, used INTEGER NOT NULL, budget INTEGER NOT NULL, PRIMARY KEY(day,provider));
      CREATE TABLE IF NOT EXISTS breaker(provider TEXT PRIMARY KEY, failures INTEGER NOT NULL, open_until TEXT);
      CREATE TABLE IF NOT EXISTS forecast_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL, area TEXT NOT NULL, horizon_minutes INTEGER NOT NULL,
        origin_timestamp TEXT NOT NULL, target_timestamp TEXT NOT NULL, generated_at TEXT NOT NULL,
        predicted_congestion_percent REAL NOT NULL, model_version TEXT,
        data_source TEXT NOT NULL, data_quality TEXT NOT NULL,
        UNIQUE(city,area,horizon_minutes,origin_timestamp));
    """)
    return db


class _PostgresCompat:
    """Bridge the existing Phase 1 DB-API calls to SQLAlchemy/psycopg."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement: str, parameters=()):
        ignored = "INSERT OR IGNORE INTO" in statement.upper()
        statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        statement = statement.replace("?", "%s")
        if ignored and "ON CONFLICT" not in statement.upper():
            statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return self.connection.exec_driver_sql(statement, parameters)

    def executescript(self, script: str):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def close(self):
        self.connection.close()


_pg_engine = None
_pg_engine_url: str | None = None


def _connect_postgres(url: str):
    global _pg_engine, _pg_engine_url
    try:
        from sqlalchemy import create_engine
        from services.db_schema import metadata
    except ImportError as exc:
        raise RuntimeError("PostgreSQL support requires SQLAlchemy and psycopg; install requirements.txt") from exc
    normalized = url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url
    if _pg_engine is None or _pg_engine_url != normalized:
        _pg_engine = create_engine(normalized, pool_pre_ping=True)
        _pg_engine_url = normalized
    metadata.create_all(_pg_engine, checkfirst=True)
    return _PostgresCompat(_pg_engine.connect())


def record_forecast(city: str, area: str, horizon_minutes: int, origin_timestamp: str,
                    target_timestamp: str, generated_at: str, predicted_congestion_percent: float,
                    model_version: str | None, data_source: str, data_quality: str) -> bool:
    """Persist a forecast for later honest forecast-versus-observation evaluation."""
    with closing(connect()) as db, db:
        cursor = db.execute("""INSERT OR IGNORE INTO forecast_records
          (city,area,horizon_minutes,origin_timestamp,target_timestamp,generated_at,
           predicted_congestion_percent,model_version,data_source,data_quality)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (city, area, horizon_minutes, origin_timestamp, target_timestamp, generated_at,
           predicted_congestion_percent, model_version, data_source, data_quality))
    return cursor.rowcount == 1


def forecast_actual_history(city: str | None = None, area: str | None = None,
                           limit: int = 100, offset: int = 0) -> dict:
    """Return persisted forecasts and nearest same-corridor observations within one poll step."""
    where = []
    values: list[Any] = []
    if city:
        where.append("f.city=?")
        values.append(city)
    if area:
        where.append("f.area=?")
        values.append(area)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with closing(connect()) as db:
        total = db.execute("SELECT COUNT(*) FROM forecast_records f" + clause, values).fetchone()[0]
        rows = db.execute("""SELECT f.id,f.city,f.area,f.horizon_minutes,f.origin_timestamp,
          f.target_timestamp,f.generated_at,f.predicted_congestion_percent,f.model_version,
          f.data_source,f.data_quality FROM forecast_records f""" + clause +
          " ORDER BY f.generated_at DESC LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        fields = ("id", "city", "area", "horizon_minutes", "origin_timestamp", "target_timestamp",
                  "generated_at", "predicted_congestion_percent", "model_version", "data_source", "data_quality")
        result_items = []
        for row in rows:
            item = dict(zip(fields, row))
            target = datetime.fromisoformat(str(item["target_timestamp"]).replace("Z", "+00:00"))
            lower = (target - timedelta(minutes=15)).astimezone(timezone.utc).isoformat()
            upper = (target + timedelta(minutes=15)).astimezone(timezone.utc).isoformat()
            candidates = db.execute("""SELECT timestamp_utc,congestion_percent FROM observations
                WHERE city=? AND area=? AND timestamp_utc>=? AND timestamp_utc<=?""",
                (item["city"], item["area"], lower, upper)).fetchall()
            nearest = None
            for actual_time, actual_value in candidates:
                actual_dt = datetime.fromisoformat(str(actual_time).replace("Z", "+00:00"))
                delta = abs((actual_dt - target).total_seconds())
                if nearest is None or delta < nearest[0]:
                    nearest = (delta, actual_time, actual_value)
            item["actual_timestamp"] = nearest[1] if nearest else None
            item["actual_congestion_percent"] = nearest[2] if nearest else None
            result_items.append(item)
    return {"items": result_items, "total": total,
            "limit": limit, "offset": offset}


def utc_timestamp(value: Any = None) -> str:
    if value is None:
        dt = datetime.now(LOCAL_TZ)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def corridor_key(reading: dict) -> str:
    raw = "|".join(str(reading.get(k, "")).strip().casefold() for k in ("city", "area"))
    raw += f"|{float(reading['latitude']):.6f}|{float(reading['longitude']):.6f}"
    return hashlib.sha256(raw.encode()).hexdigest()


def start_run(source: str) -> str:
    run_id = str(uuid.uuid4())
    with closing(connect()) as db, db:
        db.execute("INSERT INTO runs(id,started_at,source) VALUES(?,?,?)", (run_id, utc_timestamp(), source))
    return run_id


def finish_run(run_id: str, status: str) -> None:
    with closing(connect()) as db, db:
        db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))


def recover_interrupted_runs() -> int:
    """Mark runs left open by process termination; observations remain committed."""
    with closing(connect()) as db, db:
        cursor = db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
        return cursor.rowcount


def record_observation(reading: dict, source: str, run_id: str, quality: str = "validated") -> bool:
    if not isinstance(reading.get("city"), str) or not reading["city"].strip():
        raise ValueError("Missing city")
    if not isinstance(reading.get("area"), str) or not reading["area"].strip():
        raise ValueError("Missing corridor/area")
    if reading.get("congestion_percent") is None:
        raise ValueError("Missing congestion_percent; Phase 1 does not infer missing values")
    for field in ("latitude", "longitude", "current_speed_kmh", "free_flow_speed_kmh", "congestion_percent"):
        try:
            value = float(reading[field])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Missing or invalid {field}") from exc
        if not math.isfinite(value):
            raise ValueError(f"Non-finite {field}")
    if not 0 <= float(reading["congestion_percent"]) <= 100:
        raise ValueError("congestion_percent must be between 0 and 100")
    if reading.get("confidence") is not None:
        confidence = float(reading["confidence"])
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
    valid, reason, row = validate_reading_fields(reading)
    if not valid:
        raise ValueError(reason or "invalid observation")
    row["timestamp"] = utc_timestamp(row["timestamp"])
    if reading.get("confidence") is None:
        row["confidence"] = None
    key = corridor_key(row)
    fields = ("timestamp", "city", "area", "latitude", "longitude", "current_speed_kmh", "free_flow_speed_kmh", "current_travel_time_seconds", "free_flow_travel_time_seconds", "confidence", "congestion_percent")
    with closing(connect()) as db, db:
        prior = db.execute("SELECT MAX(timestamp_utc) FROM observations WHERE corridor=?", (key,)).fetchone()[0]
        if prior and datetime.fromisoformat(row["timestamp"]) - datetime.fromisoformat(prior) > timedelta(seconds=POLL_MINUTES * 90):
            quality = "gap_after_previous_observation"
        cursor = db.execute("""INSERT OR IGNORE INTO observations
          (corridor,timestamp_utc,city,area,latitude,longitude,current_speed_kmh,free_flow_speed_kmh,current_travel_time_seconds,free_flow_travel_time_seconds,confidence,congestion_percent,source,quality,run_id)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (key, row[fields[0]], *(row[f] for f in fields[1:]), source, quality, run_id))
    return cursor.rowcount == 1


def reserve_daily_request(provider: str, daily_budget: int) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    with closing(connect()) as db, db:
        db.execute("INSERT OR IGNORE INTO daily_budget VALUES(?,?,0,?)", (day, provider, daily_budget))
        result = db.execute("UPDATE daily_budget SET used=used+1 WHERE day=? AND provider=? AND used<budget", (day, provider)).rowcount
        if result != 1:
            raise RuntimeError(f"{provider} daily request budget reached")


def readiness() -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=MIN_HISTORY_DAYS)
    with closing(connect()) as db:
        rows = db.execute("SELECT corridor,city,area,latitude,longitude,MIN(timestamp_utc),MAX(timestamp_utc) FROM observations GROUP BY corridor ORDER BY city,area").fetchall()
    corridors = []
    for key, city, area, lat, lon, first, last in rows:
        first_dt, last_dt = datetime.fromisoformat(first), datetime.fromisoformat(last)
        days = max(0, (last_dt.date() - first_dt.date()).days + 1)
        with closing(connect()) as db:
            recent_count = db.execute("SELECT COUNT(*) FROM observations WHERE corridor=? AND timestamp_utc>=? AND timestamp_utc<=?", (key, start.isoformat(), now.isoformat())).fetchone()[0]
        expected = max(1, math.floor((now - start).total_seconds() / (POLL_MINUTES * 60)))
        coverage = min(1.0, recent_count / expected)
        ready = first_dt <= start and last_dt >= now - timedelta(minutes=2 * POLL_MINUTES) and coverage >= MIN_COVERAGE
        corridors.append({"city":city,"area":area,"latitude":lat,"longitude":lon,"coverage":round(coverage,4),"first_timestamp":first,"last_timestamp":last,"history_days":days,"observations":recent_count,"ready":ready,"message":"Forecast ready" if ready else f"Collecting data: {min(days, MIN_HISTORY_DAYS)} of {MIN_HISTORY_DAYS} days"})
    return {"poll_interval_minutes":POLL_MINUTES,"horizons_minutes":list(HORIZONS_MINUTES),"minimum_history_days":MIN_HISTORY_DAYS,"minimum_coverage":MIN_COVERAGE,"corridors":corridors}


def import_csv(path: Path, source: str = "csv_import") -> dict:
    run_id = start_run(source)
    imported = rejected = duplicates = 0
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    if record_observation(row, source, run_id): imported += 1
                    else: duplicates += 1
                except (ValueError, KeyError, TypeError):
                    rejected += 1
        finish_run(run_id, "complete")
    except Exception:
        finish_run(run_id, "failed")
        raise
    return {"run_id":run_id,"imported":imported,"duplicates":duplicates,"rejected":rejected}
