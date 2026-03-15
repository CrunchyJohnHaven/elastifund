"""Config-driven automation entrypoint for flywheel cycle packets."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from hashlib import sha256

from data_layer import database

from inventory.metrics.evidence_plane import _coalesce_float
from .bridge import build_cycle_packet_from_bot_db
from .contracts import CyclePacket
from .runner import DEFAULT_ARTIFACT_ROOT, run_cycle


def load_config(path: str | Path) -> dict[str, Any]:
    """Load an automation config file from JSON."""

    return json.loads(Path(path).read_text())


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _safe_text(value: object) -> str:
    text = str(value or "").strip()
    return text


def _safe_float(value: object) -> float | None:
    return _coalesce_float(value)


def _safe_iso_age_minutes(value: object) -> float | None:
    raw = _safe_text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - parsed).total_seconds() / 60.0, 0.0)
    except Exception:
        return None


def _is_fresh(age_minutes: float | None, max_age_minutes: float | None) -> bool:
    if age_minutes is None:
        return False
    if max_age_minutes is None:
        return True
    return age_minutes <= max_age_minutes


def _build_backlog_candidate_snapshot(candidate: dict[str, Any], *, control: dict[str, Any]) -> dict[str, Any]:
    packet_timestamp = str(candidate["packet_timestamp"])
    packet_age_minutes = _safe_iso_age_minutes(candidate.get("packet_timestamp"))
    openclaw_age_minutes = _safe_float(control.get("openclaw_age_minutes"))
    return {
        "snapshot_date": packet_timestamp.split("T")[0],
        "starting_bankroll": 0.0,
        "ending_bankroll": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "open_positions": 0,
        "closed_trades": 0,
        "win_rate": _safe_float(candidate.get("candidate_confidence")),
        "fill_rate": 1.0,
        "avg_slippage_bps": 0.0,
        "rolling_brier": 0.22,
        "rolling_ece": 0.0,
        "max_drawdown_pct": 0.0,
        "kill_events": 0,
        "metrics": {
            **{k: v for k, v in candidate.items() if v is not None},
            "control_context": control,
            "candidate_source": "openclaw",
            "comparison_only": True,
            "backlog_candidate": True,
            "packet_age_minutes": packet_age_minutes,
            "openclaw_age_minutes": openclaw_age_minutes,
            "expected_arr_delta": _safe_float(candidate.get("expected_arr_delta")),
            "expected_improvement_velocity": _safe_float(candidate.get("improvement_velocity")),
            "candidate_confidence": _safe_float(candidate.get("candidate_confidence")),
            "data_timestamp": candidate.get("data_timestamp"),
            "pipeline_version": candidate.get("pipeline_version"),
            "data_fresh": not bool(control.get("read_only")),
        },
    }


def _build_backlog_strategies_from_openclaw(
    packet: dict[str, Any],
    control: dict[str, Any],
) -> list[dict[str, Any]]:
    comparisons = packet.get("outcome_comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        return []

    packet_run_id = str(packet.get("run_id") or "").strip() or "openclaw-latest"
    packet_timestamp = str(
        packet.get("finished_at")
        or packet.get("started_at")
        or packet.get("captured_at")
        or datetime.now(timezone.utc).isoformat()
    )
    source = str(packet.get("source") or "openclaw").strip() or "openclaw"
    stale_reasons = list(control.get("stale_reasons") or [])
    packet_age_minutes = _safe_iso_age_minutes(packet_timestamp)
    min_arr_improvement_bps = control.get("max_arr_improvement_bps", 0.0)
    openclaw_age_limit = control.get("openclaw_data_age_minutes", 120.0)
    if not _is_fresh(packet_age_minutes, openclaw_age_limit):
        stale_reasons.append("openclaw_packet_stale")
    defaults = {
        "source": source,
        "pipeline_version": packet.get("pipeline_version"),
        "packet_timestamp": packet_timestamp,
        "packet_run_id": packet_run_id,
        "data_timestamp": packet.get("data_timestamp"),
        "source_artifact": packet.get("source_artifacts")[0]
        if isinstance(packet.get("source_artifacts"), list) and packet.get("source_artifacts")
        else None,
    }

    best_by_key: dict[tuple[str, str, str, str], tuple[float, dict[str, Any]]] = {}
    for raw in comparisons:
        if not isinstance(raw, dict):
            continue
        strategy_id = _safe_text(raw.get("strategy_id") or raw.get("case_id") or raw.get("market_id") or raw.get("id"))
        market_hash = _safe_text(raw.get("market_hash") or raw.get("case_id") or strategy_id)
        if not strategy_id:
            continue
        arr_delta = _safe_float(raw.get("expected_arr_delta"))
        confidence = _safe_float(raw.get("candidate_confidence"))
        improvement_velocity = _safe_float(raw.get("improvement_velocity"))
        if arr_delta is None:
            arr_delta = _safe_float(packet.get("expected_arr_delta"))
        if confidence is None:
            confidence = _safe_float(packet.get("candidate_confidence"))
        if improvement_velocity is None:
            improvement_velocity = _safe_float(packet.get("improvement_velocity"))
        if packet.get("data_timestamp") is not None:
            candidate_data_timestamp = _safe_text(packet.get("data_timestamp"))
        else:
            candidate_data_timestamp = _safe_text(raw.get("data_timestamp"))
        if packet.get("pipeline_version") is not None:
            candidate_pipeline_version = _safe_text(packet.get("pipeline_version"))
        else:
            candidate_pipeline_version = _safe_text(control.get("pipeline_version"))

        if stale_reasons:
            continue
        if min_arr_improvement_bps > 0 and (arr_delta is None or arr_delta < min_arr_improvement_bps):
            continue
        key = (
            strategy_id,
            source,
            packet_timestamp,
            market_hash,
        )
        score = round((arr_delta or 0.0) * 100 + (confidence or 0.0) * 10, 6)
        existing = best_by_key.get(key)
        if existing is None or score > existing[0]:
            best_by_key[key] = (
                score,
                {
                    "strategy_id": strategy_id,
                    "market_hash": market_hash,
                    "expected_arr_delta": arr_delta,
                    "improvement_velocity": improvement_velocity,
                    "candidate_confidence": confidence,
                    "data_timestamp": candidate_data_timestamp,
                    "pipeline_version": candidate_pipeline_version,
                    "case_id": _safe_text(raw.get("case_id") or raw.get("id")),
                    **defaults,
                    "stale_reasons": stale_reasons,
                },
            )

    strategies: list[dict[str, Any]] = []
    for _, candidate in best_by_key.values():
        strategy_key = f"{source}:{candidate['strategy_id']}"
        packet_key = f"{candidate['packet_run_id']}:{candidate['strategy_id']}:{candidate['market_hash']}"
        version_label = str(sha256(packet_key.encode("utf-8")).hexdigest()[:16])
        snapshot = _build_backlog_candidate_snapshot(candidate, control=control)
        strategies.append(
            {
                "strategy_key": strategy_key,
                "version_label": version_label,
                "lane": "openclaw_comparison",
                "artifact_uri": None,
                "git_sha": None,
                "status": "candidate",
                "deployments": [
                    {
                        "environment": "sim",
                        "capital_cap_usd": 0.0,
                        "status": "active",
                        "notes": f"Imported from {source} openclaw packet {packet_run_id}",
                        "snapshot": snapshot,
                    }
                ],
            }
        )
    return strategies


def _load_openclaw_packet(control: dict[str, Any]) -> dict[str, Any] | None:
    path = Path(control.get("openclaw_path") or "")
    if not path.exists():
        return None
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(packet, dict):
        return None
    return packet


def _build_control_context() -> dict[str, Any]:
    return {
        "read_only": _env_bool("JJ_FLYWHEEL_READ_ONLY", False),
        "stale_reasons": _env_list("JJ_BLOCK_REASONS"),
        "max_arr_improvement_bps": _env_float("JJ_MIN_ARR_IMPROVEMENT_BPS", 0.0),
        "min_data_age_minutes": _env_float("JJ_DATA_MAX_AGE_MINUTES", 15.0),
        "openclaw_data_age_minutes": _env_float("JJ_OPENCLAW_MAX_AGE_MINUTES", 120.0),
        "openclaw_age_minutes": _env_float("JJ_OPENCLAW_MAX_AGE_MINUTES", 120.0),
        "stale_fail_open_limit": _env_int("JJ_MAX_STALE_FAIL_OPEN", 3),
        "openclaw_path": os.getenv("FLYWHEEL_OPENCLAW_NORMALIZED_PATH"),
    }


def build_cycle_packet_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Build one combined flywheel cycle packet from runtime config."""

    strategies: list[dict[str, Any]] = []
    control = _build_control_context()
    openclaw_packet = _load_openclaw_packet(control)
    for item in config.get("strategies", []):
        cycle_packet = build_cycle_packet_from_bot_db(
            item["bot_db"],
            strategy_key=item["strategy_key"],
            version_label=item["version_label"],
            lane=item["lane"],
            environment=item["environment"],
            capital_cap_usd=float(item["capital_cap_usd"]),
            artifact_uri=item.get("artifact_uri"),
            git_sha=item.get("git_sha"),
            lookback_days=int(item.get("lookback_days", 7)),
        )
        strategies.extend(cycle_packet["strategies"])

    if openclaw_packet is not None:
        strategies.extend(_build_backlog_strategies_from_openclaw(openclaw_packet, control))

    cycle_key = config.get("cycle_key") or _cycle_key(config.get("cycle_key_prefix", "runtime"))
    cycle_packet = {
        "cycle_key": cycle_key,
        "strategies": strategies,
        "control_context": control,
    }
    return CyclePacket.from_dict(cycle_packet).to_dict()


def build_payload_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for `build_cycle_packet_from_config`."""
    return build_cycle_packet_from_config(config)


def run_from_config(path: str | Path) -> dict[str, Any]:
    """Run the full flywheel cycle from a runtime config file."""

    config = load_config(path)
    cycle_packet = build_cycle_packet_from_config(config)
    artifact_root = config.get("artifact_dir", str(DEFAULT_ARTIFACT_ROOT))
    control_db_url = config.get("control_db_url")

    database.reset_engine()
    engine = database.get_engine(control_db_url)
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        return run_cycle(session, cycle_packet, artifact_root=artifact_root)
    finally:
        session.close()
        database.reset_engine()


def _cycle_key(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}"
