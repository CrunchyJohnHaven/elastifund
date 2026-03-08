import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.position_merger import (
    COLLATERAL_TOKEN,
    MergeCandidate,
    NodePolyMergerExecutor,
    PositionMergeService,
    PositionSnapshot,
    STANDARD_MERGE_SELECTOR,
    NEG_RISK_MERGE_SELECTOR,
    build_neg_risk_merge_calldata,
    build_standard_merge_calldata,
)


def _position(
    *,
    condition_id: str,
    token_id: str,
    opposite_token_id: str,
    outcome: str,
    size: float,
    avg_price: float,
    current_value: float,
    negative_risk: bool | None,
    mergeable: bool = True,
    title: str = "Will Alice win?",
) -> PositionSnapshot:
    return PositionSnapshot(
        user="0x" + ("aa" * 20),
        condition_id=condition_id,
        market_id=condition_id,
        token_id=token_id,
        opposite_token_id=opposite_token_id,
        title=title,
        outcome=outcome,
        size=size,
        avg_price=avg_price,
        initial_value=size * avg_price,
        current_value=current_value,
        mergeable=mergeable,
        redeemable=False,
        negative_risk=negative_risk,
    )


class TestPositionMergeService:
    def test_find_merge_candidates_pairs_yes_and_no(self):
        condition_id = "0x" + ("11" * 32)
        positions = [
            _position(
                condition_id=condition_id,
                token_id="0x" + ("01" * 20),
                opposite_token_id="0x" + ("02" * 20),
                outcome="Yes",
                size=12.5,
                avg_price=0.41,
                current_value=6.75,
                negative_risk=False,
            ),
            _position(
                condition_id=condition_id,
                token_id="0x" + ("02" * 20),
                opposite_token_id="0x" + ("01" * 20),
                outcome="No",
                size=7.0,
                avg_price=0.55,
                current_value=3.22,
                negative_risk=False,
            ),
        ]

        candidates = PositionMergeService.find_merge_candidates(positions)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.merge_size == pytest.approx(7.0)
        assert candidate.freed_capital_usdc == pytest.approx(7.0)
        assert candidate.execution_ready is True
        assert candidate.negative_risk is False
        assert candidate.yes.entry_price == pytest.approx(0.41)
        assert candidate.no.mark_price == pytest.approx(3.22 / 7.0)

    def test_candidate_blocked_when_neg_risk_unknown(self):
        condition_id = "0x" + ("12" * 32)
        positions = [
            _position(
                condition_id=condition_id,
                token_id="0x" + ("03" * 20),
                opposite_token_id="0x" + ("04" * 20),
                outcome="Yes",
                size=5.0,
                avg_price=0.4,
                current_value=2.7,
                negative_risk=None,
            ),
            _position(
                condition_id=condition_id,
                token_id="0x" + ("04" * 20),
                opposite_token_id="0x" + ("03" * 20),
                outcome="No",
                size=5.0,
                avg_price=0.6,
                current_value=2.0,
                negative_risk=None,
            ),
        ]

        candidates = PositionMergeService.find_merge_candidates(positions)

        assert len(candidates) == 1
        assert candidates[0].execution_ready is False
        assert candidates[0].note == "neg_risk_unresolved"

    def test_find_duplicate_outcome_positions_groups_same_side_lots(self):
        condition_id = "0x" + ("13" * 32)
        positions = [
            _position(
                condition_id=condition_id,
                token_id="0x" + ("07" * 20),
                opposite_token_id="0x" + ("08" * 20),
                outcome="Yes",
                size=1.5,
                avg_price=0.35,
                current_value=0.7,
                negative_risk=False,
            ),
            _position(
                condition_id=condition_id,
                token_id="0x" + ("07" * 20),
                opposite_token_id="0x" + ("08" * 20),
                outcome="YES",
                size=2.25,
                avg_price=0.38,
                current_value=0.9,
                negative_risk=False,
            ),
            _position(
                condition_id=condition_id,
                token_id="0x" + ("08" * 20),
                opposite_token_id="0x" + ("07" * 20),
                outcome="No",
                size=1.0,
                avg_price=0.62,
                current_value=0.5,
                negative_risk=False,
            ),
        ]

        duplicates = PositionMergeService.find_duplicate_outcome_positions(positions)

        assert len(duplicates) == 1
        duplicate = duplicates[0]
        assert duplicate.condition_id == condition_id
        assert duplicate.outcome == "YES"
        assert duplicate.position_count == 2
        assert duplicate.total_size == pytest.approx(3.75)


class TestCalldataBuilders:
    def test_build_standard_merge_calldata_matches_expected_layout(self):
        condition_id = "0x" + ("11" * 32)
        calldata = build_standard_merge_calldata(condition_id, 1_500_000)
        expected = (
            "0x"
            + STANDARD_MERGE_SELECTOR
            + ("0" * 24) + COLLATERAL_TOKEN.lower().removeprefix("0x")
            + ("0" * 64)
            + ("11" * 32)
            + f"{160:064x}"
            + f"{1_500_000:064x}"
            + f"{2:064x}"
            + f"{1:064x}"
            + f"{2:064x}"
        )
        assert calldata == expected

    def test_build_neg_risk_merge_calldata_matches_expected_layout(self):
        condition_id = "0x" + ("ab" * 32)
        calldata = build_neg_risk_merge_calldata(condition_id, 2_250_000)
        expected = "0x" + NEG_RISK_MERGE_SELECTOR + ("ab" * 32) + f"{2_250_000:064x}"
        assert calldata == expected


class TestNodeExecutor:
    def test_node_executor_builds_poly_merger_command(self):
        condition_id = "0x" + ("22" * 32)
        candidate = MergeCandidate(
            condition_id=condition_id,
            title="Test",
            yes=_position(
                condition_id=condition_id,
                token_id="0x" + ("05" * 20),
                opposite_token_id="0x" + ("06" * 20),
                outcome="Yes",
                size=3.0,
                avg_price=0.4,
                current_value=1.5,
                negative_risk=True,
            ),
            no=_position(
                condition_id=condition_id,
                token_id="0x" + ("06" * 20),
                opposite_token_id="0x" + ("05" * 20),
                outcome="No",
                size=3.0,
                avg_price=0.6,
                current_value=1.2,
                negative_risk=True,
            ),
            merge_size=2.5,
            freed_capital_usdc=2.5,
            negative_risk=True,
            execution_ready=True,
        )

        executor = NodePolyMergerExecutor("/tmp/poly_merger/merge.js")
        command = executor.build_command(candidate)

        assert command == [
            "node",
            "/tmp/poly_merger/merge.js",
            "2500000",
            condition_id,
            "true",
        ]
