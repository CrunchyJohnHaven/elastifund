"""Deterministic unit tests for detector plugin architecture.

All tests use hardcoded fixture data — no network calls, no randomness.
"""

import pytest
from uuid import uuid4

from src.detectors.base import Detector, Opportunity
from src.detectors.structural import StructuralDetector, _extract_yes_price
from src.store.models import DetectorOpportunity


# ── Fixtures: fake market dicts ────────────────────────────────


def _market(
    market_id: str,
    condition_id: str,
    question: str,
    yes_price: float,
    *,
    use_outcome_prices: bool = False,
) -> dict:
    """Build a minimal Gamma-API-shaped market dict."""
    m: dict = {
        "id": market_id,
        "condition_id": condition_id,
        "question": question,
    }
    if use_outcome_prices:
        import json
        m["outcomePrices"] = json.dumps([yes_price, round(1 - yes_price, 4)])
    else:
        m["tokens"] = [
            {"outcome": "Yes", "token_id": f"tok_yes_{market_id}", "price": yes_price},
            {"outcome": "No", "token_id": f"tok_no_{market_id}", "price": round(1 - yes_price, 4)},
        ]
    return m


# Three mutually exclusive outcomes that sum to > 1.0
ME_OVERPRICED = [
    _market("m1", "event_abc", "Will A happen?", 0.45),
    _market("m2", "event_abc", "Will B happen?", 0.40),
    _market("m3", "event_abc", "Will C happen?", 0.25),
    # sum = 1.10 → 10% edge
]

# Three mutually exclusive outcomes that sum to exactly 1.0 (no edge)
ME_FAIR = [
    _market("m4", "event_def", "Will D happen?", 0.50),
    _market("m5", "event_def", "Will E happen?", 0.30),
    _market("m6", "event_def", "Will F happen?", 0.20),
]

# Underpriced group: sum < 1.0 (no sell-side signal for this detector)
ME_UNDERPRICED = [
    _market("m7", "event_ghi", "Will G happen?", 0.30),
    _market("m8", "event_ghi", "Will H happen?", 0.25),
    _market("m9", "event_ghi", "Will I happen?", 0.15),
    # sum = 0.70 → no violation
]

# Single-market group (should be ignored)
ME_SINGLE = [
    _market("m10", "event_solo", "Will solo happen?", 0.60),
]


# ── Tests: _extract_yes_price ─────────────────────────────────


class TestExtractYesPrice:
    def test_tokens_list(self):
        m = _market("x", "c", "q", 0.72)
        assert _extract_yes_price(m) == 0.72

    def test_outcome_prices_string(self):
        m = _market("x", "c", "q", 0.65, use_outcome_prices=True)
        assert _extract_yes_price(m) == 0.65

    def test_missing_data_returns_none(self):
        assert _extract_yes_price({"id": "x"}) is None

    def test_empty_tokens_returns_none(self):
        assert _extract_yes_price({"id": "x", "tokens": []}) is None

    def test_bad_outcome_prices_returns_none(self):
        assert _extract_yes_price({"id": "x", "outcomePrices": "not_json"}) is None


# ── Tests: Mutual Exclusivity ─────────────────────────────────


class TestMutualExclusivity:
    @pytest.fixture
    def detector(self) -> StructuralDetector:
        # Use a non-existent path so no implications are loaded
        return StructuralDetector(mappings_path="/dev/null/none.json", min_edge_pct=0.5)

    @pytest.mark.asyncio
    async def test_overpriced_group_detected(self, detector):
        opps = await detector.scan(ME_OVERPRICED)
        assert len(opps) == 1
        opp = opps[0]
        assert opp.detector == "structural"
        assert opp.kind == "mutual_exclusivity"
        assert opp.edge_pct == pytest.approx(10.0, abs=0.1)
        assert set(opp.market_ids) == {"m1", "m2", "m3"}
        assert opp.meta["condition_id"] == "event_abc"

    @pytest.mark.asyncio
    async def test_fair_group_no_signal(self, detector):
        opps = await detector.scan(ME_FAIR)
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_underpriced_group_no_signal(self, detector):
        opps = await detector.scan(ME_UNDERPRICED)
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_single_market_ignored(self, detector):
        opps = await detector.scan(ME_SINGLE)
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_mixed_batch(self, detector):
        """Only the overpriced group surfaces when mixing fair and overpriced."""
        all_markets = ME_OVERPRICED + ME_FAIR + ME_UNDERPRICED + ME_SINGLE
        opps = await detector.scan(all_markets)
        assert len(opps) == 1
        assert opps[0].meta["condition_id"] == "event_abc"

    @pytest.mark.asyncio
    async def test_min_edge_filter(self):
        """Edge below threshold is suppressed."""
        detector = StructuralDetector(mappings_path="/dev/null/none.json", min_edge_pct=15.0)
        opps = await detector.scan(ME_OVERPRICED)  # 10% edge
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_empty_markets(self, detector):
        opps = await detector.scan([])
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_outcome_prices_format(self, detector):
        """Detector works with outcomePrices string format too."""
        markets = [
            _market("op1", "event_op", "Q1?", 0.55, use_outcome_prices=True),
            _market("op2", "event_op", "Q2?", 0.50, use_outcome_prices=True),
        ]
        # sum = 1.05 → 5% edge
        opps = await detector.scan(markets)
        assert len(opps) == 1
        assert opps[0].edge_pct == pytest.approx(5.0, abs=0.1)


