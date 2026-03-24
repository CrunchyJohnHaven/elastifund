from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import doctor
from scripts.doctor import CheckResult, format_results


def test_format_results_aligns_rows() -> None:
    rendered = format_results(
        [
            CheckResult("python", "pass", "3.14.3"),
            CheckResult("docker_compose", "warn", "missing"),
        ]
    )

    assert "python" in rendered
    assert "docker_compose" in rendered
    assert "PASS" in rendered
    assert "WARN" in rendered


def test_check_optional_command_warns_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)

    result = doctor.check_optional_command(
        "docker",
        ["docker", "--version"],
        "docker installed",
        "docker not installed",
    )

    assert result.status == "warn"
    assert result.detail == "docker not installed"


def test_check_optional_command_warns_when_binary_errors(monkeypatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="compose failed", stdout=""),
    )

    result = doctor.check_optional_command(
        "docker_compose",
        ["docker", "compose", "version"],
        "docker compose available",
        "docker compose unavailable",
    )

    assert result.status == "warn"
    assert result.detail == "compose failed"


def test_check_preflight_warns_when_only_digital_products_fail(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)

    class _Result:
        returncode = 1
        stdout = (
            "agent_identity       PASS   ok\n"
            "digital_products     FAIL   Etsy and/or LLM credentials still placeholder\n"
        )
        stderr = ""

    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: _Result())

    result = doctor.check_preflight()

    assert result.status == "warn"
    assert result.name == "preflight"
    assert "digital_products" in result.detail


def test_check_preflight_fails_for_non_digital_failures(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)

    class _Result:
        returncode = 1
        stdout = "trading_credentials  FAIL   Polymarket credentials still placeholder\n"
        stderr = ""

    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: _Result())

    result = doctor.check_preflight()

    assert result.status == "fail"
    assert "trading_credentials" in result.detail
