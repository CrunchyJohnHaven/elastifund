"""Resolution time estimator for capital velocity optimization.

Estimates how quickly a market will resolve so the bot can prioritize
fast-resolving markets. A trade that resolves in 2 days generates 15x
more annualized return than one that takes 30 days.

Capital velocity score = edge_size / estimated_days_to_resolution

P0-55: Capital lock-up penalty — exponential decay beyond max_days
       blocks markets that tie up capital too long.
"""
import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional

try:
    import structlog
    logger = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

# Resolution time buckets (in days)
BUCKET_UNDER_1D = 0.5       # <24h → use 0.5 days for scoring
BUCKET_1_3D = 2.0            # 1-3 days
BUCKET_3_7D = 5.0            # 3-7 days
BUCKET_1_4W = 14.0           # 1-4 weeks
BUCKET_OVER_1M = 45.0        # >1 month

# Keywords that signal fast resolution
TODAY_KEYWORDS = ["today", "tonight", "this evening", "this morning", "this afternoon"]
TOMORROW_KEYWORDS = ["tomorrow"]
THIS_WEEK_KEYWORDS = ["this week", "this weekend", "this friday", "this saturday", "this sunday"]
WEATHER_KEYWORDS = [
    "temperature", "weather", "degrees", "fahrenheit", "celsius",
    "rain", "snow", "wind", "high temp", "low temp", "precipitation",
    "heat wave", "cold front", "storm",
]

# Month name mapping for date parsing
MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Date patterns in question text
# "by March 15" / "before March 15, 2026" / "on March 15th"
DATE_PATTERN = re.compile(
    r"(?:by|before|on|until)\s+"
    r"(?:(?P<month_name>\w+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(?P<year>\d{4}))?)"
    r"|"
    r"(?:(?P<day2>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month_name2>\w+)(?:\s*,?\s*(?P<year2>\d{4}))?)",
    re.IGNORECASE,
)

# "by [date]" pattern for ISO-style dates (2026-03-15)
ISO_DATE_PATTERN = re.compile(
    r"(?:by|before|on|until)\s+(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
    re.IGNORECASE,
)


