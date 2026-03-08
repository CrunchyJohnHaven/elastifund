"""Peer improvement bundle exchange for cross-fork learning."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy.orm import Session

from data_layer import crud

from .intelligence import FindingSpec, TaskSpec, record_finding_with_task

DEFAULT_REVIEW_ROOT = Path("reports") / "flywheel" / "peer_improvements"


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
