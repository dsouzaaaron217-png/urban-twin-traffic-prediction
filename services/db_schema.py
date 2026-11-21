"""SQLAlchemy Core schema shared by Alembic and the Phase 1 store."""
from sqlalchemy import Column, Float, Integer, MetaData, PrimaryKeyConstraint, String, Table, Text, UniqueConstraint

metadata = MetaData()

runs = Table(
    "runs", metadata,
    Column("id", String(36), primary_key=True), Column("started_at", String(40), nullable=False),
    Column("source", String(80), nullable=False), Column("status", String(30), nullable=False, server_default="running"),
)
observations = Table(
    "observations", metadata,
    Column("corridor", String(64), nullable=False), Column("timestamp_utc", String(40), nullable=False),
    Column("city", String(120), nullable=False), Column("area", String(180), nullable=False),
    Column("latitude", Float, nullable=False), Column("longitude", Float, nullable=False),
    Column("current_speed_kmh", Float, nullable=False), Column("free_flow_speed_kmh", Float, nullable=False),
    Column("current_travel_time_seconds", Float), Column("free_flow_travel_time_seconds", Float),
    Column("confidence", Float), Column("congestion_percent", Float, nullable=False),
    Column("source", String(80), nullable=False), Column("quality", String(80), nullable=False),
    Column("run_id", String(36), nullable=False),
    PrimaryKeyConstraint("corridor", "timestamp_utc", name="pk_observations"),
)
daily_budget = Table(
    "daily_budget", metadata,
    Column("day", String(10), nullable=False), Column("provider", String(80), nullable=False),
    Column("used", Integer, nullable=False), Column("budget", Integer, nullable=False),
    PrimaryKeyConstraint("day", "provider", name="pk_daily_budget"),
)
breaker = Table(
    "breaker", metadata,
    Column("provider", String(80), primary_key=True), Column("failures", Integer, nullable=False),
    Column("open_until", String(40)),
)
forecast_records = Table(
    "forecast_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("city", String(120), nullable=False), Column("area", String(180), nullable=False),
    Column("horizon_minutes", Integer, nullable=False), Column("origin_timestamp", String(40), nullable=False),
    Column("target_timestamp", String(40), nullable=False), Column("generated_at", String(40), nullable=False),
    Column("predicted_congestion_percent", Float, nullable=False), Column("model_version", String(100)),
    Column("data_source", String(100), nullable=False), Column("data_quality", String(100), nullable=False),
    UniqueConstraint("city", "area", "horizon_minutes", "origin_timestamp", name="uq_forecast_origin"),
)
