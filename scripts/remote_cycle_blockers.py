from __future__ import annotations

from typing import Sequence

from scripts.remote_cycle_common import dedupe_preserve_order


def classify_blocker_category(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return "truth"
    if any(
        token in normalized
        for token in (
            "finance",
            "capital",
            "reserve",
            "collateral",
            "whitelist",
            "commitment",
            "deployed",
            "notional",
            "accounting",
        )
    ):
        return "capital"
    if any(
        token in normalized
        for token in (
            "confirmation",
            "wallet_flow_vs_llm",
            "source_window_rows",
            "covered_executed_window_rows",
            "lmsr",
        )
    ):
        return "confirmation"
    if any(
        token in normalized
        for token in (
            "candidate",
            "forecast",
            "promote",
            "runtime_package",
            "trailing_",
            "a6",
            "b1",
            "flywheel",
        )
    ):
        return "candidate"
    return "truth"


def build_blocker_category_map(reasons: Sequence[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {
        "truth": [],
        "candidate": [],
        "confirmation": [],
        "capital": [],
    }
    for reason in reasons:
        category = classify_blocker_category(reason)
        grouped.setdefault(category, []).append(reason)
    for key in list(grouped):
        grouped[key] = dedupe_preserve_order([item for item in grouped[key] if item])
    return grouped
