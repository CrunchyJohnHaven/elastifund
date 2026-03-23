from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.btc5_candidate_contract import (
    build_canonical_package_contract,
    build_runtime_candidate_metadata,
    load_wallet_intel_snapshot,
    publish_wallet_prior_surface,
)
from scripts.btc5_policy_benchmark import runtime_package_hash


def _runtime_package(
    name: str,
    *,
    max_abs_delta: float = 0.00015,
    up_max_buy_price: float = 0.49,
    down_max_buy_price: float = 0.51,
    session_policy: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "profile": {
            "name": name,
            "max_abs_delta": max_abs_delta,
            "up_max_buy_price": up_max_buy_price,
            "down_max_buy_price": down_max_buy_price,
        },
        "session_policy": session_policy or [],
    }


def _directional_autoresearch_payload(
    *,
    observed_live_strategy_family: str | None = None,
    median_arr_delta_pct: float = 12.5,
    replay_pnl_delta_usd: float = 3.4,
    validation_live_filled_rows: int = 14,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "best_live_package": {
            "candidate_family": "hypothesis",
            "source": "hypothesis_best_candidate",
            "candidate_class": "promote",
            "validation_live_filled_rows": validation_live_filled_rows,
            "median_arr_delta_pct": median_arr_delta_pct,
            "replay_pnl_delta_usd": replay_pnl_delta_usd,
            "runtime_package": _runtime_package("wallet-shadow"),
        }
    }
    if observed_live_strategy_family:
        payload["best_live_package"]["observed_live_strategy_family"] = observed_live_strategy_family
    return payload


