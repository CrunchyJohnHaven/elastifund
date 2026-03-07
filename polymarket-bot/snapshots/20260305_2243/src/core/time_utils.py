"""Utility functions for time handling and conversions."""
from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime.

    Returns:
        Current UTC datetime with timezone info
    """
    return datetime.now(tz=timezone.utc)


def ms_to_datetime(milliseconds: int | float) -> datetime:
    """Convert milliseconds since epoch to datetime.

    Args:
        milliseconds: Milliseconds since Unix epoch

    Returns:
        Timezone-aware datetime object in UTC
    """
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)


def datetime_to_ms(dt: datetime) -> int:
    """Convert datetime to milliseconds since epoch.

    Args:
        dt: Datetime object to convert

    Returns:
        Milliseconds since Unix epoch as integer
    """
    return int(dt.timestamp() * 1000)


def elapsed_seconds(start: datetime) -> float:
    """Calculate elapsed seconds from start time to now.

    Args:
        start: Start datetime (typically from utc_now())

    Returns:
        Elapsed seconds as float
    """
    return (utc_now() - start).total_seconds()
