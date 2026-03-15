from __future__ import annotations

from nontrading.finance.subscriptions import SubscriptionRecord, audit_subscriptions


def make_subscription(**overrides: object) -> SubscriptionRecord:
    payload = {
        "vendor_name": "ChatGPT",
        "product_name": "Team",
        "status": "active",
        "monthly_cost_usd": 20.0,
        "billing_amount_usd": 20.0,
        "billing_period": "monthly",
        "annual_price_usd": None,
        "usage_events_30d": 12,
        "last_used_at": "2026-03-08T12:00:00+00:00",
        "source": "manual",
        "metadata": {},
    }
    payload.update(overrides)
    return SubscriptionRecord(**payload)


def test_audit_detects_duplicate_tools_and_overlapping_categories() -> None:
    report = audit_subscriptions(
        [
            make_subscription(vendor_name="ChatGPT", monthly_cost_usd=20.0, usage_events_30d=25),
            make_subscription(
                vendor_name="Claude",
                monthly_cost_usd=30.0,
                usage_events_30d=1,
                last_used_at="2026-02-01T12:00:00+00:00",
            ),
            make_subscription(
                vendor_name="GitHub Copilot",
                monthly_cost_usd=19.0,
                usage_events_30d=2,
                last_used_at="2026-02-15T12:00:00+00:00",
            ),
        ],
        as_of="2026-03-10T12:00:00+00:00",
    )

    findings = {finding.finding_type: finding for finding in report.findings}

    duplicate = findings["duplicate_tools"]
    overlap = findings["overlapping_categories"]

    assert duplicate.vendor_name == "ChatGPT"
    assert duplicate.related_vendors == ("Claude",)
    assert duplicate.estimated_savings_usd == 30.0
    assert duplicate.recommended_action == "consolidate_to_chatgpt"

    assert overlap.vendor_name in {"Claude", "GitHub Copilot"}
    assert overlap.recommended_action == "rationalize_ai_assistants"
    assert overlap.estimated_savings_usd >= 19.0


def test_audit_flags_unused_and_low_frequency_subscriptions() -> None:
    report = audit_subscriptions(
        [
            make_subscription(
                vendor_name="Figma",
                monthly_cost_usd=24.0,
                usage_events_30d=0,
                last_used_at="2026-01-01T12:00:00+00:00",
            ),
            make_subscription(
                vendor_name="Loom",
                monthly_cost_usd=15.0,
                usage_events_30d=2,
                last_used_at="2026-02-14T12:00:00+00:00",
            ),
        ],
        as_of="2026-03-10T12:00:00+00:00",
    )

    findings = {(finding.finding_type, finding.vendor_name): finding for finding in report.findings}

    unused = findings[("unused_subscription", "Figma")]
    low_frequency = findings[("low_frequency_subscription", "Loom")]

    assert unused.recommended_action == "cancel_or_pause"
    assert unused.estimated_savings_usd == 24.0
    assert unused.confidence >= 0.85

    assert low_frequency.recommended_action == "downgrade_or_pause"
    assert low_frequency.estimated_savings_usd == 7.5


def test_audit_detects_annual_switch_candidates() -> None:
    report = audit_subscriptions(
        [
            make_subscription(
                vendor_name="Linear",
                monthly_cost_usd=30.0,
                billing_amount_usd=30.0,
                annual_price_usd=300.0,
                usage_events_30d=18,
            ),
        ]
    )

    finding = next(finding for finding in report.findings if finding.finding_type == "annual_switch_candidate")

    assert finding.vendor_name == "Linear"
    assert finding.recommended_action == "switch_to_annual"
    assert finding.estimated_savings_usd == 5.0
    assert finding.metadata["annual_total_savings_usd"] == 60.0


def test_audit_emits_recurring_merchant_findings_for_untracked_spend() -> None:
    report = audit_subscriptions(
        transactions=[
            {
                "transaction_id": "tx-1",
                "posted_at": "2026-01-11T12:00:00+00:00",
                "amount_usd": -12.0,
                "merchant": "NOTION LABS",
                "description": "Notion Plus",
            },
            {
                "transaction_id": "tx-2",
                "posted_at": "2026-02-10T12:00:00+00:00",
                "amount_usd": -12.0,
                "merchant": "NOTION LABS",
                "description": "Notion Plus",
            },
            {
                "transaction_id": "tx-3",
                "posted_at": "2026-03-12T12:00:00+00:00",
                "amount_usd": -12.0,
                "merchant": "NOTION LABS",
                "description": "Notion Plus",
            },
        ]
    )

    recurring = next(finding for finding in report.findings if finding.finding_type == "recurring_merchant")

    assert recurring.vendor_name == "Notion"
    assert recurring.monthly_cost_usd == 12.0
    assert recurring.recommended_action == "review_and_classify"
    assert recurring.estimated_savings_usd == 0.0
    assert report.monthly_burn_usd == 12.0
