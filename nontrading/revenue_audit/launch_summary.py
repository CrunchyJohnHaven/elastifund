"""Canonical launch-summary contract for the JJ-N revenue-audit lane."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in some runtime contexts
    load_dotenv = None

from nontrading.config import RevenueAgentSettings
from nontrading.first_dollar import normalize_launch_summary
from nontrading.models import utc_now
from nontrading.revenue_audit.acquisition_bridge import (
    CHECKOUT_PATH_HINT,
    RevenueAuditAcquisitionBridge,
    build_sender_verification,
)
from nontrading.revenue_audit.config import RevenueAuditSettings
from nontrading.revenue_audit.fulfillment import DEFAULT_ARTIFACT_ROOT, RevenueAuditFulfillmentService
from nontrading.revenue_audit.store import RevenueAuditStore
from nontrading.store import RevenueStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "reports" / "nontrading_launch_summary.json"
CHECKOUT_SESSION_PATH = "/v1/nontrading/checkout/session"
WEBHOOK_PATH = "/v1/nontrading/webhooks/stripe"
ORDER_STATUS_PATH = "/v1/nontrading/orders/{order_id}"
SCHEMA_VERSION = "revenue_audit_launch_summary.v1"
DELIVERED_JOB_STATUSES = {"completed", "delivered"}
COMPLETED_MONITOR_STATUS = "completed"


def _load_repo_dotenv() -> None:
    if load_dotenv is None:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _has_value(value: Any) -> bool:
    return bool(str(value or "").strip())


def _is_live_http_url(value: str | None) -> bool:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"example.com", "example.invalid", "localhost"}:
        return False
    return not host.endswith(".invalid")


def _route_paths() -> set[str]:
    try:
        from hub.app.nontrading_api import router
    except Exception:
        return set()
    return {
        str(getattr(route, "path", "")).strip()
        for route in getattr(router, "routes", ())
        if str(getattr(route, "path", "")).strip()
    }


def _artifact_root() -> Path:
    root = Path(DEFAULT_ARTIFACT_ROOT)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root


def _manual_close_surface(
    *,
    db_path: Path,
    revenue_settings: RevenueAgentSettings,
) -> dict[str, Any]:
    store = RevenueStore(db_path)
    bridge = RevenueAuditAcquisitionBridge(store, revenue_settings)
    sender_verification = build_sender_verification(revenue_settings)
    launch_mode = "approval_queue_only" if sender_verification.live_send_eligible else "manual_close_only"
    selection = bridge._collect_candidates(launch_mode=launch_mode)
    selected_prospects = min(len(selection.candidates), bridge.max_prospects)
    return {
        "manual_close_ready": selected_prospects > 0,
        "launch_mode": launch_mode,
        "curated_candidates": len(selection.candidates),
        "selected_prospects": selected_prospects,
        "selection_overflow": max(len(selection.candidates) - selected_prospects, 0),
        "selection_skips": {
            "uncurated": selection.skipped_uncurated,
            "non_us": selection.skipped_non_us,
            "missing_contact": selection.skipped_missing_contact,
            "missing_evidence": selection.skipped_missing_evidence,
        },
        "sender_verification": sender_verification.to_dict(),
    }


def _fulfillment_surface() -> dict[str, Any]:
    artifact_root = _artifact_root()
    artifact_root.mkdir(parents=True, exist_ok=True)
    method_checks = {
        "fulfill_order": callable(getattr(RevenueAuditFulfillmentService, "fulfill_order", None)),
        "run_monitor": callable(getattr(RevenueAuditFulfillmentService, "run_monitor", None)),
    }
    return {
        "fulfillment_ready": all(method_checks.values()) and artifact_root.exists(),
        "artifact_root": str(artifact_root),
        "method_checks": method_checks,
    }


def _blocking_reasons(summary: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not bool(summary.get("checkout_ready")):
        blockers.append("checkout_surface_not_ready")
    if not bool(summary.get("webhook_ready")):
        blockers.append("billing_webhook_not_ready")
    if not bool(summary.get("manual_close_ready")):
        blockers.append("manual_close_lane_not_ready")
    if not bool(summary.get("fulfillment_ready")):
        blockers.append("fulfillment_surface_not_ready")
    return blockers


def coerce_launch_summary(
    payload: Mapping[str, Any] | None,
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    input_artifact: Path | None = None,
) -> dict[str, Any]:
    raw = dict(payload or {})
    normalized = normalize_launch_summary(raw)
    summary = {
        **raw,
        **normalized,
        "schema_version": str(raw.get("schema_version") or SCHEMA_VERSION),
        "generated_at": str(raw.get("generated_at") or utc_now()),
        "source_artifact": str(output_path),
    }
    if input_artifact is not None:
        summary["input_artifact"] = str(input_artifact)
    summary["launchable"] = bool(
        raw.get(
            "launchable",
            summary["checkout_ready"]
            and summary["webhook_ready"]
            and summary["manual_close_ready"]
            and summary["fulfillment_ready"],
        )
    )
    summary["blocking_reasons"] = list(raw.get("blocking_reasons") or _blocking_reasons(summary))
    return summary


def build_launch_summary(
    *,
    db_path: Path,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    _load_repo_dotenv()
    audit_settings = RevenueAuditSettings.from_env()
    revenue_settings = RevenueAgentSettings.from_env()
    route_paths = _route_paths()
    audit_store = RevenueAuditStore(db_path)

    checkout_sessions = audit_store.list_checkout_sessions()
    orders = audit_store.list_orders()
    paid_orders = [order for order in orders if str(order.status).strip().lower() == "paid"]
    fulfillment_jobs = audit_store.list_fulfillment_jobs()
    delivered_jobs = [
        job for job in fulfillment_jobs if str(job.status).strip().lower() in DELIVERED_JOB_STATUSES
    ]
    monitor_runs = audit_store.list_monitor_runs()
    completed_monitor_runs = [
        run for run in monitor_runs if str(run.status).strip().lower() == COMPLETED_MONITOR_STATUS
    ]

    manual_close_surface = _manual_close_surface(
        db_path=db_path,
        revenue_settings=revenue_settings,
    )
    fulfillment_surface = _fulfillment_surface()

    live_offer_url = None
    if _is_live_http_url(revenue_settings.public_base_url) and CHECKOUT_PATH_HINT in route_paths:
        live_offer_url = urljoin(
            revenue_settings.public_base_url.rstrip("/") + "/",
            CHECKOUT_PATH_HINT.lstrip("/"),
        )

    checkout_route_ready = (
        CHECKOUT_PATH_HINT in route_paths
        and CHECKOUT_SESSION_PATH in route_paths
        and ORDER_STATUS_PATH in route_paths
    )
    checkout_ready = bool(
        checkout_route_ready
        and _has_value(audit_settings.stripe_secret_key)
        and _is_live_http_url(audit_settings.stripe_success_url)
        and _is_live_http_url(audit_settings.stripe_cancel_url)
        and live_offer_url
        and audit_settings.pricing
    )
    webhook_ready = bool(
        WEBHOOK_PATH in route_paths
        and ORDER_STATUS_PATH in route_paths
        and _has_value(audit_settings.stripe_webhook_secret)
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "checkout_ready": checkout_ready,
        "webhook_ready": webhook_ready,
        "manual_close_ready": manual_close_surface["manual_close_ready"],
        "fulfillment_ready": fulfillment_surface["fulfillment_ready"],
        "checkout_sessions_created": len(checkout_sessions),
        "orders_recorded": len(orders),
        "paid_orders_seen": len(paid_orders),
        "paid_revenue_usd": round(sum(float(order.amount_total_usd) for order in paid_orders), 2),
        "delivery_artifacts_generated": len(delivered_jobs),
        "monitor_runs_completed": len(completed_monitor_runs),
        "live_offer_url": live_offer_url,
        "source_artifact": str(output_path),
        "launch_mode": manual_close_surface["launch_mode"],
        "curated_candidates": manual_close_surface["curated_candidates"],
        "selected_prospects": manual_close_surface["selected_prospects"],
        "selection_overflow": manual_close_surface["selection_overflow"],
        "selection_skips": manual_close_surface["selection_skips"],
        "sender_verification": manual_close_surface["sender_verification"],
        "surface_checks": {
            "routes": {
                "offer": CHECKOUT_PATH_HINT in route_paths,
                "checkout_session": CHECKOUT_SESSION_PATH in route_paths,
                "webhook": WEBHOOK_PATH in route_paths,
                "order_status": ORDER_STATUS_PATH in route_paths,
            },
            "checkout_config": {
                "stripe_secret_configured": _has_value(audit_settings.stripe_secret_key),
                "pricing_configured": bool(audit_settings.pricing),
                "success_url_ready": _is_live_http_url(audit_settings.stripe_success_url),
                "cancel_url_ready": _is_live_http_url(audit_settings.stripe_cancel_url),
                "public_base_url_ready": _is_live_http_url(revenue_settings.public_base_url),
            },
            "webhook_config": {
                "stripe_webhook_secret_configured": _has_value(audit_settings.stripe_webhook_secret),
            },
            "fulfillment": fulfillment_surface,
        },
    }
    summary["launchable"] = bool(
        summary["checkout_ready"]
        and summary["webhook_ready"]
        and summary["manual_close_ready"]
        and summary["fulfillment_ready"]
    )
    summary["blocking_reasons"] = _blocking_reasons(summary)
    return summary


def write_launch_summary_artifact(payload: Mapping[str, Any], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
