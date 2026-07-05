"""Helpers for working with application timestamps in UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC (naive = already UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_iso_datetime(raw: str) -> datetime:
    """Parse an ISO 8601 timestamp and normalize it to UTC."""
    return _ensure_utc(datetime.fromisoformat(raw.strip().replace("Z", "+00:00")))


def format_iso_datetime(dt: datetime) -> str:
    """Serialize a datetime as an ISO 8601 UTC timestamp."""
    return _ensure_utc(dt).isoformat().replace("+00:00", "Z")


def utc_now_iso() -> str:
    """Current time as an ISO 8601 UTC string."""
    return format_iso_datetime(utc_now())
