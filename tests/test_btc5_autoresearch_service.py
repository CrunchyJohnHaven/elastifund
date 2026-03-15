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

    assert "scripts/run_btc5_autoresearch_cycle_core.py" in text
    assert "--semantic-dedup-index reports/btc5_autoresearch/semantic_dedup_index.json" in text
    assert "--cycles-jsonl reports/autoresearch_cycles.jsonl" in text
    assert "--fill-feedback-state state/btc5_autoresearch_feedback_state.json" in text
    assert "Description=BTC5 Autoresearch Feedback Cycle (Core)" in text


def test_autoresearch_timeout_is_bounded() -> None:
    text = _service_text()
    timer_text = (REPO_ROOT / "deploy" / "btc5-autoresearch.timer").read_text(encoding="utf-8")

    assert "TimeoutStartSec=900" in text
    assert "MemoryMax=8G" in text
    assert "StandardOutput=journal" in text
    assert "OnUnitActiveSec=3h" in timer_text
