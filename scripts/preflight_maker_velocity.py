#!/usr/bin/env python3
"""Pre-flight validation for maker_velocity_live deployment."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import py_compile
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.maker_velocity_blitz import evaluate_blitz_launch_ready  # noqa: E402
from config.runtime_profile import RuntimeProfile, RuntimeProfileError, load_runtime_profile  # noqa: E402
from shared.python.envfile import is_placeholder_value, load_env_file  # noqa: E402


IMPORT_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bot.jj_live", ("JJLiveBot", "JJLive")),
    ("bot.ensemble_estimator", ("EnsembleEstimator",)),
    ("bot.vpin_toxicity", ("VPINDetector", "VPINManager")),
    ("bot.ws_trade_stream", ("TradeStreamManager",)),
    ("bot.maker_velocity_blitz", ("evaluate_blitz_launch_ready",)),
    ("bot.btc_5min_maker", ("BTC5MinMakerBot",)),
    ("bot.btc_5min_maker", ("MakerConfig",)),
)

ENV_REQUIREMENTS: tuple[tuple[str, ...], ...] = (
    ("POLY_PRIVATE_KEY", "POLYMARKET_PK"),
    ("POLY_SAFE_ADDRESS", "POLYMARKET_FUNDER"),
    ("ANTHROPIC_API_KEY",),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    payload: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_effective_env(repo_root: Path) -> dict[str, str]:
    env_from_file = load_env_file(repo_root / ".env")
    merged = dict(env_from_file)
    merged.update(os.environ)
    return merged


def _ok(name: str, detail: str, payload: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name=name, status="green", detail=detail, payload=payload)


def _bad(name: str, detail: str, payload: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name=name, status="red", detail=detail, payload=payload)


def _skip(name: str, detail: str, payload: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name=name, status="skip", detail=detail, payload=payload)


def validate_profile_contract(profile: RuntimeProfile) -> list[str]:
    reasons: list[str] = []
    if profile.mode.paper_trading is not False:
        reasons.append("paper_trading must be false")
    if profile.mode.allow_order_submission is not True:
        reasons.append("allow_order_submission must be true")
    if int(profile.market_filters.category_priorities.get("crypto", 0)) < 1:
        reasons.append("crypto category priority must be >= 1")
    if float(profile.risk_limits.max_position_usd) < 5.0:
        reasons.append("max_position_usd must be >= 5.0")
    if float(profile.risk_limits.kelly_fraction) <= 0:
        reasons.append("kelly_fraction must be > 0")
    if float(profile.market_filters.max_resolution_hours) > 48:
        reasons.append("max_resolution_hours must be <= 48")
    if int(profile.risk_limits.scan_interval_seconds) > 60:
        reasons.append("scan_interval_seconds must be <= 60")
    return reasons


def required_env_report(env: dict[str, str]) -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for aliases in ENV_REQUIREMENTS:
        canonical = " or ".join(aliases)
        present_alias = ""
        for key in aliases:
            value = env.get(key)
            if value is not None and not is_placeholder_value(value):
                present_alias = key
                break
        report[canonical] = {
            "present": bool(present_alias),
            "satisfied_by": present_alias,
            "aliases": list(aliases),
        }
    return report


def run_profile_load_check() -> CheckResult:
    try:
        profile = load_runtime_profile(profile_name="maker_velocity_live")
    except RuntimeProfileError as exc:
        return _bad("profile_load", f"failed to load maker_velocity_live: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        return _bad("profile_load", f"unexpected profile load error: {exc}")

    payload = {
        "paper_trading": profile.mode.paper_trading,
        "allow_order_submission": profile.mode.allow_order_submission,
        "execution_mode": profile.mode.execution_mode,
        "crypto_priority": int(profile.market_filters.category_priorities.get("crypto", 0)),
        "max_position_usd": profile.risk_limits.max_position_usd,
        "daily_loss_usd": profile.risk_limits.max_daily_loss_usd,
        "kelly_fraction": profile.risk_limits.kelly_fraction,
        "max_open_positions": profile.risk_limits.max_open_positions,
        "scan_interval_seconds": profile.risk_limits.scan_interval_seconds,
        "max_resolution_hours": profile.market_filters.max_resolution_hours,
    }
    return _ok("profile_load", "maker_velocity_live profile loaded", payload)


def run_env_check(env: dict[str, str]) -> CheckResult:
    report = required_env_report(env)
    missing = [name for name, status in report.items() if not status["present"]]
    if missing:
        return _bad("env_vars", f"missing required envs: {', '.join(missing)}", payload=report)
    return _ok("env_vars", "required env vars present", payload=report)


def run_import_check() -> CheckResult:
    errors: list[str] = []
    imported: list[str] = []
    for module_name, symbol_names in IMPORT_TARGETS:
        try:
            module = importlib.import_module(module_name)
            resolved = ""
            for symbol_name in symbol_names:
                if hasattr(module, symbol_name):
                    getattr(module, symbol_name)
                    resolved = symbol_name
                    break
            if not resolved:
                errors.append(f"{module_name}.{ '|'.join(symbol_names)}: symbol_missing")
                continue
            imported.append(f"{module_name}.{resolved}")
        except Exception as exc:
            errors.append(f"{module_name}.{ '|'.join(symbol_names)}: {exc}")
    if errors:
        return _bad("imports", "; ".join(errors), payload={"ok": imported, "errors": errors})
    return _ok("imports", f"validated {len(imported)} imports", payload={"ok": imported})


def run_syntax_check(repo_root: Path) -> CheckResult:
    py_files = sorted((repo_root / "bot").glob("*.py"))
    errors: list[str] = []
    for path in py_files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{path.name}: {exc.msg}")
    payload = {"checked_files": [str(path) for path in py_files], "checked_count": len(py_files)}
    if errors:
        payload["errors"] = errors
        return _bad("syntax_bot", f"{len(errors)} bot files failed syntax check", payload=payload)
    return _ok("syntax_bot", f"compiled {len(py_files)} bot files", payload=payload)


def run_profile_contract_check() -> CheckResult:
    try:
        profile = load_runtime_profile(profile_name="maker_velocity_live")
    except Exception as exc:
        return _bad("profile_contract", f"could not load profile for contract validation: {exc}")
    reasons = validate_profile_contract(profile)
    if reasons:
        return _bad("profile_contract", "; ".join(reasons))
    return _ok("profile_contract", "profile contract checks passed")


def run_launch_gate_check(repo_root: Path) -> CheckResult:
    reports_dir = repo_root / "reports"
    try:
        cycle = json.loads((reports_dir / "remote_cycle_status.json").read_text())
        service = json.loads((reports_dir / "remote_service_status.json").read_text())
        state = json.loads((repo_root / "jj_state.json").read_text())
    except OSError as exc:
        return _bad("launch_gate", f"missing runtime artifact: {exc}")
    except json.JSONDecodeError as exc:
        return _bad("launch_gate", f"invalid runtime artifact json: {exc}")

    decision = evaluate_blitz_launch_ready(
        remote_cycle_status=cycle,
        remote_service_status=service,
        jj_state=state,
    )
    payload = {
        "launch_go": decision.launch_go,
        "checks": decision.checks,
        "blocked_reasons": list(decision.blocked_reasons),
        "source_of_truth": decision.source_of_truth,
    }
    if decision.launch_go:
        return _ok("launch_gate", "launch gate check is GO", payload=payload)
    return _bad("launch_gate", f"launch gate blocked: {', '.join(decision.blocked_reasons)}", payload=payload)


def run_network_check(env_report: dict[str, dict[str, Any]], timeout_seconds: float = 5.0) -> CheckResult:
    wallet_keys_present = bool(
        env_report["POLY_PRIVATE_KEY or POLYMARKET_PK"]["present"]
        and env_report["POLY_SAFE_ADDRESS or POLYMARKET_FUNDER"]["present"]
    )
    if not wallet_keys_present:
        return _skip("network", "skipped network check (wallet env not configured)")

    url = "https://gamma-api.polymarket.com/markets?limit=1"
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            status_code = int(getattr(response, "status", 0))
            if status_code == 200:
                return _ok("network", "gamma api reachable (200)", payload={"url": url, "status_code": status_code})
            return _bad("network", f"unexpected gamma api status: {status_code}", payload={"url": url, "status_code": status_code})
    except URLError as exc:
        return _bad("network", f"gamma api unreachable: {exc}", payload={"url": url})
    except Exception as exc:  # pragma: no cover - defensive
        return _bad("network", f"gamma api check error: {exc}", payload={"url": url})


def evaluate_preflight(repo_root: Path, skip_network: bool = False) -> tuple[list[CheckResult], bool]:
    env = _load_effective_env(repo_root)
    checks: list[CheckResult] = []
    checks.append(run_profile_load_check())
    env_check = run_env_check(env)
    checks.append(env_check)
    env_report = env_check.payload if isinstance(env_check.payload, dict) else required_env_report(env)
    checks.append(run_import_check())
    checks.append(run_syntax_check(repo_root))
    checks.append(run_profile_contract_check())
    checks.append(run_launch_gate_check(repo_root))
    if skip_network:
        checks.append(_skip("network", "skipped by --skip-network"))
    else:
        checks.append(run_network_check(env_report))

    go = all(check.status in {"green", "skip"} for check in checks)
    return checks, go


def render_console(checks: list[CheckResult], go: bool) -> str:
    lines = []
    for check in checks:
        color = {"green": "GREEN", "red": "RED", "skip": "SKIP"}[check.status]
        lines.append(f"[{color}] {check.name}: {check.detail}")
    lines.append("")
    lines.append(f"OVERALL: {'GO' if go else 'NO-GO'}")
    return "\n".join(lines)


def write_artifact(output_path: Path, checks: list[CheckResult], go: bool) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now_iso(),
        "profile": "maker_velocity_live",
        "overall": "GO" if go else "NO-GO",
        "checks": [asdict(check) for check in checks],
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pre-flight validation for maker_velocity_live deployment.")
    parser.add_argument(
        "--repo-root",
        default=str(ROOT),
        help="Repository root path.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "reports" / "preflight_maker_velocity.json"),
        help="Output JSON artifact path.",
    )
    parser.add_argument(
        "--skip-network",
        action="store_true",
        help="Skip external Gamma API reachability check.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    checks, go = evaluate_preflight(repo_root, skip_network=bool(args.skip_network))
    artifact = write_artifact(Path(args.output).expanduser().resolve(), checks, go)
    print(render_console(checks, go))
    print("")
    print(artifact)
    return 0 if go else 2


if __name__ == "__main__":
    raise SystemExit(main())
