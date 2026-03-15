from __future__ import annotations

from collections import Counter
from typing import Any

from inventory.catalog import catalog_metadata, get_run, get_system, list_runs, list_systems, runs_metadata
from inventory.methodology import BENCHMARK_SPEC_VERSION, methodology_payload


def _filter_systems(
    category: str | None = None,
    benchmark_status: str | None = None,
    maintenance_status: str | None = None,
) -> list[dict[str, Any]]:
    systems = list_systems()
    if category:
        systems = [item for item in systems if item["category"] == category]
    if benchmark_status:
        systems = [item for item in systems if item["benchmark_status"] == benchmark_status]
    if maintenance_status:
        systems = [item for item in systems if item["maintenance_status"] == maintenance_status]
    return systems


def _enrich_run(run: dict[str, Any]) -> dict[str, Any]:
    system = get_system(run["system_id"])
    enriched = dict(run)
    if system is not None:
        enriched["system_name"] = system["name"]
        enriched["system_category"] = system["category"]
        enriched["system_tier"] = system["tier"]
    return enriched


def _paper_state_for_run(run: dict[str, Any]) -> dict[str, Any]:
    system = get_system(run["system_id"])
    paper = dict(run.get("paper_status", {}))
    return {
        "run_id": run["id"],
        "system_id": run["system_id"],
        "system_name": system["name"] if system else run["system_id"],
        "bot_id": run["system_id"],
        "bot_name": system["name"] if system else run["system_id"],
        "state": paper.get("state", "not_started"),
        "execution_label": run["execution_label"],
        "last_heartbeat": paper.get("last_heartbeat"),
        "last_error": paper.get("last_error"),
        "status_note": run.get("status_note"),
    }


def list_systems_payload(
    category: str | None = None,
    benchmark_status: str | None = None,
    maintenance_status: str | None = None,
) -> dict[str, Any]:
    meta = catalog_metadata()
    systems = _filter_systems(
        category=category,
        benchmark_status=benchmark_status,
        maintenance_status=maintenance_status,
    )
    return {
        "as_of": meta["captured_at"],
        "methodology_version": BENCHMARK_SPEC_VERSION,
        "filters": {
            "category": category,
            "benchmark_status": benchmark_status,
            "maintenance_status": maintenance_status,
        },
        "summary": {
            "total": len(systems),
            "by_category": dict(Counter(item["category"] for item in systems)),
            "by_status": dict(Counter(item["benchmark_status"] for item in systems)),
        },
        "items": systems,
    }


def system_detail_payload(system_id: str) -> dict[str, Any]:
    system = get_system(system_id)
    if system is None:
        raise LookupError(f"unknown system: {system_id}")
    related_runs = [_enrich_run(run) for run in list_runs() if run["system_id"] == system_id]
    latest_run = related_runs[0] if related_runs else None
    return {
        "as_of": catalog_metadata()["captured_at"],
        "methodology_version": BENCHMARK_SPEC_VERSION,
        "methodology": methodology_payload(),
        "system": system,
        "bot": system,
        "latest_run": latest_run,
        "runs": related_runs,
        "paper_status": _paper_state_for_run(latest_run) if latest_run else None,
    }


