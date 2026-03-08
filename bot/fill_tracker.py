#!/usr/bin/env python3
"""Track live order placements, fills, and stale cancellations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import statistics
import uuid
from typing import Any, Callable, Mapping


logger = logging.getLogger("fill_tracker")

TERMINAL_ORDER_STATUSES = {"filled", "cancelled", "canceled", "expired", "rejected"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _normalize_order_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    nested = payload.get("order")
    if isinstance(nested, Mapping):
        return dict(nested)
    return dict(payload)


def _normalize_status(status: Any, *, original_size: float | None, matched_size: float) -> str:
    text = _safe_text(status, "unknown").lower().replace(" ", "_")
    text = text.replace("-", "_")
    if original_size and original_size > 0 and matched_size >= (original_size - 1e-9):
        return "filled"
    if text in {"matched", "completed"}:
        return "filled"
    if text in {"canceled", "cancelled"}:
        return "cancelled"
    if matched_size > 0:
        return "partially_filled"
    if text in {"live", "open", "pending", "unmatched"}:
        return "open"
    return text or "unknown"


def _price_bucket(price: float | None) -> str:
    if price is None:
        return "unknown"
    bounded = max(0.0, min(0.99, float(price)))
    low = int(bounded * 10) / 10
    high = min(0.99, low + 0.09)
    return f"{low:.2f}-{high:.2f}"


@dataclass(frozen=True)
class OrderFillEvent:
    order_id: str
    market_id: str
    token_id: str
    side: str
    direction: str
    question: str
    category: str
    fill_price: float
    fill_size: float
    fill_size_usd: float
    latency_seconds: float
    cumulative_size_matched: float
    order_price: float | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class OrderReconciliationResult:
    orders_checked: int
    fills_detected: int
    stale_cancelled: int
    fill_events: tuple[OrderFillEvent, ...]
    stale_order_ids: tuple[str, ...]


class FillTracker:
    """Persist order and fill telemetry in SQLite and reconcile live orders."""

    def __init__(
        self,
        *,
        db_path: Path,
        report_path: Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.report_path = Path(report_path) if report_path else Path("reports/fill_rate_report.md")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._create_tables()

    def close(self) -> None:
        self.conn.close()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                trade_id TEXT,
                timestamp TEXT NOT NULL,
                placed_at_epoch REAL NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT,
                question TEXT,
                category TEXT,
                side TEXT,
                direction TEXT,
                price REAL,
                size REAL,
                size_usd REAL,
                order_type TEXT,
                status TEXT DEFAULT 'open',
                paper INTEGER DEFAULT 0,
                fill_count INTEGER DEFAULT 0,
                filled_size REAL DEFAULT 0.0,
                avg_fill_price REAL,
                first_fill_at TEXT,
                first_fill_latency_seconds REAL,
                last_fill_at TEXT,
                last_fill_latency_seconds REAL,
                last_size_matched REAL DEFAULT 0.0,
                last_seen_at TEXT,
                cancelled_at TEXT,
                cancel_reason TEXT,
                metadata_json TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS fills (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                trade_id TEXT,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT,
                fill_price REAL NOT NULL,
                fill_size REAL NOT NULL,
                fill_size_usd REAL NOT NULL,
                latency_seconds REAL NOT NULL,
                cumulative_size_matched REAL,
                raw_json TEXT,
                FOREIGN KEY(order_id) REFERENCES orders(order_id)
            );

            CREATE INDEX IF NOT EXISTS idx_orders_timestamp ON orders(timestamp);
            CREATE INDEX IF NOT EXISTS idx_orders_market_status ON orders(market_id, status);
            CREATE INDEX IF NOT EXISTS idx_fills_timestamp ON fills(timestamp);
            CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
            """
        )
        self.conn.commit()

    def record_order(
        self,
        *,
        order_id: str,
        market_id: str,
        token_id: str,
        question: str,
        category: str,
        side: str,
        direction: str,
        price: float,
        size: float,
        size_usd: float,
        order_type: str,
        paper: bool = False,
        trade_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        placed_at: datetime | None = None,
        status: str | None = None,
    ) -> None:
        if not order_id:
            raise ValueError("order_id is required")
        placed_at = placed_at or _utc_now()
        normalized_status = status or ("filled" if paper else "open")
        payload = json.dumps(metadata or {}, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO orders (
                order_id,
                trade_id,
                timestamp,
                placed_at_epoch,
                market_id,
                token_id,
                question,
                category,
                side,
                direction,
                price,
                size,
                size_usd,
                order_type,
                status,
                paper,
                last_seen_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                trade_id=COALESCE(excluded.trade_id, orders.trade_id),
                market_id=excluded.market_id,
                token_id=excluded.token_id,
                question=excluded.question,
                category=excluded.category,
                side=excluded.side,
                direction=excluded.direction,
                price=excluded.price,
                size=excluded.size,
                size_usd=excluded.size_usd,
                order_type=excluded.order_type,
                status=excluded.status,
                paper=excluded.paper,
                last_seen_at=excluded.last_seen_at,
                metadata_json=excluded.metadata_json
            """,
            (
                order_id,
                trade_id,
                placed_at.isoformat(),
                placed_at.timestamp(),
                market_id,
                token_id,
                question,
                category,
                side,
                direction,
                price,
                size,
                size_usd,
                order_type,
                normalized_status,
                1 if paper else 0,
                placed_at.isoformat(),
                payload,
            ),
        )
        self.conn.commit()

    def record_fill(
        self,
        *,
        order_id: str,
        market_id: str,
        fill_price: float,
        fill_size: float,
        latency_seconds: float,
        token_id: str = "",
        trade_id: str | None = None,
        fill_size_usd: float | None = None,
        cumulative_size_matched: float | None = None,
        raw_payload: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
        status: str | None = None,
    ) -> None:
        if fill_size <= 0:
            return
        occurred_at = occurred_at or _utc_now()
        fill_size_usd = fill_size_usd if fill_size_usd is not None else fill_size * fill_price
        self.conn.execute(
            """
            INSERT INTO fills (
                id,
                order_id,
                trade_id,
                timestamp,
                market_id,
                token_id,
                fill_price,
                fill_size,
                fill_size_usd,
                latency_seconds,
                cumulative_size_matched,
                raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4())[:12],
                order_id,
                trade_id,
                occurred_at.isoformat(),
                market_id,
                token_id,
                fill_price,
                fill_size,
                fill_size_usd,
                latency_seconds,
                cumulative_size_matched,
                json.dumps(dict(raw_payload or {}), sort_keys=True),
            ),
        )

        agg = self.conn.execute(
            """
            SELECT
                COUNT(*) AS fill_count,
                COALESCE(SUM(fill_size), 0.0) AS filled_size,
                COALESCE(SUM(fill_price * fill_size), 0.0) AS weighted_notional,
                MIN(timestamp) AS first_fill_at,
                MAX(timestamp) AS last_fill_at,
                MIN(latency_seconds) AS first_latency,
                MAX(latency_seconds) AS last_latency
            FROM fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

        avg_fill_price = None
        if agg["filled_size"] and agg["filled_size"] > 0:
            avg_fill_price = agg["weighted_notional"] / agg["filled_size"]

        self.conn.execute(
            """
            UPDATE orders
            SET fill_count = ?,
                filled_size = ?,
                avg_fill_price = ?,
                first_fill_at = ?,
                first_fill_latency_seconds = ?,
                last_fill_at = ?,
                last_fill_latency_seconds = ?,
                last_size_matched = ?,
                last_seen_at = ?,
                status = COALESCE(?, status)
            WHERE order_id = ?
            """,
            (
                agg["fill_count"],
                agg["filled_size"],
                avg_fill_price,
                agg["first_fill_at"],
                agg["first_latency"],
                agg["last_fill_at"],
                agg["last_latency"],
                cumulative_size_matched if cumulative_size_matched is not None else agg["filled_size"],
                occurred_at.isoformat(),
                status,
                order_id,
            ),
        )
        self.conn.commit()

    def update_order_status(
        self,
        order_id: str,
        *,
        status: str,
        last_size_matched: float | None = None,
        avg_fill_price: float | None = None,
        seen_at: datetime | None = None,
    ) -> None:
        seen_at = seen_at or _utc_now()
        self.conn.execute(
            """
            UPDATE orders
            SET status = ?,
                last_size_matched = COALESCE(?, last_size_matched),
                avg_fill_price = COALESCE(?, avg_fill_price),
                last_seen_at = ?
            WHERE order_id = ?
            """,
            (
                status,
                last_size_matched,
                avg_fill_price,
                seen_at.isoformat(),
                order_id,
            ),
        )
        self.conn.commit()

    def mark_cancelled(
        self,
        order_id: str,
        *,
        reason: str,
        cancelled_at: datetime | None = None,
    ) -> None:
        cancelled_at = cancelled_at or _utc_now()
        self.conn.execute(
            """
            UPDATE orders
            SET status = 'cancelled',
                cancelled_at = ?,
                cancel_reason = ?,
                last_seen_at = ?
            WHERE order_id = ?
            """,
            (cancelled_at.isoformat(), reason, cancelled_at.isoformat(), order_id),
        )
        self.conn.commit()

    def attach_trade_id(self, order_id: str, trade_id: str) -> None:
        self.conn.execute(
            "UPDATE orders SET trade_id = ? WHERE order_id = ?",
            (trade_id, order_id),
        )
        self.conn.commit()

    def live_open_orders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM orders
            WHERE paper = 0
              AND status NOT IN ('filled', 'cancelled', 'canceled', 'expired', 'rejected')
            ORDER BY timestamp ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def pending_order_count(self) -> int:
        return len(self.live_open_orders())

    def pending_order_notional(self) -> float:
        return sum(
            _safe_float(row.get("size_usd"), 0.0) or 0.0
            for row in self.live_open_orders()
        )

    def pending_market_ids(self) -> set[str]:
        return {
            _safe_text(row.get("market_id"))
            for row in self.live_open_orders()
            if _safe_text(row.get("market_id"))
        }

    def reconcile_open_orders(
        self,
        *,
        fetch_order: Callable[[str], Any],
        cancel_order: Callable[[str], bool] | None = None,
        max_order_age_hours: float = 2.0,
        now: datetime | None = None,
    ) -> OrderReconciliationResult:
        now = now or _utc_now()
        fills: list[OrderFillEvent] = []
        stale_order_ids: list[str] = []
        fills_detected = 0
        stale_cancelled = 0
        rows = self.live_open_orders()

        for row in rows:
            order_id = _safe_text(row.get("order_id"))
            if not order_id:
                continue
            try:
                raw_payload = fetch_order(order_id)
            except Exception as exc:
                logger.debug("order_poll_failed order=%s err=%s", order_id[:16], exc)
                continue

            payload = _normalize_order_payload(raw_payload)
            if not payload:
                continue

            original_size = _safe_float(
                payload.get("original_size")
                or payload.get("size")
                or payload.get("order_size"),
                None,
            )
            matched_size = _safe_float(
                payload.get("size_matched")
                or payload.get("filled_size")
                or payload.get("size_filled"),
                0.0,
            ) or 0.0
            avg_fill_price = _safe_float(
                payload.get("associate_trades_avg_price")
                or payload.get("avg_price")
                or payload.get("price"),
                None,
            )
            status = _normalize_status(
                payload.get("status") or payload.get("order_status"),
                original_size=original_size,
                matched_size=matched_size,
            )
            placed_at_epoch = _safe_float(row.get("placed_at_epoch"), now.timestamp()) or now.timestamp()
            latency_seconds = max(0.0, now.timestamp() - placed_at_epoch)
            last_size_matched = _safe_float(row.get("last_size_matched"), 0.0) or 0.0

            if matched_size > last_size_matched + 1e-9:
                fill_delta = matched_size - last_size_matched
                fill_price = avg_fill_price if avg_fill_price is not None else _safe_float(row.get("price"), 0.0) or 0.0
                fill_size_usd = fill_delta * fill_price
                metadata = {}
                raw_metadata = row.get("metadata_json")
                if raw_metadata:
                    try:
                        metadata = json.loads(raw_metadata)
                    except json.JSONDecodeError:
                        metadata = {}
                self.record_fill(
                    order_id=order_id,
                    market_id=_safe_text(row.get("market_id")),
                    token_id=_safe_text(row.get("token_id")),
                    fill_price=fill_price,
                    fill_size=fill_delta,
                    fill_size_usd=fill_size_usd,
                    latency_seconds=latency_seconds,
                    cumulative_size_matched=matched_size,
                    raw_payload=payload,
                    occurred_at=now,
                    status=status if status in TERMINAL_ORDER_STATUSES else "partially_filled",
                )
                fills.append(
                    OrderFillEvent(
                        order_id=order_id,
                        market_id=_safe_text(row.get("market_id")),
                        token_id=_safe_text(row.get("token_id")),
                        side=_safe_text(row.get("side")),
                        direction=_safe_text(row.get("direction")),
                        question=_safe_text(row.get("question")),
                        category=_safe_text(row.get("category"), "unknown"),
                        fill_price=fill_price,
                        fill_size=fill_delta,
                        fill_size_usd=fill_size_usd,
                        latency_seconds=latency_seconds,
                        cumulative_size_matched=matched_size,
                        order_price=_safe_float(row.get("price"), None),
                        metadata=metadata,
                    )
                )
                fills_detected += 1
            else:
                self.update_order_status(
                    order_id,
                    status=status,
                    last_size_matched=matched_size,
                    avg_fill_price=avg_fill_price,
                    seen_at=now,
                )

            order_age_hours = max(0.0, (now.timestamp() - placed_at_epoch) / 3600.0)
            if (
                cancel_order is not None
                and matched_size <= 1e-9
                and status not in TERMINAL_ORDER_STATUSES
                and order_age_hours >= max_order_age_hours
            ):
                try:
                    cancelled = bool(cancel_order(order_id))
                except Exception as exc:
                    logger.warning("stale_cancel_failed order=%s err=%s", order_id[:16], exc)
                    cancelled = False
                if cancelled:
                    self.mark_cancelled(order_id, reason="stale_order", cancelled_at=now)
                    stale_order_ids.append(order_id)
                    stale_cancelled += 1

        return OrderReconciliationResult(
            orders_checked=len(rows),
            fills_detected=fills_detected,
            stale_cancelled=stale_cancelled,
            fill_events=tuple(fills),
            stale_order_ids=tuple(stale_order_ids),
        )

    def get_summary(self, *, hours: int = 24, live_only: bool = True) -> dict[str, Any]:
        cutoff = (_utc_now() - timedelta(hours=max(1, int(hours)))).isoformat()
        where = ["timestamp >= ?"]
        params: list[Any] = [cutoff]
        if live_only:
            where.append("paper = 0")
        query = f"""
            SELECT *
            FROM orders
            WHERE {' AND '.join(where)}
            ORDER BY timestamp ASC
        """
        rows = [dict(row) for row in self.conn.execute(query, tuple(params)).fetchall()]
        total_orders = len(rows)
        filled_orders = [row for row in rows if (_safe_float(row.get("filled_size"), 0.0) or 0.0) > 0]
        cancelled_orders = [row for row in rows if _safe_text(row.get("status")).lower() == "cancelled"]
        stale_cancelled = [row for row in cancelled_orders if _safe_text(row.get("cancel_reason")) == "stale_order"]
        latencies = [
            float(row["first_fill_latency_seconds"])
            for row in rows
            if row.get("first_fill_latency_seconds") not in (None, "")
        ]
        median_latency = statistics.median(latencies) if latencies else None

        by_category: dict[str, dict[str, Any]] = {}
        by_price: dict[str, dict[str, Any]] = {}
        for row in rows:
            category = _safe_text(row.get("category"), "unknown")
            price_bucket = _price_bucket(_safe_float(row.get("price"), None))
            filled = (_safe_float(row.get("filled_size"), 0.0) or 0.0) > 0

            cat_bucket = by_category.setdefault(category, {"orders": 0, "filled": 0})
            cat_bucket["orders"] += 1
            cat_bucket["filled"] += 1 if filled else 0

            price_stats = by_price.setdefault(price_bucket, {"orders": 0, "filled": 0})
            price_stats["orders"] += 1
            price_stats["filled"] += 1 if filled else 0

        for stats in by_category.values():
            stats["fill_rate"] = (stats["filled"] / stats["orders"]) if stats["orders"] else 0.0
        for stats in by_price.values():
            stats["fill_rate"] = (stats["filled"] / stats["orders"]) if stats["orders"] else 0.0

        by_category = dict(sorted(by_category.items(), key=lambda item: item[0]))
        by_price = dict(sorted(by_price.items(), key=lambda item: item[0]))

        return {
            "window_hours": hours,
            "total_orders": total_orders,
            "filled_orders": len(filled_orders),
            "cancelled_orders": len(cancelled_orders),
            "stale_cancelled": len(stale_cancelled),
            "fill_rate": (len(filled_orders) / total_orders) if total_orders else 0.0,
            "median_fill_latency_seconds": median_latency,
            "fill_rate_by_market_category": by_category,
            "fill_rate_by_price_level": by_price,
        }

    def format_fill_rate_line(self, *, hours: int = 24, live_only: bool = True) -> str:
        summary = self.get_summary(hours=hours, live_only=live_only)
        fill_rate_pct = summary["fill_rate"] * 100.0
        return (
            f"Fill rate last {hours}h: {fill_rate_pct:.0f}% "
            f"({summary['filled_orders']}/{summary['total_orders']} orders)"
        )

    def write_report(self, *, hours: int = 24, live_only: bool = True) -> Path:
        summary = self.get_summary(hours=hours, live_only=live_only)
        generated_at = _utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
        latency = summary["median_fill_latency_seconds"]
        latency_text = (
            f"{latency / 60:.1f} minutes"
            if isinstance(latency, (int, float))
            else "n/a"
        )
        lines = [
            "# Fill Rate Report",
            "",
            f"- Generated: {generated_at}",
            f"- Window: last {summary['window_hours']} hours",
            f"- Orders placed: {summary['total_orders']}",
            f"- Orders with fills: {summary['filled_orders']}",
            f"- Fill rate: {summary['fill_rate']:.1%}",
            f"- Median first-fill latency: {latency_text}",
            f"- Cancelled orders: {summary['cancelled_orders']}",
            f"- Stale orders cancelled: {summary['stale_cancelled']}",
            "",
            "## By Category",
            "",
            "| Category | Filled / Orders | Fill Rate |",
            "|---|---:|---:|",
        ]
        if summary["fill_rate_by_market_category"]:
            for category, stats in summary["fill_rate_by_market_category"].items():
                lines.append(
                    f"| {category} | {stats['filled']}/{stats['orders']} | {stats['fill_rate']:.1%} |"
                )
        else:
            lines.append("| n/a | 0/0 | 0.0% |")

        lines.extend(
            [
                "",
                "## By Price Level",
                "",
                "| Price Bucket | Filled / Orders | Fill Rate |",
                "|---|---:|---:|",
            ]
        )
        if summary["fill_rate_by_price_level"]:
            for bucket, stats in summary["fill_rate_by_price_level"].items():
                lines.append(
                    f"| {bucket} | {stats['filled']}/{stats['orders']} | {stats['fill_rate']:.1%} |"
                )
        else:
            lines.append("| n/a | 0/0 | 0.0% |")

        self.report_path.write_text("\n".join(lines) + "\n")
        return self.report_path