def test_load_wallet_intel_snapshot_reads_db_and_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "wallet_scores.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE wallet_scores (wallet TEXT PRIMARY KEY, is_smart INTEGER, activity_score REAL)"
        )
        conn.execute(
            """
            CREATE TABLE wallet_trades (
                wallet TEXT,
                price REAL,
                timestamp INTEGER,
                is_crypto_fast INTEGER,
                side TEXT,
                outcome_index INTEGER,
                effective_outcome INTEGER,
                size REAL,
                event_slug TEXT
            )
            """
        )
        conn.execute("INSERT INTO wallet_scores(wallet, is_smart, activity_score) VALUES ('0xabc', 1, 88.0)")
        conn.execute("INSERT INTO wallet_scores(wallet, is_smart, activity_score) VALUES ('0xdef', 1, 72.0)")
        conn.execute(
            """
            INSERT INTO wallet_trades
            (wallet, price, timestamp, is_crypto_fast, side, outcome_index, effective_outcome, size, event_slug)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("0xabc", 0.40, 1773231000, 1, "BUY", 1, 1, 10.0, "btc-updown-5m-100"),
        )
        conn.execute(
            """
            INSERT INTO wallet_trades
            (wallet, price, timestamp, is_crypto_fast, side, outcome_index, effective_outcome, size, event_slug)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("0xabc", 0.55, 1773231300, 1, "SELL", 0, 1, 4.0, "btc-updown-5m-100"),
        )
        conn.execute(
            """
            INSERT INTO wallet_trades
            (wallet, price, timestamp, is_crypto_fast, side, outcome_index, effective_outcome, size, event_slug)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("0xdef", 0.60, 1773231600, 1, "BUY", 0, 0, 5.0, "btc-updown-5m-100"),
        )
        conn.commit()
    finally:
        conn.close()

    smart_wallets_path = tmp_path / "smart_wallets.json"
    smart_wallets_path.write_text(
        json.dumps({"count": 1, "wallets": {"0xabc": {"address": "0xabc", "is_smart": True}}}),
        encoding="utf-8",
    )
    roster_path = tmp_path / "mirror_wallet_roster.json"
    roster_path.write_text(
        json.dumps(
            {
                "wallets": [
                    {
                        "address": "0xabc",
                        "label": "alpha",
                        "strategy_family": "directional_shadow_momentum",
                        "maker_vs_directional_confidence": {
                            "maker_confidence": 0.2,
                            "directional_confidence": 0.8,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    archive_path = tmp_path / "btc_fast_window_confirmation_archive.json"
    archive_path.write_text(
        json.dumps(
            {
                "windows": [
                    {"slug": "btc-updown-5m-100", "resolved_side": "DOWN"},
                ]
            }
        ),
        encoding="utf-8",
    )
    maker_db_path = tmp_path / "btc_5min_maker.db"
    maker_conn = sqlite3.connect(str(maker_db_path))
    try:
        maker_conn.execute("CREATE TABLE window_trades (slug TEXT, resolved_side TEXT)")
        maker_conn.commit()
    finally:
        maker_conn.close()

    snapshot = load_wallet_intel_snapshot(
        wallet_db_path=db_path,
        smart_wallets_path=smart_wallets_path,
        mirror_wallet_roster_path=roster_path,
        btc5_maker_db_path=maker_db_path,
        btc5_confirmation_archive_path=archive_path,
    )

    assert snapshot["wallet_count"] == 1
    assert snapshot["wallet_trade_count"] == 3
    assert snapshot["smart_wallet_trade_count"] == 3
    assert snapshot["mirror_wallet_count"] == 1
    assert snapshot["resolved_wallet_count"] == 2
    assert snapshot["resolved_trade_count"] == 3
    assert snapshot["btc5_resolved_trade_count"] == 3
    assert snapshot["wallet_realized_outcome_available"] is True
    assert snapshot["wallet_realized_outcome_wallet_count"] == 2
    assert snapshot["wallet_resolved_trade_count"] == 3
    assert snapshot["ranked_wallets"][0]["wallet"] == "0xabc"
    assert snapshot["ranked_wallets"][0]["strategy_family"] == "directional_shadow_momentum"
    assert snapshot["ranked_wallets"][0]["btc5_realized_pnl"] > 0.0
    assert snapshot["wallet_cluster_rankings"][0]["wallet_cluster"] == "directional"
    assert snapshot["dominant_price_buckets"] == ["gt_0.51", "lt_0.49"]


def test_build_runtime_candidate_metadata_blocks_directional_promotion_without_same_family_live_evidence() -> None:
    snapshot = {
        "maker_support_share": 0.28,
        "directional_support_share": 0.72,
        "dominant_hours_et": [9, 10, 11],
        "dominant_price_buckets": ["0.49_to_0.51"],
        "wallet_realized_outcome_available": True,
        "wallet_realized_outcome_wallet_count": 2,
        "wallet_resolved_trade_count": 30,
        "ranked_wallets": [
            {
                "wallet": "0x1",
                "label": "momentum-x",
                "strategy_family": "directional_shadow_momentum",
                "wallet_cluster": "directional",
                "resolved_trade_count": 18,
                "btc5_resolved_trade_count": 12,
                "wallet_edge_support_score": 0.84,
                "btc5_edge_support_score": 0.81,
                "maker_vs_directional_confidence": {"maker_confidence": 0.15, "directional_confidence": 0.85},
            },
            {
                "wallet": "0x2",
                "label": "hybrid-bot",
                "strategy_family": "btc_fast_hybrid_cluster",
                "wallet_cluster": "hybrid",
                "resolved_trade_count": 11,
                "btc5_resolved_trade_count": 8,
                "wallet_edge_support_score": 0.61,
                "btc5_edge_support_score": 0.58,
                "maker_vs_directional_confidence": {"maker_confidence": 0.55, "directional_confidence": 0.45},
            },
        ],
        "mirror_wallet_roster": [],
    }
    runtime_package = _runtime_package(
        "wallet-shadow",
        session_policy=[{"name": "open_et", "et_hours": [9, 10], "up_max_buy_price": 0.49, "down_max_buy_price": 0.51}],
    )

    metadata = build_runtime_candidate_metadata(
        runtime_package=runtime_package,
        candidate_family="hypothesis",
        source="hypothesis_best_candidate",
        role="shadow",
        wallet_intel_snapshot=snapshot,
        live_runtime_package=_runtime_package("current_live_profile"),
        btc5_autoresearch_latest=_directional_autoresearch_payload(),
        btc5_autoresearch_loop_latest={},
    )

    assert metadata["strategy_family"] == "directional_shadow"
    assert metadata["benchmark_objective"] == "improve_wallet_intel_shadow_alignment"
    assert metadata["wallet_prior_support_score"] > 0.6
    assert metadata["promotion_readiness"] == "shadow_candidate_needs_same_family_live_evidence"
    assert metadata["benchmark_requirement"]["passed"] is True
    assert metadata["wallet_prior_requirement"]["status"] == "supported"
    assert metadata["live_quality_requirement"]["passed"] is False
    assert metadata["live_quality_requirement"]["canonical_live_strategy_family"] == "maker_bootstrap_live"
    assert metadata["promotion_barrier"]["promotable"] is False
    assert metadata["promotion_barrier"]["blocking_reasons"] == ["same_family_live_quality_evidence_missing"]
    assert metadata["wallet_cluster_support"]["matched_clusters"][0] == "directional"
    assert metadata["wallet_cluster_support"]["top_matches"][0]["btc5_resolved_trade_count"] == 12
    assert metadata["time_of_day_specialization"]["overlap_hours_et"] == [9, 10]


def test_build_runtime_candidate_metadata_accepts_explicit_wallet_prior_absence_with_same_family_live_evidence() -> None:
    snapshot = {
        "maker_support_share": 0.25,
        "directional_support_share": 0.75,
        "dominant_hours_et": [9, 10],
        "dominant_price_buckets": ["0.49_to_0.51"],
        "wallet_realized_outcome_available": False,
        "wallet_realized_outcome_wallet_count": 0,
        "wallet_resolved_trade_count": 0,
        "ranked_wallets": [
            {
                "wallet": "0x1",
                "label": "momentum-x",
                "strategy_family": "directional_shadow_momentum",
                "wallet_cluster": "directional",
                "resolved_trade_count": 0,
                "btc5_resolved_trade_count": 0,
                "wallet_edge_support_score": 0.82,
                "btc5_edge_support_score": 0.79,
                "maker_vs_directional_confidence": {"maker_confidence": 0.12, "directional_confidence": 0.88},
            }
        ],
        "mirror_wallet_roster": [],
    }

    metadata = build_runtime_candidate_metadata(
        runtime_package=_runtime_package("wallet-shadow"),
        candidate_family="hypothesis",
        source="hypothesis_best_candidate",
        role="shadow",
        wallet_intel_snapshot=snapshot,
        live_runtime_package=_runtime_package("current_live_profile"),
        btc5_autoresearch_latest=_directional_autoresearch_payload(
            observed_live_strategy_family="directional_shadow"
        ),
        btc5_autoresearch_loop_latest={},
    )

    assert metadata["promotion_readiness"] == "promotable"
    assert metadata["wallet_prior_requirement"]["status"] == "explicit_absence"
    assert metadata["benchmark_requirement"]["passed"] is True
    assert metadata["live_quality_requirement"]["passed"] is True
    assert metadata["promotion_barrier"]["promotable"] is True
    assert metadata["promotion_barrier"]["execution_evidence_scope"] == "strategy_family_qualified"


def test_build_canonical_package_contract_freezes_live_and_shadow_ids() -> None:
    live_runtime_package = _runtime_package("current_live_profile")
    shadow_runtime_package = _runtime_package("policy-beta", up_max_buy_price=0.48)
    snapshot = {
        "maker_support_share": 0.75,
        "directional_support_share": 0.25,
        "dominant_hours_et": [9, 10, 11],
        "dominant_price_buckets": ["0.49_to_0.51"],
        "mirror_wallet_roster": [],
    }

    contract = build_canonical_package_contract(
        live_runtime_package=live_runtime_package,
        shadow_candidates=[
            live_runtime_package,
            {
                "runtime_package": shadow_runtime_package,
                "candidate_family": "regime_policy",
                "source": "regime_best_candidate",
            },
        ],
        live_source="runtime_selection",
        wallet_intel_snapshot=snapshot,
    )

    assert contract["canonical_live_profile_id"] == "current_live_profile"
    assert contract["canonical_live_package_hash"] == runtime_package_hash(live_runtime_package)
    assert contract["strategy_family"] == "maker_bootstrap_live"
    assert contract["benchmark_objective"] == "collect_bounded_stage1_execution_evidence"
    assert contract["promotion_barrier"]["status"] == "bootstrap_execution_only"
    assert contract["shadow_comparator_profile_id"] == "policy-beta"
    assert contract["shadow_comparator_package_hash"] == runtime_package_hash(shadow_runtime_package)


def test_publish_wallet_prior_surface_writes_ranked_surface(tmp_path: Path) -> None:
    db_path = tmp_path / "wallet_scores.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE wallet_scores (
                wallet TEXT PRIMARY KEY,
                is_smart INTEGER,
                activity_score REAL,
                total_pnl REAL,
                win_rate REAL,
                resolved_trades INTEGER,
                realized_roi REAL,
                realized_edge REAL,
                ranking_score REAL,
                behavior_cluster TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE wallet_trades (
                wallet TEXT,
                price REAL,
                timestamp INTEGER,
                is_crypto_fast INTEGER,
                side TEXT,
                outcome_index INTEGER,
                effective_outcome INTEGER,
                size REAL,
                event_slug TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO wallet_scores(
                wallet, is_smart, activity_score, total_pnl, win_rate,
                resolved_trades, realized_roi, realized_edge, ranking_score, behavior_cluster
            ) VALUES ('0xabc', 1, 90.0, 3.25, 0.8, 10, 0.12, 0.325, 78.0, 'directional')
            """
        )
        conn.execute(
            """
            INSERT INTO wallet_trades(
                wallet, price, timestamp, is_crypto_fast, side, outcome_index, effective_outcome, size, event_slug
            ) VALUES ('0xabc', 0.42, 1773231000, 1, 'BUY', 1, 1, 10.0, 'btc-updown-5m-100')
            """
        )
        conn.commit()
    finally:
        conn.close()

    smart_wallets_path = tmp_path / "smart_wallets.json"
    smart_wallets_path.write_text(
        json.dumps({"count": 1, "wallets": {"0xabc": {"address": "0xabc", "is_smart": True}}}),
        encoding="utf-8",
    )
    roster_path = tmp_path / "mirror_wallet_roster.json"
    roster_path.write_text(json.dumps({"wallets": []}), encoding="utf-8")
    archive_path = tmp_path / "btc_fast_window_confirmation_archive.json"
    archive_path.write_text(
        json.dumps({"windows": [{"slug": "btc-updown-5m-100", "resolved_side": "DOWN"}]}),
        encoding="utf-8",
    )
    maker_db_path = tmp_path / "btc_5min_maker.db"
    maker_conn = sqlite3.connect(str(maker_db_path))
    try:
        maker_conn.execute("CREATE TABLE window_trades (slug TEXT, resolved_side TEXT)")
        maker_conn.commit()
    finally:
        maker_conn.close()

    output_path = tmp_path / "wallet_prior_surface.json"
    payload = publish_wallet_prior_surface(
        wallet_db_path=db_path,
        smart_wallets_path=smart_wallets_path,
        mirror_wallet_roster_path=roster_path,
        btc5_maker_db_path=maker_db_path,
        btc5_confirmation_archive_path=archive_path,
        output_path=output_path,
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["realized_wallet_count"] == 1
    assert written["top_wallets"][0]["wallet"] == "0xabc"
    assert written["top_wallets"][0]["ranking_score"] == 78.0
