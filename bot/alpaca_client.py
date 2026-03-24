#!/usr/bin/env python3
"""Minimal Alpaca REST client for the first automated trading lane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any

import httpx


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _to_iso8601(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_alpaca_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("-", "/")


def normalize_symbol_key(symbol: str) -> str:
    return normalize_alpaca_symbol(symbol).replace("/", "")


class AlpacaAPIError(RuntimeError):
    """Raised when an Alpaca API request fails."""


AlpacaClientError = AlpacaAPIError


@dataclass(frozen=True)
class AlpacaRESTConfig:
    key_id: str
    secret_key: str
    paper_trading: bool = True
    paper_base_url: str = "https://paper-api.alpaca.markets"
    live_base_url: str = "https://api.alpaca.markets"
    data_base_url: str = "https://data.alpaca.markets"
    crypto_feed_loc: str = "us"
    timeout_seconds: float = 15.0

    @property
    def trading_base_url(self) -> str:
        return self.paper_base_url if self.paper_trading else self.live_base_url


@dataclass(frozen=True)
class AlpacaClientConfig(AlpacaRESTConfig):
    """Compatibility config used by the Alpaca first-trade lane."""

    mode: str = "paper"

    @classmethod
    def from_env(cls, mode: str | None = None) -> "AlpacaClientConfig":
        resolved_mode = str(mode or os.environ.get("ALPACA_TRADING_MODE", "paper")).strip().lower()
        if resolved_mode not in {"shadow", "paper", "live"}:
            raise AlpacaAPIError(f"Unsupported Alpaca mode: {resolved_mode}")

        key_id = str(
            os.environ.get("ALPACA_PAPER_API_KEY_ID")
            or os.environ.get("APCA_API_KEY_ID")
            or os.environ.get("ALPACA_API_KEY_ID")
            or ""
        ).strip()
        secret_key = str(
            os.environ.get("ALPACA_PAPER_API_SECRET_KEY")
            or os.environ.get("APCA_API_SECRET_KEY")
            or os.environ.get("ALPACA_API_SECRET_KEY")
            or ""
        ).strip()
        if resolved_mode == "live":
            key_id = str(
                os.environ.get("ALPACA_API_KEY_ID")
                or os.environ.get("APCA_API_KEY_ID")
                or ""
            ).strip()
            secret_key = str(
                os.environ.get("ALPACA_API_SECRET_KEY")
                or os.environ.get("APCA_API_SECRET_KEY")
                or ""
            ).strip()

        if not key_id or not secret_key:
            raise AlpacaAPIError(
                "Missing Alpaca credentials. Set ALPACA_PAPER_API_KEY_ID / "
                "ALPACA_PAPER_API_SECRET_KEY for paper or ALPACA_API_KEY_ID / "
                "ALPACA_API_SECRET_KEY for live."
            )

        return cls(
            key_id=key_id,
            secret_key=secret_key,
            paper_trading=resolved_mode != "live",
            paper_base_url=str(
                os.environ.get("ALPACA_PAPER_TRADING_BASE_URL")
                or os.environ.get("ALPACA_PAPER_BASE_URL")
                or "https://paper-api.alpaca.markets"
            ).rstrip("/"),
            live_base_url=str(
                os.environ.get("ALPACA_TRADING_BASE_URL")
                or os.environ.get("ALPACA_LIVE_BASE_URL")
                or "https://api.alpaca.markets"
            ).rstrip("/"),
            data_base_url=str(os.environ.get("ALPACA_DATA_BASE_URL") or "https://data.alpaca.markets").rstrip("/"),
            crypto_feed_loc=str(os.environ.get("ALPACA_CRYPTO_FEED_LOC") or "us").strip().lower() or "us",
            timeout_seconds=float(os.environ.get("ALPACA_TIMEOUT_SECONDS") or 15.0),
            mode=resolved_mode,
        )


class AlpacaClient:
    """Small sync REST wrapper with only the calls needed for the first trade."""

    def __init__(
        self,
        config: AlpacaRESTConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._client = http_client or httpx.Client(timeout=config.timeout_seconds)

    @classmethod
    def from_env(
        cls,
        *,
        paper_trading: bool | None = None,
        http_client: httpx.Client | None = None,
    ) -> "AlpacaClient":
        key_id = str(
            os.environ.get("APCA_API_KEY_ID")
            or os.environ.get("ALPACA_API_KEY_ID")
            or ""
        ).strip()
        secret_key = str(
            os.environ.get("APCA_API_SECRET_KEY")
            or os.environ.get("ALPACA_API_SECRET_KEY")
            or ""
        ).strip()
        if not key_id or not secret_key:
            raise AlpacaAPIError(
                "Missing Alpaca credentials. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in .env."
            )

        resolved_paper = (
            _parse_bool(os.environ.get("ALPACA_PAPER_TRADING"), default=True)
            if paper_trading is None
            else bool(paper_trading)
        )
        config = AlpacaRESTConfig(
            key_id=key_id,
            secret_key=secret_key,
            paper_trading=resolved_paper,
            paper_base_url=str(os.environ.get("ALPACA_PAPER_BASE_URL") or "https://paper-api.alpaca.markets").rstrip("/"),
            live_base_url=str(os.environ.get("ALPACA_LIVE_BASE_URL") or "https://api.alpaca.markets").rstrip("/"),
            data_base_url=str(os.environ.get("ALPACA_DATA_BASE_URL") or "https://data.alpaca.markets").rstrip("/"),
            crypto_feed_loc=str(os.environ.get("ALPACA_CRYPTO_FEED_LOC") or "us").strip().lower() or "us",
            timeout_seconds=float(os.environ.get("ALPACA_TIMEOUT_SECONDS") or 15.0),
        )
        return cls(config, http_client=http_client)

    @property
    def paper_trading(self) -> bool:
        return bool(self.config.paper_trading)

    @property
    def environment(self) -> str:
        return "paper" if self.paper_trading else "live"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AlpacaClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.config.key_id,
            "APCA-API-SECRET-KEY": self.config.secret_key,
        }

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        response = self._client.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
        )
        if response.status_code >= 400:
            message = response.text[:500]
            raise AlpacaAPIError(f"Alpaca API {response.status_code} for {url}: {message}")
        if not response.text:
            return {}
        return response.json()

    def get_account(self) -> dict[str, Any]:
        return self._request_json("GET", f"{self.config.trading_base_url}/v2/account")

    def list_positions(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"{self.config.trading_base_url}/v2/positions")
        return payload if isinstance(payload, list) else []

    def list_orders(self, *, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
        payload = self._request_json(
            "GET",
            f"{self.config.trading_base_url}/v2/orders",
            params={"status": status, "limit": int(limit), "direction": "desc"},
        )
        return payload if isinstance(payload, list) else []

    def get_asset(self, symbol: str) -> dict[str, Any]:
        normalized = normalize_symbol_key(symbol)
        payload = self._request_json("GET", f"{self.config.trading_base_url}/v2/assets/{normalized}")
        return payload if isinstance(payload, dict) else {}

    def get_position_qty(self, symbol: str) -> float:
        needle = normalize_symbol_key(symbol)
        for row in self.list_positions():
            current = normalize_symbol_key(str(row.get("symbol") or ""))
            if current == needle:
                try:
                    return float(row.get("qty") or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    def get_crypto_bars(
        self,
        symbol: str | None = None,
        *,
        symbols: list[str] | None = None,
        timeframe: str = "1Min",
        limit: int = 120,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> Any:
        if symbols is not None:
            payload: dict[str, list[dict[str, Any]]] = {}
            for current in symbols:
                payload[normalize_alpaca_symbol(current)] = self.get_crypto_bars(
                    normalize_alpaca_symbol(current),
                    timeframe=timeframe,
                    limit=limit,
                    start=start,
                    end=end,
                )
            return {"bars": payload}

        if symbol is None:
            raise ValueError("get_crypto_bars requires symbol or symbols")
        normalized = normalize_alpaca_symbol(symbol)
        params: dict[str, Any] = {
            "symbols": normalized,
            "timeframe": timeframe,
            "limit": int(limit),
        }
        start_value = _to_iso8601(start)
        end_value = _to_iso8601(end)
        if start_value:
            params["start"] = start_value
        if end_value:
            params["end"] = end_value
        payload = self._request_json(
            "GET",
            f"{self.config.data_base_url}/v1beta3/crypto/{self.config.crypto_feed_loc}/bars",
            params=params,
        )
        bars = (payload.get("bars") or {}).get(normalized, [])
        return bars if isinstance(bars, list) else []

    def get_crypto_snapshot(self, symbol: str) -> dict[str, Any]:
        normalized = normalize_alpaca_symbol(symbol)
        payload = self._request_json(
            "GET",
            f"{self.config.data_base_url}/v1beta3/crypto/{self.config.crypto_feed_loc}/snapshots",
            params={"symbols": normalized},
        )
        snapshots = payload.get("snapshots") or {}
        snapshot = snapshots.get(normalized)
        return snapshot if isinstance(snapshot, dict) else {}

    def get_latest_crypto_orderbooks(self, *, symbols: list[str]) -> dict[str, Any]:
        orderbooks: dict[str, Any] = {}
        for symbol in symbols:
            normalized = normalize_alpaca_symbol(symbol)
            snapshot = self.get_crypto_snapshot(normalized)
            quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
            bid = float(quote.get("bp") or 0.0)
            ask = float(quote.get("ap") or 0.0)
            orderbooks[normalized] = {
                "b": [{"p": bid, "s": float(quote.get("bs") or 0.0)}],
                "a": [{"p": ask, "s": float(quote.get("as") or 0.0)}],
            }
        return {"orderbooks": orderbooks}

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        time_in_force: str,
        notional_usd: float | None = None,
        qty: float | None = None,
        limit_price: float | None = None,
        client_order_id: str | None = None,
        extended_hours: bool | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_alpaca_symbol(symbol)
        payload: dict[str, Any] = {
            "symbol": normalized,
            "side": str(side).strip().lower(),
            "type": str(order_type).strip().lower(),
            "time_in_force": str(time_in_force).strip().lower(),
        }
        if client_order_id:
            payload["client_order_id"] = str(client_order_id)
        if limit_price is not None:
            payload["limit_price"] = round(float(limit_price), 8)
        if qty is not None:
            payload["qty"] = round(float(qty), 8)
        elif notional_usd is not None:
            payload["notional"] = round(float(notional_usd), 2)
        else:
            raise ValueError("submit_order requires either qty or notional_usd")
        if extended_hours is not None:
            payload["extended_hours"] = bool(extended_hours)
        return self._request_json(
            "POST",
            f"{self.config.trading_base_url}/v2/orders",
            json_body=payload,
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"{self.config.trading_base_url}/v2/orders/{order_id}")
