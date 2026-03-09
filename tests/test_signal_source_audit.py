from __future__ import annotations

import json
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
    assert comparison["wallet_flow_any_win_rate_delta_vs_llm_only"] == 0.5
    assert payload["recommendations"]["wallet_flow"]["recommendation"] == "keep"
    assert payload["state_snapshot"]["trade_log_has_source_attribution"] is True
