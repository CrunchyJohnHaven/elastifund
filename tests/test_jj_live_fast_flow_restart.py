from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import bot.jj_live as jj_live_module
from bot.jj_live import JJLive
from bot.jj_live import RollingNotionalBudgetTracker


EMPTY_COMBINATORIAL_CYCLE = {
    "a6_detected": 0,
    "b1_detected": 0,
    "shadow_logged": 0,
    "live_attempted": 0,
    "blocked": 0,
    "active_baskets": 0,
    "arb_budget_in_use_usd": 0.0,
    "kill_triggers": [],
    "metrics": {},
}


class DummyState:
    def __init__(self) -> None:
        self.state = {
            "bankroll": 1_000.0,
            "total_deployed": 0.0,
            "daily_pnl": 0.0,
            "open_positions": {},
            "cycles_completed": 0,
            "started_at": "2026-03-08T00:00:00+00:00",
            "total_pnl": 0.0,
            "total_trades": 0,
            "trades_today": 0,
            "veterans_allocation": 0.0,
        }

    def sync_resolved_positions(self, _db) -> int:
        return 0

    def check_daily_loss_limit(self) -> bool:
        return True

    def count_active_linked_baskets(self) -> int:
        return 0

    def has_position(self, market_id: str) -> bool:
        return market_id in self.state["open_positions"]

    def get_arb_budget_in_use_usd(self) -> float:
        return 0.0

    def save(self) -> None:
        return None


class DummyAdaptivePlatt:
    enabled = False
    active_mode = "static"
    active_a = jj_live_module.PLATT_A
    active_b = jj_live_module.PLATT_B

    def refresh(self, force: bool = False) -> bool:
        return False

    def summary(self) -> dict:
        return {
            "selected_variant": "static",
            "active_mode": "static",
            "a": self.active_a,
            "b": self.active_b,
            "samples": 0,
            "last_refit_rows": 0,
        }

    def calibrate(self, raw_prob: float) -> float:
        return float(raw_prob)


class DummyDB:
    def __init__(self) -> None:
        self.cycles: list[dict] = []

    def log_cycle(self, payload: dict) -> None:
        self.cycles.append(payload)


class DummyScanner:
    def __init__(self, markets: list[dict]) -> None:
        self._markets = markets

    def fetch_active_markets(self, limit: int = 100) -> list[dict]:
        return list(self._markets[:limit])

    @staticmethod
    def extract_prices(market: dict) -> dict:
        prices = market.get("outcomePrices", [0.5, 0.5])
        return {"YES": float(prices[0])}

    @staticmethod
    def extract_token_ids(market: dict) -> list[str]:
        return list(market.get("clobTokenIds", []))


class DummyNotifier:
    async def send_message(self, *_args, **_kwargs):
        return True

    async def send_error(self, *_args, **_kwargs):
        return True

    async def send_startup(self, *_args, **_kwargs):
        return True


class DummyCombinatorialConfig:
    def any_enabled(self) -> bool:
        return True


def test_real_jj_live_import_surface_exposes_wallet_flow_hook():
    assert hasattr(JJLive, "_build_startup_lane_health")
    assert hasattr(JJLive, "_wallet_flow_bootstrap_status")
    assert hasattr(jj_live_module, "wallet_flow_get_signals")
    assert jj_live_module.wallet_flow_get_signals is None or callable(
        jj_live_module.wallet_flow_get_signals
    )


