"""Peer improvement bundle exchange for cross-fork learning."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy.orm import Session

from data_layer import crud

from .intelligence import FindingSpec, TaskSpec, record_finding_with_task

DEFAULT_REVIEW_ROOT = Path("reports") / "flywheel" / "peer_improvements"
DEFAULT_KNOWLEDGE_PACK_REVIEW_ROOT = Path("reports") / "flywheel" / "knowledge_packs"

_KNOWLEDGE_PACK_SCHEMA_VERSION = 1
_SAFE_LITERAL_FIELDS = {
    "artifact_uri",
    "captured_at",
    "channel",
    "compliance_status",
    "detector_family",
    "detector_key",
    "engine_family",
    "engine_key",
    "engine_version",
    "environment",
    "generated_by",
    "issue_type",
    "lane",
    "proof_type",
    "ref_key",
    "scope",
    "sha256",
    "status",
    "template_key",
    "variant",
}
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PAYMENT_TOKEN_RE = re.compile(r"\b(?:cs|ch|pi|pm|in)_[A-Za-z0-9_]+\b")
_LONG_NUMBER_RE = re.compile(r"\b(?:\d[ -]?){12,19}\b")
_BLOCKED_KNOWLEDGE_KEYS = {
    "address",
    "billing_address",
    "card_brand",
    "card_last4",
    "card_number",
    "checkout_session_id",
    "customer_email",
    "customer_id",
    "customer_identity",
    "customer_name",
    "email",
    "first_name",
    "full_name",
    "identity",
    "inbox_body",
    "inbox_content",
    "inbox_subject",
    "last_name",
    "message_body",
    "message_subject",
    "payment_details",
    "payment_id",
    "payment_intent_id",
    "phone",
    "raw_customer_identity",
    "raw_inbox_content",
    "raw_payment_details",
    "transaction_id",
}
_ENGINE_METADATA_FIELDS = {
    "compliance_status",
    "engine_family",
    "environment",
    "generated_by",
    "lane",
    "observed_end_at",
    "observed_start_at",
    "sample_size",
    "status",
    "summary",
}
_DETECTOR_SUMMARY_FIELDS = {
    "avg_revenue_usd",
    "avg_severity",
    "confidence",
    "conversion_rate",
    "detector_family",
    "detector_key",
    "issue_type",
    "proof_refs",
    "recall",
    "refund_rate",
    "sample_size",
    "status",
    "summary",
}
_TEMPLATE_VARIANT_FIELDS = {
    "avg_order_value_usd",
    "channel",
    "conversion_rate",
    "net_revenue_usd",
    "proof_refs",
    "refund_rate",
    "sample_size",
    "status",
    "summary",
    "template_key",
    "variant",
}
_AGGREGATED_OUTCOME_FIELDS = {
    "audits_purchased",
    "avg_fulfillment_hours",
    "chargeback_rate",
    "churn_rate",
    "complaint_rate",
    "conversion_rate",
    "expected_net_cash_30d",
    "fulfillments_completed",
    "gross_margin_pct",
    "gross_revenue_usd",
    "net_revenue_usd",
    "observed_count",
    "prospects_scanned",
    "refund_count",
    "refund_rate",
    "refunds_usd",
}
_PENALTY_FIELDS = {
    "complaint_penalty",
    "compliance_penalty",
    "domain_health_penalty",
    "fulfillment_penalty",
    "refund_penalty",
    "score_penalty_total",
}
_PROOF_REFERENCE_FIELDS = {
    "artifact_uri",
    "captured_at",
    "notes",
    "proof_type",
    "ref_key",
    "scope",
    "sha256",
}


def export_improvement_bundle(
    session: Session,
    *,
    peer_name: str,
    strategy_key: str,
    version_label: str,
    include_paths: Sequence[str | Path],
    outcome: str = "mixed",
    summary: str | None = None,
    hypothesis: str | None = None,
    repo_root: str | Path = ".",
    output_path: str | Path | None = None,
    signing_secret: str | None = None,
    base_ref: str = "HEAD",
) -> dict[str, Any]:
    """Create a portable improvement bundle with code, claims, and evidence."""

    if not include_paths:
        raise ValueError("include_paths must contain at least one file")

    version = crud.get_strategy_version(session, strategy_key, version_label)
    if version is None:
        raise RuntimeError(
            f"Unknown strategy version: {strategy_key}:{version_label}. "
            "Register or run the strategy locally before exporting a peer bundle."
        )

    snapshot = crud.get_latest_snapshot(session, strategy_version_id=version.id)
    decision = next(
        iter(crud.list_promotion_decisions(session, strategy_version_id=version.id, limit=1)),
        None,
    )

    repo_root_path = Path(repo_root).resolve()
    files = _collect_code_files(include_paths, repo_root_path)
    patch_text = _build_patch(repo_root_path, [row["path"] for row in files], base_ref=base_ref)
    generated_at = datetime.now(timezone.utc).isoformat()
    bundle_id = _bundle_id(peer_name, strategy_key, version_label, generated_at)

    body = {
        "bundle_id": bundle_id,
        "bundle_type": "peer_improvement",
        "schema_version": 1,
        "peer_name": peer_name,
        "generated_at": generated_at,
        "claim": {
            "outcome": outcome,
            "summary": summary or _default_summary(decision, snapshot, strategy_key, version_label),
            "hypothesis": hypothesis,
        },
        "strategy": {
            "strategy_key": version.strategy_key,
            "version_label": version.version_label,
            "lane": version.lane,
            "artifact_uri": version.artifact_uri,
            "git_sha": version.git_sha,
            "config": version.config,
        },
        "evidence": {
            "latest_snapshot": _snapshot_dict(snapshot),
            "latest_decision": _decision_dict(decision),
        },
        "code": {
            "repo_root_label": str(repo_root_path),
            "base_ref": base_ref,
            "patch_diff": patch_text,
            "files": files,
        },
    }
    bundle = _attach_integrity(body, signing_secret)

    write_path = write_improvement_bundle(bundle, output_path) if output_path else None
    verification_status = "signed" if signing_secret else "unsigned"
    record = crud.get_peer_improvement_bundle(session, bundle_id, direction="exported")
    if record is None:
        crud.create_peer_improvement_bundle(
            session,
            bundle_id=bundle_id,
            peer_name=peer_name,
            strategy_key=version.strategy_key,
            version_label=version.version_label,
            lane=version.lane,
            outcome=outcome,
            direction="exported",
            verification_status=verification_status,
            status="recorded",
            summary=bundle["claim"]["summary"],
            hypothesis=hypothesis,
            bundle_sha256=bundle["integrity"]["bundle_sha256"],
            signature_hmac_sha256=bundle["integrity"].get("signature_hmac_sha256"),
            review_artifact_path=str(write_path) if write_path else None,
            raw_bundle=bundle,
        )
        session.commit()

    return bundle


def import_improvement_bundle(
    session: Session,
    bundle: dict[str, Any],
    *,
    review_root: str | Path = DEFAULT_REVIEW_ROOT,
    signing_secret: str | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    """Verify, store, and materialize a peer improvement bundle for local review."""

    verification = verify_improvement_bundle(
        bundle,
        signing_secret=signing_secret,
        require_signature=require_signature,
    )
    bundle_id = bundle["bundle_id"]
    existing = crud.get_peer_improvement_bundle(session, bundle_id, direction="imported")
    if existing is not None:
        return {
            "bundle_id": bundle_id,
            "cycle_key": f"improvement-{bundle_id}",
            "tasks_created": 0,
            "already_imported": True,
            "verification_status": existing.verification_status,
            "review_dir": existing.review_artifact_path,
        }

    cycle_key = f"improvement-{bundle_id}"
    cycle = crud.get_flywheel_cycle(session, cycle_key)
    if cycle is None:
        cycle = crud.create_flywheel_cycle(
            session,
            cycle_key=cycle_key,
            status="completed",
            summary=f"Imported peer improvement bundle from {bundle['peer_name']}",
        )

    review_dir = Path(review_root) / bundle_id
    write_review_packet(review_dir, bundle, verification)

    crud.create_peer_improvement_bundle(
        session,
        bundle_id=bundle_id,
        peer_name=bundle["peer_name"],
        strategy_key=bundle["strategy"]["strategy_key"],
        version_label=bundle["strategy"]["version_label"],
        lane=bundle["strategy"].get("lane"),
        outcome=bundle["claim"]["outcome"],
        direction="imported",
        verification_status=verification["verification_status"],
        status="review_pending",
        summary=bundle["claim"].get("summary"),
        hypothesis=bundle["claim"].get("hypothesis"),
        bundle_sha256=verification["bundle_sha256"],
        signature_hmac_sha256=bundle.get("integrity", {}).get("signature_hmac_sha256"),
        review_artifact_path=str(review_dir),
        cycle_id=cycle.id,
        raw_bundle=bundle,
    )

    record_finding_with_task(
        session,
        finding=FindingSpec(
            finding_key=f"peer_improvement:{bundle_id}",
            cycle_id=cycle.id,
            strategy_version_id=None,
            lane=bundle["strategy"].get("lane"),
            environment=None,
            source_kind="peer_improvement",
            finding_type="peer_improvement",
            title=f"Peer improvement from {bundle['peer_name']}: {bundle['strategy']['strategy_key']}",
            summary=_task_details(bundle, verification),
            lesson="Peer code should enter bounded local replay before any paper or live adoption.",
            evidence={
                "bundle_id": bundle_id,
                "verification": verification,
                "claim": bundle.get("claim", {}),
                "strategy": bundle.get("strategy", {}),
                "review_dir": str(review_dir),
            },
            priority=_task_priority(bundle["claim"]["outcome"]),
            confidence=None,
            status="open",
        ),
        task=TaskSpec(
            cycle_id=cycle.id,
            strategy_version_id=None,
            action="recommend",
            title=_task_title(bundle),
            details=_task_details(bundle, verification),
            priority=_task_priority(bundle["claim"]["outcome"]),
            status="open",
            lane=bundle["strategy"].get("lane"),
            environment=None,
            source_kind="peer_improvement",
            source_ref=bundle_id,
            metadata={
                "bundle_id": bundle_id,
                "review_dir": str(review_dir),
                "verification_status": verification["verification_status"],
            },
        ),
    )
    session.commit()

    return {
        "bundle_id": bundle_id,
        "cycle_key": cycle_key,
        "tasks_created": 1,
        "already_imported": False,
        "verification_status": verification["verification_status"],
        "review_dir": str(review_dir),
    }


def publish_knowledge_pack(
    session: Session,
    *,
    peer_name: str,
    engine_key: str,
    engine_version: str,
    engine_metadata: dict[str, Any] | None = None,
    detector_summaries: Sequence[dict[str, Any]] | None = None,
    template_variants: Sequence[dict[str, Any]] | None = None,
    aggregated_outcomes: dict[str, Any] | None = None,
    penalty_metrics: dict[str, Any] | None = None,
    proof_references: Sequence[dict[str, Any]] | None = None,
    output_path: str | Path | None = None,
    signing_secret: str | None = None,
) -> dict[str, Any]:
    """Publish a sanitized non-trading knowledge pack for peer sharing."""

    generated_at = datetime.now(timezone.utc).isoformat()
    bundle_id = _bundle_id(peer_name, engine_key, engine_version, generated_at)

    sanitized_engine, redactions = _sanitize_knowledge_mapping(
        engine_metadata or {},
        allowed_fields=_ENGINE_METADATA_FIELDS,
    )
    sanitized_engine["engine_key"] = _sanitize_public_value("engine_key", engine_key)
    sanitized_engine["engine_version"] = _sanitize_public_value("engine_version", engine_version)
    sanitized_engine.setdefault("engine_family", "non_trading")
    sanitized_engine.setdefault("lane", "revenue_audit")

    sanitized_detectors, detector_redactions = _sanitize_knowledge_rows(
        detector_summaries or [],
        allowed_fields=_DETECTOR_SUMMARY_FIELDS,
    )
    redactions.update(detector_redactions)

    sanitized_templates, template_redactions = _sanitize_knowledge_rows(
        template_variants or [],
        allowed_fields=_TEMPLATE_VARIANT_FIELDS,
    )
    redactions.update(template_redactions)

    sanitized_outcomes, outcome_redactions = _sanitize_knowledge_mapping(
        aggregated_outcomes or {},
        allowed_fields=_AGGREGATED_OUTCOME_FIELDS,
    )
    redactions.update(outcome_redactions)

    sanitized_penalties, penalty_redactions = _sanitize_knowledge_mapping(
        penalty_metrics or {},
        allowed_fields=_PENALTY_FIELDS,
    )
    redactions.update(penalty_redactions)
    sanitized_penalties["score_penalty_total"] = _knowledge_penalty_total(sanitized_penalties)

    sanitized_proofs, proof_redactions = _sanitize_knowledge_rows(
        proof_references or [],
        allowed_fields=_PROOF_REFERENCE_FIELDS,
    )
    redactions.update(proof_redactions)

    if "sample_size" not in sanitized_engine:
        sample_size = int(
            sanitized_outcomes.get("observed_count")
            or sanitized_outcomes.get("audits_purchased")
            or len(sanitized_templates)
            or len(sanitized_detectors)
            or 0
        )
        sanitized_engine["sample_size"] = sample_size

    body = {
        "bundle_id": bundle_id,
        "bundle_type": "knowledge_pack",
        "schema_version": _KNOWLEDGE_PACK_SCHEMA_VERSION,
        "peer_name": peer_name,
        "generated_at": generated_at,
        "engine": sanitized_engine,
        "detector_summaries": sanitized_detectors,
        "template_variants": sanitized_templates,
        "aggregated_outcomes": sanitized_outcomes,
        "penalty_metrics": sanitized_penalties,
        "proof_references": sanitized_proofs,
        "privacy": {
            "raw_customer_data_included": False,
            "redaction_counts": dict(sorted(redactions.items())),
        },
    }
    body["leaderboard_entry"] = build_knowledge_pack_leaderboard_entry(body)
    pack = _attach_integrity(body, signing_secret)

    write_path = write_knowledge_pack(pack, output_path) if output_path else None
    verification_status = "signed" if signing_secret else "unsigned"
    record = crud.get_peer_improvement_bundle(session, bundle_id, direction="exported")
    if record is None:
        crud.create_peer_improvement_bundle(
            session,
            bundle_id=bundle_id,
            peer_name=peer_name,
            strategy_key=engine_key,
            version_label=engine_version,
            lane=sanitized_engine.get("lane"),
            outcome="knowledge_pack",
            direction="exported",
            verification_status=verification_status,
            status="recorded",
            summary=sanitized_engine.get("summary"),
            hypothesis=None,
            bundle_sha256=pack["integrity"]["bundle_sha256"],
            signature_hmac_sha256=pack["integrity"].get("signature_hmac_sha256"),
            review_artifact_path=str(write_path) if write_path else None,
            raw_bundle=pack,
        )
        session.commit()

    return pack


def pull_knowledge_pack(
    session: Session,
    bundle: dict[str, Any],
    *,
    review_root: str | Path = DEFAULT_KNOWLEDGE_PACK_REVIEW_ROOT,
    signing_secret: str | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    """Verify, store, and materialize a peer knowledge pack for local review."""

    verification = verify_knowledge_pack(
        bundle,
        signing_secret=signing_secret,
        require_signature=require_signature,
    )
    bundle_id = bundle["bundle_id"]
    existing = crud.get_peer_improvement_bundle(session, bundle_id, direction="imported")
    if existing is not None:
        return {
            "bundle_id": bundle_id,
            "cycle_key": f"knowledge-{bundle_id}",
            "tasks_created": 0,
            "already_imported": True,
            "verification_status": existing.verification_status,
            "review_dir": existing.review_artifact_path,
        }

    cycle_key = f"knowledge-{bundle_id}"
    cycle = crud.get_flywheel_cycle(session, cycle_key)
    if cycle is None:
        cycle = crud.create_flywheel_cycle(
            session,
            cycle_key=cycle_key,
            status="completed",
            summary=f"Pulled knowledge pack from {bundle['peer_name']}",
        )

    review_dir = Path(review_root) / bundle_id
    write_knowledge_pack_review_packet(review_dir, bundle, verification)
    entry = build_knowledge_pack_leaderboard_entry(
        bundle,
        verification_status=verification["verification_status"],
    )

    crud.create_peer_improvement_bundle(
        session,
        bundle_id=bundle_id,
        peer_name=bundle["peer_name"],
        strategy_key=bundle["engine"]["engine_key"],
        version_label=bundle["engine"]["engine_version"],
        lane=bundle["engine"].get("lane"),
        outcome="knowledge_pack",
        direction="imported",
        verification_status=verification["verification_status"],
        status="review_pending",
        summary=bundle["engine"].get("summary"),
        hypothesis=None,
        bundle_sha256=verification["bundle_sha256"],
        signature_hmac_sha256=bundle.get("integrity", {}).get("signature_hmac_sha256"),
        review_artifact_path=str(review_dir),
        cycle_id=cycle.id,
        raw_bundle=bundle,
    )

    record_finding_with_task(
        session,
        finding=FindingSpec(
            finding_key=f"peer_knowledge_pack:{bundle_id}",
            cycle_id=cycle.id,
            strategy_version_id=None,
            lane=bundle["engine"].get("lane"),
            environment=bundle["engine"].get("environment"),
            source_kind="knowledge_pack",
            finding_type="peer_knowledge_pack",
            title=(
                f"Knowledge pack from {bundle['peer_name']}: "
                f"{bundle['engine']['engine_key']}:{bundle['engine']['engine_version']}"
            ),
            summary=_knowledge_pack_task_details(bundle, verification),
            lesson=(
                "Only sanitized outcomes and proof hashes should be federated; raw customer"
                " data stays local by design."
            ),
            evidence={
                "bundle_id": bundle_id,
                "verification": verification,
                "leaderboard_entry": entry,
                "review_dir": str(review_dir),
            },
            priority=_knowledge_pack_priority(entry),
            confidence=None,
            status="open",
        ),
        task=TaskSpec(
            cycle_id=cycle.id,
            strategy_version_id=None,
            action="recommend",
            title=_knowledge_pack_task_title(bundle),
            details=_knowledge_pack_task_details(bundle, verification),
            priority=_knowledge_pack_priority(entry),
            status="open",
            lane=bundle["engine"].get("lane"),
            environment=bundle["engine"].get("environment"),
            source_kind="knowledge_pack",
            source_ref=bundle_id,
            metadata={
                "bundle_id": bundle_id,
                "review_dir": str(review_dir),
                "verification_status": verification["verification_status"],
                "leaderboard_entry": entry,
            },
        ),
    )
    session.commit()

    return {
        "bundle_id": bundle_id,
        "cycle_key": cycle_key,
        "tasks_created": 1,
        "already_imported": False,
        "verification_status": verification["verification_status"],
        "review_dir": str(review_dir),
    }


def verify_knowledge_pack(
    bundle: dict[str, Any],
    *,
    signing_secret: str | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    """Verify integrity, schema, and optional signature for a knowledge pack."""

    _validate_knowledge_pack_schema(bundle)

    integrity = bundle.get("integrity") or {}
    body = _bundle_body(bundle)
    canonical = _canonical_json(body)
    expected_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if integrity.get("bundle_sha256") != expected_sha:
        raise ValueError("Knowledge pack SHA256 mismatch")

    signature = integrity.get("signature_hmac_sha256")
    if signature:
        if signing_secret is None:
            verification_status = "signature_unchecked"
        else:
            expected_signature = _sign_body(body, signing_secret)
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("Invalid knowledge pack signature")
            verification_status = "verified"
    else:
        if require_signature:
            raise ValueError("Signature required but knowledge pack is unsigned")
        verification_status = "unsigned"

    return {
        "bundle_sha256": expected_sha,
        "verification_status": verification_status,
        "detector_count": len(bundle.get("detector_summaries", [])),
        "template_count": len(bundle.get("template_variants", [])),
        "proof_count": len(bundle.get("proof_references", [])),
    }


def write_knowledge_pack(bundle: dict[str, Any], output_path: str | Path) -> str:
    """Write a knowledge pack to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    return str(path)


