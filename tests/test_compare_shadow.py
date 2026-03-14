"""Tests for scripts/compare_shadow_vs_live.py."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# Patch DB paths before import
@pytest.fixture(autouse=True)
def _patch_db_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.compare_shadow_vs_live.SHADOW_DB", tmp_path / "shadow.db"
    )
    monkeypatch.setattr(
        "scripts.compare_shadow_vs_live.BTC5_DB", tmp_path / "btc5.db"
    )
    monkeypatch.setattr(
        "scripts.compare_shadow_vs_live.OUTPUT_DIR", tmp_path / "reports"
    )


def _create_shadow_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE shadow_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lane TEXT, market_id TEXT, question TEXT, direction TEXT,
            market_price REAL, estimated_prob REAL, edge REAL,
            confidence REAL, reasoning TEXT, hypothetical_size_usd REAL,
            timestamp_utc TEXT, extra_json TEXT, resolved INTEGER DEFAULT 0,
            resolution_price REAL, hypothetical_pnl REAL, resolved_at TEXT
        );
    """)
    conn.commit()
    return conn


def _create_btc5_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id TEXT, status TEXT, pnl REAL, created_at TEXT
        );
    """)
    conn.commit()
    return conn


class TestGenerateReport:
    def test_no_dbs_exist(self, tmp_path, monkeypatch):
        from scripts.compare_shadow_vs_live import generate_report

        report = generate_report()
        assert "error" in report["wallet_flow"]
        assert "error" in report["btc5_live"]

    def test_empty_dbs(self, tmp_path, monkeypatch):
        from scripts.compare_shadow_vs_live import generate_report

        shadow_path = tmp_path / "shadow.db"
        btc5_path = tmp_path / "btc5.db"
        _create_shadow_db(shadow_path)
        _create_btc5_db(btc5_path)

        monkeypatch.setattr(
            "scripts.compare_shadow_vs_live.SHADOW_DB", shadow_path
        )
        monkeypatch.setattr(
            "scripts.compare_shadow_vs_live.BTC5_DB", btc5_path
        )

        report = generate_report()
        assert report["wallet_flow"]["total_signals"] == 0
        assert report["btc5_live"]["total_fills"] == 0

    def test_with_shadow_data(self, tmp_path, monkeypatch):
        from scripts.compare_shadow_vs_live import generate_report

        shadow_path = tmp_path / "shadow.db"
        conn = _create_shadow_db(shadow_path)
        conn.execute(
            """INSERT INTO shadow_signals
               (lane, market_id, question, direction, market_price,
                estimated_prob, edge, confidence, reasoning,
                hypothetical_size_usd, timestamp_utc, resolved,
                hypothetical_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("wallet_flow", "0xabc", "Test?", "buy_yes", 0.5, 0.6, 0.1,
             0.65, "test", 5.0, "2026-03-14T12:00:00", 1, 2.50),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(
            "scripts.compare_shadow_vs_live.SHADOW_DB", shadow_path
        )

        report = generate_report()
        assert report["wallet_flow"]["total_signals"] == 1
        assert report["wallet_flow"]["wins"] == 1


class TestFormatMarkdown:
    def test_basic_formatting(self):
        from scripts.compare_shadow_vs_live import _format_markdown

        report = {
            "generated_at": "2026-03-14T00:00:00",
            "since": None,
            "wallet_flow": {"error": "shadow DB not found"},
            "lmsr": {"error": "shadow DB not found"},
            "btc5_live": {"error": "BTC5 DB not found"},
            "overlap": {"error": "missing"},
            "ranking": [],
        }
        md = _format_markdown(report)
        assert "Shadow vs Live" in md
        assert "ERROR" in md