def _make_live(tmp_path: Path, *, markets: list[dict]) -> JJLive:
    live = JJLive.__new__(JJLive)
    live.paper_mode = True
    live.runtime_mode = "shadow"
    live.allow_order_submission = True
    live.allow_order_submission = True
    live.enable_llm_signals = False
    live.enable_wallet_flow = True
    live.enable_lmsr = False
    live.enable_cross_platform_arb = False
    live.fast_flow_only = True
    live.wallet_flow_scores_file = tmp_path / "smart_wallets.json"
    live.wallet_flow_db_file = tmp_path / "wallet_scores.db"
    live._startup_lane_health = {}
    live._last_lane_health = {}
    live._elastic_market_lookup = {}
    live._elastic_token_market_index = {}
    live._anomaly_task = None
    live.state = DummyState()
    live.db = DummyDB()
    live.adaptive_platt = DummyAdaptivePlatt()
    live.scanner = DummyScanner(markets)
    live.notifier = DummyNotifier()
    live.quarantine = None
    live.fill_tracker = None
    live.position_merger = None
    live.clob = None
    live.trade_stream = None
    live.lead_lag = None
    live.anomaly_consumer = None
    live.sum_violation_scanner = None
    live.sum_violation_strategy = None
    live.combinatorial_cfg = None
    live.lmsr_module_available = False
    live.lmsr_engine = None
    live.wallet_flow_module_available = True
    live.wallet_flow_available = True
    live.arb_module_available = False
    live.arb_available = False
    live.analyzer = None
    live.ensemble_mode = False
    live.multi_sim = SimpleNamespace()
    live._write_intel_snapshot = lambda *args, **kwargs: None
    live._process_combinatorial_cycle = lambda cycle_num: ([], dict(EMPTY_COMBINATORIAL_CYCLE))
    live._get_elastic_ml_feedback = lambda market_id: {
        "market_id": market_id,
        "size_multiplier": 1.0,
        "paused": False,
        "pause_reason": "",
    }

    async def _refresh_elastic_ml_state(*, force: bool = False) -> dict:
        return {}

    live._refresh_elastic_ml_state = _refresh_elastic_ml_state
    live.pm_hourly_campaign_enabled = False
    live.pm_campaign_max_resolution_hours = 0.0
    live.pm_campaign_budget = RollingNotionalBudgetTracker(cap_usd=0.0, window_seconds=3600)
    live.pm_campaign_decision_log_path = tmp_path / "pm_campaign.log"
    live._pm_campaign_recent_decisions = []
    return live


def test_startup_lane_health_reports_fast_flow_bootstrap_and_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)

    live = JJLive.__new__(JJLive)
    live.enable_llm_signals = True
    live.enable_wallet_flow = True
    live.enable_lmsr = True
    live.enable_cross_platform_arb = True
    live.fast_flow_only = True
    live.analyzer = object()
    live.wallet_flow_module_available = True
    live.wallet_flow_scores_file = tmp_path / "missing-smart-wallets.json"
    live.wallet_flow_db_file = tmp_path / "missing-wallet-scores.db"
    live.lmsr_module_available = True
    live.lmsr_engine = object()
    live.arb_module_available = True
    live.sum_violation_strategy = object()
    live.combinatorial_cfg = DummyCombinatorialConfig()
    live.pm_hourly_campaign_enabled = False
    live.pm_campaign_max_resolution_hours = 0.0
    live.pm_campaign_budget = RollingNotionalBudgetTracker(cap_usd=0.0, window_seconds=3600)
    live.pm_campaign_decision_log_path = tmp_path / "pm_campaign.log"
    live._pm_campaign_recent_decisions = []

    health = live._build_startup_lane_health()

    assert health["llm"]["status"] == "disabled"
    assert health["wallet_flow"]["reason"] == "missing_scores_json,missing_scores_db"
    assert health["lmsr"]["status"] == "active"
    assert health["cross_platform_arb"]["reason"] == "no_credentials"
    assert health["combinatorial"]["status"] == "disabled"


def test_cycle_lane_health_marks_combinatorial_gate_blocks(tmp_path):
    live = JJLive.__new__(JJLive)
    live.enable_llm_signals = False
    live.enable_wallet_flow = False
    live.enable_lmsr = False
    live.enable_cross_platform_arb = False
    live.fast_flow_only = False
    live.analyzer = None
    live.wallet_flow_module_available = False
    live.wallet_flow_scores_file = tmp_path / "smart_wallets.json"
    live.wallet_flow_db_file = tmp_path / "wallet_scores.db"
    live.lmsr_module_available = False
    live.lmsr_engine = None
    live.arb_module_available = False
    live.sum_violation_strategy = object()
    live.combinatorial_cfg = DummyCombinatorialConfig()

    health = live._build_cycle_lane_health(
        llm_signals=[],
        wallet_signals=[],
        lmsr_signals=[],
        arb_signals=[],
        combinatorial_signals=[],
        sum_violation_signals=[],
        combinatorial_cycle={
            **EMPTY_COMBINATORIAL_CYCLE,
            "blocked": 1,
            "metrics": {"health": {"a6": {"status": "blocked"}}},
        },
    )

    assert health["combinatorial"]["status"] == "blocked"
    assert health["combinatorial"]["reason"] == "blocked_by_gate"


