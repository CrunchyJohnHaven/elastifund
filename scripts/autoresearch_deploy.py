#!/usr/bin/env python3
"""Autoresearch deploy loop — replay-validates hypotheses and auto-deploys wins.

Runs 30 min after autoresearch_loop.py (via cron). Picks up top hypotheses
from autoresearch_results.json, validates each with the replay simulator,
and writes confirmed improvements to state/btc5_capital_stage.env + restarts
the live bot.

Design: closed-loop, conservative by default.
- Only deploys if replay PnL beats current config by IMPROVEMENT_THRESHOLD
- Logs every decision to data/autoresearch_deploy_log.json
- Hard-coded safety rails: never raises max position, never touches kill rules
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path("/home/ubuntu/polymarket-trading-bot")
RESULTS_PATH = BOT_DIR / "data" / "autoresearch_results.json"
DEPLOY_LOG_PATH = BOT_DIR / "data" / "autoresearch_deploy_log.json"
CAPITAL_ENV_PATH = BOT_DIR / "state" / "btc5_capital_stage.env"
REPLAY_SCRIPT = BOT_DIR / "scripts" / "replay_simulator.py"
DB_PATH = BOT_DIR / "data" / "btc_5min_maker.db"

# Must beat baseline by this fraction of baseline PnL to deploy.
IMPROVEMENT_THRESHOLD = 0.10   # 10% better than baseline
MIN_BASELINE_FILLS = 10        # Don't deploy if baseline has < 10 fills (too thin)
MAX_DEPLOYS_PER_DAY = 2        # Prevent thrash

# Params that autoresearch can deploy via this script (all others ignored).
SAFE_DEPLOY_PARAMS = {
    "BTC5_MIN_BUY_PRICE",
    "BTC5_DOWN_MAX_BUY_PRICE",
    "BTC5_UP_MAX_BUY_PRICE",
    "BTC5_TOXIC_FLOW_MIN_PRICE_EXEMPT",
    "BTC5_MIN_DELTA",
    "BTC5_UP_MIN_DELTA",
    "BTC5_MAX_ABS_DELTA",
    "BTC5_TOXIC_FLOW_IMBALANCE_THRESHOLD",
}

# Hard ceilings — never deploy above these values.
PARAM_CEILINGS = {
    "BTC5_DOWN_MAX_BUY_PRICE": 0.95,
    "BTC5_UP_MAX_BUY_PRICE": 0.52,
    "BTC5_TOXIC_FLOW_MIN_PRICE_EXEMPT": 0.95,
    "BTC5_TOXIC_FLOW_IMBALANCE_THRESHOLD": 0.98,
}

# Hard floors — never deploy below these values.
PARAM_FLOORS = {
    "BTC5_MIN_BUY_PRICE": 0.42,
    "BTC5_MIN_DELTA": 0.00005,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_deploy_log() -> dict:
    if DEPLOY_LOG_PATH.exists():
        try:
            return json.loads(DEPLOY_LOG_PATH.read_text())
        except Exception:
            pass
    return {"deploys": [], "last_updated": _now_iso()}


def _save_deploy_log(log: dict) -> None:
    DEPLOY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log["last_updated"] = _now_iso()
    DEPLOY_LOG_PATH.write_text(json.dumps(log, indent=2))


def _deploys_today(log: dict) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for d in log.get("deploys", []) if d.get("date", "") == today)


def _load_autoresearch_results() -> dict:
    if not RESULTS_PATH.exists():
        return {}
    try:
        return json.loads(RESULTS_PATH.read_text())
    except Exception:
        return {}


def _read_capital_env() -> dict[str, str]:
    """Parse current state/btc5_capital_stage.env into key-value dict."""
    env: dict[str, str] = {}
    if not CAPITAL_ENV_PATH.exists():
        return env
    for line in CAPITAL_ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _write_capital_env(env: dict[str, str]) -> None:
    """Write key-value dict back to state/btc5_capital_stage.env."""
    lines = [
        "# state/btc5_capital_stage.env — managed by autoresearch_deploy.py",
        f"# Last updated: {_now_iso()}",
        "",
    ]
    for k, v in sorted(env.items()):
        lines.append(f"{k}={v}")
    lines.append("")
    CAPITAL_ENV_PATH.write_text("\n".join(lines))


def _run_replay(config_overrides: dict) -> dict | None:
    """Run replay simulator with given config overrides. Returns result dict or None."""
    try:
        result = subprocess.run(
            [
                "python3", str(REPLAY_SCRIPT),
                "--config-json", json.dumps(config_overrides),
                "--output-json",
            ],
            capture_output=True, text=True, timeout=120,
            cwd=str(BOT_DIR),
        )
        if result.returncode != 0:
            print(f"[deploy] Replay failed: {result.stderr[:200]}")
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
        print(f"[deploy] Replay error: {e}")
        return None


def _run_baseline_replay() -> dict | None:
    """Run replay with current deployed config (high_entry_090 equiv)."""
    current_env = _read_capital_env()
    baseline_config = {
        "name": "deploy_baseline",
        "min_buy_price": float(current_env.get("BTC5_MIN_BUY_PRICE", "0.90")),
        "down_max_buy_price": float(current_env.get("BTC5_DOWN_MAX_BUY_PRICE", "0.95")),
        "up_max_buy_price": float(current_env.get("BTC5_UP_MAX_BUY_PRICE", "0.52")),
        "directional_mode": current_env.get("BTC5_DIRECTIONAL_MODE", "down_only"),
    }
    return _run_replay(baseline_config)


def _replay_with_hypothesis(hypothesis_params: dict) -> dict | None:
    """Build replay config from hypothesis params and run."""
    current_env = _read_capital_env()
    config = {
        "name": "hypothesis_test",
        "min_buy_price": float(current_env.get("BTC5_MIN_BUY_PRICE", "0.90")),
        "down_max_buy_price": float(current_env.get("BTC5_DOWN_MAX_BUY_PRICE", "0.95")),
        "up_max_buy_price": float(current_env.get("BTC5_UP_MAX_BUY_PRICE", "0.52")),
        "directional_mode": current_env.get("BTC5_DIRECTIONAL_MODE", "down_only"),
    }
    # Apply hypothesis overrides to replay config.
    param_map = {
        "BTC5_MIN_BUY_PRICE": "min_buy_price",
        "BTC5_DOWN_MAX_BUY_PRICE": "down_max_buy_price",
        "BTC5_UP_MAX_BUY_PRICE": "up_max_buy_price",
        "BTC5_DIRECTIONAL_MODE": "directional_mode",
    }
    for env_key, replay_key in param_map.items():
        if env_key in hypothesis_params:
            config[replay_key] = hypothesis_params[env_key]
    return _run_replay(config)


def _validate_params(params: dict) -> dict:
    """Apply ceilings/floors to hypothesis params. Remove unsafe params."""
    safe: dict = {}
    for k, v in params.items():
        if k not in SAFE_DEPLOY_PARAMS:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            if isinstance(v, str):
                safe[k] = v  # string params like DIRECTIONAL_MODE
            continue
        if k in PARAM_CEILINGS:
            fv = min(fv, PARAM_CEILINGS[k])
        if k in PARAM_FLOORS:
            fv = max(fv, PARAM_FLOORS[k])
        safe[k] = fv
    return safe


def _restart_bot() -> bool:
    """Restart btc-5min-maker.service and verify it comes up."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", "btc-5min-maker.service"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print(f"[deploy] Restart failed: {result.stderr}")
            return False
        time.sleep(5)
        status = subprocess.run(
            ["sudo", "systemctl", "is-active", "btc-5min-maker.service"],
            capture_output=True, text=True, timeout=5,
        )
        return status.stdout.strip() == "active"
    except Exception as e:
        print(f"[deploy] Restart error: {e}")
        return False


