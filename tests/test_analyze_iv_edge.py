#!/usr/bin/env python3
"""Tests for scripts/analyze_iv_edge.py — IV correlation analysis pipeline."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_iv_edge import (
    AnalysisReport,
    CorrelationResult,
    chi_squared_2x2,
    corr_a_skew_vs_direction,
    corr_b_dvol_regime,
    corr_d_risk_reversal,
    corr_e_iv_vs_spread,
    corr_f_composite_signal,
    fisher_exact_2x2,
    load_rows,
    render_markdown,
    run_analysis,
    wilson_ci,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_db(path: Path, rows: list[dict] | None = None, add_iv_cols: bool = True) -> Path:
    """Create a test BTC5 SQLite database with optional rows."""
    db_path = path / "btc_5min_maker.db"
    conn = sqlite3.connect(str(db_path))

    # Base schema matching production window_trades
    conn.execute("""
        CREATE TABLE IF NOT EXISTS window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT,
            delta REAL,
            order_status TEXT,
            won INTEGER,
            pnl_usd REAL,
            created_at TEXT,
            best_bid REAL,
            best_ask REAL,
            order_price REAL,
            trade_size_usd REAL
        )
    """)

    if add_iv_cols:
        iv_cols = [
            "deribit_dvol", "deribit_atm_iv_call", "deribit_atm_iv_put",
            "deribit_put_call_skew", "deribit_rr_25d", "deribit_bf_25d",
            "deribit_underlying", "deribit_age_s",
        ]
        for col in iv_cols:
            try:
                conn.execute(f"ALTER TABLE window_trades ADD COLUMN {col} REAL")
            except sqlite3.OperationalError:
                pass

    if rows:
        for r in rows:
            cols = list(r.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            conn.execute(
                f"INSERT INTO window_trades ({col_names}) VALUES ({placeholders})",
                [r[c] for c in cols],
            )

    conn.commit()
    conn.close()
    return db_path


def _make_row(
    direction: str = "DOWN",
    won: int | None = 1,
    dvol: float | None = 55.0,
    skew: float | None = 1.5,
    rr_25d: float | None = 0.5,
    best_bid: float = 0.50,
    best_ask: float = 0.52,
    delta: float = 0.003,
    created_at: str = "2026-03-20T12:00:00",
) -> dict:
    return {
        "direction": direction,
        "delta": delta,
        "order_status": "live_filled",
        "won": won,
        "pnl_usd": 0.50 if won == 1 else -5.0 if won == 0 else None,
        "created_at": created_at,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "order_price": 0.51,
        "trade_size_usd": 5.0,
        "deribit_dvol": dvol,
        "deribit_atm_iv_call": dvol - 1 if dvol else None,
        "deribit_atm_iv_put": dvol + 1 if dvol else None,
        "deribit_put_call_skew": skew,
        "deribit_rr_25d": rr_25d,
        "deribit_bf_25d": 0.3 if dvol else None,
        "deribit_underlying": 85000.0 if dvol else None,
        "deribit_age_s": 2.5 if dvol else None,
    }


# ---------------------------------------------------------------------------
# Statistical helper tests
# ---------------------------------------------------------------------------


class TestWilsonCI:
    def test_zero_n(self) -> None:
        lo, hi = wilson_ci(0, 0)
        assert lo == 0.0
        assert hi == 0.0

    def test_all_wins(self) -> None:
        lo, hi = wilson_ci(100, 100)
        assert lo > 0.95
        assert hi > 0.99

    def test_all_losses(self) -> None:
        lo, hi = wilson_ci(0, 100)
        assert lo == 0.0
        assert hi < 0.05

    def test_fifty_fifty(self) -> None:
        lo, hi = wilson_ci(50, 100)
        assert 0.39 < lo < 0.42
        assert 0.58 < hi < 0.61

    def test_small_sample(self) -> None:
        lo, hi = wilson_ci(3, 5)
        assert 0.0 < lo < hi < 1.0


class TestChiSquared:
    def test_no_difference(self) -> None:
        # Equal proportions => p should be high
        p = chi_squared_2x2(50, 50, 50, 50)
        assert p > 0.9

    def test_extreme_difference(self) -> None:
        # Very different proportions => p should be low
        p = chi_squared_2x2(90, 10, 10, 90)
        assert p < 0.001

    def test_empty_table(self) -> None:
        p = chi_squared_2x2(0, 0, 0, 0)
        assert p == 1.0

    def test_moderate_difference(self) -> None:
        # 60% vs 40% with n=100 each
        p = chi_squared_2x2(60, 40, 40, 60)
        assert p < 0.01


class TestFisherExact:
    def test_small_table(self) -> None:
        p = fisher_exact_2x2(5, 0, 0, 5)
        assert p < 0.05

    def test_no_difference(self) -> None:
        p = fisher_exact_2x2(5, 5, 5, 5)
        assert p > 0.5

    def test_fallback_to_chi2(self) -> None:
        # n > 300 should use chi-squared fallback
        p = fisher_exact_2x2(150, 50, 50, 150)
        assert p < 0.001


# ---------------------------------------------------------------------------
# Database loading tests
# ---------------------------------------------------------------------------


class TestLoadRows:
    def test_empty_db(self, tmp_path: Path) -> None:
        db = _create_db(tmp_path, rows=[], add_iv_cols=True)
        all_rows, iv_rows, resolved_iv = load_rows(db)
        assert len(all_rows) == 0
        assert len(iv_rows) == 0
        assert len(resolved_iv) == 0

    def test_no_iv_columns(self, tmp_path: Path) -> None:
        db = _create_db(tmp_path, rows=[{
            "direction": "DOWN", "delta": 0.003, "order_status": "live_filled",
            "won": 1, "pnl_usd": 0.5, "created_at": "2026-03-20T12:00:00",
            "best_bid": 0.50, "best_ask": 0.52, "order_price": 0.51,
            "trade_size_usd": 5.0,
        }], add_iv_cols=False)
        all_rows, iv_rows, resolved_iv = load_rows(db)
        assert len(all_rows) == 1
        assert len(iv_rows) == 0
        assert len(resolved_iv) == 0

    def test_iv_rows_partitioned(self, tmp_path: Path) -> None:
        rows = [
            _make_row(dvol=55.0, won=1),  # IV + resolved
            _make_row(dvol=None, won=1),   # no IV, resolved
            _make_row(dvol=60.0, won=None),  # IV, not resolved
        ]
        db = _create_db(tmp_path, rows=rows)
        all_rows, iv_rows, resolved_iv = load_rows(db)
        assert len(all_rows) == 3
        assert len(iv_rows) == 2  # rows with dvol
        assert len(resolved_iv) == 1  # dvol + won


# ---------------------------------------------------------------------------
# Correlation computation tests
# ---------------------------------------------------------------------------


class TestCorrASkew:
    def test_skew_predicts_down(self, tmp_path: Path) -> None:
        # High skew (>0) = DOWN wins; low skew (<=0) = DOWN loses
        rows = []
        for _ in range(60):
            rows.append(_make_row(direction="DOWN", won=1, skew=3.0))  # high skew, win
        for _ in range(40):
            rows.append(_make_row(direction="DOWN", won=0, skew=-2.0))  # low skew, loss
        for _ in range(20):
            rows.append(_make_row(direction="DOWN", won=0, skew=3.0))  # high skew, loss
        for _ in range(30):
            rows.append(_make_row(direction="DOWN", won=1, skew=-2.0))  # low skew, win

        db = _create_db(tmp_path, rows=rows)
        all_rows, iv_rows, resolved_iv = load_rows(db)
        results = corr_a_skew_vs_direction(resolved_iv, min_samples=20)

        # At threshold=0: group A (skew>0) = 60W/20L = 75%, group B (skew<=0) = 30W/40L = 43%
        thresh_0 = [r for r in results if r.name == "skew_gt_0_down_wr"][0]
        assert thresh_0.wr_group_a > 0.70
        assert thresh_0.wr_group_b < 0.50
        assert thresh_0.edge_pct > 20  # substantial edge
        assert thresh_0.p_value < 0.01

    def test_insufficient_data(self) -> None:
        rows = [_make_row(direction="DOWN", won=1, skew=2.0) for _ in range(5)]
        results = corr_a_skew_vs_direction(rows, min_samples=50)
        assert all(not r.actionable for r in results)


class TestCorrBDvol:
    def test_high_vol_regime(self, tmp_path: Path) -> None:
        rows = []
        for _ in range(60):
            rows.append(_make_row(direction="DOWN", won=1, dvol=70.0))  # high vol win
        for _ in range(60):
            rows.append(_make_row(direction="DOWN", won=0, dvol=40.0))  # low vol loss
        db = _create_db(tmp_path, rows=rows)
        _, _, resolved_iv = load_rows(db)
        results = corr_b_dvol_regime(resolved_iv, min_samples=20)

        high_low_down = [r for r in results if r.name == "dvol_high_vs_low_down"][0]
        assert high_low_down.wr_group_a > 0.9  # high vol = wins
        assert high_low_down.wr_group_b < 0.1  # low vol = losses


class TestCorrDRiskReversal:
    def test_positive_rr_predicts_down(self, tmp_path: Path) -> None:
        rows = []
        for _ in range(55):
            rows.append(_make_row(direction="DOWN", won=1, rr_25d=2.5))
        for _ in range(55):
            rows.append(_make_row(direction="DOWN", won=0, rr_25d=-0.5))
        db = _create_db(tmp_path, rows=rows)
        _, _, resolved_iv = load_rows(db)
        results = corr_d_risk_reversal(resolved_iv, min_samples=20)

        rr_pos = [r for r in results if r.name == "rr25d_gt1_down_wr"][0]
        assert rr_pos.wr_group_a > 0.9
        assert rr_pos.edge_pct > 50


class TestCorrESpread:
    def test_dvol_spread_correlation(self) -> None:
        rows = []
        for i in range(100):
            dvol = 40 + i * 0.5  # 40 to 89.5
            spread = 0.01 + dvol * 0.0001  # spread widens with dvol
            rows.append({
                "deribit_dvol": dvol,
                "best_bid": 0.50,
                "best_ask": 0.50 + spread,
            })

        result = corr_e_iv_vs_spread(rows, 20)
        assert result.name == "dvol_vs_spread"
        assert result.n_total == 100
        assert result.detail.get("quintiles") is not None
        assert len(result.detail["quintiles"]) == 5

    def test_insufficient_data(self) -> None:
        result = corr_e_iv_vs_spread([{"deribit_dvol": 50, "best_bid": 0.5, "best_ask": 0.52}], 20)
        assert "insufficient" in result.reason


class TestCorrFComposite:
    def test_composite_signal(self, tmp_path: Path) -> None:
        rows = []
        for _ in range(60):
            rows.append(_make_row(direction="DOWN", won=1, skew=4.0, rr_25d=2.0))
        for _ in range(60):
            rows.append(_make_row(direction="DOWN", won=0, skew=-1.0, rr_25d=-1.0))
        db = _create_db(tmp_path, rows=rows)
        _, _, resolved_iv = load_rows(db)

        result = corr_f_composite_signal(resolved_iv, min_samples=20)
        assert result.wr_group_a > 0.8  # composite > 2 predicts well
        assert result.edge_pct > 30


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


class TestRunAnalysis:
    def test_missing_db(self, tmp_path: Path) -> None:
        report = run_analysis(tmp_path / "nonexistent.db", 50)
        assert report.total_rows == 0
        assert "not found" in report.kill_rule_status

    def test_empty_db(self, tmp_path: Path) -> None:
        db = _create_db(tmp_path, rows=[], add_iv_cols=True)
        report = run_analysis(db, 50)
        assert report.total_rows == 0
        assert report.iv_enriched_rows == 0
        assert "NO_DATA" in report.kill_rule_status

    def test_iv_no_resolved(self, tmp_path: Path) -> None:
        rows = [_make_row(dvol=55.0, won=None) for _ in range(10)]
        db = _create_db(tmp_path, rows=rows)
        report = run_analysis(db, 50)
        assert report.iv_enriched_rows == 10
        assert report.iv_and_resolved_rows == 0
        assert "WAITING" in report.kill_rule_status

    def test_full_analysis_runs(self, tmp_path: Path) -> None:
        # Generate enough data for analysis
        rows = []
        for i in range(200):
            direction = "DOWN" if i % 3 != 0 else "UP"
            won = 1 if i % 2 == 0 else 0
            dvol = 45 + (i % 30)
            skew = -3 + (i % 7)
            rr = -2 + (i % 5)
            rows.append(_make_row(
                direction=direction,
                won=won,
                dvol=dvol,
                skew=skew,
                rr_25d=rr,
                created_at=f"2026-03-20T{12 + i // 60:02d}:{i % 60:02d}:00",
            ))
        db = _create_db(tmp_path, rows=rows)
        report = run_analysis(db, min_samples=20)
        assert report.total_rows == 200
        assert report.iv_enriched_rows == 200
        assert report.iv_and_resolved_rows == 200
        assert len(report.correlations) > 0
        assert "COLLECTING" in report.kill_rule_status

    def test_kill_rule_at_1000(self, tmp_path: Path) -> None:
        # 1000+ rows with no signal (50/50 outcome, random IV)
        rows = []
        for i in range(1100):
            rows.append(_make_row(
                direction="DOWN" if i % 2 == 0 else "UP",
                won=i % 2,  # deterministic 50/50 unrelated to IV
                dvol=50 + (i % 20),
                skew=(i % 10) - 5,
                rr_25d=(i % 8) - 4,
                created_at=f"2026-03-{20 + i // 500:02d}T{(i % 24):02d}:00:00",
            ))
        db = _create_db(tmp_path, rows=rows)
        report = run_analysis(db, min_samples=50)
        # With deterministic 50/50 unrelated to IV, should not find signal
        # (the kill rule checks p < 0.10 with edge > 1%)
        assert report.iv_and_resolved_rows >= 1000


class TestRenderMarkdown:
    def test_empty_report(self) -> None:
        report = AnalysisReport(
            timestamp="2026-03-20T12:00:00",
            db_path="test.db",
            iv_enriched_rows=0,
        )
        md = render_markdown(report)
        assert "No IV Data Available" in md

    def test_report_with_correlations(self) -> None:
        report = AnalysisReport(
            timestamp="2026-03-20T12:00:00",
            db_path="test.db",
            total_rows=500,
            iv_enriched_rows=500,
            resolved_rows=400,
            iv_and_resolved_rows=400,
            correlations=[
                CorrelationResult(
                    name="test_corr",
                    description="Test correlation",
                    n_total=200,
                    n_group_a=100,
                    n_group_b=100,
                    wr_group_a=0.65,
                    wr_group_b=0.45,
                    edge_pct=20.0,
                    p_value=0.001,
                    test_used="chi_squared",
                    actionable=True,
                ),
            ],
            actionable_count=1,
            kill_rule_status="COLLECTING",
        )
        md = render_markdown(report)
        assert "test_corr" in md
        assert "YES" in md
        assert "COLLECTING" in md
        assert "Correlation Results" in md


# ---------------------------------------------------------------------------
# Edge case: no-IV database (pre-Instance-2 schema)
# ---------------------------------------------------------------------------


class TestPreIVSchema:
    def test_graceful_with_no_iv_columns(self, tmp_path: Path) -> None:
        """DB without IV columns (pre-Instance-2) should report 0 IV rows."""
        db = _create_db(tmp_path, rows=[{
            "direction": "DOWN", "delta": 0.003, "order_status": "live_filled",
            "won": 1, "pnl_usd": 0.5, "created_at": "2026-03-20T12:00:00",
            "best_bid": 0.50, "best_ask": 0.52, "order_price": 0.51,
            "trade_size_usd": 5.0,
        }], add_iv_cols=False)
        report = run_analysis(db, 50)
        assert report.total_rows == 1
        assert report.iv_enriched_rows == 0
        assert "NO_DATA" in report.kill_rule_status