def test_run_cycle_skips_wallet_flow_cleanly_when_bootstrap_missing(tmp_path, monkeypatch):
    live = _make_live(
        tmp_path,
        markets=[
            {
                "id": "m-crypto",
                "question": "Will Bitcoin be up or down at 10:15 AM ET?",
                "outcomePrices": [0.42, 0.58],
                "clobTokenIds": ["yes-token", "no-token"],
                "volume": 500.0,
                "liquidity": 200.0,
            }
        ],
    )

    def _should_not_run():
        raise AssertionError("wallet flow detector should not run without bootstrap artifacts")

    monkeypatch.setattr(jj_live_module, "wallet_flow_get_signals", _should_not_run)

    summary = asyncio.run(live.run_cycle())

    assert summary["status"] == "ok"
    assert summary["trades_placed"] == 0
    assert summary["lane_health"]["wallet_flow"]["status"] == "not_ready"
    assert summary["lane_health"]["wallet_flow"]["reason"] == "missing_scores_json,missing_scores_db"


def test_run_cycle_executes_wallet_signal_in_fast_flow_mode(tmp_path, monkeypatch):
    live = _make_live(
        tmp_path,
        markets=[
            {
                "id": "m-crypto",
                "question": "Will Bitcoin be up or down at 10:15 AM ET?",
                "outcomePrices": [0.42, 0.58],
                "clobTokenIds": ["yes-token", "no-token"],
                "volume": 500.0,
                "liquidity": 200.0,
            }
        ],
    )

    live.wallet_flow_scores_file.write_text(
        json.dumps({"wallets": {"0xabc": {"address": "0xabc", "activity_score": 80.0}}})
    )
    live.wallet_flow_db_file.touch()

    monkeypatch.setattr(
        jj_live_module,
        "wallet_flow_get_signals",
        lambda: [
            {
                "market_id": "m-crypto",
                "question": "Will Bitcoin be up or down at 10:15 AM ET?",
                "direction": "buy_yes",
                "market_price": 0.5,
                "estimated_prob": 0.74,
                "edge": 0.18,
                "confidence": 0.74,
                "reasoning": "Wallet flow consensus",
                "source": "wallet_flow",
                "resolution_hours": 0.25,
                "velocity_score": 120.0,
            }
        ],
    )

    captured_orders: list[dict] = []

    async def _place_order(**kwargs):
        captured_orders.append(kwargs)
        return True

    live.place_order = _place_order

    summary = asyncio.run(live.run_cycle())

    assert summary["status"] == "ok"
    assert summary["trades_placed"] == 1
    assert summary["lane_health"]["wallet_flow"]["status"] == "active"
    assert captured_orders
    assert captured_orders[0]["market_id"] == "m-crypto"
    assert captured_orders[0]["price"] == 0.42


