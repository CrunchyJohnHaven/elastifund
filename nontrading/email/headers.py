"""Helpers for compliant unsubscribe headers."""

from __future__ import annotations


def build_list_unsubscribe_headers(unsubscribe_url: str, mailto_address: str | None = None) -> dict[str, str]:
    values = [f"<{unsubscribe_url}>"]
    if mailto_address:
        values.append(f"<mailto:{mailto_address}?subject=unsubscribe>")
    return {
        "List-Unsubscribe": ", ".join(values),
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }

