"""Small process-local HTTP observability, rate limiting, and read caching."""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from functools import wraps
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from settings import settings
from schemas import ErrorResponse

_logger = logging.getLogger("trafficwatch.http")
_lock = threading.Lock()
_counts: dict[str, int] = defaultdict(int)
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)
_cache: dict[str, tuple[float, Any]] = {}


def error_payload(code: str, message: str, details: dict | None = None) -> dict:
    payload = ErrorResponse(error=code, message=message, details=details).model_dump(mode="json")
    # `detail` is retained as a compatibility alias for existing frontend callers.
    payload["detail"] = message
    return payload


async def request_middleware(request: Request, call_next: Callable):
    given_id = request.headers.get("X-Request-ID", "")
    request_id = given_id if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", given_id) else str(uuid.uuid4())
    request.state.request_id = request_id
    ip = request.client.host if request.client else "unknown"
    start = time.monotonic()
    status = 500

    if request.method != "OPTIONS" and request.url.path not in {"/health", "/metrics"}:
        now = time.monotonic()
        with _lock:
            bucket = _rate_buckets[ip]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= settings.rate_limit_per_minute:
                status = 429
                response = JSONResponse(
                    status_code=status,
                    content=error_payload("rate_limit_exceeded", "Request limit exceeded."),
                    headers={"Retry-After": "60"},
                )
                _counts[str(status)] += 1
                response.headers["X-Request-ID"] = request_id
                _log_request(request, request_id, status, start)
                return response
            bucket.append(now)

    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        with _lock:
            _counts[str(status)] += 1
        _log_request(request, request_id, status, start)
        if "response" in locals():
            response.headers["X-Request-ID"] = request_id


def _log_request(request: Request, request_id: str, status: int, start: float) -> None:
    _logger.info(json.dumps({
        "event": "http_request", "request_id": request_id,
        "method": request.method, "path": request.url.path,
        "status_code": status,
        "duration_ms": round((time.monotonic() - start) * 1000, 2),
    }, separators=(",", ":")))


def request_metrics() -> dict:
    with _lock:
        responses = dict(_counts)
    return {"requests_total": sum(responses.values()), "responses_by_status": responses}


def cached_read(ttl_seconds: float = 5.0):
    """Cache synchronous public read results by endpoint arguments."""
    def decorate(fn: Callable):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            key = f"{fn.__module__}.{fn.__qualname__}:{args!r}:{sorted(kwargs.items())!r}"
            now = time.monotonic()
            with _lock:
                cached = _cache.get(key)
                if cached and cached[0] > now:
                    return copy.deepcopy(cached[1])
            value = fn(*args, **kwargs)
            with _lock:
                _cache[key] = (now + ttl_seconds, copy.deepcopy(value))
            return value
        return wrapped
    return decorate


def invalidate_read_cache() -> None:
    with _lock:
        _cache.clear()


def reset_http_state() -> None:
    """Reset process-local counters, rate buckets and cache for isolated tests."""
    with _lock:
        _counts.clear()
        _rate_buckets.clear()
        _cache.clear()
