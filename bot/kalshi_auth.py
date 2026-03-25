"""Shared Kalshi credential resolution helpers."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_PLACEHOLDER_TOKENS = (
    "your-kalshi",
    "placeholder",
    "replace-me",
    "changeme",
    "example",
)


def _clean_text(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def _is_placeholder(value: str | None) -> bool:
    text = _clean_text(value).lower()
    if not text:
        return True
    return any(token in text for token in _PLACEHOLDER_TOKENS)


def _normalize_private_key_pem(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if "\\n" in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    if "BEGIN RSA PRIVATE KEY" not in text and "BEGIN PRIVATE KEY" not in text:
        return None
    if not text.endswith("\n"):
        text += "\n"
    return text


def _decode_private_key_b64(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        decoded = base64.b64decode(text).decode("utf-8")
    except Exception:
        return None
    return _normalize_private_key_pem(decoded)


def _candidate_key_paths(env: Mapping[str, str]) -> list[Path]:
    configured = _clean_text(env.get("KALSHI_RSA_KEY_PATH"))
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(__file__).resolve().parents[1] / "bot" / "kalshi" / "kalshi_rsa_private.pem",
        Path(__file__).resolve().parents[1] / "kalshi" / "kalshi_rsa_private.pem",
    ]
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


@dataclass(frozen=True)
class KalshiCredentials:
    api_key_id: str = ""
    private_key_pem: str | None = None
    private_key_source: str | None = None
    private_key_path: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key_id and self.private_key_pem)

    @property
    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not self.private_key_pem:
            missing.append("KALSHI_RSA_PRIVATE_KEY/KALSHI_RSA_PRIVATE_KEY_B64/KALSHI_RSA_KEY_PATH")
        return missing


def load_kalshi_credentials(env: Mapping[str, str] | None = None) -> KalshiCredentials:
    raw_env = env or os.environ
    api_key_id = _clean_text(raw_env.get("KALSHI_API_KEY_ID"))
    if _is_placeholder(api_key_id):
        api_key_id = ""

    inline_pem = _normalize_private_key_pem(raw_env.get("KALSHI_RSA_PRIVATE_KEY"))
    if inline_pem is not None:
        return KalshiCredentials(
            api_key_id=api_key_id,
            private_key_pem=inline_pem,
            private_key_source="env:KALSHI_RSA_PRIVATE_KEY",
        )

    b64_pem = _decode_private_key_b64(raw_env.get("KALSHI_RSA_PRIVATE_KEY_B64"))
    if b64_pem is not None:
        return KalshiCredentials(
            api_key_id=api_key_id,
            private_key_pem=b64_pem,
            private_key_source="env:KALSHI_RSA_PRIVATE_KEY_B64",
        )

    for path in _candidate_key_paths(raw_env):
        if not path.exists():
            continue
        try:
            pem_text = _normalize_private_key_pem(path.read_text(encoding="utf-8"))
        except OSError:
            pem_text = None
        if pem_text is None:
            continue
        return KalshiCredentials(
            api_key_id=api_key_id,
            private_key_pem=pem_text,
            private_key_source=f"path:{path}",
            private_key_path=str(path),
        )

    return KalshiCredentials(api_key_id=api_key_id)
