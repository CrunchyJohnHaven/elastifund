from __future__ import annotations

from nontrading.finance import AllocationCandidate, FinanceAllocator, FinanceBucket, FinancePolicy, FinanceSnapshot, ResourceAskKind


def test_allocator_respects_cash_floor_action_cap_and_monthly_commitment_cap() -> None:
    policy = FinancePolicy(
        single_action_cap_usd=250.0,
        monthly_new_commitment_cap_usd=1000.0,
        min_cash_reserve_months=1.0,
    )
    snapshot = FinanceSnapshot(
        liquid_cash_usd=1200.0,
        monthly_burn_usd=600.0,
        recurring_commitments_monthly_usd=550.0,
        monthly_new_commitments_usd=900.0,
        illiquid_equity_usd=100_000.0,
        active_experiment_budget_usd=40.0,
    )
    allocator = FinanceAllocator(policy)
    plan = allocator.allocate(
        snapshot=snapshot,
        candidates=[
            AllocationCandidate(
                candidate_id="fund_trading",
                label="Fund trading",
                bucket=FinanceBucket.FUND_TRADING,
                requested_amount_usd=400.0,
                expected_net_value_30d=80.0,
                expected_information_gain_30d=20.0,
                confidence=0.8,
                ask_kind=ResourceAskKind.CAPITAL,
            ),
            AllocationCandidate(
                candidate_id="buy_tool",
                label="Buy tool",
                bucket=FinanceBucket.BUY_TOOL_OR_DATA,
                requested_amount_usd=150.0,
                expected_net_value_30d=10.0,
                expected_information_gain_30d=30.0,
                confidence=0.7,
                ask_kind=ResourceAskKind.TOOL,
            ),
            AllocationCandidate(
                candidate_id="fund_nontrading",
                label="Fund JJ-N",
                bucket=FinanceBucket.FUND_NONTRADING,
                requested_amount_usd=80.0,
                expected_net_value_30d=25.0,
                expected_information_gain_30d=5.0,
                recurring_commitment_monthly_usd=150.0,
                confidence=0.6,
                ask_kind=ResourceAskKind.EXPERIMENT,
            ),
        ],
    )

    funded = {item["candidate_id"]: item for item in plan["ranked_actions"]}

    assert plan["finance_snapshot"]["reserve_floor_usd"] == 600.0
    assert plan["finance_snapshot"]["free_cash_after_floor_usd"] == 600.0
    assert plan["finance_snapshot"]["capital_ready_to_deploy_usd"] == 600.0
    assert plan["finance_snapshot"]["ignored_illiquid_equity_usd"] == 100000.0
    assert funded["fund_trading"]["recommended_amount_usd"] == 250.0
    assert "single_action_cap" in funded["fund_trading"]["constraint_hits"]
    assert funded["fund_trading"]["decision"] == "approve"
    assert funded["buy_tool"]["recommended_amount_usd"] == 150.0
    assert funded["fund_nontrading"]["recommended_amount_usd"] == 0.0
    assert "monthly_new_commitment_cap" in funded["fund_nontrading"]["constraint_hits"]
    assert funded["fund_nontrading"]["decision"] == "ask"
    assert plan["bucket_totals"]["fund_trading"] == 250.0
    assert plan["bucket_totals"]["buy_tool_or_data"] == 150.0
    assert plan["bucket_totals"]["keep_in_cash"] == 800.0
    assert any(ask["ask_type"] == "experiment" for ask in plan["resource_asks"])
    assert plan["cycle_budget_ledger"]["dollars"]["approved_usd"] == 400.0
    assert plan["cycle_budget_ledger"]["model_minutes"]["approved_total"] == 0.0