def rankings_payload(
    category: str | None = None,
    track: str | None = None,
    window: str = "30d",
) -> dict[str, Any]:
    systems = {system["id"]: system for system in list_systems()}
    entries: list[dict[str, Any]] = []
    for run in list_runs():
        system = systems.get(run["system_id"])
        if system is None:
            continue
        if category and system["category"] != category:
            continue
        if track and run["track"] != track:
            continue
        overall_score = run.get("score_breakdown", {}).get("overall")
        if run["status"] != "completed" or overall_score is None:
            continue
        entries.append(
            {
                "system_id": system["id"],
                "system_name": system["name"],
                "bot_id": system["id"],
                "bot_name": system["name"],
                "category": system["category"],
                "track": run["track"],
                "run_id": run["id"],
                "overall_score": overall_score,
                "score_breakdown": run["score_breakdown"],
            }
        )
    entries.sort(key=lambda item: item["overall_score"], reverse=True)
    for index, item in enumerate(entries, start=1):
        item["rank"] = index
    state = "active" if entries else "methodology_only"
    return {
        "as_of": runs_metadata()["as_of"],
        "methodology_version": BENCHMARK_SPEC_VERSION,
        "state": state,
        "filters": {"category": category, "track": track, "window": window},
        "message": (
            "Methodology is published. Rankings will populate after Tier-1 T0-T5 runs complete."
            if not entries
            else "Rankings are based on completed benchmark runs only."
        ),
        "items": entries,
    }


def runs_payload(
    system_id: str | None = None,
    status: str | None = None,
    bot_id: str | None = None,
) -> dict[str, Any]:
    if system_id and bot_id and system_id != bot_id:
        raise ValueError("system_id and bot_id must match when both are provided")
    selected_system_id = system_id or bot_id
    runs = [_enrich_run(run) for run in list_runs()]
    if selected_system_id:
        runs = [run for run in runs if run["system_id"] == selected_system_id]
    if status:
        runs = [run for run in runs if run["status"] == status]
    if selected_system_id is None:
        runs = [
            run
            for run in runs
            if not bool(run.get("comparison_mode") == "comparison_only" or run.get("allocator_eligible") is False)
        ]
    return {
        "as_of": runs_metadata()["as_of"],
        "state": runs_metadata()["state"],
        "methodology_version": BENCHMARK_SPEC_VERSION,
        "filters": {"system_id": selected_system_id, "bot_id": selected_system_id, "status": status},
        "total": len(runs),
        "items": runs,
    }


def run_artifacts_payload(run_id: str) -> dict[str, Any]:
    run = get_run(run_id)
    if run is None:
        raise LookupError(f"unknown run: {run_id}")
    return {
        "as_of": runs_metadata()["as_of"],
        "methodology_version": BENCHMARK_SPEC_VERSION,
        "run_id": run_id,
        "status": run["status"],
        "artifact_state": "published" if run.get("artifacts") else "not_available",
        "artifacts": run.get("artifacts", []),
        "status_note": run.get("status_note"),
    }


def paper_status_payload(system_id: str | None = None, bot_id: str | None = None) -> dict[str, Any]:
    if system_id and bot_id and system_id != bot_id:
        raise ValueError("system_id and bot_id must match when both are provided")
    selected_system_id = system_id or bot_id
    runs = list_runs()
    if selected_system_id:
        runs = [run for run in runs if run["system_id"] == selected_system_id]
    items = [_paper_state_for_run(run) for run in runs]
    overall_state = "running" if any(item["state"] == "running" for item in items) else "not_started"
    return {
        "as_of": runs_metadata()["as_of"],
        "methodology_version": BENCHMARK_SPEC_VERSION,
        "state": overall_state,
        "filters": {"system_id": selected_system_id, "bot_id": selected_system_id},
        "message": (
            "Paper status remains not started until the planned Tier-1 runs move out of queue."
            if not items or overall_state == "not_started"
            else "At least one benchmark paper run is active."
        ),
        "items": items,
    }


# Compatibility aliases: retained while API consumers migrate from bot_* naming.
def list_bots_payload(
    category: str | None = None,
    benchmark_status: str | None = None,
    maintenance_status: str | None = None,
) -> dict[str, Any]:
    return list_systems_payload(
        category=category,
        benchmark_status=benchmark_status,
        maintenance_status=maintenance_status,
    )


def bot_detail_payload(bot_id: str) -> dict[str, Any]:
    try:
        return system_detail_payload(bot_id)
    except LookupError as exc:
        raise LookupError(f"unknown bot: {bot_id}") from exc
