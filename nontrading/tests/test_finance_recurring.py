from __future__ import annotations

from nontrading.finance.recurring import FinanceTransaction, detect_recurring_merchants
from nontrading.finance.vendor_registry import DEFAULT_VENDOR_REGISTRY, resolve_vendor


def test_vendor_registry_resolves_noisy_aliases() -> None:
    match = resolve_vendor("ANTHROPIC*CLAUDE PRO", "Claude Team Plan", registry=DEFAULT_VENDOR_REGISTRY)

    assert match.profile.canonical_name == "Claude"
    assert match.profile.duplicate_group == "general_llm"
    assert match.confidence >= 0.8


def test_detects_monthly_recurring_merchant_and_monthly_cost() -> None:
    transactions = [
        FinanceTransaction(
            transaction_id="tx-1",
            posted_at="2026-01-05T12:00:00+00:00",
            amount_usd=-20.0,
            merchant="OPENAI*CHATGPT",
            description="ChatGPT Team",
        ),
        FinanceTransaction(
            transaction_id="tx-2",
            posted_at="2026-02-04T12:00:00+00:00",
            amount_usd=-20.0,
            merchant="OPENAI*CHATGPT",
            description="ChatGPT Team",
        ),
        FinanceTransaction(
            transaction_id="tx-3",
            posted_at="2026-03-06T12:00:00+00:00",
            amount_usd=-20.0,
            merchant="OPENAI*CHATGPT",
            description="ChatGPT Team",
        ),
        FinanceTransaction(
            transaction_id="salary-1",
            posted_at="2026-03-07T12:00:00+00:00",
            amount_usd=5000.0,
            merchant="Payroll",
            direction="deposit",
        ),
    ]

    commitments = detect_recurring_merchants(transactions)

    assert len(commitments) == 1
    commitment = commitments[0]
    assert commitment.canonical_vendor_name == "ChatGPT"
    assert commitment.billing_period == "monthly"
    assert commitment.monthly_cost_usd == 20.0
    assert commitment.occurrence_count == 3
    assert commitment.confidence >= 0.85
    assert commitment.transaction_ids == ("tx-1", "tx-2", "tx-3")