def test_illiquid_equity_never_counts_as_deployable_cash() -> None:
    policy = FinancePolicy(single_action_cap_usd=250.0, min_cash_reserve_months=1.0)
    snapshot = FinanceSnapshot(
        liquid_cash_usd=100.0,
        monthly_burn_usd=200.0,
        illiquid_equity_usd=5000.0,
    )
    allocator = FinanceAllocator(policy)
    plan = allocator.allocate(
        snapshot=snapshot,
        candidates=[
            AllocationCandidate(
                candidate_id="buy_data",
                label="Buy market data",
                bucket=FinanceBucket.BUY_TOOL_OR_DATA,
                requested_amount_usd=50.0,
                expected_net_value_30d=0.0,
                expected_information_gain_30d=25.0,
                confidence=0.9,
                ask_kind=ResourceAskKind.DATA,
            )
        ],
    )

    candidate = next(item for item in plan["ranked_actions"] if item["candidate_id"] == "buy_data")

    assert plan["finance_snapshot"]["reserve_floor_usd"] == 200.0
    assert plan["finance_snapshot"]["free_cash_after_floor_usd"] == 0.0
    assert plan["finance_snapshot"]["capital_ready_to_deploy_usd"] == 0.0
    assert plan["finance_snapshot"]["ignored_illiquid_equity_usd"] == 5000.0
    assert candidate["recommended_amount_usd"] == 0.0
    assert "cash_after_floor" in candidate["constraint_hits"]
    assert plan["bucket_totals"]["keep_in_cash"] == 100.0
    assert plan["resource_asks"][0]["ask_type"] == "data"


def test_escalated_model_minutes_require_explicit_value_case() -> None:
    policy = FinancePolicy(single_action_cap_usd=250.0, min_cash_reserve_months=1.0)
    snapshot = FinanceSnapshot(liquid_cash_usd=500.0, monthly_burn_usd=100.0)
    allocator = FinanceAllocator(policy)

    plan = allocator.allocate(
        snapshot=snapshot,
        candidates=[
            AllocationCandidate(
                candidate_id="escalated_review",
                label="Escalated review",
                bucket=FinanceBucket.BUY_TOOL_OR_DATA,
                requested_amount_usd=50.0,
                expected_net_value_30d=10.0,
                expected_information_gain_30d=5.0,
                confidence=0.5,
                ask_kind=ResourceAskKind.TOOL,
                model_tier="conflict_arbitration",
                model_minutes=30.0,
            )
        ],
    )

    candidate = plan["ranked_actions"][0]

    assert candidate["decision"] == "deny"
    assert "missing_model_value_case" in candidate["constraint_hits"]
    assert candidate["model_value_case_pass"] is False
    assert plan["cycle_budget_ledger"]["model_minutes"]["escalated_without_value_case"] == 30.0


def test_allocator_emits_lane_metadata_and_blocks_hard_gated_candidate() -> None:
    policy = FinancePolicy(single_action_cap_usd=250.0, min_cash_reserve_months=1.0)
    snapshot = FinanceSnapshot(liquid_cash_usd=500.0, monthly_burn_usd=100.0)
    allocator = FinanceAllocator(policy)

    plan = allocator.allocate(
        snapshot=snapshot,
        candidates=[
            AllocationCandidate(
                candidate_id="fund_trading",
                label="Fund trading",
                bucket=FinanceBucket.FUND_TRADING,
                requested_amount_usd=100.0,
                expected_net_value_30d=20.0,
                expected_information_gain_30d=5.0,
                confidence=0.8,
                ask_kind=ResourceAskKind.CAPITAL,
                expected_arr_lift_30d=20.0,
                hard_blockers=("service_not_running", "runtime_package_load_pending"),
                decision_reason="Hold incremental trading capital until launch blockers clear.",
            )
        ],
    )

    candidate = plan["ranked_actions"][0]

    assert candidate["lane"] == "trading"
    assert candidate["confidence_adjusted_score"] == 21.0
    assert candidate["recommended_amount_usd"] == 0.0
    assert candidate["decision"] == "ask"
    assert candidate["decision_reason"] == "Hold incremental trading capital until launch blockers clear."
    assert "service_not_running" in candidate["constraint_hits"]
