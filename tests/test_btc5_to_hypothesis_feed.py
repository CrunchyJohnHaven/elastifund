"""Tests for scripts/btc5_to_hypothesis_feed.py"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.btc5_to_hypothesis_feed import (
    parse_env_file,
    load_latest_probe,
    load_cycle_history,
    extract_skip_distribution,
    extract_hour_performance,
    extract_direction_bias,
    analyze_parameter_performance,
    generate_implications,
    build_feedback,
)


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def sample_env_file(tmp_dir):
    path = tmp_dir / "test.env"
    path.write_text(
        "# comment\n"
        "BTC5_MAX_ABS_DELTA=0.003\n"
        "BTC5_DIRECTION=DOWN\n"
        "EMPTY_LINE=\n"
        "\n"
        "QUOTED='hello'\n"
    )
    return str(path)


@pytest.fixture
def sample_probe_file(tmp_dir):
    path = tmp_dir / "latest.json"
    probe = {
        "hypothesis_id": "hyp_down_up0.49_down0.51_hour_et_11",
        "status": "collecting",
        "direction_bias": "DOWN",
        "parameters": {"delta": 0.003, "direction": "DOWN"},
        "evidence_fills": 5,
        "evidence_grade": "exploratory",
    }
    path.write_text(json.dumps(probe))
    return str(path)


@pytest.fixture
def sample_cycles_file(tmp_dir):
    path = tmp_dir / "cycles.jsonl"
    cycles = [
        {"parameters": {"delta": "0.003"}, "pnl": 1.5},
        {"parameters": {"delta": "0.005"}, "pnl": -0.5},
        {"parameters": {"delta": "0.003", "direction": "DOWN"}, "pnl": 2.0},
    ]
    path.write_text("\n".join(json.dumps(c) for c in cycles))
    return str(path)


@pytest.fixture
def sample_db(tmp_dir):
    db_path = str(tmp_dir / "btc5.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            skip_reason TEXT,
            fill_time TEXT,
            pnl REAL,
            direction TEXT
        )
    """)
    # Insert skip records
    for _ in range(10):
        conn.execute(
            "INSERT INTO trades (skip_reason) VALUES (?)",
            ("skip_delta_too_large",),
        )
    for _ in range(3):
        conn.execute(
            "INSERT INTO trades (skip_reason) VALUES (?)",
            ("skip_shadow_only",),
        )

    # Insert filled trades with hour and direction
    fills = [
        ("2026-03-14T03:00:00", 0.5, "DOWN"),
        ("2026-03-14T03:30:00", 0.3, "DOWN"),
        ("2026-03-14T03:45:00", -0.1, "DOWN"),
        ("2026-03-14T08:00:00", -0.5, "UP"),
        ("2026-03-14T08:30:00", -0.3, "UP"),
        ("2026-03-14T14:00:00", 1.0, "DOWN"),
        ("2026-03-14T14:30:00", 0.8, "DOWN"),
    ]
    for fill_time, pnl, direction in fills:
        conn.execute(
            "INSERT INTO trades (fill_time, pnl, direction) VALUES (?, ?, ?)",
            (fill_time, pnl, direction),
        )

    conn.commit()
    conn.close()
    return db_path


class TestParseEnvFile:
    def test_parses_key_value(self, sample_env_file):
        result = parse_env_file(sample_env_file)
        assert result["BTC5_MAX_ABS_DELTA"] == "0.003"
        assert result["BTC5_DIRECTION"] == "DOWN"

    def test_strips_quotes(self, sample_env_file):
        result = parse_env_file(sample_env_file)
        assert result["QUOTED"] == "hello"

    def test_missing_file(self):
        result = parse_env_file("/nonexistent/path.env")
        assert result == {}


class TestLoadLatestProbe:
    def test_loads_probe(self, sample_probe_file):
        probe = load_latest_probe(sample_probe_file)
        assert probe["hypothesis_id"] == "hyp_down_up0.49_down0.51_hour_et_11"
        assert probe["evidence_fills"] == 5

    def test_missing_file(self):
        probe = load_latest_probe("/nonexistent/latest.json")
        assert probe == {}


class TestLoadCycleHistory:
    def test_loads_cycles(self, sample_cycles_file):
        cycles = load_cycle_history(sample_cycles_file)
        assert len(cycles) == 3
        assert cycles[0]["pnl"] == 1.5

    def test_missing_file(self):
        cycles = load_cycle_history("/nonexistent/cycles.jsonl")
        assert cycles == []

    def test_max_cycles(self, sample_cycles_file):
        cycles = load_cycle_history(sample_cycles_file, max_cycles=2)
        assert len(cycles) == 2


