"""Canonical launch-summary contract for the JJ-N revenue-audit lane."""

from __future__ import annotations

from collections.abc import Mapping
import json
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
DEFAULT_OPERATOR_CHECKLIST_PATH = PROJECT_ROOT / "reports" / "nontrading_launch_operator_checklist.json"
CHECKOUT_SESSION_PATH = "/v1/nontrading/checkout/session"
WEBHOOK_PATH = "/v1/nontrading/webhooks/stripe"
ORDER_LOOKUP_PATH = "/v1/nontrading/orders/lookup"
ORDER_STATUS_PATH = "/v1/nontrading/orders/{order_id}"
SCHEMA_VERSION = "revenue_audit_launch_summary.v1"
OPERATOR_CHECKLIST_SCHEMA_VERSION = "revenue_audit_launch_operator_checklist.v1"
DELIVERED_JOB_STATUSES = {"completed", "delivered"}
COMPLETED_MONITOR_STATUS = "completed"
IGNORED_BLOCKING_REASONS = {
    "checkout_surface_not_ready",
    "billing_webhook_not_ready",
}


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


def _success_url_ready(value: str | None) -> bool:
    text = str(value or "").strip()
    return _is_live_http_url(text) and (
        "{CHECKOUT_SESSION_ID}" in text or "session_id=" in text
    )


