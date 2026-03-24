"""Tests for the hypothesis card dataclass and ValidatedNetEdge scorecard."""

import json
import time

from src.hypothesis_card import HypothesisCard, ProofStatus, ValidatedNetEdge


class TestValidatedNetEdge:
    def test_positive_net_edge(self):
        vne = ValidatedNetEdge(
            lower_confidence_bound_gross_alpha=0.05,
            all_in_execution_cost=0.01,
            financing_funding=0.005,
            model_error_buffer=0.005,
            tail_risk_penalty=0.005,
        )
        assert vne.net_edge == 0.025
        assert vne.is_interesting is True

    def test_negative_net_edge(self):
        vne = ValidatedNetEdge(
            lower_confidence_bound_gross_alpha=0.01,
            all_in_execution_cost=0.02,
            financing_funding=0.005,
            model_error_buffer=0.005,
            tail_risk_penalty=0.005,
        )
        assert vne.net_edge < 0
        assert vne.is_interesting is False

    def test_zero_net_edge(self):
        vne = ValidatedNetEdge()
        assert vne.net_edge == 0.0
        assert vne.is_interesting is False

    def test_to_dict_includes_computed(self):
        vne = ValidatedNetEdge(lower_confidence_bound_gross_alpha=0.10)
        d = vne.to_dict()
        assert "net_edge" in d
        assert "is_interesting" in d
        assert d["net_edge"] == 0.10
        assert d["is_interesting"] is True


class TestHypothesisCard:
    def _make_card(self, **kwargs) -> HypothesisCard:
        defaults = {
            "hypothesis_name": "test_strategy",
            "hypothesis_id": "hyp_001",
            "family": "btc5",
            "market_and_universe": "Polymarket BTC 5-min",
            "horizon": "5 minutes",
            "economic_mechanism": "Market makers slow to reprice after BTC moves",
            "signal_definition": "BTC return > threshold triggers directional bet",
            "execution_style": "Maker only, post-only limit orders",
            "expected_costs": "0% maker fee, ~1c spread",
        }
        defaults.update(kwargs)
        return HypothesisCard(**defaults)

    def test_default_proof_statuses(self):
        card = self._make_card()
        statuses = card.proof_statuses()
        assert all(s == ProofStatus.NOT_STARTED for s in statuses.values())

    def test_all_proofs_passed(self):
        card = self._make_card()
        for proof in ("mechanism", "data", "statistical", "execution", "live"):
            card.update_proof(proof, ProofStatus.PASSED)
        assert card.all_proofs_passed() is True
        assert card.any_proof_failed() is False
        assert card.passed_proof_count() == 5

    def test_any_proof_failed(self):
        card = self._make_card()
        card.update_proof("mechanism", ProofStatus.PASSED)
        card.update_proof("data", ProofStatus.FAILED, "Look-ahead detected")
        assert card.all_proofs_passed() is False
        assert card.any_proof_failed() is True
        assert card.passed_proof_count() == 1

    def test_update_proof_invalid(self):
        card = self._make_card()
        try:
            card.update_proof("bogus", ProofStatus.PASSED)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_update_proof_sets_notes(self):
        card = self._make_card()
        card.update_proof("mechanism", ProofStatus.PASSED, "Confirmed by order flow analysis")
        assert card.mechanism_proof_notes == "Confirmed by order flow analysis"

    def test_serialization_round_trip(self):
        card = self._make_card()
        card.update_proof("mechanism", ProofStatus.PASSED, "Verified")
        card.update_proof("data", ProofStatus.IN_PROGRESS)
        card.validated_net_edge = ValidatedNetEdge(
            lower_confidence_bound_gross_alpha=0.03,
            all_in_execution_cost=0.01,
        )
        card.failure_modes = ["regime change", "fee increase"]
        card.tags = ["btc", "5min"]

        d = card.to_dict()
        restored = HypothesisCard.from_dict(d)

        assert restored.hypothesis_name == "test_strategy"
        assert restored.mechanism_proof_status == ProofStatus.PASSED
        assert restored.data_proof_status == ProofStatus.IN_PROGRESS
        assert abs(restored.validated_net_edge.net_edge - 0.02) < 1e-10
        assert restored.failure_modes == ["regime change", "fee increase"]
        assert restored.tags == ["btc", "5min"]

    def test_to_json(self):
        card = self._make_card()
        j = card.to_json()
        parsed = json.loads(j)
        assert parsed["hypothesis_name"] == "test_strategy"
        assert parsed["mechanism_proof_status"] == "not_started"

    def test_updated_at_changes_on_proof_update(self):
        card = self._make_card()
        original = card.updated_at
        # Ensure enough time passes for float comparison
        time.sleep(0.01)
        card.update_proof("mechanism", ProofStatus.PASSED)
        assert card.updated_at > original
