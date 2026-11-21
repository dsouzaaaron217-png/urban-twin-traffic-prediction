import os
from typing import List
from dotenv import load_dotenv
from pathlib import Path
from pydantic import Field, BaseModel

_DEFAULT_CORS = [
    "http://localhost:8080", "http://127.0.0.1:8080",
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:3000", "http://127.0.0.1:3000",
]

# Load environment configuration before reading settings
load_dotenv()

class Settings(BaseModel):
    # Core configuration
    @property
    def tomtom_api_key(self) -> str | None:
        return os.getenv("TOMTOM_API_KEY")

    @property
    def enable_tomtom_scheduler(self) -> bool:
        return os.getenv("ENABLE_TOMTOM_SCHEDULER", "false").lower() == "true"

    @property
    def enable_model_retraining(self) -> bool:
        return os.getenv("ENABLE_MODEL_RETRAINING", "false").lower() == "true"

    @property
    def model_retrain_interval_hours(self) -> int:
        return max(1, int(os.getenv("MODEL_RETRAIN_INTERVAL_HOURS", "24")))

    # CORS allowed origins (explicit, no wildcard for credentials)
    cors_allowed_origins: List[str] = Field(default_factory=lambda: [
        item.strip() for item in os.getenv("CORS_ALLOWED_ORIGINS", ",".join(_DEFAULT_CORS)).split(",") if item.strip()
    ])

    # API key must be supplied via environment, no default secret.
    @property
    def api_key(self) -> str | None:
        return os.getenv("API_KEY")

    # Rate limiting (requests per minute per IP)
    @property
    def rate_limit_per_minute(self) -> int:
        return max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE", "600")))

    # Database URL – defaults to SQLite for development
    @property
    def database_url(self) -> str:
        value = os.getenv("DATABASE_URL")
        if value:
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+psycopg://", 1)
            return value
        default_db = Path(__file__).resolve().parent / "data" / "phase1_ingestion.sqlite3"
        return f"sqlite:///{default_db.as_posix()}"

# Instantiate settings
settings = Settings()
