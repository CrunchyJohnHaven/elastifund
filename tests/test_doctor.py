from __future__ import annotations

from types import SimpleNamespace

from scripts import doctor
from scripts.doctor import CheckResult, format_results


def test_format_results_aligns_rows():
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


def test_check_optional_command_warns_when_missing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)

    result = doctor.check_optional_command(
        "docker",
        ["docker", "--version"],
        "docker installed",
        "docker not installed",
    )

    assert result.status == "warn"
    assert result.detail == "docker not installed"


def test_check_optional_command_warns_when_binary_errors(monkeypatch):
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