# ── Tests: Implication Bounds ─────────────────────────────────


class TestImplicationBounds:
    @pytest.fixture
    def imp_mappings_path(self, tmp_path):
        import json
        mappings = {
            "groups": [
                {
                    "label": "A implies B",
                    "implies": [
                        {
                            "if_market": "cond_A",
                            "then_market": "cond_B",
                        }
                    ],
                }
            ]
        }
        p = tmp_path / "implications.json"
        p.write_text(json.dumps(mappings))
        return p

    @pytest.fixture
    def detector(self, imp_mappings_path) -> StructuralDetector:
        return StructuralDetector(mappings_path=imp_mappings_path, min_edge_pct=0.5)

    @pytest.mark.asyncio
    async def test_violation_detected(self, detector):
        """price(A)=0.70 > price(B)=0.50 → violation."""
        markets = [
            _market("mA", "cond_A", "Will A?", 0.70),
            _market("mB", "cond_B", "Will B?", 0.50),
        ]
        opps = await detector.scan(markets)
        assert len(opps) == 1
        opp = opps[0]
        assert opp.kind == "implication"
        assert opp.edge_pct == pytest.approx(20.0, abs=0.1)
        assert set(opp.market_ids) == {"mA", "mB"}

    @pytest.mark.asyncio
    async def test_no_violation_when_compliant(self, detector):
        """price(A)=0.40 <= price(B)=0.60 → no violation."""
        markets = [
            _market("mA", "cond_A", "Will A?", 0.40),
            _market("mB", "cond_B", "Will B?", 0.60),
        ]
        opps = await detector.scan(markets)
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_equal_prices_no_violation(self, detector):
        """price(A) == price(B) → no violation."""
        markets = [
            _market("mA", "cond_A", "Will A?", 0.55),
            _market("mB", "cond_B", "Will B?", 0.55),
        ]
        opps = await detector.scan(markets)
        assert len(opps) == 0

    @pytest.mark.asyncio
    async def test_missing_market_skipped(self, detector):
        """If one side of the implication is missing, skip it."""
        markets = [
            _market("mA", "cond_A", "Will A?", 0.70),
            # cond_B not present
        ]
        opps = await detector.scan(markets)
        assert len(opps) == 0


# ── Tests: Detector Interface ─────────────────────────────────


class TestDetectorInterface:
    def test_structural_is_detector(self):
        det = StructuralDetector(mappings_path="/dev/null/none.json")
        assert isinstance(det, Detector)

    def test_name_property(self):
        det = StructuralDetector(mappings_path="/dev/null/none.json")
        assert det.name == "structural"


# ── Tests: Opportunity dataclass ──────────────────────────────


class TestOpportunity:
    def test_frozen(self):
        opp = Opportunity(
            detector="test",
            kind="test_kind",
            group_label="test group",
            market_ids=("m1", "m2"),
            edge_pct=5.0,
            detail="test detail",
        )
        with pytest.raises(AttributeError):
            opp.edge_pct = 10.0  # type: ignore[misc]

    def test_fields(self):
        opp = Opportunity(
            detector="structural",
            kind="mutual_exclusivity",
            group_label="ME: test",
            market_ids=("m1", "m2"),
            edge_pct=3.5,
            detail="sum exceeded",
            prices={"m1": 0.6, "m2": 0.5},
        )
        assert opp.detector == "structural"
        assert opp.market_ids == ("m1", "m2")
        assert opp.prices["m1"] == 0.6


# ── Tests: DB Model ───────────────────────────────────────────


class TestDetectorOpportunityModel:
    @pytest.mark.asyncio
    async def test_create_and_query(self, db_session):
        row = DetectorOpportunity(
            id=str(uuid4()),
            run_id="run_001",
            detector="structural",
            kind="mutual_exclusivity",
            group_label="test group",
            market_ids=["m1", "m2"],
            edge_pct=5.5,
            detail="test",
            prices={"m1": 0.55, "m2": 0.50},
            meta_data={"condition_id": "cond_123"},
        )
        db_session.add(row)
        await db_session.flush()

        from sqlalchemy import select
        stmt = select(DetectorOpportunity).where(DetectorOpportunity.run_id == "run_001")
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()
        assert fetched.detector == "structural"
        assert fetched.edge_pct == 5.5
        assert "m1" in fetched.market_ids


# ── Tests: Sorting ────────────────────────────────────────────


class TestSorting:
    @pytest.mark.asyncio
    async def test_results_sorted_by_edge_descending(self):
        """When multiple groups are overpriced, highest edge comes first."""
        detector = StructuralDetector(mappings_path="/dev/null/none.json", min_edge_pct=0.5)
        markets = [
            # Group 1: 10% edge
            _market("a1", "ev1", "Q1?", 0.45),
            _market("a2", "ev1", "Q2?", 0.40),
            _market("a3", "ev1", "Q3?", 0.25),
            # Group 2: 5% edge
            _market("b1", "ev2", "Q4?", 0.55),
            _market("b2", "ev2", "Q5?", 0.50),
        ]
        opps = await detector.scan(markets)
        assert len(opps) == 2
        assert opps[0].edge_pct > opps[1].edge_pct
        assert opps[0].meta["condition_id"] == "ev1"
        assert opps[1].meta["condition_id"] == "ev2"
