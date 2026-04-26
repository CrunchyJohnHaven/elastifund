from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


router = APIRouter(tags=["manage-control-plane"])

REPORTS_DIR = REPO_ROOT / "reports"
CONTROL_DIR = REPORTS_DIR / "console_runtime"
SIMULATION_REPORTS_DIR = REPORTS_DIR / "simulation"
TRADING_DB_PATH = REPO_ROOT / "data" / "btc_5min_maker.db"
SCRATCH_STATE_DIR = REPO_ROOT / "state" / "console_runtime"
SCRATCH_STATE_DIR.mkdir(parents=True, exist_ok=True)
POLY_HISTORY_GLOB = "Polymarket-History-*.csv"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_json_any(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _relative_path_text(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if numeric == numeric else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_name(value: Any) -> str:
    text = str(value or "unknown").strip()
    if not text:
        return "unknown"
    return text.replace("_", " ")


def _candidate_label(candidate: dict[str, Any] | None, fallback: str = "candidate") -> str:
    payload = candidate if isinstance(candidate, dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    for key in ("name", "candidate_label", "policy_id", "id"):
        if profile.get(key):
            return str(profile[key])
        if payload.get(key):
            return str(payload[key])
    return fallback


def _finding(title: str, detail: str, *, tone: str = "warn", metric: Any | None = None) -> dict[str, Any]:
    payload = {"title": title, "detail": detail, "tone": tone}
    if metric is not None:
        payload["metric"] = metric
    return payload


def _load_trading_data(limit: int = 12) -> dict[str, Any]:
    if not TRADING_DB_PATH.exists():
        return {
            "db_path": _relative_path_text(TRADING_DB_PATH),
            "available": False,
            "rows_total": 0,
            "latest_activity_at": None,
            "recent_rows": [],
        }

    conn = sqlite3.connect(TRADING_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS count FROM window_trades")
        rows_total = _safe_int(cur.fetchone()["count"], 0)

        cur.execute(
            """
            SELECT
                COUNT(*) AS rows_total,
                SUM(CASE WHEN COALESCE(filled, 0) = 1 THEN 1 ELSE 0 END) AS filled_rows,
                SUM(CASE WHEN order_status LIKE 'skip_%' THEN 1 ELSE 0 END) AS skipped_rows,
                SUM(CASE WHEN order_status IN ('pending_reservation', 'reserved', 'posted', 'open') THEN 1 ELSE 0 END) AS pending_rows,
                SUM(CASE WHEN direction = 'DOWN' THEN 1 ELSE 0 END) AS down_rows,
                SUM(CASE WHEN direction = 'UP' THEN 1 ELSE 0 END) AS up_rows,
                SUM(COALESCE(realized_pnl_usd, pnl_usd, 0)) AS realized_pnl_usd,
                MAX(COALESCE(updated_at, created_at)) AS latest_activity_at
            FROM window_trades
            """
        )
        summary_row = cur.fetchone()

        cur.execute(
            """
            SELECT
                slug,
                direction,
                order_status,
                order_price,
                trade_size_usd,
                delta,
                COALESCE(realized_pnl_usd, pnl_usd) AS pnl_usd,
                COALESCE(updated_at, created_at) AS activity_at
            FROM window_trades
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        recent_rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

    return {
        "db_path": _relative_path_text(TRADING_DB_PATH),
        "available": True,
        "rows_total": rows_total,
        "filled_rows": _safe_int(summary_row["filled_rows"], 0),
        "skipped_rows": _safe_int(summary_row["skipped_rows"], 0),
        "pending_rows": _safe_int(summary_row["pending_rows"], 0),
        "down_rows": _safe_int(summary_row["down_rows"], 0),
        "up_rows": _safe_int(summary_row["up_rows"], 0),
        "realized_pnl_usd": _safe_float(summary_row["realized_pnl_usd"], 0.0),
        "latest_activity_at": summary_row["latest_activity_at"],
        "recent_rows": recent_rows,
    }


def _discover_polymarket_history_csv() -> Path | None:
    configured = None
    if "POLYMARKET_HISTORY_CSV" in os.environ:
        configured = Path(os.environ["POLYMARKET_HISTORY_CSV"]).expanduser()
        if configured.exists():
            return configured
    candidates: list[Path] = []
    for root in (REPO_ROOT / "data", Path.home() / "Downloads"):
        if not root.exists():
            continue
        candidates.extend(path for path in root.glob(POLY_HISTORY_GLOB) if path.is_file())
    if not candidates:
        return None
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return candidates[0]


async def _run_command(command: list[str], cwd: Path = REPO_ROOT, timeout_seconds: int = 1200) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "ok": False,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": f"Timed out after {timeout_seconds}s",
        }
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": stdout.decode("utf-8", errors="replace")[-3000:].strip(),
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-3000:].strip(),
    }


def _lane_payload(
    *,
    job_name: str,
    label: str,
    artifact: Path | None,
    state: "JobState",
    headline: str,
    tone: str,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    if state.running:
        status = "running"
    elif state.last_error:
        status = "failed"
    elif state.last_success_at:
        status = "ready"
    else:
        status = "idle"
    return {
        "job": job_name,
        "label": label,
        "artifact": _relative_path_text(artifact),
        "status": status,
        "tone": tone,
        "enabled": state.enabled,
        "running": state.running,
        "headline": headline,
        "last_started_at": state.last_started_at,
        "last_finished_at": state.last_finished_at,
        "last_success_at": state.last_success_at,
        "last_duration_seconds": state.last_duration_seconds,
        "next_run_at": state.next_run_at,
        "summary": state.last_output_summary,
        "findings": findings[:4],
    }


def _extract_autoresearch_lane(payload: dict[str, Any], state: "JobState") -> dict[str, Any]:
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    candidate = payload.get("best_candidate") if isinstance(payload.get("best_candidate"), dict) else {}
    candidate_name = _candidate_label(candidate, "best candidate")
    monte_carlo = candidate.get("monte_carlo") if isinstance(candidate.get("monte_carlo"), dict) else {}
    historical = candidate.get("historical") if isinstance(candidate.get("historical"), dict) else {}
    findings = [
        _finding(
            "Decision",
            f"{str(decision.get('action') or 'hold').upper()} because {str(decision.get('reason') or 'no explicit reason published').replace('_', ' ')}.",
            tone="warn" if str(decision.get("action") or "hold").lower() == "hold" else "good",
        ),
        _finding(
            "Lead package",
            f"{_compact_name(candidate_name)} · {historical.get('replay_live_filled_rows') or historical.get('baseline_live_filled_rows') or 0} filled rows · profit probability {_safe_float(monte_carlo.get('profit_probability'), 0.0):.3f}.",
            tone="good" if _safe_float(monte_carlo.get("profit_probability"), 0.0) >= 0.55 else "warn",
        ),
        _finding(
            "Tail risk",
            f"P95 drawdown ${_safe_float(monte_carlo.get('p95_max_drawdown_usd'), 0.0):.2f} · median pnl ${_safe_float(monte_carlo.get('median_total_pnl_usd'), 0.0):.2f}.",
            tone="bad" if _safe_float(monte_carlo.get("p95_max_drawdown_usd"), 0.0) > 50 else "warn",
        ),
    ]
    return _lane_payload(
        job_name="autoresearch",
        label="BTC5 autoresearch",
        artifact=CONTROL_DIR / "btc5_autoresearch" / "latest.json",
        state=state,
        headline=f"{str(decision.get('action') or 'hold').upper()} · {_compact_name(candidate_name)}",
        tone="good" if str(decision.get("action") or "").lower() == "promote" else "warn",
        findings=findings,
    )


def _extract_hypothesis_lane(payload: dict[str, Any], state: "JobState") -> dict[str, Any]:
    best = payload.get("best_hypothesis") if isinstance(payload.get("best_hypothesis"), dict) else {}
    summary = best.get("summary") if isinstance(best.get("summary"), dict) else {}
    hypothesis = best.get("hypothesis") if isinstance(best.get("hypothesis"), dict) else {}
    name = str(hypothesis.get("name") or payload.get("best_candidate", {}).get("name") or "hypothesis frontier")
    findings = [
        _finding(
            "Best hypothesis",
            f"{_compact_name(name)} · validation median ARR {_safe_float(summary.get('validation_median_arr_pct'), 0.0):,.1f}% · P05 {_safe_float(summary.get('validation_p05_arr_pct'), 0.0):,.1f}%.",
            tone="good" if _safe_float(summary.get("validation_p05_arr_pct"), 0.0) > 0 else "warn",
        ),
        _finding(
            "Evidence",
            f"{_safe_int(summary.get('validation_live_filled_rows'), 0)} live fills · generalization {_safe_float(summary.get('generalization_ratio'), 0.0):.2f} · band {payload.get('evidence_band') or summary.get('evidence_band') or 'exploratory'}.",
            tone="good" if _safe_int(summary.get("validation_live_filled_rows"), 0) >= 10 else "warn",
        ),
        _finding(
            "Next follow-ups",
            f"{len(payload.get('follow_up_candidates') or [])} follow-ups published · deployment recommendation {str(payload.get('deployment_recommendation') or 'hold_current').replace('_', ' ')}.",
            tone="warn",
        ),
    ]
    return _lane_payload(
        job_name="hypothesis_lab",
        label="Hypothesis lab",
        artifact=REPORTS_DIR / "btc5_hypothesis_lab" / "summary.json",
        state=state,
        headline=f"{str(payload.get('deployment_recommendation') or 'hold_current').replace('_', ' ')} · {_compact_name(name)}",
        tone="good" if str(payload.get("deployment_recommendation") or "").lower() == "promote" else "warn",
        findings=findings,
    )


def _extract_policy_lane(payload: dict[str, Any], state: "JobState") -> dict[str, Any]:
    selection = payload.get("selection_recommendation") if isinstance(payload.get("selection_recommendation"), dict) else {}
    ranked = payload.get("ranked_policies") if isinstance(payload.get("ranked_policies"), list) else []
    leader = ranked[0] if ranked else {}
    policy_id = str(selection.get("policy_id") or leader.get("policy_id") or "policy frontier")
    findings = [
        _finding(
            "Selected policy",
            f"{_compact_name(policy_id)} · loss improvement {_safe_float(selection.get('loss_improvement_vs_incumbent'), 0.0):,.2f} vs incumbent.",
            tone="good" if _safe_float(selection.get("loss_improvement_vs_incumbent"), 0.0) > 0 else "warn",
        ),
        _finding(
            "Return profile",
            f"Median 30d {_safe_float(leader.get('median_30d_return_pct'), 0.0):,.1f}% · P05 {_safe_float(leader.get('p05_30d_return_pct'), 0.0):,.1f}% · CI [{_safe_float(leader.get('bootstrap_ci_low'), 0.0):.1f}, {_safe_float(leader.get('bootstrap_ci_high'), 0.0):.1f}].",
            tone="good" if _safe_float(leader.get("bootstrap_ci_low"), 0.0) > 0 else "warn",
        ),
        _finding(
            "Frontier depth",
            f"{len(ranked)} ranked policies published from the latest market-backed frontier.",
            tone="warn",
        ),
    ]
    return _lane_payload(
        job_name="policy_frontier",
        label="Policy frontier",
        artifact=REPORTS_DIR / "btc5_market_policy_frontier" / "latest.json",
        state=state,
        headline=f"{_compact_name(policy_id)} leads frontier",
        tone="good" if _safe_float(selection.get("loss_improvement_vs_incumbent"), 0.0) > 0 else "warn",
        findings=findings,
    )


def _extract_monte_carlo_lane(payload: dict[str, Any], state: "JobState") -> dict[str, Any]:
    best = payload.get("best_candidate") if isinstance(payload.get("best_candidate"), dict) else {}
    profile = best.get("profile") if isinstance(best.get("profile"), dict) else {}
    monte_carlo = best.get("monte_carlo") if isinstance(best.get("monte_carlo"), dict) else {}
    capital = payload.get("capital_ladder_summary") if isinstance(payload.get("capital_ladder_summary"), dict) else {}
    next_gate = capital.get("next_notional_gate") if isinstance(capital.get("next_notional_gate"), dict) else {}
    findings = [
        _finding(
            "Best guardrail candidate",
            f"{_compact_name(profile.get('name') or 'candidate')} · profit probability {_safe_float(monte_carlo.get('profit_probability'), 0.0):.3f} · median pnl ${_safe_float(monte_carlo.get('median_total_pnl_usd'), 0.0):.2f}.",
            tone="good" if _safe_float(monte_carlo.get("profit_probability"), 0.0) >= 0.55 else "bad",
        ),
        _finding(
            "Tail profile",
            f"Loss-hit {_safe_float(monte_carlo.get('loss_limit_hit_probability'), 0.0):.3f} · non-positive {_safe_float(monte_carlo.get('non_positive_path_probability'), 0.0):.3f} · P95 drawdown ${_safe_float(monte_carlo.get('p95_max_drawdown_usd'), 0.0):.2f}.",
            tone="bad" if _safe_float(monte_carlo.get("loss_limit_hit_probability"), 0.0) > 0.35 else "warn",
        ),
        _finding(
            "Capital ladder",
            f"Next gate {str(next_gate.get('status') or capital.get('live_now', {}).get('status') or 'unknown').replace('_', ' ')} at ${_safe_float(next_gate.get('trade_size_usd'), 0.0):.2f}.",
            tone="bad" if str(next_gate.get("status") or "").startswith("blocked") else "good",
        ),
    ]
    return _lane_payload(
        job_name="monte_carlo",
        label="Monte Carlo",
        artifact=REPORTS_DIR / "btc5_monte_carlo_latest.json",
        state=state,
        headline=f"{_compact_name(profile.get('name') or 'candidate')} stress test",
        tone="bad" if _safe_float(monte_carlo.get("loss_limit_hit_probability"), 0.0) > 0.35 else "warn",
        findings=findings,
    )


def _extract_structural_lane(rankings_payload: dict[str, Any], results_payload: Any, state: "JobState") -> dict[str, Any]:
    if state.last_output_summary.get("input_blocked"):
        return _lane_payload(
            job_name="simulation_lab",
            label="Structural simulation lab",
            artifact=SIMULATION_REPORTS_DIR / "ranked_candidates.json",
            state=state,
            headline="awaiting Polymarket history csv",
            tone="warn",
            findings=[
                _finding(
                    "Input blocked",
                    str(state.last_output_summary.get("reason") or "No Polymarket history CSV found for a fresh structural replay."),
                    tone="warn",
                ),
            ],
        )
    ranked = rankings_payload.get("ranked_candidates") if isinstance(rankings_payload.get("ranked_candidates"), list) else []
    leader = ranked[0] if ranked else {}
    results_count = len(results_payload) if isinstance(results_payload, list) else 0
    blockers = leader.get("blockers") if isinstance(leader.get("blockers"), list) else []
    findings = [
        _finding(
            "Lead structural lane",
            f"{_compact_name(leader.get('lane') or leader.get('candidate_name') or 'none')} · expected pnl ${_safe_float(leader.get('expected_pnl_usd'), 0.0):.2f} · fills {_safe_int(leader.get('simulation_fills'), _safe_int(leader.get('fills_simulated'), 0))}.",
            tone="good" if _safe_float(leader.get("expected_pnl_usd"), 0.0) > 0 else "warn",
        ),
        _finding(
            "Promotion state",
            f"{str(leader.get('promotion_ready') or leader.get('simulation_ready') or False).lower()} · blockers {', '.join(str(item) for item in blockers[:3]) or 'none'}.",
            tone="bad" if blockers else "good",
        ),
        _finding(
            "Simulation depth",
            f"{results_count} structural scenarios replayed in the latest lab run.",
            tone="warn",
        ),
    ]
    return _lane_payload(
        job_name="simulation_lab",
        label="Structural simulation lab",
        artifact=SIMULATION_REPORTS_DIR / "ranked_candidates.json",
        state=state,
        headline=f"{_compact_name(leader.get('lane') or leader.get('candidate_name') or 'no structural leader')}",
        tone="good" if _safe_float(leader.get("expected_pnl_usd"), 0.0) > 0 and not blockers else "warn",
        findings=findings,
    )


@dataclass
class JobSpec:
    name: str
    label: str
    interval_seconds: int
    runner: Callable[[], Awaitable[dict[str, Any]]]
    output_path: Path | None = None
    first_run_delay_seconds: int = 0
    enabled: bool = True


@dataclass
class JobState:
    name: str
    label: str
    interval_seconds: int
    enabled: bool = True
    running: bool = False
    runs_total: int = 0
    failures_total: int = 0
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    last_duration_seconds: float | None = None
    next_run_at: str | None = None
    last_output_summary: dict[str, Any] = field(default_factory=dict)


class LocalManageControlPlane:
    def __init__(self) -> None:
        self.started_at: str | None = None
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._clients: set[WebSocket] = set()
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._state_lock = asyncio.Lock()
        self._snapshot_cache: dict[str, Any] = {}
        self.simulation_job_names = (
            "autoresearch",
            "hypothesis_lab",
            "policy_frontier",
            "monte_carlo",
            "simulation_lab",
        )

        self.job_specs: dict[str, JobSpec] = {
            "health": JobSpec(
                name="health",
                label="Health snapshot",
                interval_seconds=300,
                runner=self._run_health_snapshot,
                output_path=REPORTS_DIR / "btc5_health_latest.json",
                first_run_delay_seconds=1,
            ),
            "cohort": JobSpec(
                name="cohort",
                label="Validation cohort",
                interval_seconds=900,
                runner=self._run_validation_cohort,
                output_path=REPORTS_DIR / "btc5_validation_cohort_latest.json",
                first_run_delay_seconds=2,
            ),
            "filters": JobSpec(
                name="filters",
                label="Filter economics",
                interval_seconds=3600,
                runner=self._run_filter_economics,
                output_path=REPORTS_DIR / "btc5_filter_economics_latest.json",
                first_run_delay_seconds=3,
            ),
            "hypothesis_lab": JobSpec(
                name="hypothesis_lab",
                label="Hypothesis lab",
                interval_seconds=3600,
                runner=self._run_hypothesis_lab,
                output_path=REPORTS_DIR / "btc5_hypothesis_lab" / "summary.json",
                first_run_delay_seconds=4,
            ),
            "policy_frontier": JobSpec(
                name="policy_frontier",
                label="Policy frontier",
                interval_seconds=3600,
                runner=self._run_policy_frontier,
                output_path=REPORTS_DIR / "btc5_market_policy_frontier" / "latest.json",
                first_run_delay_seconds=6,
            ),
            "autoresearch": JobSpec(
                name="autoresearch",
                label="BTC5 autoresearch",
                interval_seconds=6 * 3600,
                runner=self._run_autoresearch_cycle,
                output_path=CONTROL_DIR / "btc5_autoresearch" / "latest.json",
                first_run_delay_seconds=8,
            ),
            "monte_carlo": JobSpec(
                name="monte_carlo",
                label="Monte Carlo",
                interval_seconds=2 * 3600,
                runner=self._run_monte_carlo,
                output_path=REPORTS_DIR / "btc5_monte_carlo_latest.json",
                first_run_delay_seconds=10,
            ),
            "simulation_lab": JobSpec(
                name="simulation_lab",
                label="Structural simulation lab",
                interval_seconds=3 * 3600,
                runner=self._run_structural_simulation_lab,
                output_path=SIMULATION_REPORTS_DIR / "ranked_candidates.json",
                first_run_delay_seconds=12,
            ),
        }
        self.job_states: dict[str, JobState] = {
            name: JobState(
                name=spec.name,
                label=spec.label,
                interval_seconds=spec.interval_seconds,
                enabled=spec.enabled,
            )
            for name, spec in self.job_specs.items()
        }

    async def start(self) -> None:
        async with self._state_lock:
            if self.started_at is not None:
                return
            self.started_at = _iso_utc_now()
            for spec in self.job_specs.values():
                self._run_locks[spec.name] = asyncio.Lock()
                self.job_states[spec.name].next_run_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=spec.first_run_delay_seconds)
                ).isoformat().replace("+00:00", "Z")
                self._tasks[spec.name] = asyncio.create_task(self._job_loop(spec), name=f"manage-job-{spec.name}")
        await self._emit("control_plane.started", {"started_at": self.started_at})
        await self._broadcast_snapshot()

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.started_at = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        await websocket.send_json({"type": "snapshot", "payload": self.snapshot()})

    async def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def snapshot(self) -> dict[str, Any]:
        now = _iso_utc_now()
        return {
            "generated_at": now,
            "started_at": self.started_at,
            "running": self.started_at is not None,
            "jobs": [self._job_state_payload(name) for name in sorted(self.job_states)],
            "events": list(self._events)[-40:],
            "simulation": self._simulation_state(),
            "trading_data": _load_trading_data(),
        }

    async def run_now(self, job_name: str, source: str = "manual") -> dict[str, Any]:
        spec = self.job_specs.get(job_name)
        if not spec:
            raise KeyError(job_name)
        return await self._execute_job(spec, source=source)

    async def pause(self, job_name: str) -> dict[str, Any]:
        state = self.job_states.get(job_name)
        if not state:
            raise KeyError(job_name)
        state.enabled = False
        state.next_run_at = None
        await self._emit("job.paused", {"job": job_name})
        await self._broadcast_snapshot()
        return self._job_state_payload(job_name)

    async def resume(self, job_name: str) -> dict[str, Any]:
        spec = self.job_specs.get(job_name)
        state = self.job_states.get(job_name)
        if not spec or not state:
            raise KeyError(job_name)
        state.enabled = True
        state.next_run_at = (datetime.now(timezone.utc) + timedelta(seconds=spec.interval_seconds)).isoformat().replace("+00:00", "Z")
        await self._emit("job.resumed", {"job": job_name})
        await self._broadcast_snapshot()
        return self._job_state_payload(job_name)

    async def _job_loop(self, spec: JobSpec) -> None:
        if spec.first_run_delay_seconds > 0:
            await asyncio.sleep(spec.first_run_delay_seconds)
        while True:
            state = self.job_states[spec.name]
            if state.enabled:
                await self._execute_job(spec, source="scheduler")
                state.next_run_at = (datetime.now(timezone.utc) + timedelta(seconds=spec.interval_seconds)).isoformat().replace("+00:00", "Z")
                await self._broadcast_snapshot()
                await asyncio.sleep(spec.interval_seconds)
            else:
                await asyncio.sleep(1)

    async def _execute_job(self, spec: JobSpec, *, source: str) -> dict[str, Any]:
        lock = self._run_locks.setdefault(spec.name, asyncio.Lock())
        async with lock:
            state = self.job_states[spec.name]
            if state.running:
                return self._job_state_payload(spec.name)
            state.running = True
            state.last_started_at = _iso_utc_now()
            await self._emit("job.started", {"job": spec.name, "label": spec.label, "source": source})
            await self._broadcast_snapshot()
            started = datetime.now(timezone.utc)
            result = await spec.runner()
            finished = datetime.now(timezone.utc)
            state.running = False
            state.runs_total += 1
            state.last_finished_at = finished.isoformat().replace("+00:00", "Z")
            state.last_duration_seconds = round((finished - started).total_seconds(), 3)
            state.last_output_summary = result.get("summary") or {}
            if result.get("ok"):
                state.last_success_at = state.last_finished_at
                state.last_error = None
                await self._emit(
                    "job.completed",
                    {"job": spec.name, "label": spec.label, "source": source, "summary": state.last_output_summary},
                )
            else:
                state.failures_total += 1
                state.last_error = result.get("error") or result.get("stderr_tail") or "Job failed"
                await self._emit(
                    "job.failed",
                    {"job": spec.name, "label": spec.label, "source": source, "error": state.last_error},
                )
            if spec.name in self.simulation_job_names:
                await self._emit(
                    "simulation.findings",
                    {"job": spec.name, "label": spec.label, "lane": self._simulation_lane_payload(spec.name)},
                )
            await self._broadcast_snapshot()
            return self._job_state_payload(spec.name)

    async def _broadcast_snapshot(self) -> None:
        payload = {"type": "snapshot", "payload": self.snapshot()}
        stale: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_json(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self._clients.discard(client)

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "payload": payload, "ts": _iso_utc_now()}
        self._events.append(event)
        stale: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_json(event)
            except Exception:
                stale.append(client)
        for client in stale:
            self._clients.discard(client)

    def _job_state_payload(self, job_name: str) -> dict[str, Any]:
        state = self.job_states[job_name]
        return {
            "name": state.name,
            "label": state.label,
            "interval_seconds": state.interval_seconds,
            "enabled": state.enabled,
            "running": state.running,
            "runs_total": state.runs_total,
            "failures_total": state.failures_total,
            "last_started_at": state.last_started_at,
            "last_finished_at": state.last_finished_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "last_duration_seconds": state.last_duration_seconds,
            "next_run_at": state.next_run_at,
            "last_output_summary": state.last_output_summary,
        }

    def _simulation_lane_payload(self, job_name: str) -> dict[str, Any]:
        state = self.job_states[job_name]
        if job_name == "autoresearch":
            payload = _load_json(CONTROL_DIR / "btc5_autoresearch" / "latest.json") or {}
            return _extract_autoresearch_lane(payload, state)
        if job_name == "hypothesis_lab":
            payload = _load_json(REPORTS_DIR / "btc5_hypothesis_lab" / "summary.json") or {}
            return _extract_hypothesis_lane(payload, state)
        if job_name == "policy_frontier":
            payload = _load_json(REPORTS_DIR / "btc5_market_policy_frontier" / "latest.json") or {}
            return _extract_policy_lane(payload, state)
        if job_name == "monte_carlo":
            payload = _load_json(REPORTS_DIR / "btc5_monte_carlo_latest.json") or {}
            return _extract_monte_carlo_lane(payload, state)
        if job_name == "simulation_lab":
            rankings = _load_json(SIMULATION_REPORTS_DIR / "ranked_candidates.json") or {}
            latest = _load_json_any(SIMULATION_REPORTS_DIR / "latest.json")
            return _extract_structural_lane(rankings, latest, state)
        return _lane_payload(
            job_name=job_name,
            label=state.label,
            artifact=self.job_specs.get(job_name).output_path if self.job_specs.get(job_name) else None,
            state=state,
            headline=state.label,
            tone="warn",
            findings=[],
        )

    def _simulation_state(self) -> dict[str, Any]:
        lanes = [self._simulation_lane_payload(job_name) for job_name in self.simulation_job_names if job_name in self.job_states]
        findings: list[dict[str, Any]] = []
        for lane in lanes:
            lane_ts = lane.get("last_finished_at") or lane.get("last_started_at") or lane.get("last_success_at")
            for finding in lane.get("findings") or []:
                findings.append({
                    "lane": lane.get("label"),
                    "job": lane.get("job"),
                    "tone": finding.get("tone", lane.get("tone", "warn")),
                    "title": finding.get("title"),
                    "detail": finding.get("detail"),
                    "metric": finding.get("metric"),
                    "ts": lane_ts,
                })
        findings.sort(key=lambda item: _parse_iso(item.get("ts")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        active_jobs = [lane["job"] for lane in lanes if lane.get("running")]
        return {
            "generated_at": _iso_utc_now(),
            "active_jobs": active_jobs,
            "lanes": lanes,
            "findings": findings[:14],
        }

    async def _run_health_snapshot(self) -> dict[str, Any]:
        result = await _run_command([sys.executable, str(REPO_ROOT / "scripts" / "render_btc5_health_snapshot.py")], timeout_seconds=180)
        payload = _load_json(REPORTS_DIR / "btc5_health_latest.json") or {}
        return {
            **result,
            "summary": {
                "bot_running": payload.get("bot_running"),
                "last_fill_age_seconds": payload.get("last_fill_age_seconds"),
                "rolling_win_rate_50": payload.get("rolling_win_rate_50"),
            },
            "artifact": str(REPORTS_DIR / "btc5_health_latest.json"),
        }

    async def _run_validation_cohort(self) -> dict[str, Any]:
        result = await _run_command([sys.executable, str(REPO_ROOT / "scripts" / "render_btc5_validation_cohort.py")], timeout_seconds=180)
        payload = _load_json(REPORTS_DIR / "btc5_validation_cohort_latest.json") or {}
        return {
            **result,
            "summary": {
                "resolved_down_fills": payload.get("resolved_down_fills"),
                "recommendation": payload.get("recommendation"),
                "checkpoint_status": payload.get("checkpoint_status"),
            },
            "artifact": str(REPORTS_DIR / "btc5_validation_cohort_latest.json"),
        }

    async def _run_filter_economics(self) -> dict[str, Any]:
        output_path = REPORTS_DIR / "btc5_filter_economics_latest.json"
        result = await _run_command(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "render_btc5_filter_economics.py"),
                "--output",
                str(output_path),
            ],
            timeout_seconds=300,
        )
        payload = _load_json(output_path) or {}
        filters = payload.get("filters") or payload.get("filter_economics") or {}
        summary = {
            "tracked_filters": len(filters) if isinstance(filters, dict) else 0,
            "net_value_usd": payload.get("net_filter_value_usd"),
        }
        return {**result, "summary": summary, "artifact": str(output_path)}

    async def _run_hypothesis_lab(self) -> dict[str, Any]:
        output_dir = REPORTS_DIR / "btc5_hypothesis_lab"
        override_env = SCRATCH_STATE_DIR / "btc5_autoresearch.env"
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "btc5_hypothesis_lab.py"),
            "--db-path",
            str(REPO_ROOT / "data" / "btc_5min_maker.db"),
            "--strategy-env",
            str(REPO_ROOT / "config" / "btc5_strategy.env"),
            "--override-env",
            str(override_env),
            "--output-dir",
            str(output_dir),
            "--write-latest",
        ]
        result = await _run_command(command, timeout_seconds=1800)
        payload = _load_json(output_dir / "summary.json") or {}
        best = payload.get("best_hypothesis") if isinstance(payload.get("best_hypothesis"), dict) else {}
        summary = best.get("summary") if isinstance(best.get("summary"), dict) else {}
        hypothesis = best.get("hypothesis") if isinstance(best.get("hypothesis"), dict) else {}
        return {
            **result,
            "summary": {
                "deployment_recommendation": payload.get("deployment_recommendation"),
                "best_hypothesis": hypothesis.get("name"),
                "validation_live_filled_rows": summary.get("validation_live_filled_rows"),
            },
            "artifact": str(output_dir / "summary.json"),
        }

    async def _run_policy_frontier(self) -> dict[str, Any]:
        latest_json = REPORTS_DIR / "btc5_market_policy_frontier" / "latest.json"
        latest_json.parent.mkdir(parents=True, exist_ok=True)
        latest_md = latest_json.with_suffix(".md")
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_btc5_policy_autoresearch.py"),
            "--latest-json",
            str(latest_json),
            "--latest-md",
            str(latest_md),
            "--description",
            "manage control plane policy frontier refresh",
        ]
        result = await _run_command(command, timeout_seconds=1800)
        payload = _load_json(latest_json) or {}
        selection = payload.get("selection_recommendation") if isinstance(payload.get("selection_recommendation"), dict) else {}
        return {
            **result,
            "summary": {
                "policy_id": selection.get("policy_id"),
                "loss_improvement_vs_incumbent": selection.get("loss_improvement_vs_incumbent"),
                "selection_source": selection.get("selection_source"),
            },
            "artifact": str(latest_json),
        }

    async def _run_autoresearch_cycle(self) -> dict[str, Any]:
        report_dir = CONTROL_DIR / "btc5_autoresearch"
        current_probe_latest = CONTROL_DIR / "btc5_autoresearch_current_probe" / "latest.json"
        override_env = SCRATCH_STATE_DIR / "btc5_autoresearch.env"
        report_dir.mkdir(parents=True, exist_ok=True)
        current_probe_latest.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_btc5_autoresearch_cycle.py"),
            "--db-path",
            str(REPO_ROOT / "data" / "btc_5min_maker.db"),
            "--strategy-env",
            str(REPO_ROOT / "config" / "btc5_strategy.env"),
            "--override-env",
            str(override_env),
            "--report-dir",
            str(report_dir),
            "--current-probe-latest",
            str(current_probe_latest),
            "--runtime-truth",
            str(REPORTS_DIR / "runtime_truth_latest.json"),
        ]
        result = await _run_command(command, timeout_seconds=1800)
        payload = _load_json(report_dir / "latest.json") or {}
        decision = payload.get("decision") or {}
        summary = {
            "action": decision.get("action"),
            "confidence": decision.get("confidence"),
            "best_candidate": ((payload.get("best_candidate") or {}).get("candidate_label")),
        }
        return {**result, "summary": summary, "artifact": str(report_dir / "latest.json")}

    async def _run_monte_carlo(self) -> dict[str, Any]:
        command = [
            sys.executable,
            "-m",
            "scripts.btc5_monte_carlo_core",
            "--mode",
            "quick",
            "--db-path",
            str(REPO_ROOT / "data" / "btc_5min_maker.db"),
            "--runtime-truth",
            str(REPORTS_DIR / "runtime_truth_latest.json"),
            "--write-latest",
        ]
        result = await _run_command(command, timeout_seconds=1800)
        payload = _load_json(REPORTS_DIR / "btc5_monte_carlo_latest.json") or {}
        best = payload.get("best_candidate") if isinstance(payload.get("best_candidate"), dict) else {}
        monte_carlo = best.get("monte_carlo") if isinstance(best.get("monte_carlo"), dict) else {}
        return {
            **result,
            "summary": {
                "candidate": _candidate_label(best, "candidate"),
                "profit_probability": monte_carlo.get("profit_probability"),
                "p95_drawdown_usd": monte_carlo.get("p95_max_drawdown_usd"),
            },
            "artifact": str(REPORTS_DIR / "btc5_monte_carlo_latest.json"),
        }

    async def _run_structural_simulation_lab(self) -> dict[str, Any]:
        output_dir = SIMULATION_REPORTS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = _discover_polymarket_history_csv()
        if csv_path is None:
            return {
                "ok": True,
                "returncode": 0,
                "stdout_tail": "",
                "stderr_tail": "",
                "summary": {
                    "input_blocked": True,
                    "reason": f"No {POLY_HISTORY_GLOB} found under data/ or ~/Downloads for a fresh structural replay.",
                },
                "artifact": str(SIMULATION_REPORTS_DIR / "ranked_candidates.json"),
            }
        command = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "simulation_lab.py"),
            "all",
            "--csv",
            str(csv_path),
        ]
        result = await _run_command(command, timeout_seconds=1800)
        rankings = _load_json(SIMULATION_REPORTS_DIR / "ranked_candidates.json") or {}
        leader = (rankings.get("ranked_candidates") or [{}])[0]
        return {
            **result,
            "summary": {
                "candidate_count": rankings.get("candidate_count"),
                "leader": leader.get("lane") or leader.get("candidate_name"),
                "expected_pnl_usd": leader.get("expected_pnl_usd"),
            },
            "artifact": str(SIMULATION_REPORTS_DIR / "ranked_candidates.json"),
        }


control_plane = LocalManageControlPlane()


@router.get("/api/v1/control-plane/state", response_model=None)
async def get_control_plane_state(
    request: Request,
    raw: bool = Query(default=False),
) -> dict[str, Any] | RedirectResponse:
    accept = request.headers.get("accept", "").lower()
    if not raw and "text/html" in accept:
        return RedirectResponse(url="/manage/?panel=control-plane", status_code=307)
    return control_plane.snapshot()


@router.post("/api/v1/control-plane/jobs/{job_name}/run")
async def run_control_plane_job(job_name: str) -> dict[str, Any]:
    if job_name not in control_plane.job_specs:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")
    state = await control_plane.run_now(job_name)
    return {"acknowledged": True, "job": state}


@router.post("/api/v1/control-plane/jobs/{job_name}/pause")
async def pause_control_plane_job(job_name: str) -> dict[str, Any]:
    if job_name not in control_plane.job_specs:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")
    state = await control_plane.pause(job_name)
    return {"acknowledged": True, "job": state}


@router.post("/api/v1/control-plane/jobs/{job_name}/resume")
async def resume_control_plane_job(job_name: str) -> dict[str, Any]:
    if job_name not in control_plane.job_specs:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")
    state = await control_plane.resume(job_name)
    return {"acknowledged": True, "job": state}


@router.websocket("/ws/control-plane")
async def control_plane_ws(websocket: WebSocket) -> None:
    await control_plane.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await control_plane.disconnect(websocket)
    except Exception:
        await control_plane.disconnect(websocket)
