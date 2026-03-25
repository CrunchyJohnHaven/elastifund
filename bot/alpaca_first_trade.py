#!/usr/bin/env python3
"""End-to-end Alpaca first-trade lane with proof artifacts and queue execution."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.alpaca_client import (
    AlpacaClient,
    AlpacaClientConfig,
    AlpacaClientError,
    classify_alpaca_api_error,
)
from bot.proof_types import build_evidence_record, build_promotion_ticket, build_thesis_record
from bot.thesis_foundry import DEFAULT_OUTPUT_PATH as DEFAULT_FOUNDRY_OUTPUT_PATH
from bot.thesis_foundry import build_thesis_candidates
from bot.lane_supervisor import (
    DEFAULT_ALPACA_QUEUE_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_SUPERVISOR_OUTPUT_PATH,
    run_supervisor,
)
from scripts.report_envelope import write_report
from strategies.alpaca_crypto_momentum import (
    AlpacaMomentumVariant,
    TopOfBook,
    default_alpaca_momentum_variants,
    parse_crypto_bars_response,
    parse_latest_orderbooks_response,
    rank_momentum_candidates,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LANE_PATH = REPO_ROOT / "reports" / "parallel" / "alpaca_crypto_lane.json"
DEFAULT_EXECUTION_PATH = REPO_ROOT / "reports" / "alpaca_first_trade" / "latest.json"
DEFAULT_EXECUTION_HISTORY_PATH = REPO_ROOT / "reports" / "alpaca_first_trade" / "history.jsonl"
DEFAULT_STATE_PATH = REPO_ROOT / "state" / "alpaca_first_trade_state.json"
DEFAULT_THESIS_BUNDLE_SCRIPT = REPO_ROOT / "scripts" / "thesis_bundle.py"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime | None = None) -> str:
    timestamp = dt or _utc_now()
    return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _alerts_enabled() -> bool:
    raw = str(os.environ.get("ALPACA_TELEGRAM_ALERTS", "true")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _extract_execution_report(report: dict[str, Any]) -> dict[str, Any]:
    execution_report = report.get("execution_report")
    if isinstance(execution_report, dict):
        return execution_report
    return report


def build_alpaca_trade_alert(report: dict[str, Any]) -> str | None:
    """Build a low-noise Telegram alert for meaningful Alpaca execution events."""
    if not _alerts_enabled() or not isinstance(report, dict):
        return None

    execution_report = _extract_execution_report(report)
    action = str(execution_report.get("action") or "").strip().lower()
    if action not in {"entry", "exit"}:
        return None

    mode = str(execution_report.get("mode") or "paper").strip().upper() or "PAPER"
    symbol = str(execution_report.get("symbol") or "").strip()
    queue_entry = execution_report.get("queue_entry") if isinstance(execution_report.get("queue_entry"), dict) else {}
    order = execution_report.get("order") if isinstance(execution_report.get("order"), dict) else {}

    lines = [f"ALPACA {action.upper()} [{mode}]"]
    if symbol:
        lines.append(f"Symbol: {symbol}")

    variant_id = str(
        execution_report.get("variant_id")
        or queue_entry.get("variant_id")
        or ""
    ).strip()
    if variant_id:
        lines.append(f"Variant: {variant_id}")

    if action == "entry":
        notional = _safe_float(execution_report.get("notional_usd"))
        if notional > 0:
            lines.append(f"Notional: ${notional:.2f}")
        prob_positive = _safe_float(
            queue_entry.get("model_probability")
            or queue_entry.get("prob_positive")
        )
        if prob_positive > 0:
            lines.append(f"Prob positive: {prob_positive:.1%}")
        expected_edge_bps = _safe_float(queue_entry.get("expected_edge_bps"))
        if expected_edge_bps > 0:
            lines.append(f"Expected edge: {expected_edge_bps:.1f} bps")
    else:
        unrealized_bps = _safe_float(execution_report.get("unrealized_bps"))
        realized_log_return = execution_report.get("realized_log_return")
        lines.append(f"Exit signal: {unrealized_bps:.1f} bps")
        if realized_log_return is not None:
            lines.append(f"Realized log return: {float(realized_log_return):.5f}")

    filled_avg_price = _safe_float(order.get("filled_avg_price"))
    if filled_avg_price > 0:
        lines.append(f"Fill price: ${filled_avg_price:.4f}")
    order_id = str(order.get("id") or "").strip()
    if order_id:
        lines.append(f"Order ID: {order_id}")

    summary = str(execution_report.get("summary") or report.get("summary") or "").strip()
    if summary:
        lines.append(f"Summary: {summary}")
    return "\n".join(lines)


def send_alpaca_trade_alert(
    report: dict[str, Any],
    *,
    send_message: Callable[[str], bool] | None = None,
) -> bool:
    """Send a Telegram alert when the Alpaca lane performs an entry or exit."""
    message = build_alpaca_trade_alert(report)
    if not message:
        return False

    sender = send_message
    if sender is None:
        try:
            from bot.health_monitor import build_telegram_sender
        except Exception:
            build_telegram_sender = None
        sender = build_telegram_sender() if build_telegram_sender is not None else None
    if sender is None:
        return False
    try:
        return bool(sender(message))
    except Exception:
        return False


@dataclass(frozen=True)
class AlpacaFirstTradeConfig:
    mode: str = "paper"
    allow_live: bool = False
    symbols: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
    timeframe: str = "1Min"
    bars_limit: int = 240
    order_notional_usd: float = 25.0
    max_notional_usd: float = 50.0
    min_cash_buffer_usd: float = 25.0
    min_prob_positive: float = 0.55
    min_expected_edge_bps: float = 60.0
    max_spread_bps: float = 35.0
    lane_path: Path = DEFAULT_LANE_PATH
    execution_path: Path = DEFAULT_EXECUTION_PATH
    execution_history_path: Path = DEFAULT_EXECUTION_HISTORY_PATH
    state_path: Path = DEFAULT_STATE_PATH
    foundry_output_path: Path = DEFAULT_FOUNDRY_OUTPUT_PATH
    supervisor_output_path: Path = DEFAULT_SUPERVISOR_OUTPUT_PATH
    alpaca_queue_path: Path = DEFAULT_ALPACA_QUEUE_PATH

    @classmethod
    def from_env(cls, mode: str | None = None) -> "AlpacaFirstTradeConfig":
        resolved_mode = str(mode or os.environ.get("ALPACA_TRADING_MODE", "paper")).strip().lower()
        symbols = tuple(
            symbol.strip() for symbol in os.environ.get("ALPACA_SYMBOLS", "BTC/USD,ETH/USD,SOL/USD").split(",")
            if symbol.strip()
        )
        return cls(
            mode=resolved_mode,
            allow_live=os.environ.get("ALPACA_ALLOW_LIVE", "false").strip().lower() == "true",
            symbols=symbols or ("BTC/USD",),
            timeframe=os.environ.get("ALPACA_TIMEFRAME", "1Min").strip() or "1Min",
            bars_limit=max(60, _safe_int(os.environ.get("ALPACA_BARS_LIMIT"), 240)),
            order_notional_usd=max(1.0, _safe_float(os.environ.get("ALPACA_ORDER_NOTIONAL_USD"), 25.0)),
            max_notional_usd=max(1.0, _safe_float(os.environ.get("ALPACA_MAX_NOTIONAL_USD"), 50.0)),
            min_cash_buffer_usd=max(0.0, _safe_float(os.environ.get("ALPACA_MIN_CASH_BUFFER_USD"), 25.0)),
            min_prob_positive=min(0.99, max(0.01, _safe_float(os.environ.get("ALPACA_MIN_PROB_POSITIVE"), 0.55))),
            min_expected_edge_bps=max(0.0, _safe_float(os.environ.get("ALPACA_MIN_EXPECTED_EDGE_BPS"), 60.0)),
            max_spread_bps=max(1.0, _safe_float(os.environ.get("ALPACA_MAX_SPREAD_BPS"), 35.0)),
        )


@dataclass
class AlpacaFirstTradeState:
    consumed_thesis_ids: list[str] = field(default_factory=list)
    variant_live_returns: dict[str, list[float]] = field(default_factory=dict)
    open_trade: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AlpacaFirstTradeState":
        return cls(
            consumed_thesis_ids=list(payload.get("consumed_thesis_ids") or []),
            variant_live_returns={
                str(key): [float(value) for value in values or []]
                for key, values in dict(payload.get("variant_live_returns") or {}).items()
            },
            open_trade=dict(payload.get("open_trade")) if isinstance(payload.get("open_trade"), dict) else None,
        )


class AlpacaFirstTradeSystem:
    """Runs the Alpaca candidate lane and executes the first approved trade."""

    def __init__(self, config: AlpacaFirstTradeConfig):
        self.config = config

    def load_state(self) -> AlpacaFirstTradeState:
        if not self.config.state_path.exists():
            return AlpacaFirstTradeState()
        try:
            payload = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            return AlpacaFirstTradeState.from_dict(payload if isinstance(payload, dict) else {})
        except Exception:
            return AlpacaFirstTradeState()

    def save_state(self, state: AlpacaFirstTradeState) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_path.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def build_client(self) -> AlpacaClient:
        client_config = AlpacaClientConfig.from_env(mode=self.config.mode)
        return AlpacaClient(client_config)

    def build_variants(self) -> tuple[AlpacaMomentumVariant, ...]:
        return default_alpaca_momentum_variants(self.config.symbols)

    def run_lane(self, client: AlpacaClient) -> dict[str, Any]:
        state = self.load_state()
        bars_payload = client.get_crypto_bars(
            symbols=list(self.config.symbols),
            timeframe=self.config.timeframe,
            limit=self.config.bars_limit,
        )
        books_payload = client.get_latest_crypto_orderbooks(symbols=list(self.config.symbols))
        bars_by_symbol = parse_crypto_bars_response(bars_payload)
        books_by_symbol = parse_latest_orderbooks_response(books_payload)
        variants = self.build_variants()

        ranked = rank_momentum_candidates(
            bars_by_symbol=bars_by_symbol,
            books_by_symbol=books_by_symbol,
            variants=variants,
            live_return_map=state.variant_live_returns,
            recommended_notional_usd=min(self.config.order_notional_usd, self.config.max_notional_usd),
            min_prob_positive=self.config.min_prob_positive,
            min_expected_edge_bps=self.config.min_expected_edge_bps,
            max_spread_bps=self.config.max_spread_bps,
        )

        candidate_rows = [
            score.to_candidate_row(execution_mode=self.config.mode)
            for score in ranked
        ]
        payload = {
            "artifact": "alpaca_crypto_lane.v1",
            "generated_at": _iso_z(),
            "mode": self.config.mode,
            "symbols": list(self.config.symbols),
            "timeframe": self.config.timeframe,
            "bars_limit": self.config.bars_limit,
            "candidate_count": len(candidate_rows),
            "candidate_rows": candidate_rows,
            "live_return_variants": len(state.variant_live_returns),
            "source_summary": {
                "bars_symbols": sorted(bars_by_symbol.keys()),
                "book_symbols": sorted(books_by_symbol.keys()),
            },
        }
        status = "fresh" if candidate_rows else "blocked"
        blockers = [] if candidate_rows else ["no_alpaca_candidates"]
        summary = (
            f"{len(candidate_rows)} Alpaca crypto candidates ready"
            if candidate_rows
            else "alpaca lane found no crypto candidates that cleared the gates"
        )
        report = write_report(
            self.config.lane_path,
            artifact="alpaca_crypto_lane",
            payload=payload,
            status=status,
            source_of_truth="alpaca market-data bars; alpaca latest crypto orderbooks",
            freshness_sla_seconds=300,
            blockers=blockers,
            summary=summary,
        )
        return report

    def build_foundry_and_supervisor(self) -> dict[str, Any]:
        foundry_payload = build_thesis_candidates()
        self.config.foundry_output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.foundry_output_path.write_text(
            json.dumps(foundry_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        # Best effort: refresh the authoritative thesis bundle, but keep going if
        # the rest of the kernel is currently blocked or stale.
        subprocess.run(
            [sys.executable, str(DEFAULT_THESIS_BUNDLE_SCRIPT)],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
        )

        supervisor_payload = run_supervisor(
            alpaca_queue_path=self.config.alpaca_queue_path,
            output_path=self.config.supervisor_output_path,
        )
        if int(supervisor_payload.get("alpaca_candidates_routed") or 0) == 0:
            supervisor_payload = run_supervisor(
                thesis_path=self.config.foundry_output_path,
                alpaca_queue_path=self.config.alpaca_queue_path,
                output_path=self.config.supervisor_output_path,
            )
        return {
            "foundry": foundry_payload,
            "supervisor": supervisor_payload,
        }

    def _read_queue_rows(self) -> list[dict[str, Any]]:
        if not self.config.alpaca_queue_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.config.alpaca_queue_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def _append_history(self, payload: dict[str, Any]) -> None:
        self.config.execution_history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config.execution_history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def _find_position(self, positions: list[dict[str, Any]], symbol: str) -> dict[str, Any] | None:
        for position in positions:
            if str(position.get("symbol") or "") == symbol:
                return position
        return None

    def _queue_entry_key(self, queue_entry: dict[str, Any]) -> str:
        thesis_id = str(queue_entry.get("thesis_id") or "").strip()
        queued_at = str(queue_entry.get("queued_at") or "").strip()
        symbol = str(queue_entry.get("ticker") or queue_entry.get("symbol") or "").strip()
        if thesis_id and queued_at:
            return f"{thesis_id}|{queued_at}"
        if thesis_id and symbol:
            return f"{thesis_id}|{symbol}"
        return thesis_id

    def _select_next_queue_entry(self, state: AlpacaFirstTradeState) -> dict[str, Any] | None:
        consumed = set(state.consumed_thesis_ids)
        for row in self._read_queue_rows():
            queue_entry_key = self._queue_entry_key(row)
            if queue_entry_key and queue_entry_key not in consumed:
                return row
        return None

    def _consume_queue_entry(self, state: AlpacaFirstTradeState, queue_entry: dict[str, Any]) -> None:
        queue_entry_key = self._queue_entry_key(queue_entry)
        if not queue_entry_key:
            return
        state.consumed_thesis_ids.append(queue_entry_key)
        state.consumed_thesis_ids = state.consumed_thesis_ids[-200:]
        self.save_state(state)

    def _preflight_live_entry(
        self,
        *,
        client: AlpacaClient,
        account: dict[str, Any],
        symbol: str,
    ) -> tuple[list[str], dict[str, Any]]:
        blockers: list[str] = []
        details: dict[str, Any] = {
            "account": {
                "status": account.get("status"),
                "trading_blocked": account.get("trading_blocked"),
                "account_blocked": account.get("account_blocked"),
                "transfers_blocked": account.get("transfers_blocked"),
                "crypto_status": account.get("crypto_status"),
            }
        }

        if self.config.mode != "live":
            return blockers, details

        crypto_status = str(account.get("crypto_status") or "").strip().lower()
        if crypto_status and crypto_status not in {"active", "enabled"}:
            blockers.append("alpaca_crypto_not_enabled")

        asset: dict[str, Any] = {}
        get_asset = getattr(client, "get_asset", None)
        if callable(get_asset):
            try:
                maybe_asset = get_asset(symbol)
                if isinstance(maybe_asset, dict):
                    asset = maybe_asset
            except AlpacaClientError:
                blockers.append("alpaca_asset_lookup_failed")
        if asset:
            details["asset"] = {
                "symbol": asset.get("symbol"),
                "status": asset.get("status"),
                "tradable": asset.get("tradable"),
                "class": asset.get("class") or asset.get("asset_class"),
            }
            if asset.get("tradable") is False:
                blockers.append("alpaca_symbol_not_tradable")
            asset_status = str(asset.get("status") or "").strip().lower()
            if asset_status and asset_status not in {"active"}:
                blockers.append("alpaca_asset_inactive")

        return sorted(set(blockers)), details

    def _compute_realized_log_return(self, *, entry_price: float, exit_price: float) -> float | None:
        if entry_price <= 0 or exit_price <= 0:
            return None
        fee_bps = _safe_float(os.environ.get("ALPACA_CRYPTO_TAKER_FEE_BPS"), 25.0)
        roundtrip_cost = (2.0 * fee_bps) / 10_000.0
        raw_return = (exit_price / entry_price) - 1.0 - roundtrip_cost
        if raw_return <= -0.999999:
            return None
        return float(__import__("math").log(1.0 + raw_return))

    def _write_execution_report(
        self,
        *,
        payload: dict[str, Any],
        status: str,
        blockers: list[str],
        summary: str,
    ) -> dict[str, Any]:
        report = write_report(
            self.config.execution_path,
            artifact="alpaca_first_trade",
            payload=payload,
            status=status,
            source_of_truth="alpaca account; alpaca positions; alpaca orders; alpaca crypto lane queue",
            freshness_sla_seconds=300,
            blockers=blockers,
            summary=summary,
        )
        self._append_history(report)
        return report

    def execute_from_queue(self, client: AlpacaClient) -> dict[str, Any]:
        now = time.time()
        state = self.load_state()
        account = client.get_account()
        positions = client.list_positions()
        available_cash = _safe_float(account.get("cash"))

        if self.config.mode == "shadow":
            return self._write_execution_report(
                payload={
                    "mode": self.config.mode,
                    "action": "no_execute",
                    "account_cash": available_cash,
                },
                status="blocked",
                blockers=["shadow_mode_no_orders"],
                summary="alpaca first-trade executor stayed in shadow mode",
            )
        if self.config.mode == "live" and not self.config.allow_live:
            return self._write_execution_report(
                payload={
                    "mode": self.config.mode,
                    "action": "no_execute",
                    "account_cash": available_cash,
                },
                status="blocked",
                blockers=["live_mode_not_allowed"],
                summary="alpaca first-trade executor refused live mode without ALPACA_ALLOW_LIVE=true",
            )

        open_trade = state.open_trade
        if open_trade:
            symbol = str(open_trade.get("symbol") or "")
            position = self._find_position(positions, symbol)
            if position is None:
                state.open_trade = None
                self.save_state(state)
            else:
                entry_price = _safe_float(open_trade.get("entry_price"))
                current_price = _safe_float(position.get("current_price") or position.get("market_value"))
                variant_id = str(open_trade.get("variant_id") or "")
                elapsed_minutes = max(0.0, (now - _safe_float(open_trade.get("opened_at"))) / 60.0)
                hold_bars = _safe_int(open_trade.get("hold_bars"), 15)
                should_exit = elapsed_minutes >= hold_bars
                unrealized_bps = 0.0
                if entry_price > 0 and current_price > 0:
                    unrealized_bps = ((current_price / entry_price) - 1.0) * 10_000.0
                if unrealized_bps <= -_safe_float(open_trade.get("stop_loss_bps"), 70.0):
                    should_exit = True
                if unrealized_bps >= _safe_float(open_trade.get("take_profit_bps"), 150.0):
                    should_exit = True

                if should_exit:
                    qty = str(position.get("qty") or open_trade.get("qty") or "")
                    order = client.submit_order(
                        symbol=symbol,
                        side="sell",
                        order_type="market",
                        time_in_force="gtc",
                        qty=qty,
                        client_order_id=f"alpaca-exit-{uuid.uuid4().hex[:12]}",
                    )
                    realized_log_return = self._compute_realized_log_return(
                        entry_price=entry_price,
                        exit_price=_safe_float(order.get("filled_avg_price")) or current_price,
                    )
                    if realized_log_return is not None:
                        state.variant_live_returns.setdefault(variant_id, []).append(realized_log_return)
                    state.open_trade = None
                    self.save_state(state)
                    payload = {
                        "mode": self.config.mode,
                        "action": "exit",
                        "symbol": symbol,
                        "qty": qty,
                        "order": order,
                        "variant_id": variant_id,
                        "unrealized_bps": round(unrealized_bps, 2),
                        "realized_log_return": realized_log_return,
                    }
                    return self._write_execution_report(
                        payload=payload,
                        status="fresh",
                        blockers=[],
                        summary=f"alpaca first-trade system exited {symbol}",
                    )

                return self._write_execution_report(
                    payload={
                        "mode": self.config.mode,
                        "action": "hold_open_position",
                        "symbol": symbol,
                        "elapsed_minutes": round(elapsed_minutes, 2),
                        "unrealized_bps": round(unrealized_bps, 2),
                    },
                    status="fresh",
                    blockers=[],
                    summary=f"alpaca first-trade system is holding {symbol}",
                )

        queue_entry = self._select_next_queue_entry(state)
        if queue_entry is None:
            return self._write_execution_report(
                payload={
                    "mode": self.config.mode,
                    "action": "no_candidate",
                    "account_cash": available_cash,
                },
                status="blocked",
                blockers=["no_unconsumed_alpaca_candidates"],
                summary="alpaca first-trade executor found no queued candidates",
            )

        symbol = str(queue_entry.get("ticker") or queue_entry.get("symbol") or "")
        variant_id = str(queue_entry.get("variant_id") or "")
        prob_positive = _safe_float(queue_entry.get("model_probability") or queue_entry.get("prob_positive"))
        expected_edge_bps = _safe_float(queue_entry.get("expected_edge_bps"))
        if expected_edge_bps <= 0.0:
            expected_edge_bps = _safe_float(queue_entry.get("spread_adjusted_edge")) * 10_000.0
        requested_notional = min(
            self.config.max_notional_usd,
            max(1.0, _safe_float(queue_entry.get("recommended_notional_usd"), self.config.order_notional_usd)),
        )
        cash_limit = max(0.0, available_cash - self.config.min_cash_buffer_usd)
        final_notional = min(requested_notional, cash_limit)
        # Bootstrap mode: first trade has no live returns yet — use relaxed gates
        replay_count = _safe_int(queue_entry.get("replay_trade_count"), 0)
        is_bootstrap = replay_count < 8
        effective_min_prob = 0.51 if is_bootstrap else self.config.min_prob_positive
        effective_min_edge = 1.0 if is_bootstrap else self.config.min_expected_edge_bps

        blockers: list[str] = []
        if not symbol:
            blockers.append("missing_symbol")
        if final_notional <= 0:
            blockers.append("insufficient_cash_after_buffer")
        if prob_positive < effective_min_prob:
            blockers.append("prob_positive_below_gate")
        if expected_edge_bps < effective_min_edge:
            blockers.append("expected_edge_below_gate")
        existing_positions = [pos.get("symbol") for pos in positions]
        if existing_positions:
            blockers.append("existing_positions_present")

        live_preflight_blockers, live_preflight_details = self._preflight_live_entry(
            client=client,
            account=account,
            symbol=symbol,
        )
        blockers.extend(live_preflight_blockers)

        evidence = build_evidence_record(
            source_module="alpaca_first_trade",
            evidence_type="alpaca_crypto_candidate",
            timestamp_utc=now,
            staleness_limit_s=300.0,
            payload=dict(queue_entry),
            confidence=min(0.99, max(0.0, prob_positive)),
        )
        thesis = build_thesis_record(
            hypothesis=f"alpaca crypto momentum {variant_id} on {symbol}",
            strategy_class="alpaca_crypto_momentum",
            evidence_refs=[evidence.hash],
            calibrated_probability=min(0.99, max(0.0, prob_positive)),
            confidence_interval=(max(0.0, prob_positive - 0.1), min(0.99, prob_positive + 0.1)),
            edge_estimate=expected_edge_bps,
            regime_context=f"{symbol} crypto spot momentum",
            kill_rule_results={"blockers": blockers, "mode": self.config.mode},
            created_utc=now,
            expires_utc=now + 300.0,
        )
        ticket = build_promotion_ticket(
            thesis_ref=thesis.thesis_id,
            evidence_refs=[evidence.hash],
            constraint_result={"allowed": not blockers, "blockers": blockers},
            stage_gate_result={"mode": self.config.mode, "promotion_stage": "micro_live"},
            position_size_usd=final_notional,
            max_loss_usd=min(final_notional, final_notional * 0.10),
            execution_mode=self.config.mode,
            approved_utc=now,
            expires_utc=now + 300.0,
            promotion_path="alpaca_first_trade",
        )

        if blockers:
            self._consume_queue_entry(state, queue_entry)
            return self._write_execution_report(
                payload={
                    "mode": self.config.mode,
                    "action": "blocked",
                    "queue_entry": queue_entry,
                    "evidence_record": evidence.to_dict(),
                    "thesis_record": thesis.to_dict(),
                    "promotion_ticket": ticket.to_dict(),
                    "account_cash": available_cash,
                    "live_preflight": live_preflight_details,
                },
                status="blocked",
                blockers=sorted(set(blockers)),
                summary=f"alpaca first-trade candidate for {symbol} was blocked",
            )

        try:
            order = client.submit_order(
                symbol=symbol,
                side="buy",
                order_type="market",
                time_in_force="gtc",
                notional_usd=round(final_notional, 2),
                client_order_id=f"alpaca-entry-{uuid.uuid4().hex[:12]}",
            )
        except AlpacaClientError as exc:
            classification = classify_alpaca_api_error(exc)
            if classification["status"] == "blocked":
                self._consume_queue_entry(state, queue_entry)
            return self._write_execution_report(
                payload={
                    "mode": self.config.mode,
                    "action": "blocked" if classification["status"] == "blocked" else "error",
                    "symbol": symbol,
                    "queue_entry": queue_entry,
                    "evidence_record": evidence.to_dict(),
                    "thesis_record": thesis.to_dict(),
                    "promotion_ticket": ticket.to_dict(),
                    "account_cash": available_cash,
                    "live_preflight": live_preflight_details,
                    "error": classification["error"],
                },
                status=classification["status"],
                blockers=list(classification["blockers"]),
                summary=str(classification["summary"]),
            )
        state.open_trade = {
            "thesis_id": queue_entry.get("thesis_id"),
            "variant_id": variant_id,
            "symbol": symbol,
            "opened_at": now,
            "entry_price": _safe_float(order.get("filled_avg_price") or queue_entry.get("last_price")),
            "qty": order.get("filled_qty") or order.get("qty"),
            "hold_bars": _safe_int(queue_entry.get("hold_bars"), 15),
            "stop_loss_bps": _safe_float(queue_entry.get("stop_loss_bps"), 70.0),
            "take_profit_bps": _safe_float(queue_entry.get("take_profit_bps"), 150.0),
        }
        self._consume_queue_entry(state, queue_entry)
        self.save_state(state)

        payload = {
            "mode": self.config.mode,
            "action": "entry",
            "symbol": symbol,
            "notional_usd": round(final_notional, 2),
            "order": order,
            "queue_entry": queue_entry,
            "evidence_record": evidence.to_dict(),
            "thesis_record": thesis.to_dict(),
            "promotion_ticket": ticket.to_dict(),
        }
        return self._write_execution_report(
            payload=payload,
            status="fresh",
            blockers=[],
            summary=f"alpaca first-trade system entered {symbol}",
        )

    def run_full_cycle(self, *, client: AlpacaClient | None = None) -> dict[str, Any]:
        close_client = False
        if client is None:
            client = self.build_client()
            close_client = True
        try:
            lane_report = self.run_lane(client)
            routing = self.build_foundry_and_supervisor()
            execution_report = self.execute_from_queue(client)
            return {
                "lane_report": lane_report,
                "routing": routing,
                "execution_report": execution_report,
            }
        finally:
            if close_client:
                client.close()