def load_knowledge_pack(path: str | Path) -> dict[str, Any]:
    """Load a knowledge pack from JSON."""

    return json.loads(Path(path).read_text())


def write_knowledge_pack_review_packet(
    review_dir: str | Path,
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, str]:
    """Materialize a local review packet from a peer knowledge pack."""

    root = Path(review_dir)
    root.mkdir(parents=True, exist_ok=True)

    bundle_path = root / "knowledge_pack.json"
    review_md_path = root / "review.md"
    leaderboard_json_path = root / "leaderboard.json"
    leaderboard_md_path = root / "leaderboard.md"

    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    review_md_path.write_text(render_knowledge_pack_review_markdown(bundle, verification))
    leaderboard_json_path.write_text(
        json.dumps(
            build_knowledge_pack_leaderboard_entry(
                bundle,
                verification_status=verification["verification_status"],
            ),
            indent=2,
            sort_keys=True,
        )
    )
    leaderboard_md_path.write_text(
        render_knowledge_pack_leaderboard_markdown(bundle, verification)
    )

    return {
        "bundle_json": str(bundle_path),
        "review_md": str(review_md_path),
        "leaderboard_json": str(leaderboard_json_path),
        "leaderboard_md": str(leaderboard_md_path),
    }


def render_knowledge_pack_review_markdown(
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> str:
    """Render a local review checklist for a peer knowledge pack."""

    engine = bundle["engine"]
    outcomes = bundle["aggregated_outcomes"]
    penalties = bundle["penalty_metrics"]
    entry = build_knowledge_pack_leaderboard_entry(
        bundle,
        verification_status=verification["verification_status"],
    )
    lines = [
        "# Peer Knowledge Pack Review Packet",
        "",
        f"- Bundle: `{bundle['bundle_id']}`",
        f"- Peer: `{bundle['peer_name']}`",
        f"- Engine: `{engine['engine_key']}:{engine['engine_version']}`",
        f"- Verification: `{verification['verification_status']}`",
        f"- Bundle SHA256: `{verification['bundle_sha256']}`",
        "",
        "## Sanitized Scope",
        "",
        engine.get("summary") or "No summary provided.",
        "",
        f"- Lane: `{engine.get('lane') or 'n/a'}`",
        f"- Environment: `{engine.get('environment') or 'n/a'}`",
        f"- Sample size: `{engine.get('sample_size')}`",
        f"- Raw customer data included: `{bundle['privacy']['raw_customer_data_included']}`",
        "",
        "## Outcome Scorecard",
        "",
        f"- Expected net cash 30d: `{outcomes.get('expected_net_cash_30d')}`",
        f"- Net revenue USD: `{outcomes.get('net_revenue_usd')}`",
        f"- Conversion rate: `{outcomes.get('conversion_rate')}`",
        f"- Refund rate: `{outcomes.get('refund_rate')}`",
        f"- Fulfillment penalty: `{penalties.get('fulfillment_penalty')}`",
        f"- Total penalty: `{entry['penalty_total']}`",
        f"- Leaderboard score: `{entry['score_after_penalty']}`",
        "",
        "## Local Review Gates",
        "",
        "1. Confirm the pack remains sanitized and contains no customer identities.",
        "2. Replay the detector and template learnings locally before adoption.",
        "3. Compare net-cash and penalty assumptions to local reality.",
        "4. Reject if compliance, refund, or fulfillment penalties worsen locally.",
        "",
        "## Included Proof References",
        "",
    ]
    for row in bundle.get("proof_references", []):
        lines.append(
            f"- `{row['ref_key']}` type=`{row.get('proof_type')}` sha256=`{row.get('sha256')}`"
        )
    if not bundle.get("proof_references"):
        lines.append("- No proof references were attached.")
    lines.append("")
    return "\n".join(lines)


def render_knowledge_pack_leaderboard_markdown(
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> str:
    """Render a leaderboard-ready markdown summary for a knowledge pack."""

    entry = build_knowledge_pack_leaderboard_entry(
        bundle,
        verification_status=verification["verification_status"],
    )
    return "\n".join(
        [
            "# Knowledge Pack Leaderboard Entry",
            "",
            f"- Peer: `{entry['peer_name']}`",
            f"- Engine: `{entry['engine_key']}:{entry['engine_version']}`",
            f"- Verification: `{entry['verification_status']}`",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Score after penalty | {entry['score_after_penalty']:.3f} |",
            f"| Score before penalty | {entry['score_before_penalty']:.3f} |",
            f"| Penalty total | {entry['penalty_total']:.3f} |",
            f"| Expected net cash 30d | ${entry['expected_net_cash_30d']:.2f} |",
            f"| Conversion rate | {entry['conversion_rate']:.2%} |",
            f"| Refund rate | {entry['refund_rate']:.2%} |",
            f"| Churn rate | {entry['churn_rate']:.2%} |",
            f"| Gross margin | {entry['gross_margin_pct']:.2%} |",
            f"| Proof count | {entry['proof_count']} |",
        ]
    ) + "\n"


def build_knowledge_pack_leaderboard_entry(
    bundle: dict[str, Any],
    *,
    verification_status: str | None = None,
) -> dict[str, Any]:
    """Build a stable leaderboard row from a sanitized knowledge pack."""

    engine = bundle.get("engine") or {}
    outcomes = bundle.get("aggregated_outcomes") or {}
    penalties = bundle.get("penalty_metrics") or {}

    expected_net_cash_30d = float(
        outcomes.get("expected_net_cash_30d")
        or outcomes.get("net_revenue_usd")
        or 0.0
    )
    conversion_rate = float(outcomes.get("conversion_rate") or 0.0)
    refund_rate = float(outcomes.get("refund_rate") or 0.0)
    churn_rate = float(outcomes.get("churn_rate") or 0.0)
    gross_margin_pct = float(outcomes.get("gross_margin_pct") or 0.0)
    penalty_total = _knowledge_penalty_total(penalties)
    score_before_penalty = round(
        expected_net_cash_30d
        + (conversion_rate * 100.0)
        + (gross_margin_pct * 25.0)
        - (refund_rate * 50.0)
        - (churn_rate * 50.0),
        6,
    )
    score_after_penalty = round(score_before_penalty - (penalty_total * 100.0), 6)

    return {
        "peer_name": str(bundle.get("peer_name") or "unknown"),
        "engine_key": str(engine.get("engine_key") or "unknown"),
        "engine_version": str(engine.get("engine_version") or "unknown"),
        "engine_family": str(engine.get("engine_family") or "non_trading"),
        "lane": str(engine.get("lane") or "revenue_audit"),
        "environment": str(engine.get("environment") or "n/a"),
        "sample_size": int(engine.get("sample_size") or outcomes.get("observed_count") or 0),
        "expected_net_cash_30d": round(expected_net_cash_30d, 6),
        "conversion_rate": round(conversion_rate, 6),
        "refund_rate": round(refund_rate, 6),
        "churn_rate": round(churn_rate, 6),
        "gross_margin_pct": round(gross_margin_pct, 6),
        "penalty_total": round(penalty_total, 6),
        "score_before_penalty": score_before_penalty,
        "score_after_penalty": score_after_penalty,
        "proof_count": len(bundle.get("proof_references") or []),
        "verification_status": verification_status or "unknown",
    }


def verify_improvement_bundle(
    bundle: dict[str, Any],
    *,
    signing_secret: str | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    """Verify integrity and optional signature for a bundle."""

    integrity = bundle.get("integrity") or {}
    body = _bundle_body(bundle)
    canonical = _canonical_json(body)
    expected_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if integrity.get("bundle_sha256") != expected_sha:
        raise ValueError("Bundle SHA256 mismatch")

    for file_row in bundle.get("code", {}).get("files", []):
        content_sha = hashlib.sha256(file_row["content"].encode("utf-8")).hexdigest()
        if content_sha != file_row["sha256"]:
            raise ValueError(f"File content hash mismatch for {file_row['path']}")

    signature = integrity.get("signature_hmac_sha256")
    if signature:
        if signing_secret is None:
            verification_status = "signature_unchecked"
        else:
            expected_signature = _sign_body(body, signing_secret)
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("Invalid improvement bundle signature")
            verification_status = "verified"
    else:
        if require_signature:
            raise ValueError("Signature required but bundle is unsigned")
        verification_status = "unsigned"

    return {
        "bundle_sha256": expected_sha,
        "verification_status": verification_status,
        "file_count": len(bundle.get("code", {}).get("files", [])),
        "has_patch": bool(bundle.get("code", {}).get("patch_diff")),
    }


def write_improvement_bundle(bundle: dict[str, Any], output_path: str | Path) -> str:
    """Write an improvement bundle to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    return str(path)


def load_improvement_bundle(path: str | Path) -> dict[str, Any]:
    """Load a bundle from JSON."""

    return json.loads(Path(path).read_text())


def write_review_packet(
    review_dir: str | Path,
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, str]:
    """Materialize a local review packet from a peer bundle."""

    root = Path(review_dir)
    root.mkdir(parents=True, exist_ok=True)

    bundle_path = root / "bundle.json"
    review_md_path = root / "review.md"
    pr_body_path = root / "pr_body.md"
    patch_path = root / "patch.diff"
    files_root = root / "files"
    files_root.mkdir(parents=True, exist_ok=True)

    bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True))
    review_md_path.write_text(render_review_markdown(bundle, verification))
    pr_body_path.write_text(render_pr_body(bundle, verification))

    if bundle.get("code", {}).get("patch_diff"):
        patch_path.write_text(bundle["code"]["patch_diff"])

    for file_row in bundle.get("code", {}).get("files", []):
        target = files_root / _safe_relpath(file_row["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_row["content"])

    return {
        "bundle": str(bundle_path),
        "review_md": str(review_md_path),
        "pr_body_md": str(pr_body_path),
        "patch_diff": str(patch_path) if patch_path.exists() else "",
        "files_dir": str(files_root),
    }


def render_review_markdown(bundle: dict[str, Any], verification: dict[str, Any]) -> str:
    """Render a review checklist for a peer bundle."""

    strategy = bundle["strategy"]
    claim = bundle["claim"]
    snapshot = bundle["evidence"].get("latest_snapshot") or {}
    decision = bundle["evidence"].get("latest_decision") or {}
    files = bundle.get("code", {}).get("files", [])

    lines = [
        "# Peer Improvement Review Packet",
        "",
        f"- Bundle: `{bundle['bundle_id']}`",
        f"- Peer: `{bundle['peer_name']}`",
        f"- Strategy: `{strategy['strategy_key']}:{strategy['version_label']}`",
        f"- Outcome claim: `{claim['outcome']}`",
        f"- Verification: `{verification['verification_status']}`",
        f"- Bundle SHA256: `{verification['bundle_sha256']}`",
        "",
        "## Claim",
        "",
        claim.get("summary") or "No summary provided.",
        "",
        "## Hypothesis",
        "",
        claim.get("hypothesis") or "No hypothesis provided.",
        "",
        "## Local Review Gates",
        "",
        "1. Inspect `patch.diff` and the extracted code files.",
        "2. Replay the change on local data before any deployment.",
        "3. If replay passes, promote only to `paper` or `shadow` first.",
        "4. Record whether the peer result reproduces locally.",
        "",
        "## Latest Peer Evidence",
        "",
        f"- Decision: `{decision.get('decision')}` from `{decision.get('from_stage')}` to `{decision.get('to_stage')}`",
        f"- Reason: `{decision.get('reason_code')}`",
        f"- Snapshot date: `{snapshot.get('snapshot_date')}`",
        f"- Realized PnL: `{snapshot.get('realized_pnl')}`",
        f"- Closed trades: `{snapshot.get('closed_trades')}`",
        f"- Fill rate: `{snapshot.get('fill_rate')}`",
        f"- Avg slippage bps: `{snapshot.get('avg_slippage_bps')}`",
        "",
        "## Included Files",
        "",
    ]
    for file_row in files:
        lines.append(
            f"- `{file_row['path']}` sha256=`{file_row['sha256']}` bytes={file_row['size_bytes']}"
        )
    if not files:
        lines.append("- No code files were attached.")
    lines.append("")
    return "\n".join(lines)


def render_pr_body(bundle: dict[str, Any], verification: dict[str, Any]) -> str:
    """Render a draft PR body for a local adoption attempt."""

    strategy = bundle["strategy"]
    claim = bundle["claim"]
    return "\n".join(
        [
            f"# Peer Bundle Intake: {strategy['strategy_key']} {strategy['version_label']}",
            "",
            "## Source",
            "",
            f"- Peer: `{bundle['peer_name']}`",
            f"- Bundle ID: `{bundle['bundle_id']}`",
            f"- Verification: `{verification['verification_status']}`",
            "",
            "## Claim",
            "",
            claim.get("summary") or "No summary provided.",
            "",
            "## Hypothesis",
            "",
            claim.get("hypothesis") or "No hypothesis provided.",
            "",
            "## Required Local Checks",
            "",
            "- Replay on local event history",
            "- Shadow or paper deployment only",
            "- Compare local fill/slippage behavior",
            "- Reject if it widens live risk or fails reproduction",
            "",
        ]
    ) + "\n"


def _collect_code_files(
    include_paths: Sequence[str | Path],
    repo_root: Path,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in include_paths:
        path = Path(item)
        abs_path = path if path.is_absolute() else repo_root / path
        abs_path = abs_path.resolve()
        if not abs_path.exists() or not abs_path.is_file():
            raise FileNotFoundError(f"Improvement bundle path is not a file: {item}")
        content = abs_path.read_text()
        rel_path = _export_relpath(abs_path, repo_root)
        files.append(
            {
                "path": rel_path,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "size_bytes": abs_path.stat().st_size,
                "content": content,
            }
        )
    files.sort(key=lambda row: row["path"])
    return files


def _build_patch(repo_root: Path, relative_paths: list[str], *, base_ref: str) -> str | None:
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return None
    command = [
        "git",
        "-C",
        str(repo_root),
        "diff",
        "--no-ext-diff",
        "--binary",
        base_ref,
        "--",
        *relative_paths,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode not in {0, 1}:
        return None
    text = result.stdout.strip()
    return text or None


def _default_summary(
    decision: Any,
    snapshot: Any,
    strategy_key: str,
    version_label: str,
) -> str:
    if decision is not None and decision.notes:
        return decision.notes
    if snapshot is not None:
        return (
            f"Shared from {strategy_key}:{version_label} with realized_pnl={snapshot.realized_pnl} "
            f"and closed_trades={snapshot.closed_trades}."
        )
    return f"Peer bundle for {strategy_key}:{version_label}."


def _snapshot_dict(snapshot: Any) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "snapshot_date": snapshot.snapshot_date,
        "starting_bankroll": snapshot.starting_bankroll,
        "ending_bankroll": snapshot.ending_bankroll,
        "realized_pnl": snapshot.realized_pnl,
        "unrealized_pnl": snapshot.unrealized_pnl,
        "open_positions": snapshot.open_positions,
        "closed_trades": snapshot.closed_trades,
        "win_rate": snapshot.win_rate,
        "fill_rate": snapshot.fill_rate,
        "avg_slippage_bps": snapshot.avg_slippage_bps,
        "rolling_brier": snapshot.rolling_brier,
        "rolling_ece": snapshot.rolling_ece,
        "max_drawdown_pct": snapshot.max_drawdown_pct,
        "kill_events": snapshot.kill_events,
        "metrics": snapshot.metrics,
    }


def _decision_dict(decision: Any) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "decision": decision.decision,
        "from_stage": decision.from_stage,
        "to_stage": decision.to_stage,
        "reason_code": decision.reason_code,
        "notes": decision.notes,
        "metrics": decision.metrics,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


def _validate_knowledge_pack_schema(bundle: dict[str, Any]) -> None:
    body = _bundle_body(bundle)
    if body.get("bundle_type") != "knowledge_pack":
        raise ValueError("Bundle is not a knowledge pack")
    if int(body.get("schema_version") or 0) != _KNOWLEDGE_PACK_SCHEMA_VERSION:
        raise ValueError("Unsupported knowledge pack schema version")

    required_sections = (
        "engine",
        "detector_summaries",
        "template_variants",
        "aggregated_outcomes",
        "penalty_metrics",
        "proof_references",
        "privacy",
        "leaderboard_entry",
    )
    for key in required_sections:
        if key not in body:
            raise ValueError(f"Knowledge pack missing required section: {key}")

    blocked = _collect_blocked_knowledge_keys(body)
    if blocked:
        raise ValueError(f"Knowledge pack contains blocked private fields: {sorted(blocked)}")

    if body["privacy"].get("raw_customer_data_included") is not False:
        raise ValueError("Knowledge pack privacy contract violated")

    expected_entry = build_knowledge_pack_leaderboard_entry(body)
    if body.get("leaderboard_entry") != expected_entry:
        raise ValueError("Knowledge pack leaderboard entry mismatch")


def _sanitize_knowledge_rows(
    rows: Sequence[dict[str, Any]],
    *,
    allowed_fields: set[str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    redactions: Counter[str] = Counter()
    sanitized_rows: list[dict[str, Any]] = []
    for row in rows:
        sanitized, row_redactions = _sanitize_knowledge_mapping(
            row,
            allowed_fields=allowed_fields,
        )
        if sanitized:
            sanitized_rows.append(sanitized)
        redactions.update(row_redactions)
    return sanitized_rows, redactions


def _sanitize_knowledge_mapping(
    payload: dict[str, Any],
    *,
    allowed_fields: set[str],
) -> tuple[dict[str, Any], Counter[str]]:
    redactions: Counter[str] = Counter()
    sanitized: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if key in allowed_fields:
            sanitized[key] = _sanitize_public_value(key, value)
        else:
            redactions[key] += 1
    return sanitized, redactions


def _sanitize_public_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) if isinstance(value, float) else int(value)
    if isinstance(value, str):
        return value if key in _SAFE_LITERAL_FIELDS else _redact_private_tokens(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_public_value(key, item) for item in value if item is not None]
    if isinstance(value, dict):
        return {
            nested_key: _sanitize_public_value(nested_key, nested_value)
            for nested_key, nested_value in value.items()
            if nested_key not in _BLOCKED_KNOWLEDGE_KEYS
        }
    return _redact_private_tokens(str(value))


def _redact_private_tokens(value: str) -> str:
    redacted = _EMAIL_RE.sub("<redacted-email>", value)
    redacted = _PAYMENT_TOKEN_RE.sub("<redacted-payment>", redacted)
    redacted = _LONG_NUMBER_RE.sub("<redacted-number>", redacted)
    return redacted


def _collect_blocked_knowledge_keys(payload: Any, *, path: tuple[str, ...] = ()) -> set[str]:
    blocked: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _BLOCKED_KNOWLEDGE_KEYS and path != ("privacy", "redaction_counts"):
                blocked.add(key)
            blocked.update(_collect_blocked_knowledge_keys(value, path=(*path, key)))
    elif isinstance(payload, list):
        for item in payload:
            blocked.update(_collect_blocked_knowledge_keys(item, path=path))
    return blocked


def _knowledge_penalty_total(penalties: dict[str, Any]) -> float:
    explicit = penalties.get("score_penalty_total")
    if explicit is not None:
        return round(float(explicit), 6)
    return round(
        float(penalties.get("refund_penalty") or 0.0)
        + float(penalties.get("fulfillment_penalty") or 0.0)
        + float(penalties.get("domain_health_penalty") or 0.0)
        + float(penalties.get("compliance_penalty") or 0.0)
        + float(penalties.get("complaint_penalty") or 0.0),
        6,
    )


def _knowledge_pack_priority(entry: dict[str, Any]) -> int:
    if entry["score_after_penalty"] >= 50.0:
        return 20
    if entry["score_after_penalty"] >= 10.0:
        return 30
    return 40


def _knowledge_pack_task_title(bundle: dict[str, Any]) -> str:
    return (
        f"Review knowledge pack from {bundle['peer_name']}: "
        f"{bundle['engine']['engine_key']}:{bundle['engine']['engine_version']}"
    )


def _knowledge_pack_task_details(
    bundle: dict[str, Any],
    verification: dict[str, Any],
) -> str:
    entry = build_knowledge_pack_leaderboard_entry(
        bundle,
        verification_status=verification["verification_status"],
    )
    return (
        f"verification={verification['verification_status']}; "
        f"score={entry['score_after_penalty']:.3f}; "
        f"net_cash_30d={entry['expected_net_cash_30d']:.2f}; "
        f"penalty_total={entry['penalty_total']:.3f}"
    )


def _attach_integrity(body: dict[str, Any], signing_secret: str | None) -> dict[str, Any]:
    bundle = dict(body)
    bundle_sha = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    integrity = {"bundle_sha256": bundle_sha}
    if signing_secret:
        integrity["signature_hmac_sha256"] = _sign_body(body, signing_secret)
    bundle["integrity"] = integrity
    return bundle


def _sign_body(body: dict[str, Any], signing_secret: str) -> str:
    return hmac.new(
        signing_secret.encode("utf-8"),
        _canonical_json(body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _bundle_body(bundle: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in bundle.items() if key != "integrity"}


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _bundle_id(peer_name: str, strategy_key: str, version_label: str, generated_at: str) -> str:
    safe_peer = peer_name.replace(" ", "-").lower()
    safe_strategy = strategy_key.replace(" ", "-").lower()
    safe_version = version_label.replace(" ", "-").lower()
    safe_ts = generated_at.replace(":", "").replace("+", "").replace(".", "-")
    return f"{safe_peer}-{safe_strategy}-{safe_version}-{safe_ts}"


def _export_relpath(abs_path: Path, repo_root: Path) -> str:
    try:
        return abs_path.relative_to(repo_root).as_posix()
    except ValueError:
        return abs_path.name


def _safe_relpath(path_str: str) -> Path:
    path = Path(path_str)
    parts = [
        part
        for part in path.parts
        if part not in {"", ".", ".."} and part not in {path.anchor, "/", "\\"}
    ]
    return Path(*parts) if parts else Path("file.txt")


def _task_title(bundle: dict[str, Any]) -> str:
    return (
        f"Review peer {bundle['claim']['outcome']} bundle from {bundle['peer_name']}: "
        f"{bundle['strategy']['strategy_key']}:{bundle['strategy']['version_label']}"
    )


def _task_details(bundle: dict[str, Any], verification: dict[str, Any]) -> str:
    return (
        f"Verification={verification['verification_status']}; "
        f"summary={bundle['claim'].get('summary') or 'n/a'}"
    )


def _task_priority(outcome: str) -> int:
    if outcome == "improved":
        return 25
    if outcome == "failed":
        return 35
    return 30
