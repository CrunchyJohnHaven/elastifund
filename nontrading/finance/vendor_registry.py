"""Vendor normalization helpers for finance analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass

VENDOR_CATEGORY_HINTS = {
    "chatgpt": "ai_assistant",
    "claude": "ai_assistant",
    "cursor": "developer_tooling",
    "github": "developer_tooling",
    "linear": "project_management",
    "notion": "knowledge_management",
    "slack": "communication",
    "figma": "design",
    "google workspace": "productivity_suite",
    "dropbox": "storage",
    "aws": "compute",
    "replit": "compute",
    "polymarket": "trading_capital",
    "kalshi": "trading_capital",
    "rent": "housing",
}


@dataclass(frozen=True)
class VendorProfile:
    canonical_name: str
    category: str
    duplicate_group: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class VendorMatch:
    profile: VendorProfile
    confidence: float


DEFAULT_VENDOR_REGISTRY: tuple[VendorProfile, ...] = (
    VendorProfile("ChatGPT", "ai_assistant", "general_llm", aliases=("openai", "chatgpt")),
    VendorProfile("Claude", "ai_assistant", "general_llm", aliases=("anthropic", "claude")),
    VendorProfile("GitHub Copilot", "ai_assistant", "ai_assistant_overlap", aliases=("github copilot", "copilot")),
    VendorProfile("Linear", "project_management", "project_management", aliases=("linear",)),
    VendorProfile("Figma", "design", "design", aliases=("figma",)),
    VendorProfile("Loom", "communication", "communication", aliases=("loom",)),
    VendorProfile("Notion", "knowledge_management", "knowledge_management", aliases=("notion",)),
)


def normalize_vendor(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def resolve_vendor(merchant: str, description: str = "", *, registry: tuple[VendorProfile, ...] = DEFAULT_VENDOR_REGISTRY) -> VendorMatch:
    haystack = normalize_vendor(" ".join(part for part in (merchant, description) if part))
    best_profile = registry[0]
    best_confidence = 0.0
    for profile in registry:
        alias_matches = [
            alias for alias in (profile.canonical_name, *profile.aliases)
            if normalize_vendor(alias) and normalize_vendor(alias) in haystack
        ]
        if not alias_matches:
            continue
        confidence = 0.6 + min(0.35, 0.1 * len(alias_matches))
        if normalize_vendor(profile.canonical_name) in haystack:
            confidence += 0.05
        if confidence > best_confidence:
            best_profile = profile
            best_confidence = confidence
    if best_confidence == 0.0:
        fallback_category = "uncategorized"
        raw_search = f"{merchant} {description}".lower()
        for key, normalized in VENDOR_CATEGORY_HINTS.items():
            if key in raw_search:
                fallback_category = normalized
                break
        best_profile = VendorProfile(
            canonical_name=merchant.strip() or description.strip() or "Unknown",
            category=fallback_category,
            duplicate_group="uncategorized",
        )
        best_confidence = 0.4
    return VendorMatch(profile=best_profile, confidence=min(best_confidence, 0.99))


def infer_category(vendor: str, category: str = "", product_name: str = "") -> str:
    explicit = category.strip().lower()
    if explicit:
        return explicit.replace(" ", "_")
    search = " ".join(part for part in (vendor, product_name) if part).lower()
    resolved = resolve_vendor(vendor, product_name)
    if resolved.confidence >= 0.75 and resolved.profile.category:
        return resolved.profile.category
    for key, normalized in VENDOR_CATEGORY_HINTS.items():
        if key in search:
            return normalized
    return "uncategorized"