class TestExtractSkipDistribution:
    def test_extracts_skips(self, sample_db):
        dist = extract_skip_distribution(sample_db)
        assert dist["skip_delta_too_large"] == 10
        assert dist["skip_shadow_only"] == 3

    def test_missing_db(self):
        dist = extract_skip_distribution("/nonexistent/db.db")
        assert dist == {}


class TestExtractHourPerformance:
    def test_extracts_hours(self, sample_db):
        perf = extract_hour_performance(sample_db)
        # SQLite strftime extracts hours from the stored timestamps
        assert len(perf) > 0
        # All 7 fills should be accounted for
        total_count = sum(v["count"] for v in perf.values())
        assert total_count == 7
        # Net P&L should be positive (sum of all fill pnl = 1.7)
        total_pnl = sum(v["total_pnl"] for v in perf.values())
        assert total_pnl > 0

    def test_missing_db(self):
        perf = extract_hour_performance("/nonexistent/db.db")
        assert perf == {}


class TestExtractDirectionBias:
    def test_extracts_directions(self, sample_db):
        bias = extract_direction_bias(sample_db)
        assert "DOWN" in bias
        assert "UP" in bias
        assert bias["DOWN"]["count"] == 5
        assert bias["UP"]["count"] == 2
        assert bias["DOWN"]["total_pnl"] > 0
        assert bias["UP"]["total_pnl"] < 0

    def test_missing_db(self):
        bias = extract_direction_bias("/nonexistent/db.db")
        assert bias == {}


class TestAnalyzeParameterPerformance:
    def test_analyzes_params(self, sample_cycles_file):
        cycles = load_cycle_history(sample_cycles_file)
        analysis = analyze_parameter_performance(cycles)
        assert analysis["sample_size"] == 3
        assert "winning_params" in analysis
        assert "losing_params" in analysis

    def test_empty_cycles(self):
        analysis = analyze_parameter_performance([])
        assert analysis["sample_size"] == 0


class TestGenerateImplications:
    def test_delta_skip_implication(self):
        skip_dist = {"skip_delta_too_large": 50, "skip_shadow_only": 10}
        implications = generate_implications(skip_dist, {}, {}, {})
        delta_imp = [i for i in implications if "Delta filter" in i]
        assert len(delta_imp) == 1
        assert "BTC5_MAX_ABS_DELTA" in delta_imp[0]

    def test_direction_bias_implication(self):
        direction_bias = {
            "DOWN": {"count": 20, "wins": 12, "total_pnl": 5.0, "win_rate": 0.60},
            "UP": {"count": 15, "wins": 5, "total_pnl": -3.0, "win_rate": 0.33},
        }
        implications = generate_implications({}, {}, direction_bias, {})
        down_imp = [i for i in implications if "DOWN" in i]
        assert len(down_imp) >= 1

    def test_hour_implication(self):
        hour_perf = {
            "3": {"count": 10, "total_pnl": 2.0},
            "8": {"count": 10, "total_pnl": -1.5},
        }
        implications = generate_implications({}, hour_perf, {}, {})
        assert any("Losing hours" in i for i in implications)
        assert any("Winning hours" in i for i in implications)


class TestBuildFeedback:
    def test_full_build(self, sample_probe_file, sample_env_file, sample_cycles_file, sample_db):
        feedback = build_feedback(
            probe_path=sample_probe_file,
            env_path=sample_env_file,
            cycles_path=sample_cycles_file,
            db_path=sample_db,
        )
        assert "generated_at" in feedback
        assert feedback["source"] == "btc5_autoresearch"
        assert feedback["current_probe"]["hypothesis_id"] == "hyp_down_up0.49_down0.51_hour_et_11"
        assert feedback["active_overrides"]["BTC5_DIRECTION"] == "DOWN"
        assert len(feedback["skip_distribution"]) == 2
        assert len(feedback["implications"]) > 0
        assert "research_recommendations" in feedback

    def test_build_with_missing_files(self, tmp_dir):
        feedback = build_feedback(
            probe_path="/nonexistent/probe.json",
            env_path="/nonexistent/env",
            cycles_path="/nonexistent/cycles.jsonl",
            db_path="/nonexistent/db.db",
        )
        assert feedback["source"] == "btc5_autoresearch"
        assert feedback["current_probe"]["hypothesis_id"] == "unknown"
        assert feedback["cycle_count"] == 0
