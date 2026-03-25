from __future__ import annotations

import base64
from pathlib import Path

from bot.kalshi_auth import load_kalshi_credentials


_PEM = "-----BEGIN RSA PRIVATE KEY-----\\nabc123\\n-----END RSA PRIVATE KEY-----"


def test_load_kalshi_credentials_accepts_inline_private_key() -> None:
    credentials = load_kalshi_credentials(
        {
            "KALSHI_API_KEY_ID": "real-kalshi-key",
            "KALSHI_RSA_PRIVATE_KEY": _PEM,
        }
    )

    assert credentials.configured is True
    assert credentials.private_key_source == "env:KALSHI_RSA_PRIVATE_KEY"
    assert "BEGIN RSA PRIVATE KEY" in str(credentials.private_key_pem)


def test_load_kalshi_credentials_accepts_base64_private_key() -> None:
    pem = _PEM.replace("\\n", "\n") + "\n"
    credentials = load_kalshi_credentials(
        {
            "KALSHI_API_KEY_ID": "real-kalshi-key",
            "KALSHI_RSA_PRIVATE_KEY_B64": base64.b64encode(pem.encode("utf-8")).decode("ascii"),
        }
    )

    assert credentials.configured is True
    assert credentials.private_key_source == "env:KALSHI_RSA_PRIVATE_KEY_B64"
    assert credentials.private_key_pem == pem


def test_load_kalshi_credentials_falls_back_to_existing_path(tmp_path: Path) -> None:
    key_path = tmp_path / "kalshi.pem"
    key_path.write_text(_PEM.replace("\\n", "\n") + "\n", encoding="utf-8")

    credentials = load_kalshi_credentials(
        {
            "KALSHI_API_KEY_ID": "real-kalshi-key",
            "KALSHI_RSA_KEY_PATH": str(key_path),
        }
    )

    assert credentials.configured is True
    assert credentials.private_key_path == str(key_path)