def estimate_resolution_days(
    question: str,
    end_date: Optional[str] = None,
    created_at: Optional[str] = None,
    category: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Estimate the number of days until a market resolves.

    Uses a priority-ordered heuristic:
    1. If end_date is set and near, use it directly
    2. Parse dates from question text ("by March 15")
    3. Keyword matching (today, tomorrow, weather)
    4. Category-based defaults

    Args:
        question: Market question text
        end_date: Market end date (ISO format from Gamma API)
        created_at: Market creation date (ISO format)
        category: Market category tag
        now: Override for current time (for testing)

    Returns:
        Dict with: estimated_days, bucket, method, confidence
    """
    if now is None:
        now = datetime.now(timezone.utc)

    question_lower = question.lower().strip()

    # 1. Check end_date from API — most reliable
    if end_date:
        end_dt = _parse_iso_date(end_date)
        if end_dt:
            days_until = max(0.25, (end_dt - now).total_seconds() / 86400)
            bucket = _days_to_bucket(days_until)
            return {
                "estimated_days": round(days_until, 1),
                "bucket": bucket,
                "method": "end_date",
                "confidence": "high",
            }

    # 2. Look for "today" / "tonight" keywords
    if any(kw in question_lower for kw in TODAY_KEYWORDS):
        return {
            "estimated_days": BUCKET_UNDER_1D,
            "bucket": "<24h",
            "method": "keyword_today",
            "confidence": "high",
        }

    # 3. "tomorrow" keywords
    if any(kw in question_lower for kw in TOMORROW_KEYWORDS):
        return {
            "estimated_days": 1.0,
            "bucket": "1-3d",
            "method": "keyword_tomorrow",
            "confidence": "high",
        }

    # 4. "this week/weekend" keywords
    if any(kw in question_lower for kw in THIS_WEEK_KEYWORDS):
        return {
            "estimated_days": BUCKET_3_7D,
            "bucket": "3-7d",
            "method": "keyword_this_week",
            "confidence": "medium",
        }

    # 5. Parse explicit dates from question text
    parsed_date = _parse_date_from_question(question, now)
    if parsed_date:
        days_until = max(0.25, (parsed_date - now).total_seconds() / 86400)
        bucket = _days_to_bucket(days_until)
        return {
            "estimated_days": round(days_until, 1),
            "bucket": bucket,
            "method": "parsed_date",
            "confidence": "medium",
        }

    # 6. Weather markets resolve fast (typically 24-48h)
    if any(kw in question_lower for kw in WEATHER_KEYWORDS):
        return {
            "estimated_days": BUCKET_1_3D,
            "bucket": "1-3d",
            "method": "weather_category",
            "confidence": "medium",
        }

    # 7. Category-based defaults
    if category:
        cat_lower = category.lower()
        if cat_lower in ("weather",):
            return {
                "estimated_days": BUCKET_1_3D,
                "bucket": "1-3d",
                "method": "category_weather",
                "confidence": "medium",
            }
        if cat_lower in ("sports",):
            return {
                "estimated_days": BUCKET_3_7D,
                "bucket": "3-7d",
                "method": "category_sports",
                "confidence": "low",
            }

    # 8. Default: assume 1-4 weeks for political/economic/unknown
    return {
        "estimated_days": BUCKET_1_4W,
        "bucket": "1-4w",
        "method": "default",
        "confidence": "low",
    }


def capital_velocity_penalty(
    estimated_days: float,
    max_days: float = 14.0,
    decay_rate: float = 0.1,
) -> float:
    """Smooth penalty for markets that lock capital too long.

    Returns a multiplier in (0, 1] that discounts expected value.
    Markets under max_days get no penalty (1.0). Beyond max_days
    the penalty decays exponentially.

    penalty = exp(-decay_rate * max(0, estimated_days - max_days))

    Examples (default params, max_days=14):
        2 days  → 1.0   (no penalty)
        14 days → 1.0   (at threshold)
        21 days → 0.50  (7 days over)
        28 days → 0.25  (14 days over)
        45 days → 0.05  (31 days over, nearly blocked)

    Args:
        estimated_days: Estimated days to resolution.
        max_days: Maximum days before penalty kicks in (default 14).
        decay_rate: Exponential decay rate (default 0.1).

    Returns:
        Penalty multiplier in (0, 1].
    """
    if estimated_days <= 0:
        estimated_days = 0.25
    overshoot = max(0.0, estimated_days - max_days)
    return math.exp(-decay_rate * overshoot)


def capital_velocity_score(edge: float, estimated_days: float) -> float:
    """Compute capital velocity score.

    Higher score = more attractive (high edge + fast resolution).
    Annualized edge per unit time = edge / days * 365

    Args:
        edge: Absolute edge (e.g., 0.15 for 15%)
        estimated_days: Estimated days to resolution

    Returns:
        Capital velocity score (edge / days, annualized)
    """
    if estimated_days <= 0:
        estimated_days = 0.25  # Floor at 6 hours
    return (edge / estimated_days) * 365.0


def velocity_adjusted_ev(
    edge: float,
    estimated_days: float,
    taker_fee: float = 0.0,
    max_days: float = 14.0,
    decay_rate: float = 0.1,
) -> dict:
    """Expected value adjusted for fees, capital velocity, and lock-up penalty.

    Combines:
    1. Net edge (after taker fees)
    2. Capital velocity (annualized edge per day)
    3. Lock-up penalty (exponential decay beyond max_days)

    adjusted_ev = velocity_score * penalty

    Args:
        edge: Absolute raw edge (e.g., 0.15 for 15%)
        estimated_days: Estimated days to resolution
        taker_fee: Taker fee to subtract from edge
        max_days: Max days before penalty applies
        decay_rate: Penalty decay rate

    Returns:
        Dict with: net_edge, penalty, velocity_score, adjusted_ev, blocked
    """
    net_edge = edge - taker_fee
    if net_edge <= 0:
        return {
            "net_edge": net_edge,
            "penalty": 0.0,
            "velocity_score": 0.0,
            "adjusted_ev": 0.0,
            "blocked": True,
        }

    penalty = capital_velocity_penalty(estimated_days, max_days, decay_rate)
    vel_score = capital_velocity_score(net_edge, estimated_days)
    adjusted_ev = vel_score * penalty

    # Block if penalty makes it effectively worthless (<2% of original)
    blocked = penalty < 0.02

    return {
        "net_edge": round(net_edge, 6),
        "penalty": round(penalty, 4),
        "velocity_score": round(vel_score, 2),
        "adjusted_ev": round(adjusted_ev, 2),
        "blocked": blocked,
    }


def rank_signals_by_velocity(
    signals: list[dict],
    top_n: int = 5,
) -> list[dict]:
    """Rank signals by capital velocity score and return top N.

    Each signal dict must have:
        - edge: float (absolute mispricing)
        - estimated_days: float (estimated resolution time)

    Adds velocity_score to each signal and returns sorted top N.

    Args:
        signals: List of signal dicts with edge and estimated_days
        top_n: Maximum signals to return

    Returns:
        Top N signals sorted by velocity_score descending
    """
    for sig in signals:
        edge = abs(sig.get("edge", 0))
        est_days = sig.get("estimated_days", BUCKET_1_4W)
        sig["velocity_score"] = capital_velocity_score(edge, est_days)

    ranked = sorted(signals, key=lambda s: s["velocity_score"], reverse=True)

    if ranked:
        logger.info(
            "velocity_ranking",
            total_signals=len(signals),
            top_n=top_n,
            best_score=round(ranked[0]["velocity_score"], 2) if ranked else 0,
            worst_included=round(ranked[min(top_n - 1, len(ranked) - 1)]["velocity_score"], 2) if ranked else 0,
        )

    return ranked[:top_n]


def _days_to_bucket(days: float) -> str:
    """Convert days to a human-readable bucket label."""
    if days < 1:
        return "<24h"
    if days <= 3:
        return "1-3d"
    if days <= 7:
        return "3-7d"
    if days <= 28:
        return "1-4w"
    return ">1m"


def _parse_iso_date(date_str: str) -> Optional[datetime]:
    """Parse an ISO date string from Gamma API."""
    if not date_str:
        return None
    try:
        # Handle "2026-03-31T12:00:00Z" and "2026-03-31"
        date_str = date_str.strip()
        if "T" in date_str:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return datetime.fromisoformat(date_str + "T00:00:00+00:00")
    except (ValueError, TypeError):
        return None


def _parse_date_from_question(question: str, now: datetime) -> Optional[datetime]:
    """Try to extract a target date from the question text."""
    current_year = now.year

    # Try ISO-style dates first (2026-03-15)
    iso_match = ISO_DATE_PATTERN.search(question)
    if iso_match:
        try:
            parts = iso_match.group(1).replace("/", "-").split("-")
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]),
                            tzinfo=timezone.utc)
        except (ValueError, IndexError):
            pass

    # Try natural language dates
    for match in DATE_PATTERN.finditer(question):
        month_name = match.group("month_name") or match.group("month_name2")
        day_str = match.group("day") or match.group("day2")
        year_str = match.group("year") or match.group("year2")

        if not month_name or not day_str:
            continue

        month_name_lower = month_name.lower()
        if month_name_lower not in MONTH_MAP:
            continue

        month = MONTH_MAP[month_name_lower]
        day = int(day_str)
        year = int(year_str) if year_str else current_year

        try:
            target = datetime(year, month, day, tzinfo=timezone.utc)
            # If target is in the past and no year was specified, try next year
            if target < now and not year_str:
                target = datetime(year + 1, month, day, tzinfo=timezone.utc)
            return target
        except ValueError:
            continue

    return None