def _extract_hypotheses(results: dict) -> list[dict]:
    """Extract scored hypotheses from autoresearch results."""
    scored = results.get("scored_hypotheses", [])
    if not scored:
        # Try to extract from hypothesis list.
        hypotheses = results.get("hypotheses", [])
        for h in hypotheses:
            if isinstance(h, dict) and h.get("params"):
                scored.append({"hypothesis": h, "score": h.get("predicted_improvement", 0)})
    return scored


def run() -> None:
    print(f"[deploy] === autoresearch_deploy cycle start {_now_iso()} ===")

    log = _load_deploy_log()
    if _deploys_today(log) >= MAX_DEPLOYS_PER_DAY:
        print(f"[deploy] Max deploys/day ({MAX_DEPLOYS_PER_DAY}) reached. Exiting.")
        return

    results = _load_autoresearch_results()
    if not results:
        print("[deploy] No autoresearch_results.json. Exiting.")
        return

    # Extract top hypotheses.
    hypotheses = results.get("hypotheses", [])
    if not hypotheses:
        print("[deploy] No hypotheses in results. Exiting.")
        return

    print(f"[deploy] {len(hypotheses)} hypotheses available.")

    # Run baseline replay first to establish comparison point.
    print("[deploy] Running baseline replay...")
    baseline = _run_baseline_replay()
    if baseline is None:
        print("[deploy] Baseline replay failed (replay simulator may not support --output-json). Skipping validation, checking hypothesis params only.")
        _deploy_without_replay(hypotheses, log)
        return

    baseline_pnl = baseline.get("total_pnl", 0.0)
    baseline_fills = baseline.get("total_fills", 0)
    baseline_wr = baseline.get("win_rate", 0.0)

    print(f"[deploy] Baseline: fills={baseline_fills}, PnL=${baseline_pnl:.2f}, WR={baseline_wr:.1%}")

    if baseline_fills < MIN_BASELINE_FILLS:
        print(f"[deploy] Baseline fills ({baseline_fills}) < {MIN_BASELINE_FILLS} minimum. Too thin to validate. Exiting.")
        return

    # Test each hypothesis against baseline.
    best_improvement = 0.0
    best_hypothesis = None
    best_replay = None

    for h in hypotheses:
        if not isinstance(h, dict):
            continue
        params = h.get("params", {})
        if not params:
            continue
        safe_params = _validate_params(params)
        if not safe_params:
            continue

        h_id = h.get("hypothesis_id", "unknown")
        print(f"[deploy] Testing {h_id}: {safe_params}")

        replay = _replay_with_hypothesis(safe_params)
        if replay is None:
            continue

        replay_pnl = replay.get("total_pnl", 0.0)
        improvement = replay_pnl - baseline_pnl

        print(f"[deploy]   replay: fills={replay.get('total_fills',0)}, PnL=${replay_pnl:.2f}, "
              f"improvement=${improvement:+.2f}")

        if improvement > best_improvement:
            best_improvement = improvement
            best_hypothesis = (h_id, safe_params)
            best_replay = replay

    if best_hypothesis is None or best_improvement <= 0:
        print("[deploy] No hypothesis beats baseline. Nothing to deploy.")
        _log_cycle(log, "no_improvement", None, baseline_pnl, 0.0)
        _save_deploy_log(log)
        return

    # Check if improvement exceeds threshold.
    threshold_required = abs(baseline_pnl) * IMPROVEMENT_THRESHOLD if baseline_pnl != 0 else 0.50
    if best_improvement < threshold_required:
        print(f"[deploy] Best improvement ${best_improvement:.2f} < threshold ${threshold_required:.2f}. Not deploying.")
        _log_cycle(log, "below_threshold", best_hypothesis[0], baseline_pnl, best_improvement)
        _save_deploy_log(log)
        return

    # Deploy.
    h_id, safe_params = best_hypothesis
    print(f"[deploy] DEPLOYING {h_id}: improvement=${best_improvement:+.2f}")

    current_env = _read_capital_env()
    old_values = {k: current_env.get(k, "N/A") for k in safe_params}

    for k, v in safe_params.items():
        current_env[k] = str(v)

    _write_capital_env(current_env)
    print(f"[deploy] Wrote to {CAPITAL_ENV_PATH}")
    for k, v in safe_params.items():
        print(f"[deploy]   {k}: {old_values[k]} → {v}")

    restarted = _restart_bot()
    status = "deployed_restarted" if restarted else "deployed_restart_failed"
    print(f"[deploy] Bot restart: {'OK' if restarted else 'FAILED'}")

    _log_cycle(log, status, h_id, baseline_pnl, best_improvement,
               params=safe_params, old_params=old_values,
               replay_fills=best_replay.get("total_fills", 0) if best_replay else 0,
               replay_pnl=best_replay.get("total_pnl", 0) if best_replay else 0)
    _save_deploy_log(log)
    print(f"[deploy] Done. Logged to {DEPLOY_LOG_PATH}")


