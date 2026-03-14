#!/usr/bin/env python3
"""Validation tests for deploy/btc5-autoresearch.service."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO_ROOT / "deploy" / "btc5-autoresearch.service"


def _service_text() -> str:
    return SERVICE_PATH.read_text(encoding="utf-8")


def test_autoresearch_unit_uses_fast_cycle_profile() -> None:
    text = _service_text()

    assert "scripts/btc5_dual_autoresearch_ops.py refresh --write-morning-report" in text
    assert "mkdir -p state reports/autoresearch" in text
    assert "Description=BTC5 Dual Autoresearch Surface Refresh Shim" in text


def test_autoresearch_timeout_is_bounded() -> None:
    text = _service_text()
    timer_text = (REPO_ROOT / "deploy" / "btc5-autoresearch.timer").read_text(encoding="utf-8")

    assert "TimeoutStartSec=300" in text
    assert "StandardOutput=journal" in text
    assert "OnUnitActiveSec=15min" in timer_text
