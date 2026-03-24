"""Tests for the negative-results library."""

import tempfile
from pathlib import Path

from src.negative_results import NegativeResult, NegativeResultsLibrary


def _make_lib(threshold: int = 3) -> NegativeResultsLibrary:
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "negative.db"
    return NegativeResultsLibrary(db_path, family_kill_threshold=threshold)


def _make_result(result_id: str = "nr_001", **kwargs) -> NegativeResult:
    defaults = {
        "result_id": result_id,
        "hypothesis_id": "hyp_001",
        "hypothesis_name": "BTC 5-min momentum",
        "family": "btc5",
        "kill_rule": "negative_expectancy",
        "kill_details": "EV taker = -0.02 after costs",
        "what_failed": "Momentum signal on BTC 5-min markets",
        "why_it_failed": "Spread + fees exceed edge",
        "what_was_learned": "Need maker-only execution or wider thresholds",
    }
    defaults.update(kwargs)
    return NegativeResult(**defaults)


class TestNegativeResult:
    def test_to_dict(self):
        nr = _make_result()
        d = nr.to_dict()
        assert d["result_id"] == "nr_001"
        assert d["kill_rule"] == "negative_expectancy"
        assert isinstance(d["counter_hypotheses"], list)


class TestNegativeResultsLibrary:
    def test_record_and_get(self):
        lib = _make_lib()
        nr = _make_result()
        lib.record(nr)

        retrieved = lib.get("nr_001")
        assert retrieved is not None
        assert retrieved.hypothesis_name == "BTC 5-min momentum"

    def test_get_nonexistent(self):
        lib = _make_lib()
        assert lib.get("nope") is None

    def test_list_by_family(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001", family="btc5"))
        lib.record(_make_result("nr_002", family="btc5"))
        lib.record(_make_result("nr_003", family="eth5"))

        btc5 = lib.list_by_family("btc5")
        assert len(btc5) == 2

    def test_list_by_kill_rule(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001", kill_rule="negative_expectancy"))
        lib.record(_make_result("nr_002", kill_rule="regime_decay"))
        lib.record(_make_result("nr_003", kill_rule="negative_expectancy"))

        neg_ev = lib.list_by_kill_rule("negative_expectancy")
        assert len(neg_ev) == 2

    def test_family_kill_count(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001", family="btc5"))
        lib.record(_make_result("nr_002", family="btc5"))
        assert lib.family_kill_count("btc5") == 2

    def test_family_veto_under_threshold(self):
        lib = _make_lib(threshold=3)
        lib.record(_make_result("nr_001", family="btc5"))
        lib.record(_make_result("nr_002", family="btc5"))
        assert lib.is_family_vetoed("btc5") is False

    def test_family_veto_at_threshold(self):
        lib = _make_lib(threshold=3)
        for i in range(3):
            lib.record(_make_result(f"nr_{i}", family="btc5"))
        assert lib.is_family_vetoed("btc5") is True

    def test_empty_family_not_vetoed(self):
        lib = _make_lib()
        assert lib.is_family_vetoed("") is False

    def test_vetoed_families(self):
        lib = _make_lib(threshold=2)
        lib.record(_make_result("nr_001", family="btc5"))
        lib.record(_make_result("nr_002", family="btc5"))
        lib.record(_make_result("nr_003", family="eth5"))

        vetoed = lib.vetoed_families()
        assert "btc5" in vetoed
        assert "eth5" not in vetoed

    def test_kill_rule_summary(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001", kill_rule="regime_decay"))
        lib.record(_make_result("nr_002", kill_rule="regime_decay"))
        lib.record(_make_result("nr_003", kill_rule="leakage"))

        summary = lib.kill_rule_summary()
        assert summary["regime_decay"] == 2
        assert summary["leakage"] == 1

    def test_lessons_for_family(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001", family="btc5", what_was_learned="Lesson A"))
        lib.record(_make_result("nr_002", family="btc5", what_was_learned="Lesson B"))

        lessons = lib.lessons_for_family("btc5")
        assert len(lessons) == 2
        assert "Lesson A" in lessons

    def test_dead_end_context_empty(self):
        lib = _make_lib()
        assert lib.dead_end_context() == ""

    def test_dead_end_context_with_vetoed(self):
        lib = _make_lib(threshold=2)
        lib.record(_make_result("nr_001", family="btc5", kill_rule="leakage", what_was_learned="Check data"))
        lib.record(_make_result("nr_002", family="btc5", kill_rule="regime_decay", what_was_learned="Too fragile"))

        ctx = lib.dead_end_context()
        assert "VETOED STRATEGY FAMILIES" in ctx
        assert "btc5" in ctx
        assert "Lesson:" in ctx

    def test_list_all(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001"))
        lib.record(_make_result("nr_002"))
        assert len(lib.list_all()) == 2

    def test_upsert_on_duplicate(self):
        lib = _make_lib()
        lib.record(_make_result("nr_001", what_was_learned="v1"))
        lib.record(_make_result("nr_001", what_was_learned="v2"))
        result = lib.get("nr_001")
        assert result.what_was_learned == "v2"
