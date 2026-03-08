"""Small helpers for reading and updating dotenv-style files."""

from __future__ import annotations

import re
from pathlib import Path

ENV_KEY_RE = re.compile(r"^\s*([A-Z0-9_]+)\s*=")

PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "local-bootstrap-token",
    "none",
    "change-this-elastic-password",
    "change-this-kibana-password",
    "replace-with-a-32-char-minimum-key",
    "replace-me-generated-by-setup",
    "your-api-key-here",
    "your-api-secret-here",
    "your-api-passphrase-here",
    "your-private-key-here-without-0x-prefix",
    "your-anthropic-api-key-here",
    "your-openai-api-key-here",
    "your-groq-api-key-here",
    "xai-your-key-here",
    "0xyourpolymarketwalletaddress",
    "unsubscribe@example.invalid",
    "partnerships@example.invalid",
    "https://example.invalid",
}

PLACEHOLDER_PREFIXES = (
    "change-this-",
    "replace-me",
    "replace-with-",
    "your-",
    "example",
    "0xyour",
    "placeholder",
)


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        if not raw_line or raw_line.lstrip().startswith("#"):
            continue
        match = ENV_KEY_RE.match(raw_line)
        if not match:
            continue
        key = match.group(1)
        _, raw_value = raw_line.split("=", 1)
        values[key] = _strip_quotes(raw_value.strip())
    return values


def write_env_file(path: Path, template_path: Path, updates: dict[str, str]) -> None:
    base_path = path if path.exists() else template_path
    text = base_path.read_text() if base_path.exists() else ""
    path.write_text(apply_env_updates(text, updates))


def apply_env_updates(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen: set[str] = set()
    rendered: list[str] = []

    for line in lines:
        match = ENV_KEY_RE.match(line)
        if not match:
            rendered.append(line)
            continue
        key = match.group(1)
        if key in updates:
            rendered.append(f"{key}={format_env_value(updates[key])}")
            seen.add(key)
        else:
            rendered.append(line)

    missing = [key for key in updates if key not in seen]
    if missing:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# ===========================================")
        rendered.append("# Elastifund fork-and-run onboarding")
        rendered.append("# ===========================================")
        for key in missing:
            rendered.append(f"{key}={format_env_value(updates[key])}")
    rendered.append("")
    return "\n".join(rendered)


def format_env_value(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "":
        return ""
    if any(char.isspace() for char in text) or "#" in text or '"' in text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def is_placeholder_value(value: str | None) -> bool:
    if value is None:
        return True
    normalized = _strip_quotes(value.strip()).lower()
    if normalized in PLACEHOLDER_VALUES:
        return True
    return any(normalized.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
