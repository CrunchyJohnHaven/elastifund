"""Recurring-spend detection for imported finance transactions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from nontrading.finance.models import FinanceRecurringCommitment, FinanceTransaction
from nontrading.finance.store import FinanceStore
from nontrading.finance.vendor_registry import infer_category, normalize_vendor, resolve_vendor


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class RecurringMerchant:
    canonical_vendor_name: str
    billing_period: str
    monthly_cost_usd: float
    occurrence_count: int
    confidence: float
    transaction_ids: tuple[str, ...]
    vendor_category: str = "uncategorized"


def detect_recurring_merchants(transactions: list[FinanceTransaction]) -> list[RecurringMerchant]:
    grouped: dict[str, list[FinanceTransaction]] = defaultdict(list)
    for transaction in transactions:
        if transaction.amount_usd >= 0:
            continue
        grouped[normalize_vendor(transaction.merchant or transaction.description)].append(transaction)

    commitments: list[RecurringMerchant] = []
    for vendor_key, rows in grouped.items():
        if not vendor_key or len(rows) < 2:
            continue
        sorted_rows = sorted(rows, key=lambda item: _parse_date(item.posted_at))
        intervals = [
            max((_parse_date(sorted_rows[index].posted_at) - _parse_date(sorted_rows[index - 1].posted_at)).days, 0)
            for index in range(1, len(sorted_rows))
        ]
        if not intervals:
            continue
        median_interval = median(intervals)
        if median_interval < 20 or median_interval > 40:
            continue
        median_amount = round(median(abs(item.amount_usd) for item in sorted_rows), 2)
        match = resolve_vendor(sorted_rows[-1].merchant, sorted_rows[-1].description)
        commitments.append(
            RecurringMerchant(
                canonical_vendor_name=match.profile.canonical_name,
                billing_period="monthly",
                monthly_cost_usd=median_amount,
                occurrence_count=len(sorted_rows),
                confidence=max(match.confidence, 0.85 if len(sorted_rows) >= 3 else 0.75),
                transaction_ids=tuple(item.transaction_id for item in sorted_rows),
                vendor_category=match.profile.category,
            )
        )
    return commitments


def detect_recurring_commitments(store: FinanceStore) -> list[FinanceRecurringCommitment]:
    commitments: list[FinanceRecurringCommitment] = []
    for recurring in detect_recurring_merchants(store.list_transactions()):
        vendor_key = normalize_vendor(recurring.canonical_vendor_name)
        category = infer_category(recurring.canonical_vendor_name, recurring.vendor_category)
        commitment = FinanceRecurringCommitment(
            commitment_key=f"recurring::{vendor_key}",
            vendor=recurring.canonical_vendor_name,
            category=category,
            amount_usd=recurring.monthly_cost_usd,
            monthly_cost_usd=recurring.monthly_cost_usd,
            cadence="monthly",
            essential=category in {"housing", "insurance", "utilities"},
            source="transactions",
            metadata={
                "sample_count": recurring.occurrence_count,
                "confidence": recurring.confidence,
                "transaction_ids": list(recurring.transaction_ids),
            },
        )
        store.upsert_recurring_commitment(commitment)
        commitments.append(commitment)
    return commitments
