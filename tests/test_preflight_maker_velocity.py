from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.preflight_maker_velocity import (  # noqa: E402
    CheckResult,
    render_console,
    required_env_report,
    run_network_check,
    validate_profile_contract,
)


def _profile_stub(**overrides):
    profile = SimpleNamespace(
        mode=SimpleNamespace(paper_trading=False, allow_order_submission=True),
        market_filters=SimpleNamespace(
            category_priorities={"crypto": 3},
            max_resolution_hours=24.0,
        ),
        risk_limits=SimpleNamespace(
            max_position_usd=10.0,
            kelly_fraction=0.25,
            scan_interval_seconds=30,
        ),
    )
    for section_name, values in overrides.items():
        section = getattr(profile, section_name)
        for key, value in values.items():
            setattr(section, key, value)
    return profile


def test_validate_profile_contract_passes_on_expected_shape() -> None:
    reasons = validate_profile_contract(_profile_stub())
    assert reasons == []


def test_validate_profile_contract_collects_all_reasons() -> None:
    reasons = validate_profile_contract(
        _profile_stub(
            mode={"paper_trading": True, "allow_order_submission": False},
            market_filters={"category_priorities": {"crypto": 0}, "max_resolution_hours": 72.0},
            risk_limits={"max_position_usd": 1.0, "kelly_fraction": 0.0, "scan_interval_seconds": 120},
        )
    )
    assert "paper_trading must be false" in reasons
    assert "allow_order_submission must be true" in reasons
    assert "crypto category priority must be >= 1" in reasons
    assert "max_position_usd must be >= 5.0" in reasons
    assert "kelly_fraction must be > 0" in reasons
    assert "max_resolution_hours must be <= 48" in reasons
    assert "scan_interval_seconds must be <= 60" in reasons


def test_required_env_report_honors_aliases() -> None:
    report = required_env_report(
        {
            "POLYMARKET_PK": "abc",
            "POLYMARKET_FUNDER": "0x123",
            "ANTHROPIC_API_KEY": "sk-ant-1",
        }
    )
    assert report["POLY_PRIVATE_KEY or POLYMARKET_PK"]["present"] is True
    assert report["POLY_PRIVATE_KEY or POLYMARKET_PK"]["satisfied_by"] == "POLYMARKET_PK"
    assert report["POLY_SAFE_ADDRESS or POLYMARKET_FUNDER"]["present"] is True
    assert report["ANTHROPIC_API_KEY"]["present"] is True


def test_network_check_skips_when_wallet_env_missing() -> None:
    env_report = required_env_report({"ANTHROPIC_API_KEY": "sk-ant-1"})
    result = run_network_check(env_report)
    assert result.status == "skip"


def test_render_console_formats_overall_status() -> None:
    checks = [
        CheckResult(name="profile_load", status="green", detail="ok"),
        CheckResult(name="imports", status="red", detail="failed"),
    ]
    output = render_console(checks, go=False)
    assert "[GREEN] profile_load: ok" in output
    assert "[RED] imports: failed" in output
    assert "OVERALL: NO-GO" in output
