from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bot.jj_live import TradeDatabase
from scripts.run_signal_source_audit import build_audit_payload


def _write_state(path: Path, *, total_trades: int, cycles_completed: int, trade_log: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "total_trades": total_trades,
                "cycles_completed": cycles_completed,
                "open_positions": {},
                "trade_log": trade_log,
            }
        )
    )


def _write_btc5_probe_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE window_trades (
                slug TEXT,
                window_start_ts INTEGER,
                window_end_ts INTEGER,
                decision_ts INTEGER,
                direction TEXT,
                order_status TEXT,
                order_price REAL,
                trade_size_usd REAL,
                filled INTEGER,
                resolved_side TEXT,
                won INTEGER,
                pnl_usd REAL,
                best_bid REAL,
                best_ask REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO window_trades(
                slug, window_start_ts, window_end_ts, decision_ts, direction, order_status,
                order_price, trade_size_usd, filled, resolved_side, won, pnl_usd, best_bid, best_ask
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _write_wallet_flow_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE wallet_scores (
                wallet TEXT PRIMARY KEY,
                total_trades INTEGER,
                crypto_trades INTEGER,
                unique_markets INTEGER,
                wins INTEGER,
                losses INTEGER,
                total_pnl REAL,
                total_volume REAL,
                avg_size REAL,
                win_rate REAL,
                activity_score REAL,
                is_smart INTEGER,
                last_active TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE wallet_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT,
                condition_id TEXT,
                title TEXT,
                side TEXT,
                outcome TEXT,
                outcome_index INTEGER,
                effective_outcome INTEGER,
                size REAL,
                price REAL,
                timestamp INTEGER,
                is_crypto_fast INTEGER,
                event_slug TEXT,
                pnl REAL
            )
            """
        )
        wallets = sorted({row[0] for row in rows})
        conn.executemany(
            """
            INSERT INTO wallet_scores(
                wallet, total_trades, crypto_trades, unique_markets, wins, losses, total_pnl,
                total_volume, avg_size, win_rate, activity_score, is_smart, last_active, updated_at
            ) VALUES (?, 10, 10, 3, 0, 0, 0.0, 100.0, 10.0, 0.5, 90.0, 1, '1773137400', '2026-03-10T12:00:00+00:00')
            """,
            [(wallet,) for wallet in wallets],
        )
        conn.executemany(
            """
            INSERT INTO wallet_trades(
                wallet, condition_id, title, side, outcome, outcome_index, effective_outcome,
                size, price, timestamp, is_crypto_fast, event_slug, pnl
            ) VALUES (?, 'cond', 'BTC 5m', 'BUY', 'Down', 1, ?, ?, ?, ?, 1, ?, NULL)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_build_audit_payload_handles_empty_runtime(tmp_path):
    state_path = tmp_path / "jj_state.json"
    _write_state(state_path, total_trades=0, cycles_completed=314, trade_log=[])

    payload = build_audit_payload(
        db_path=tmp_path / "missing.db",
        state_path=state_path,
        minimum_signal_sample=50,
    )

    assert payload["trade_totals"]["total_trades"] == 0
    assert payload["state_snapshot"]["cycles_completed"] == 314
    assert payload["recommendations"]["wallet_flow"]["recommendation"] == "collect_more_data"
    assert payload["recommendations"]["microstructure_gate"]["recommendation"] == "keep_as_gate"
    assert "combined_sources_vs_single_source" in payload
    assert "ranking_snapshot" in payload
    assert payload["capital_ranking_support"]["stale_threshold_hours"] == 6.0
    assert payload["capital_ranking_support"]["audit_generated_at"]
    assert payload["capital_ranking_support"]["trade_attribution_ready"] is False
    assert payload["capital_ranking_support"]["supports_capital_allocation"] is False
    assert payload["capital_ranking_support"]["wallet_flow_confirmation_ready"] is False
    assert payload["capital_ranking_support"]["btc_fast_window_confirmation_ready"] is False
    assert payload["capital_ranking_support"]["confirmation_support_status"] == "blocked"
    assert payload["capital_ranking_support"]["capital_expansion_support_status"] == "blocked"
    assert payload["capital_ranking_support"]["stage_upgrade_support_status"] == "limited"
    assert payload["capital_ranking_support"]["stage_upgrade_blocking_checks"] == [
        "trade_attribution_not_ready",
        "wallet_flow_vs_llm_not_ready",
    ]
    assert "btc5_probe_db_not_provided" in payload["btc_fast_window_confirmation"]["missing_requirements"]


def test_build_audit_payload_compares_wallet_flow_against_llm(tmp_path):
    db_path = tmp_path / "jj_trades.db"
    state_path = tmp_path / "jj_state.json"
    db = TradeDatabase(db_path=db_path)

    llm_ids = []
    wallet_ids = []
    for idx in range(2):
        llm_ids.append(
            db.log_trade(
                {
                    "market_id": f"llm-{idx}",
                    "question": f"LLM trade {idx}",
                    "direction": "buy_yes",
                    "entry_price": 0.45,
                    "edge": 0.11,
                    "confidence": 0.71,
                    "position_size_usd": 1.0,
                    "source": "llm",
                    "source_combo": "llm",
                    "source_components": ["llm"],
                    "source_count": 1,
                }
            )
        )
        wallet_ids.append(
            db.log_trade(
                {
                    "market_id": f"wallet-{idx}",
                    "question": f"Wallet trade {idx}",
                    "direction": "buy_yes",
                    "entry_price": 0.41,
                    "edge": 0.18,
                    "confidence": 0.79,
                    "position_size_usd": 1.0,
                    "source": "wallet_flow",
                    "source_combo": "wallet_flow",
                    "source_components": ["wallet_flow"],
                    "source_count": 1,
                }
            )
        )

    now = "2026-03-09T12:00:00+00:00"
    db.conn.execute(
        "UPDATE trades SET outcome = 'won', pnl = 0.20, resolved_at = ? WHERE id = ?",
        (now, llm_ids[0]),
    )
    db.conn.execute(
        "UPDATE trades SET outcome = 'lost', pnl = -0.15, resolved_at = ? WHERE id = ?",
        (now, llm_ids[1]),
    )
    db.conn.execute(
        "UPDATE trades SET outcome = 'won', pnl = 0.25, resolved_at = ? WHERE id = ?",
        (now, wallet_ids[0]),
    )
    db.conn.execute(
        "UPDATE trades SET outcome = 'won', pnl = 0.22, resolved_at = ? WHERE id = ?",
        (now, wallet_ids[1]),
    )
    db.conn.commit()
    db.close()

    _write_state(
        state_path,
        total_trades=4,
        cycles_completed=320,
        trade_log=[
            {
                "market_id": "wallet-1",
                "question": "Wallet trade 1",
                "direction": "buy_yes",
                "price": 0.41,
                "size_usd": 1.0,
                "edge": 0.18,
                "order_id": "paper-1",
                "source": "wallet_flow",
                "source_combo": "wallet_flow",
                "source_components": ["wallet_flow"],
                "source_count": 1,
                "timestamp": now,
            }
        ],
    )

    payload = build_audit_payload(
        db_path=db_path,
        state_path=state_path,
        minimum_signal_sample=2,
    )

    wallet_metrics = payload["by_component_source"]["wallet_flow"]
    llm_metrics = payload["by_component_source"]["llm"]
    comparison = payload["wallet_flow_vs_llm"]

    assert wallet_metrics["total_trades"] == 2
    assert wallet_metrics["wins"] == 2
    assert llm_metrics["total_trades"] == 2
    assert llm_metrics["wins"] == 1
    assert comparison["status"] == "ready"
    assert comparison["winner"] == "wallet_flow"
    assert comparison["wallet_flow_any_win_rate_delta_vs_llm_only"] == 0.5
    assert payload["combined_sources_vs_single_source"]["status"] == "insufficient_data"
    assert payload["combined_sources_vs_single_source"]["combined_sources_beat_single_source_lanes"] is None
    assert payload["ranking_snapshot"]["best_component_source"]["source"] == "wallet_flow"
    assert payload["ranking_snapshot"]["best_component_source"]["win_rate"] == 1.0
    assert payload["recommendations"]["wallet_flow"]["recommendation"] == "keep"
    assert payload["state_snapshot"]["trade_log_has_source_attribution"] is True
    assert payload["capital_ranking_support"]["trade_attribution_ready"] is True
    assert payload["capital_ranking_support"]["wallet_flow_vs_llm_status"] == "ready"
    assert payload["capital_ranking_support"]["best_component_source"] == "wallet_flow"
    assert payload["capital_ranking_support"]["audit_generated_at"]
    assert payload["capital_ranking_support"]["supports_capital_allocation"] is True
    assert payload["capital_ranking_support"]["wallet_flow_confirmation_ready"] is True
    assert payload["capital_ranking_support"]["btc_fast_window_confirmation_ready"] is False
    assert payload["capital_ranking_support"]["confirmation_support_status"] == "limited"
    assert payload["capital_ranking_support"]["capital_expansion_support_status"] == "ready"
    assert payload["capital_ranking_support"]["stage_upgrade_support_status"] == "ready"
    assert payload["capital_ranking_support"]["stage_upgrade_blocking_checks"] == []


def test_build_audit_payload_keeps_capital_allocation_ready_but_stage_upgrade_limited(tmp_path):
    db_path = tmp_path / "jj_trades.db"
    state_path = tmp_path / "jj_state.json"
    db = TradeDatabase(db_path=db_path)
    db.log_trade(
        {
            "market_id": "llm-1",
            "question": "LLM trade 1",
            "direction": "buy_yes",
            "entry_price": 0.45,
            "edge": 0.11,
            "confidence": 0.71,
            "position_size_usd": 1.0,
            "source": "llm",
            "source_combo": "llm",
            "source_components": ["llm"],
            "source_count": 1,
        }
    )
    db.close()

    _write_state(
        state_path,
        total_trades=1,
        cycles_completed=321,
        trade_log=[
            {
                "market_id": "llm-1",
                "question": "LLM trade 1",
                "direction": "buy_yes",
                "price": 0.45,
                "size_usd": 1.0,
                "edge": 0.11,
                "order_id": "paper-1",
                "source": "llm",
                "source_combo": "llm",
                "source_components": ["llm"],
                "source_count": 1,
                "timestamp": "2026-03-09T12:00:00+00:00",
            }
        ],
    )

    payload = build_audit_payload(
        db_path=db_path,
        state_path=state_path,
        minimum_signal_sample=2,
    )

    capital_support = payload["capital_ranking_support"]

    assert capital_support["trade_attribution_ready"] is True
    assert capital_support["wallet_flow_vs_llm_status"] == "insufficient_data"
    assert capital_support["supports_capital_allocation"] is True
    assert capital_support["wallet_flow_confirmation_ready"] is False
    assert capital_support["btc_fast_window_confirmation_ready"] is False
    assert capital_support["confirmation_support_status"] == "limited"
    assert capital_support["capital_expansion_support_status"] == "ready"
    assert capital_support["stage_upgrade_support_status"] == "limited"
    assert capital_support["stage_upgrade_blocking_checks"] == ["wallet_flow_vs_llm_not_ready"]


def test_build_audit_payload_emits_btc_fast_window_confirmation_metrics(tmp_path):
    db_path = tmp_path / "jj_trades.db"
    state_path = tmp_path / "jj_state.json"
    probe_db_path = tmp_path / "btc_5min_maker.remote_probe.db"
    wallet_db_path = tmp_path / "wallet_scores.db"
    db = TradeDatabase(db_path=db_path)
    db.log_trade(
        {
            "market_id": "llm-1",
            "question": "LLM trade 1",
            "direction": "buy_yes",
            "entry_price": 0.45,
            "edge": 0.11,
            "confidence": 0.71,
            "position_size_usd": 1.0,
            "source": "llm",
            "source_combo": "llm",
            "source_components": ["llm"],
            "source_count": 1,
        }
    )
    db.close()

    _write_state(
        state_path,
        total_trades=1,
        cycles_completed=322,
        trade_log=[
            {
                "market_id": "llm-1",
                "question": "LLM trade 1",
                "direction": "buy_yes",
                "price": 0.45,
                "size_usd": 1.0,
                "edge": 0.11,
                "order_id": "paper-1",
                "source": "llm",
                "source_combo": "llm",
                "source_components": ["llm"],
                "source_count": 1,
                "timestamp": "2026-03-10T12:00:00+00:00",
            }
        ],
    )
    _write_btc5_probe_db(
        probe_db_path,
        [
            ("btc-updown-5m-1", 100, 400, 390, "DOWN", "live_filled", 0.48, 5.0, 1, "DOWN", 1, 5.0, 0.47, 0.49),
            ("btc-updown-5m-2", 500, 800, 790, "UP", "live_filled", 0.49, 5.0, 1, "DOWN", 0, -4.0, 0.48, 0.50),
            ("btc-updown-5m-3", 900, 1200, 1190, "DOWN", "live_filled", 0.47, 5.0, 1, "DOWN", 1, 3.0, 0.46, 0.48),
        ],
    )
    _write_wallet_flow_db(
        wallet_db_path,
        [
            ("wallet-a", 1, 12.0, 0.48, 390, "btc-updown-5m-1"),
            ("wallet-b", 1, 10.0, 0.47, 389, "btc-updown-5m-1"),
            ("wallet-a", 1, 9.0, 0.46, 790, "btc-updown-5m-2"),
            ("wallet-c", 1, 8.0, 0.45, 788, "btc-updown-5m-2"),
            ("wallet-b", 1, 7.0, 0.47, 1189, "btc-updown-5m-3"),
            ("wallet-c", 1, 6.0, 0.46, 1188, "btc-updown-5m-3"),
        ],
    )

    payload = build_audit_payload(
        db_path=db_path,
        state_path=state_path,
        minimum_signal_sample=2,
        btc5_probe_db_path=probe_db_path,
        wallet_db_path=wallet_db_path,
        edge_db_path=tmp_path / "missing_edge.db",
    )

    confirmation = payload["btc_fast_window_confirmation"]
    wallet_flow_summary = confirmation["by_source"]["wallet_flow"]
    capital_support = payload["capital_ranking_support"]

    assert confirmation["status"] == "ready"
    assert confirmation["summary"]["ready_sources"] == ["wallet_flow"]
    assert confirmation["summary"]["best_source_by_confirmation_lift"] == "wallet_flow"
    assert confirmation["summary"]["confirmation_coverage_ratio"] == 1.0
    assert confirmation["summary"]["confirmation_resolved_window_coverage"] == 1.0
    assert confirmation["summary"]["confirmation_executed_window_coverage"] == 1.0
    assert confirmation["summary"]["confirmation_false_suppression_cost_usd"] == 0.0
    assert wallet_flow_summary["status"] == "ready"
    assert wallet_flow_summary["source_window_rows"] == 3
    assert wallet_flow_summary["covered_executed_window_rows"] == 3
    assert wallet_flow_summary["confirmed_good_trade_rows"] == 2
    assert wallet_flow_summary["suppressed_bad_window_rows"] == 1
    assert wallet_flow_summary["false_suppression_cost_usd"] == 0.0
    assert wallet_flow_summary["false_confirmation_cost_usd"] == 0.0
    assert wallet_flow_summary["confirmation_lift_avg_pnl_usd"] > 0
    assert capital_support["btc_fast_window_confirmation_ready"] is True
    assert capital_support["confirmation_support_status"] == "ready"
    assert capital_support["confirmation_sources_ready"] == ["wallet_flow"]
    assert capital_support["best_confirmation_source"] == "wallet_flow"
    assert capital_support["confirmation_resolved_window_coverage"] == 1.0
    assert capital_support["confirmation_executed_window_coverage"] == 1.0
    assert capital_support["confirmation_false_suppression_cost_usd"] == 0.0
