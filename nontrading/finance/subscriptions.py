"""Subscription and cost-cutting analysis for the finance worker."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from nontrading.finance.models import AuditFinding
from nontrading.finance.recurring import FinanceTransaction, detect_recurring_merchants
from nontrading.finance.store import FinanceStore
from nontrading.finance.vendor_registry import infer_category, normalize_vendor, resolve_vendor

UTC = timezone.utc


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class SubscriptionRecord:
    vendor_name: str
    product_name: str = ""
    status: str = "active"
    monthly_cost_usd: float = 0.0
    billing_amount_usd: float = 0.0
    billing_period: str = "monthly"
    annual_price_usd: float | None = None
    usage_events_30d: int = 0
    last_used_at: str | None = None
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def category(self) -> str:
        return infer_category(self.vendor_name, "", self.product_name)

    @property
    def duplicate_group(self) -> str:
        return resolve_vendor(self.vendor_name, self.product_name).profile.duplicate_group


@dataclass(frozen=True)
class SubscriptionFinding:
    finding_type: str
    vendor_name: str
    related_vendors: tuple[str, ...] = ()
    monthly_cost_usd: float = 0.0
    estimated_savings_usd: float = 0.0
    recommended_action: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_audit_finding(self) -> AuditFinding:
        kind_map = {
            "duplicate_tools": "duplicate_tooling",
            "overlapping_categories": "overlapping_tool_category",
            "unused_subscription": "low_usage_subscription",
            "low_frequency_subscription": "low_usage_subscription",
            "annual_switch_candidate": "annual_savings_candidate",
        }
        return AuditFinding(
            finding_id=f"{self.finding_type}::{normalize_vendor(self.vendor_name)}",
            kind=kind_map.get(self.finding_type, self.finding_type),
            vendor=self.vendor_name,
            category=str(self.metadata.get("category") or ""),
            monthly_cost_usd=self.monthly_cost_usd,
            confidence=self.confidence,
            recommended_action=self.recommended_action,
            estimated_savings_usd=self.estimated_savings_usd,
            rollback=str(self.metadata.get("rollback") or ""),
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class SubscriptionAuditReport:
    findings: tuple[SubscriptionFinding, ...]
    monthly_burn_usd: float
    gaps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [asdict(item) for item in self.findings],
            "gaps": list(self.gaps),
            "summary": {
                "subscription_burn_monthly": self.monthly_burn_usd,
                "cut_candidates_monthly": round(sum(item.estimated_savings_usd for item in self.findings), 2),
                "active_subscriptions": sum(1 for item in self.findings if item.finding_type != "recurring_merchant"),
                "recurring_commitments": sum(1 for item in self.findings if item.finding_type == "recurring_merchant"),
            },
        }


def _coerce_subscription(item: Any) -> SubscriptionRecord:
    if isinstance(item, SubscriptionRecord):
        return item
    if isinstance(item, dict):
        return SubscriptionRecord(**item)
    raise TypeError(f"Unsupported subscription payload: {type(item)!r}")


def _coerce_transaction(item: Any) -> FinanceTransaction:
    if isinstance(item, FinanceTransaction):
        return item
    if isinstance(item, dict):
        return FinanceTransaction(**item)
    raise TypeError(f"Unsupported transaction payload: {type(item)!r}")


def _build_report(
    subscriptions: Iterable[SubscriptionRecord],
    *,
    transactions: Iterable[FinanceTransaction] = (),
    as_of: str | None = None,
) -> SubscriptionAuditReport:
    as_of_dt = _parse_date(as_of) or datetime.now(UTC)
    subscription_list = [item for item in subscriptions if item.status.lower() == "active"]
    findings: list[SubscriptionFinding] = []

    duplicate_groups: dict[str, list[SubscriptionRecord]] = defaultdict(list)
    category_groups: dict[str, list[SubscriptionRecord]] = defaultdict(list)
    for subscription in subscription_list:
        duplicate_groups[subscription.duplicate_group].append(subscription)
        category_groups[subscription.category].append(subscription)

        last_used_at = _parse_date(subscription.last_used_at)
        days_since_last_use = (as_of_dt - last_used_at).days if last_used_at is not None else None
        if subscription.usage_events_30d <= 0 or (days_since_last_use is not None and days_since_last_use >= 45):
            findings.append(
                SubscriptionFinding(
                    finding_type="unused_subscription",
                    vendor_name=subscription.vendor_name,
                    monthly_cost_usd=subscription.monthly_cost_usd,
                    estimated_savings_usd=subscription.monthly_cost_usd,
                    recommended_action="cancel_or_pause",
                    confidence=0.9,
                    metadata={"category": subscription.category},
                )
            )
        elif subscription.usage_events_30d <= 2:
            findings.append(
                SubscriptionFinding(
                    finding_type="low_frequency_subscription",
                    vendor_name=subscription.vendor_name,
                    monthly_cost_usd=subscription.monthly_cost_usd,
                    estimated_savings_usd=round(subscription.monthly_cost_usd * 0.5, 2),
                    recommended_action="downgrade_or_pause",
                    confidence=0.74,
                    metadata={"category": subscription.category},
                )
            )

        if subscription.billing_period == "monthly" and subscription.annual_price_usd:
            annual_total_savings = round(subscription.monthly_cost_usd * 12.0 - subscription.annual_price_usd, 2)
            if annual_total_savings > 0:
                findings.append(
                    SubscriptionFinding(
                        finding_type="annual_switch_candidate",
                        vendor_name=subscription.vendor_name,
                        monthly_cost_usd=subscription.monthly_cost_usd,
                        estimated_savings_usd=round(annual_total_savings / 12.0, 2),
                        recommended_action="switch_to_annual",
                        confidence=0.82,
                        metadata={
                            "category": subscription.category,
                            "annual_total_savings_usd": annual_total_savings,
                        },
                    )
                )

    for group_name, items in duplicate_groups.items():
        if len(items) < 2:
            continue
        sorted_items = sorted(items, key=lambda item: (-item.usage_events_30d, item.monthly_cost_usd, item.vendor_name))
        primary = sorted_items[0]
        related = tuple(item.vendor_name for item in sorted_items[1:])
        savings = round(sum(item.monthly_cost_usd for item in sorted_items[1:]), 2)
        findings.append(
            SubscriptionFinding(
                finding_type="duplicate_tools",
                vendor_name=primary.vendor_name,
                related_vendors=related,
                monthly_cost_usd=primary.monthly_cost_usd,
                estimated_savings_usd=savings,
                recommended_action=f"consolidate_to_{normalize_vendor(primary.vendor_name).replace(' ', '_')}",
                confidence=0.88,
                metadata={"category": primary.category, "duplicate_group": group_name},
            )
        )

    for category_name, items in category_groups.items():
        if len(items) < 2:
            continue
        worst = min(items, key=lambda item: (item.usage_events_30d, item.monthly_cost_usd))
        if category_name == "ai_assistant":
            action = "rationalize_ai_assistants"
        else:
            action = f"rationalize_{category_name}"
        findings.append(
            SubscriptionFinding(
                finding_type="overlapping_categories",
                vendor_name=worst.vendor_name,
                related_vendors=tuple(item.vendor_name for item in items if item.vendor_name != worst.vendor_name),
                monthly_cost_usd=worst.monthly_cost_usd,
                estimated_savings_usd=max(worst.monthly_cost_usd, min(item.monthly_cost_usd for item in items)),
                recommended_action=action,
                confidence=0.7,
                metadata={"category": category_name},
            )
        )

    recurring = detect_recurring_merchants([_coerce_transaction(item) for item in transactions])
    for item in recurring:
        findings.append(
            SubscriptionFinding(
                finding_type="recurring_merchant",
                vendor_name=item.canonical_vendor_name,
                monthly_cost_usd=item.monthly_cost_usd,
                estimated_savings_usd=0.0,
                recommended_action="review_and_classify",
                confidence=item.confidence,
                metadata={"category": item.vendor_category},
            )
        )

    findings = list({(finding.finding_type, finding.vendor_name): finding for finding in findings}.values())
    findings.sort(key=lambda item: (item.estimated_savings_usd, item.confidence), reverse=True)
    monthly_burn_usd = round(
        sum(item.monthly_cost_usd for item in subscription_list) + sum(item.monthly_cost_usd for item in recurring),
        2,
    )
    gaps = ()
    if not subscription_list and not recurring:
        gaps = ("subscriptions_missing", "recurring_commitments_missing")
    return SubscriptionAuditReport(findings=tuple(findings), monthly_burn_usd=monthly_burn_usd, gaps=gaps)


def audit_subscriptions(
    subscriptions_or_store: FinanceStore | Iterable[SubscriptionRecord] | None = None,
    *,
    transactions: Iterable[FinanceTransaction | dict[str, Any]] = (),
    as_of: str | None = None,
) -> SubscriptionAuditReport | dict[str, Any]:
    if isinstance(subscriptions_or_store, FinanceStore):
        subscriptions = [
            SubscriptionRecord(
                vendor_name=item.vendor,
                product_name=item.product_name,
                status=item.status,
                monthly_cost_usd=item.monthly_cost_usd,
                billing_amount_usd=item.monthly_cost_usd,
                billing_period=item.billing_cycle,
                annual_price_usd=(
                    float(item.metadata.get("annual_price_usd"))
                    if item.metadata.get("annual_price_usd") is not None
                    else None
                ),
                usage_events_30d=int(item.metadata.get("usage_events_30d", 0) or 0),
                last_used_at=item.metadata.get("last_used_at"),
                source=item.source,
                metadata=item.metadata,
            )
            for item in subscriptions_or_store.list_subscriptions()
        ]
        txns = list(subscriptions_or_store.list_transactions())
        report = _build_report(subscriptions, transactions=txns, as_of=as_of)
        summary = report.to_dict()
        summary["findings"] = [item.to_audit_finding().to_dict() for item in report.findings]
        return summary

    subscriptions = [_coerce_subscription(item) for item in (subscriptions_or_store or ())]
    txns = [_coerce_transaction(item) for item in transactions]
    return _build_report(subscriptions, transactions=txns, as_of=as_of)
