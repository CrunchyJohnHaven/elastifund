#!/usr/bin/env python3
"""Alpaca executor adapter for strike-desk / strike-factory packets."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import time
from typing import Any

from bot.alpaca_client import AlpacaClient, AlpacaAPIError


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_side(raw: str) -> str:
    normalized = str(raw or "").strip().lower()
    if normalized in {"buy", "yes", "long", "up"}:
        return "buy"
    if normalized in {"sell", "no", "short", "down"}:
        return "sell"
    return "buy"


@dataclass
class AlpacaExecutionRecord:
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    notional_usd: float | None
    qty: float | None
    limit_price: float | None
    submit: bool
    environment: str
    response: dict[str, Any] = field(default_factory=dict)


class AlpacaExecutor:
    """Minimal executor that translates strike-desk payloads into Alpaca orders."""

    def __init__(
        self,
        client: AlpacaClient,
        *,
        submit: bool,
        allow_live_env_var: str = "ALPACA_ALLOW_LIVE",
        poll_seconds: float = 0.75,
    ) -> None:
        self.client = client
        self.submit = bool(submit)
        self.allow_live_env_var = str(allow_live_env_var)
        self.poll_seconds = float(poll_seconds)
        self.submissions: list[AlpacaExecutionRecord] = []

    def _extract_order_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        trade_record = payload.get("trade_record") if isinstance(payload.get("trade_record"), dict) else {}
        signal_metadata = trade_record.get("signal_metadata") if isinstance(trade_record.get("signal_metadata"), dict) else {}
        order_metadata = payload.get("order_metadata") if isinstance(payload.get("order_metadata"), dict) else {}
        signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}

        symbol = str(
            order_metadata.get("symbol")
            or signal_metadata.get("symbol")
            or payload.get("market_id")
            or ""
        ).strip()
        if not symbol:
            raise ValueError("Alpaca executor requires order_metadata.symbol or signal_metadata.symbol")

        side = _normalize_side(
            str(
                order_metadata.get("alpaca_side")
                or signal_metadata.get("alpaca_side")
                or signal.get("direction")
                or payload.get("side")
                or "buy"
            )
        )
        order_type = str(
            order_metadata.get("alpaca_order_type")
            or signal_metadata.get("alpaca_order_type")
            or "market"
        ).strip().lower()
        time_in_force = str(
            order_metadata.get("alpaca_time_in_force")
            or signal_metadata.get("alpaca_time_in_force")
            or ("gtc" if order_type == "market" else "ioc")
        ).strip().lower()
        limit_price = _safe_float(
            order_metadata.get("alpaca_limit_price")
            or signal_metadata.get("alpaca_limit_price")
        )
        qty = _safe_float(
            order_metadata.get("alpaca_qty")
            or signal_metadata.get("alpaca_qty")
        )
        notional_usd = _safe_float(
            order_metadata.get("alpaca_notional_usd")
            or signal_metadata.get("alpaca_notional_usd")
            or payload.get("size_usd")
        )

        if side == "sell" and qty is None:
            qty = _safe_float(
                order_metadata.get("position_qty")
                or signal_metadata.get("position_qty")
                or payload.get("order_size")
            )
        if order_type == "limit" and limit_price is None:
            limit_price = _safe_float(payload.get("order_price") or payload.get("price"))
        return {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "limit_price": limit_price,
            "qty": qty,
            "notional_usd": notional_usd,
            "client_order_id": str(order_metadata.get("packet_id") or signal.get("packet_id") or "") or None,
        }

    def place_order(self, **payload: Any) -> dict[str, Any]:
        order = self._extract_order_fields(dict(payload))
        symbol = order["symbol"]
        side = order["side"]
        order_type = order["order_type"]
        time_in_force = order["time_in_force"]
        limit_price = order["limit_price"]
        qty = order["qty"]
        notional_usd = order["notional_usd"]
        client_order_id = order["client_order_id"]

        if self.client.environment == "live" and not _parse_bool(os.environ.get(self.allow_live_env_var), default=False):
            raise RuntimeError(
                f"{self.allow_live_env_var}=true is required before live Alpaca submissions are allowed."
            )

        if not self.submit:
            response = {
                "status": "shadow",
                "filled": False,
                "environment": self.client.environment,
                "symbol": symbol,
                "side": side,
                "type": order_type,
            }
            self.submissions.append(
                AlpacaExecutionRecord(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    notional_usd=notional_usd,
                    qty=qty,
                    limit_price=limit_price,
                    submit=False,
                    environment=self.client.environment,
                    response=response,
                )
            )
            return response

        response = self.client.submit_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            time_in_force=time_in_force,
            notional_usd=notional_usd,
            qty=qty,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )
        order_id = str(response.get("id") or "")
        status = str(response.get("status") or "submitted").strip().lower()
        if order_id and status in {"new", "accepted", "pending_new", "accepted_for_bidding"}:
            time.sleep(self.poll_seconds)
            try:
                response = self.client.get_order(order_id)
                status = str(response.get("status") or status).strip().lower()
            except AlpacaAPIError:
                pass

        filled = status in {"filled", "partially_filled"}
        normalized = {
            "status": status,
            "filled": filled,
            "order_id": order_id,
            "filled_avg_price": response.get("filled_avg_price"),
            "filled_qty": response.get("filled_qty"),
            "environment": self.client.environment,
            "raw": response,
        }
        self.submissions.append(
            AlpacaExecutionRecord(
                symbol=symbol,
                side=side,
                order_type=order_type,
                time_in_force=time_in_force,
                notional_usd=notional_usd,
                qty=qty,
                limit_price=limit_price,
                submit=True,
                environment=self.client.environment,
                response=normalized,
            )
        )
        return normalized

