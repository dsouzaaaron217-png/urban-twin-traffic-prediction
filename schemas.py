from pydantic import BaseModel, Field
from typing import Generic, List, TypeVar, Optional
from datetime import datetime, timezone

T = TypeVar('T')

class ErrorResponse(BaseModel):
    """Unified error payload returned by the API."""
    error: str = Field(..., description='Short error code or type')
    message: str = Field(..., description='Human‑readable description')
    details: Optional[dict] = Field(None, description='Optional machine‑readable details')
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PageParams(BaseModel):
    limit: int = Field(20, ge=1, le=100, description='Maximum items per page')
    offset: int = Field(0, ge=0, description='Zero‑based offset')

class PaginatedResponse(BaseModel, Generic[T]):
    limit: int
    offset: int
    total: int
    items: List[T]


class TrafficCurrentItem(BaseModel):
    timestamp: datetime
    city: str
    area: str
    latitude: float
    longitude: float
    current_speed_kmh: float
    free_flow_speed_kmh: float
    congestion_percent: float
    source: str
    quality: str


class TrafficCurrentResponse(BaseModel):
    generated_at: datetime
    items: List[TrafficCurrentItem]
    total: int
    limit: int
    offset: int


class ForecastApiResponse(BaseModel):
    city: str
    area: str
    horizon_minutes: int
    data_quality: dict
    model_version: str | None
    generated_at: datetime
    forecast_available: bool
    forecast: dict | None = None
    fallback_model: str | None = None
    fallback_reason: str | None = None
    reason: str | None = None


class AlertItem(BaseModel):
    id: str
    type: str
    severity: str
    message: str
    city: str | None = None
    area: str | None = None
    generated_at: datetime


class AlertsResponse(BaseModel):
    items: List[AlertItem]
    total: int
    limit: int
    offset: int