def test_run_cycle_hydrates_recent_fast_markets_when_primary_scan_misses_them(tmp_path, monkeypatch):
    live = _make_live(tmp_path, markets=[])

    live.wallet_flow_scores_file.write_text(
        json.dumps({"wallets": {"0xabc": {"address": "0xabc", "activity_score": 80.0}}})
    )
    live.wallet_flow_db_file.touch()

    monkeypatch.setattr(
        jj_live_module,
        "wallet_flow_get_signals",
        lambda: [
            {
                "market_id": "m-recent",
                "question": "Bitcoin Up or Down - March 8, 10:15PM-10:20PM ET",
                "direction": "buy_yes",
                "market_price": 0.5,
                "estimated_prob": 0.79,
                "edge": 0.19,
                "confidence": 0.79,
                "reasoning": "Wallet flow consensus",
                "source": "wallet_flow",
                "resolution_hours": 0.25,
                "velocity_score": 120.0,
            }
        ],
    )

    async def _fetch_recent_trade_hydrated_markets():
        return (
            [
                {
                    "id": "m-recent",
                    "conditionId": "m-recent",
                    "question": "Bitcoin Up or Down - March 8, 10:15PM-10:20PM ET",
                    "outcomePrices": [0.44, 0.56],
                    "clobTokenIds": ["recent-yes", "recent-no"],
                    "volume": 750.0,
                    "liquidity": 300.0,
                    "endDate": "2026-03-09T03:20:00Z",
                    "acceptingOrders": True,
                    "closed": False,
                }
            ],
            {
                "recent_trades_fetched": 1000,
                "recent_market_hydrations": 1,
                "recent_fast_markets_seen": 1,
            },
        )

    live._fetch_recent_trade_hydrated_markets = _fetch_recent_trade_hydrated_markets

    captured_orders: list[dict] = []

    async def _place_order(**kwargs):
        captured_orders.append(kwargs)
        return True

    live.place_order = _place_order

    summary = asyncio.run(live.run_cycle())

    assert summary["status"] == "ok"
    assert summary["trades_placed"] == 1
    assert captured_orders
    assert captured_orders[0]["market_id"] == "m-recent"
    assert captured_orders[0]["price"] == 0.44


def test_run_cycle_late_hydrates_wallet_signal_when_scan_has_other_fast_market(tmp_path, monkeypatch):
    live = _make_live(
        tmp_path,
        markets=[
            {
                "id": "m-scanner",
                "conditionId": "cond-scanner",
                "question": "Bitcoin Up or Down - March 9, 8:00AM-8:15AM ET",
                "outcomePrices": [0.42, 0.58],
                "clobTokenIds": ["scanner-yes", "scanner-no"],
                "volume": 500.0,
                "liquidity": 200.0,
                "endDate": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            }
        ],
    )

    live.wallet_flow_scores_file.write_text(
        json.dumps({"wallets": {"0xabc": {"address": "0xabc", "activity_score": 80.0}}})
    )
    live.wallet_flow_db_file.touch()

    monkeypatch.setattr(
        jj_live_module,
        "wallet_flow_get_signals",
        lambda: [
            {
                "market_id": "cond-missing",
                "question": "Bitcoin Up or Down - March 9, 8:00AM-8:15AM ET",
                "direction": "buy_no",
                "market_price": 0.5,
                "estimated_prob": 0.74,
                "edge": 0.18,
                "confidence": 0.74,
                "reasoning": "Wallet flow consensus",
                "source": "wallet_flow",
                "resolution_hours": 0.25,
                "velocity_score": 120.0,
            }
        ],
    )

    hydrated_market_ids: list[str] = []

    async def _fetch_market_metadata_for_signal(market_id, market_lookup):
        hydrated_market_ids.append(market_id)
        market_lookup["cond-missing"] = {
            "question": "Bitcoin Up or Down - March 9, 8:00AM-8:15AM ET",
            "token_ids": ["missing-yes", "missing-no"],
            "yes_price": 0.44,
            "volume": 750.0,
            "liquidity": 300.0,
            "tags": [],
            "category": "crypto",
            "resolution_hours": 0.25,
            "llm_allowed": False,
        }
        return market_lookup["cond-missing"]

    live._fetch_market_metadata_for_signal = _fetch_market_metadata_for_signal

    captured_orders: list[dict] = []

    async def _place_order(**kwargs):
        captured_orders.append(kwargs)
        return True

    live.place_order = _place_order

    summary = asyncio.run(live.run_cycle())

    assert summary["status"] == "ok"
    assert summary["trades_placed"] == 1
    assert hydrated_market_ids == ["cond-missing"]
    assert captured_orders
    assert captured_orders[0]["market_id"] == "cond-missing"
    assert captured_orders[0]["price"] == 0.56
