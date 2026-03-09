#!/usr/bin/env python3
"""Validation tests for deploy/btc-5min-maker.service."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO_ROOT / "deploy" / "btc-5min-maker.service"


def _load_service() -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(SERVICE_PATH, encoding="utf-8")
    return parser


def test_service_file_has_required_sections_and_keys() -> None:
    parser = _load_service()

    assert parser.has_section("Unit")
    assert parser.has_option("Unit", "Description")
    assert parser.has_option("Unit", "After")
    assert parser.has_section("Service")
    assert parser.has_option("Service", "WorkingDirectory")
    assert parser.has_option("Service", "EnvironmentFile")
    assert parser.has_option("Service", "ExecStart")
    assert parser.has_section("Install")
    assert parser.get("Install", "WantedBy") == "multi-user.target"


def test_execstart_targets_btc_5min_maker_entrypoint() -> None:
    parser = _load_service()
    exec_start = parser.get("Service", "ExecStart")

    assert "/usr/bin/python3" in exec_start
    assert "bot/btc_5min_maker.py" in exec_start
    assert "--continuous" in exec_start
    assert "--live" in exec_start


def test_working_directory_matches_environment_file_root() -> None:
    parser = _load_service()
    working_dir = parser.get("Service", "WorkingDirectory").rstrip("/")
    env_file = parser.get("Service", "EnvironmentFile")

    assert env_file == f"{working_dir}/.env"
