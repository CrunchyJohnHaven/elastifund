"""Identity helpers for agent bootstrap."""

from __future__ import annotations

import re
import secrets


def generate_agent_id(agent_name: str) -> str:
    slug = slugify(agent_name) or "agent"
    return f"elastifund-{slug}-{secrets.token_hex(3)}"


def generate_secret(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")
