from __future__ import annotations

from pathlib import Path

import pytest

from nontrading.config import RevenueAgentSettings
from nontrading.main import RuntimeSafetyError, build_runtime


def test_live_provider_blocks_placeholder_sender_domain(tmp_path: Path) -> None:
    settings = RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        provider="sendgrid",
        sendgrid_api_key="test-key",
        from_email="ops@example.invalid",
    )

    with pytest.raises(RuntimeSafetyError):
        build_runtime(settings, dry_run=False)


def test_dry_run_allows_placeholder_sender_domain(tmp_path: Path) -> None:
    settings = RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        from_email="ops@example.invalid",
    )

    _, pipeline = build_runtime(settings, dry_run=True)
    assert pipeline.run_mode == "sim"