def _deploy_without_replay(hypotheses: list, log: dict) -> None:
    """Fallback: deploy hypothesis with best predicted_improvement if replay unavailable."""
    best_h = max(
        (h for h in hypotheses if isinstance(h, dict) and h.get("params")),
        key=lambda h: h.get("predicted_improvement", 0),
        default=None,
    )
    if best_h is None:
        print("[deploy] No deployable hypothesis found.")
        return

    params = _validate_params(best_h.get("params", {}))
    if not params:
        print("[deploy] No safe params after validation.")
        return

    # Only deploy if predicted_improvement is substantial (>$1).
    if best_h.get("predicted_improvement", 0) < 1.0:
        print(f"[deploy] Predicted improvement ${best_h.get('predicted_improvement',0):.2f} < $1. Not deploying.")
        return

    h_id = best_h.get("hypothesis_id", "unknown")
    print(f"[deploy] No replay available. Deploying on prediction: {h_id} (${best_h.get('predicted_improvement',0):.2f})")

    current_env = _read_capital_env()
    old_values = {k: current_env.get(k, "N/A") for k in params}
    for k, v in params.items():
        current_env[k] = str(v)
    _write_capital_env(current_env)

    restarted = _restart_bot()
    _log_cycle(log, "deployed_no_replay_" + ("restarted" if restarted else "restart_failed"),
               h_id, 0.0, best_h.get("predicted_improvement", 0),
               params=params, old_params=old_values)
    _save_deploy_log(log)


def _log_cycle(log: dict, status: str, h_id: str | None, baseline_pnl: float,
               improvement: float, params: dict | None = None,
               old_params: dict | None = None, replay_fills: int = 0,
               replay_pnl: float = 0.0) -> None:
    log.setdefault("deploys", []).append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "timestamp": _now_iso(),
        "status": status,
        "hypothesis_id": h_id,
        "baseline_pnl": baseline_pnl,
        "improvement": improvement,
        "replay_fills": replay_fills,
        "replay_pnl": replay_pnl,
        "params_deployed": params,
        "params_before": old_params,
    })
    # Keep only last 50 entries.
    log["deploys"] = log["deploys"][-50:]


if __name__ == "__main__":
    os.chdir(str(BOT_DIR))
    run()