def _absolute_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _mask_secret(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


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
    lane_method_checks = {
        "collect_candidates": callable(getattr(RevenueAuditAcquisitionBridge, "_collect_candidates", None)),
        "build_artifact": callable(getattr(RevenueAuditAcquisitionBridge, "build_artifact", None)),
    }
    return {
        "manual_close_ready": all(lane_method_checks.values()),
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
        "lane_method_checks": lane_method_checks,
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
    if not bool(summary.get("manual_close_ready")):
        blockers.append("manual_close_lane_not_ready")
    if not bool(summary.get("fulfillment_ready")):
        blockers.append("fulfillment_surface_not_ready")
    return blockers


def _coerce_blocking_reasons(
    raw_blocking: Any,
    *,
    fallback: list[str],
) -> list[str]:
    if isinstance(raw_blocking, (list, tuple)):
        items = [str(item).strip() for item in raw_blocking]
        normalized = [item for item in items if item and item not in IGNORED_BLOCKING_REASONS]
        if normalized:
            return normalized
    return fallback


def _fallback_operator_checklist(
    summary: Mapping[str, Any],
    *,
    output_path: Path,
) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    if not bool(summary.get("checkout_ready")):
        missing.append(
            {
                "key": "checkout_surface",
                "surface": "checkout",
                "detail": "Checkout surface is still missing one or more route or config requirements.",
            }
        )
    if not bool(summary.get("webhook_ready")):
        missing.append(
            {
                "key": "billing_webhook",
                "surface": "webhook",
                "detail": "Stripe webhook surface is still missing route or secret configuration.",
            }
        )
    if not bool(summary.get("manual_close_ready")):
        missing.append(
            {
                "key": "manual_close_lane",
                "surface": "manual_close",
                "detail": "Manual-close staging lane is not available.",
            }
        )
    if not bool(summary.get("fulfillment_ready")):
        missing.append(
            {
                "key": "fulfillment_surface",
                "surface": "fulfillment",
                "detail": "Fulfillment service is not callable or the artifact root is unavailable.",
            }
        )
    return {
        "schema_version": OPERATOR_CHECKLIST_SCHEMA_VERSION,
        "generated_at": str(summary.get("generated_at") or utc_now()),
        "source_artifact": str(output_path),
        "status": "ready" if not missing else "blocked",
        "launchable": bool(summary.get("launchable")),
        "blocking_reasons": list(summary.get("blocking_reasons") or ()),
        "live_offer_url": summary.get("live_offer_url"),
        "missing_requirements": missing,
    }


def coerce_launch_summary(
    payload: Mapping[str, Any] | None,
    *,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    input_artifact: Path | None = None,
    operator_checklist_path: Path = DEFAULT_OPERATOR_CHECKLIST_PATH,
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
            summary["manual_close_ready"]
            and summary["fulfillment_ready"],
        )
    )
    summary["blocking_reasons"] = _coerce_blocking_reasons(
        raw.get("blocking_reasons"),
        fallback=_blocking_reasons(summary),
    )
    raw_operator_checklist = raw.get("operator_checklist")
    if isinstance(raw_operator_checklist, Mapping):
        summary["operator_checklist"] = {
            **raw_operator_checklist,
            "schema_version": str(
                raw_operator_checklist.get("schema_version") or OPERATOR_CHECKLIST_SCHEMA_VERSION
            ),
            "generated_at": str(raw_operator_checklist.get("generated_at") or summary["generated_at"]),
            "source_artifact": str(raw_operator_checklist.get("source_artifact") or operator_checklist_path),
            "status": str(raw_operator_checklist.get("status") or ("ready" if summary["launchable"] else "blocked")),
            "launchable": bool(raw_operator_checklist.get("launchable", summary["launchable"])),
            "blocking_reasons": _coerce_blocking_reasons(
                raw_operator_checklist.get("blocking_reasons"),
                fallback=list(summary["blocking_reasons"]),
            ),
            "live_offer_url": raw_operator_checklist.get("live_offer_url", summary.get("live_offer_url")),
            "missing_requirements": list(raw_operator_checklist.get("missing_requirements") or ()),
        }
    else:
        summary["operator_checklist"] = _fallback_operator_checklist(
            summary,
            output_path=operator_checklist_path,
        )
    return summary


def build_launch_summary(
    *,
    db_path: Path,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    operator_checklist_path: Path = DEFAULT_OPERATOR_CHECKLIST_PATH,
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

    offer_page_url = None
    offer_api_url = None
    if audit_settings.public_base_url_ready and audit_settings.offer_path in route_paths:
        offer_page_url = _absolute_url(audit_settings.public_base_url, audit_settings.offer_path)
    if audit_settings.public_base_url_ready and CHECKOUT_PATH_HINT in route_paths:
        offer_api_url = _absolute_url(audit_settings.public_base_url, CHECKOUT_PATH_HINT)
    live_offer_url = offer_api_url or offer_page_url

    route_checks = {
        "offer_page": audit_settings.offer_path in route_paths,
        "offer_api": CHECKOUT_PATH_HINT in route_paths,
        "checkout_session": CHECKOUT_SESSION_PATH in route_paths,
        "webhook": WEBHOOK_PATH in route_paths,
        "order_lookup": ORDER_LOOKUP_PATH in route_paths,
        "order_status": ORDER_STATUS_PATH in route_paths,
        "success_page": f"{audit_settings.offer_path.rstrip('/')}/success" in route_paths,
        "cancel_page": f"{audit_settings.offer_path.rstrip('/')}/cancel" in route_paths,
    }
    checkout_config = {
        "stripe_secret_configured": _has_value(audit_settings.stripe_secret_key),
        "pricing_configured": bool(audit_settings.pricing),
        "success_url_ready": _success_url_ready(audit_settings.stripe_success_url),
        "cancel_url_ready": _is_live_http_url(audit_settings.stripe_cancel_url),
        "public_base_url_ready": audit_settings.public_base_url_ready,
    }
    webhook_config = {
        "stripe_webhook_secret_configured": _has_value(audit_settings.stripe_webhook_secret),
    }
    checkout_route_ready = bool(route_checks["offer_api"] and route_checks["checkout_session"])
    checkout_ready = bool(
        checkout_route_ready
        and checkout_config["stripe_secret_configured"]
        and checkout_config["success_url_ready"]
        and checkout_config["cancel_url_ready"]
        and live_offer_url
        and checkout_config["pricing_configured"]
    )
    webhook_ready = bool(
        route_checks["webhook"]
        and webhook_config["stripe_webhook_secret_configured"]
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
            "routes": route_checks,
            "offer_surface": {
                "offer_page_url": offer_page_url,
                "offer_api_url": offer_api_url,
                "live_offer_url": live_offer_url,
            },
            "checkout_config": checkout_config,
            "webhook_config": webhook_config,
            "manual_close": {
                "lane_method_checks": manual_close_surface["lane_method_checks"],
                "launch_mode": manual_close_surface["launch_mode"],
                "curated_candidates": manual_close_surface["curated_candidates"],
                "selected_prospects": manual_close_surface["selected_prospects"],
                "selection_overflow": manual_close_surface["selection_overflow"],
                "selection_skips": manual_close_surface["selection_skips"],
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

    missing_requirements: list[dict[str, Any]] = []
    if not route_checks["offer_api"]:
        missing_requirements.append(
            {
                "key": "offer_api_route",
                "surface": "checkout",
                "path": CHECKOUT_PATH_HINT,
                "detail": "Mount the JSON offer route on the hub router.",
            }
        )
    if not route_checks["checkout_session"]:
        missing_requirements.append(
            {
                "key": "checkout_session_route",
                "surface": "checkout",
                "path": CHECKOUT_SESSION_PATH,
                "detail": "Mount the checkout-session POST route on the hub router.",
            }
        )
    if not route_checks["webhook"]:
        missing_requirements.append(
            {
                "key": "stripe_webhook_route",
                "surface": "webhook",
                "path": WEBHOOK_PATH,
                "detail": "Mount the Stripe webhook route on the hub router.",
            }
        )
    if not checkout_config["public_base_url_ready"]:
        missing_requirements.append(
            {
                "key": "public_base_url",
                "surface": "checkout",
                "env": "JJ_N_WEBSITE_GROWTH_AUDIT_PUBLIC_BASE_URL or JJ_REVENUE_PUBLIC_BASE_URL",
                "current_value": audit_settings.public_base_url,
                "detail": "Set a non-placeholder HTTPS base URL that serves the Website Growth Audit offer surface.",
            }
        )
    if not checkout_config["stripe_secret_configured"]:
        missing_requirements.append(
            {
                "key": "stripe_secret_key",
                "surface": "checkout",
                "env": "STRIPE_SECRET_KEY",
                "current_value": _mask_secret(audit_settings.stripe_secret_key),
                "detail": "Configure a Stripe secret key so the offer page can create hosted checkout sessions.",
            }
        )
    if not checkout_config["success_url_ready"]:
        missing_requirements.append(
            {
                "key": "success_url",
                "surface": "checkout",
                "env": "JJ_N_WEBSITE_GROWTH_AUDIT_SUCCESS_URL",
                "current_value": audit_settings.stripe_success_url,
                "detail": "Use an absolute HTTPS success URL on the public host and include {CHECKOUT_SESSION_ID} or session_id=.",
            }
        )
    if not checkout_config["cancel_url_ready"]:
        missing_requirements.append(
            {
                "key": "cancel_url",
                "surface": "checkout",
                "env": "JJ_N_WEBSITE_GROWTH_AUDIT_CANCEL_URL",
                "current_value": audit_settings.stripe_cancel_url,
                "detail": "Use an absolute HTTPS cancel URL on the public host.",
            }
        )
    if not webhook_config["stripe_webhook_secret_configured"]:
        missing_requirements.append(
            {
                "key": "stripe_webhook_secret",
                "surface": "webhook",
                "env": "STRIPE_WEBHOOK_SECRET",
                "current_value": _mask_secret(audit_settings.stripe_webhook_secret),
                "detail": "Configure the Stripe webhook signing secret so paid orders can be verified.",
            }
        )
    summary["operator_checklist"] = {
        "schema_version": OPERATOR_CHECKLIST_SCHEMA_VERSION,
        "generated_at": summary["generated_at"],
        "source_artifact": str(operator_checklist_path),
        "status": "ready" if not missing_requirements else "blocked",
        "launchable": summary["launchable"],
        "blocking_reasons": list(summary["blocking_reasons"]),
        "live_offer_url": live_offer_url,
        "offer_page_url": offer_page_url,
        "offer_api_url": offer_api_url,
        "missing_requirements": missing_requirements,
        "manual_close_context": {
            "launch_mode": manual_close_surface["launch_mode"],
            "curated_candidates": manual_close_surface["curated_candidates"],
            "selected_prospects": manual_close_surface["selected_prospects"],
        },
    }
    return summary


def write_launch_summary_artifact(payload: Mapping[str, Any], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_launch_operator_checklist_artifact(
    payload: Mapping[str, Any],
    output_path: Path = DEFAULT_OPERATOR_CHECKLIST_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
