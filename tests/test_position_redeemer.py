import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.position_merger import COLLATERAL_TOKEN, PositionSnapshot
from bot.position_redeemer import (
    STANDARD_REDEEM_SELECTOR,
    PositionRedemptionService,
    build_standard_redeem_calldata,
    index_set_for_outcome_index,
)


def _position(
    *,
    condition_id: str,
    outcome: str,
    size: float,
    current_value: float,
    outcome_index: int | None,
    negative_risk: bool | None = False,
    redeemable: bool = True,
) -> PositionSnapshot:
    raw = {}
    if outcome_index is not None:
        raw["outcomeIndex"] = outcome_index
    return PositionSnapshot(
        user="0x" + ("aa" * 20),
        condition_id=condition_id,
        market_id=condition_id,
        token_id="0x" + ("01" * 20),
        opposite_token_id="0x" + ("02" * 20),
        title="BTC test market",
        outcome=outcome,
        size=size,
        avg_price=0.5,
        initial_value=size * 0.5,
        current_value=current_value,
        mergeable=False,
        redeemable=redeemable,
        negative_risk=negative_risk,
        raw=raw,
    )


def test_index_set_for_outcome_index_binary_layout():
    assert index_set_for_outcome_index(0) == 1
    assert index_set_for_outcome_index(1) == 2


def test_build_standard_redeem_calldata_matches_expected_layout():
    condition_id = "0x" + ("11" * 32)
    calldata = build_standard_redeem_calldata(condition_id, 2)
    expected = (
        "0x"
        + STANDARD_REDEEM_SELECTOR
        + ("0" * 24) + COLLATERAL_TOKEN.lower().removeprefix("0x")
        + ("0" * 64)
        + ("11" * 32)
        + f"{128:064x}"
        + f"{1:064x}"
        + f"{2:064x}"
    )
    assert calldata == expected


def test_find_redeem_candidates_keeps_positive_standard_positions():
    condition_id = "0x" + ("12" * 32)
    positions = [
        _position(condition_id=condition_id, outcome="Yes", size=10.0, current_value=10.0, outcome_index=0),
        _position(
            condition_id="0x" + ("13" * 32),
            outcome="No",
            size=5.0,
            current_value=0.0,
            outcome_index=1,
        ),
        _position(
            condition_id="0x" + ("14" * 32),
            outcome="Yes",
            size=8.0,
            current_value=8.0,
            outcome_index=0,
            negative_risk=True,
        ),
    ]

    candidates = PositionRedemptionService.find_redeem_candidates(positions)

    assert len(candidates) == 2
    assert candidates[0].condition_id == condition_id
    assert candidates[0].execution_ready is True
    assert candidates[0].freed_capital_usdc == pytest.approx(10.0)
    assert candidates[0].index_set == 1
    assert candidates[1].execution_ready is False
    assert candidates[1].note == "negative_risk_unsupported"


def test_find_redeem_candidates_falls_back_to_outcome_text():
    condition_id = "0x" + ("15" * 32)
    positions = [
        _position(
            condition_id=condition_id,
            outcome="No",
            size=6.0,
            current_value=6.0,
            outcome_index=None,
        )
    ]

    candidates = PositionRedemptionService.find_redeem_candidates(positions)

    assert len(candidates) == 1
    assert candidates[0].execution_ready is True
    assert candidates[0].outcome_index == 1
    assert candidates[0].index_set == 2
