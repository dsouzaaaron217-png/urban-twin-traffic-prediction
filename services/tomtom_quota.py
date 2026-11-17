"""Persistent, concurrency-safe monthly TomTom API quota tracking."""

from contextlib import closing
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "tomtom_usage.sqlite3"

# Initial portal usage supplied by the project owner.
# Routing and Traffic Maps remain disabled until their portal usage is verified.
PRODUCT_DEFAULTS = {
    "traffic_flow": {"limit": 20000, "initial_used": 241, "enabled": True},
    "search": {"limit": 2500, "initial_used": 0, "enabled": True},
    "routing": {"limit": 20000, "initial_used": 0, "enabled": False},
    "traffic_maps": {"limit": 20000, "initial_used": 0, "enabled": False},
}


class TomTomQuotaExceeded(RuntimeError):
    """Raised when a TomTom request is blocked by the local quota guard."""


def _current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def _initialize_database():
    """Create tables and seed the supplied initial usage exactly once."""
    with closing(_connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS monthly_usage (
                month TEXT NOT NULL,
                product TEXT NOT NULL,
                monthly_limit INTEGER NOT NULL,
                used INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                PRIMARY KEY (month, product)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS quota_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        seeded = connection.execute(
            "SELECT value FROM quota_metadata WHERE key = 'initial_baseline_seeded'"
        ).fetchone()

        month = _current_month()

        for product, settings in PRODUCT_DEFAULTS.items():
            initial_used = settings["initial_used"] if seeded is None else 0

            connection.execute("""
                INSERT OR IGNORE INTO monthly_usage
                (month, product, monthly_limit, used, enabled)
                VALUES (?, ?, ?, ?, ?)
            """, (
                month,
                product,
                settings["limit"],
                initial_used,
                int(settings["enabled"]),
            ))

        if seeded is None:
            connection.execute("""
                INSERT INTO quota_metadata (key, value)
                VALUES ('initial_baseline_seeded', 'true')
            """)


def reserve_request(product):
    """
    Atomically reserve one request before sending it.

    Reservations are deliberately not refunded after network errors or
    uncertain outcomes. This favors preventing quota overruns over
    undercounting requests.
    """
    if product not in PRODUCT_DEFAULTS:
        raise ValueError(f"Unknown TomTom quota category: {product}")

    _initialize_database()
    month = _current_month()
    settings = PRODUCT_DEFAULTS[product]

    with closing(_connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")

        connection.execute("""
            INSERT OR IGNORE INTO monthly_usage
            (month, product, monthly_limit, used, enabled)
            VALUES (?, ?, ?, 0, ?)
        """, (
            month,
            product,
            settings["limit"],
            int(settings["enabled"]),
        ))

        row = connection.execute("""
            SELECT monthly_limit, used, enabled
            FROM monthly_usage
            WHERE month = ? AND product = ?
        """, (month, product)).fetchone()

        monthly_limit, used, enabled = row

        if not enabled:
            raise TomTomQuotaExceeded(
                f"TomTom {product} requests are disabled: "
                "the starting portal usage has not been verified."
            )

        if used + 1 > monthly_limit:
            raise TomTomQuotaExceeded(
                f"TomTom {product} monthly quota reached "
                f"({used}/{monthly_limit}). Request blocked locally."
            )

        connection.execute("""
            UPDATE monthly_usage
            SET used = used + 1
            WHERE month = ? AND product = ?
        """, (month, product))


def _redact_api_key(value, params=None):
    """Remove API key values from request and HTTP error text."""
    message = str(value)
    api_key = params.get("key") if isinstance(params, dict) else None
    if api_key:
        message = message.replace(str(api_key), "[REDACTED]")
    return re.sub(r"(?i)([?&]key=)[^&\s]+", r"\1[REDACTED]", message)


def tomtom_get(product, url, params=None, timeout=10):
    """Reserve quota, then make one TomTom GET with sanitized errors."""
    reserve_request(product)
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        exc.args = (_redact_api_key(exc, params),)
        raise exc from None

    if response.url:
        response.url = _redact_api_key(response.url, params)
    return response

def get_quota_status():
    """Return local monthly quota usage without making network requests."""
    _initialize_database()
    month = _current_month()

    with closing(_connect()) as connection, connection:
        rows = connection.execute("""
            SELECT product, monthly_limit, used, enabled
            FROM monthly_usage
            WHERE month = ?
            ORDER BY product
        """, (month,)).fetchall()

    return {
        product: {
            "used": used,
            "limit": monthly_limit,
            "remaining": max(0, monthly_limit - used),
            "enabled": bool(enabled),
        }
        for product, monthly_limit, used, enabled in rows
    }
