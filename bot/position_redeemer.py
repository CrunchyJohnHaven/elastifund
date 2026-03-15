#!/usr/bin/env python3
"""Audit and redeem settled Polymarket positions."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.position_merger import (
    COLLATERAL_TOKEN,
    CONDITIONAL_TOKENS,
    DATA_API_BASE,
    DEFAULT_RELAYER_URL,
    ZERO_BYTES32,
    PreparedTransaction,
    PositionMergeService,
    PositionSnapshot,
    _encode_address,
    _encode_bytes32,
    _encode_uint256,
    default_user_address,
    normalize_binary_outcome,
)


logger = logging.getLogger("position_redeemer")

STANDARD_REDEEM_SELECTOR = "01b7037c"


def index_set_for_outcome_index(outcome_index: int) -> int:
    parsed = int(outcome_index)
    if parsed < 0:
        raise ValueError("outcome_index must be non-negative")
    return 1 << parsed


def build_standard_redeem_calldata(condition_id: str, index_set: int) -> str:
    parts = [
        STANDARD_REDEEM_SELECTOR,
        _encode_address(COLLATERAL_TOKEN),
        _encode_bytes32(ZERO_BYTES32),
        _encode_bytes32(condition_id),
        _encode_uint256(128),  # offset to uint256[] partition payload
        _encode_uint256(1),  # partition length
        _encode_uint256(index_set),
    ]
    return "0x" + "".join(parts)


@dataclass(frozen=True)
class RedeemCandidate:
    condition_id: str
    title: str
    position: PositionSnapshot
    outcome_index: int
    index_set: int
    freed_capital_usdc: float
    execution_ready: bool
    note: str = ""


@dataclass(frozen=True)
class RedeemAudit:
    user: str
    positions: tuple[PositionSnapshot, ...]
    candidates: tuple[RedeemCandidate, ...]

    @property
    def total_freed_capital_usdc(self) -> float:
        return sum(candidate.freed_capital_usdc for candidate in self.candidates)


@dataclass(frozen=True)
class RedeemExecutionResult:
    candidate: RedeemCandidate
    executor: str
    submitted: bool
    tx_hash: str | None = None
    transaction_id: str | None = None
    note: str = ""


class PositionRedemptionService:
    """Find settled winner positions that can be redeemed for collateral."""

    def __init__(self, *, merge_service: PositionMergeService | None = None) -> None:
        self.merge_service = merge_service or PositionMergeService()

    def close(self) -> None:
        self.merge_service.close()

    def build_audit(
        self,
        user_address: str,
        *,
        size_threshold: float = 0.0,
        limit: int = 500,
        min_freed_capital_usdc: float = 0.0,
        include_negative_risk: bool = False,
    ) -> RedeemAudit:
        positions = self.merge_service.fetch_positions(
            user_address,
            size_threshold=size_threshold,
            limit=limit,
            redeemable_only=True,
            enrich_prices=False,
        )
        candidates = self.find_redeem_candidates(
            positions,
            min_freed_capital_usdc=min_freed_capital_usdc,
            include_negative_risk=include_negative_risk,
        )
        return RedeemAudit(
            user=user_address,
            positions=tuple(positions),
            candidates=tuple(candidates),
        )

    @staticmethod
    def find_redeem_candidates(
        positions: Sequence[PositionSnapshot],
        *,
        min_freed_capital_usdc: float = 0.0,
        include_negative_risk: bool = False,
    ) -> list[RedeemCandidate]:
        candidates: list[RedeemCandidate] = []
        threshold = max(0.0, float(min_freed_capital_usdc))
        for position in positions:
            current_value = float(position.current_value or 0.0)
            if current_value <= 0.0 or current_value + 1e-9 < threshold:
                continue

            note = ""
            execution_ready = True

            if not position.condition_id:
                execution_ready = False
                note = "condition_id_missing"

            outcome_index = PositionRedemptionService._outcome_index(position)
            if execution_ready and outcome_index is None:
                execution_ready = False
                note = "outcome_index_missing"

            if execution_ready and position.negative_risk and not include_negative_risk:
                execution_ready = False
                note = "negative_risk_unsupported"

            if outcome_index is None:
                outcome_index = 0

            candidates.append(
                RedeemCandidate(
                    condition_id=position.condition_id or "",
                    title=position.title,
                    position=position,
                    outcome_index=outcome_index,
                    index_set=index_set_for_outcome_index(outcome_index),
                    freed_capital_usdc=current_value,
                    execution_ready=execution_ready,
                    note=note,
                )
            )

        candidates.sort(key=lambda candidate: candidate.freed_capital_usdc, reverse=True)
        return candidates

    @staticmethod
    def prepare_transaction(candidate: RedeemCandidate) -> PreparedTransaction:
        if not candidate.execution_ready:
            raise ValueError(
                f"redeem candidate is not execution ready: {candidate.note or candidate.condition_id}"
            )
        return PreparedTransaction(
            to=CONDITIONAL_TOKENS,
            data=build_standard_redeem_calldata(candidate.condition_id, candidate.index_set),
        )

    @staticmethod
    def render_markdown_report(audit: RedeemAudit) -> str:
        lines = [
            "# Position Redemption Audit",
            "",
            f"- Wallet: `{audit.user}`",
            f"- Redeemable positions scanned: {len(audit.positions)}",
            f"- Redeem-ready positions: {len(audit.candidates)}",
            f"- Redeemable collateral: ${audit.total_freed_capital_usdc:.2f}",
            "",
        ]
        if not audit.candidates:
            lines.append("No redeemable winner positions found.")
            return "\n".join(lines) + "\n"

        lines.extend(
            [
                "| Title | Outcome | Current Value | Ready | Note |",
                "|---|---|---:|---|---|",
            ]
        )
        for candidate in audit.candidates:
            lines.append(
                "| "
                f"{candidate.title or candidate.condition_id} | "
                f"{candidate.position.outcome or '?'} | "
                f"${candidate.freed_capital_usdc:.2f} | "
                f"{'yes' if candidate.execution_ready else 'no'} | "
                f"{candidate.note or ''} |"
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_json_report(audit: RedeemAudit) -> dict[str, Any]:
        return {
            "wallet": audit.user,
            "positions": [asdict(position) for position in audit.positions],
            "candidates": [asdict(candidate) for candidate in audit.candidates],
            "summary": {
                "redeemable_positions": len(audit.positions),
                "redeem_ready_positions": len(audit.candidates),
                "freed_capital_usdc": audit.total_freed_capital_usdc,
                "data_api_base": DATA_API_BASE,
            },
        }

    @staticmethod
    def _outcome_index(position: PositionSnapshot) -> int | None:
        raw_value = position.raw.get("outcomeIndex")
        try:
            if raw_value is not None:
                parsed = int(raw_value)
                if parsed >= 0:
                    return parsed
        except (TypeError, ValueError):
            pass
        normalized = normalize_binary_outcome(position.outcome)
        if normalized == "YES":
            return 0
        if normalized == "NO":
            return 1
        return None


class RelayerRedemptionExecutor:
    """Submit redemption transactions through Polymarket's relayer."""

    def __init__(
        self,
        *,
        relayer_url: str | None = None,
        chain_id: int = 137,
        private_key: str | None = None,
        builder_api_key: str | None = None,
        builder_api_secret: str | None = None,
        builder_api_passphrase: str | None = None,
        relay_tx_type: str = "SAFE",
    ) -> None:
        self.relayer_url = relayer_url or os.getenv("RELAYER_URL") or DEFAULT_RELAYER_URL
        self.chain_id = int(chain_id)
        raw_private_key = (
            private_key
            or os.getenv("POLY_PRIVATE_KEY")
            or os.getenv("POLYMARKET_PK")
            or os.getenv("PK")
        )
        if raw_private_key and not raw_private_key.startswith("0x"):
            raw_private_key = "0x" + raw_private_key
        self.private_key = raw_private_key
        self.builder_api_key = (
            builder_api_key
            or os.getenv("POLY_BUILDER_API_KEY")
            or os.getenv("POLYMARKET_API_KEY")
            or os.getenv("BUILDER_API_KEY")
        )
        self.builder_api_secret = (
            builder_api_secret
            or os.getenv("POLY_BUILDER_API_SECRET")
            or os.getenv("POLYMARKET_API_SECRET")
            or os.getenv("BUILDER_SECRET")
        )
        self.builder_api_passphrase = (
            builder_api_passphrase
            or os.getenv("POLY_BUILDER_API_PASSPHRASE")
            or os.getenv("POLYMARKET_API_PASSPHRASE")
            or os.getenv("BUILDER_PASS_PHRASE")
        )
        self.relay_tx_type = relay_tx_type.upper()

    def execute(
        self,
        candidates: Sequence[RedeemCandidate],
        *,
        dry_run: bool = True,
    ) -> list[RedeemExecutionResult]:
        prepared = [
            (candidate, PositionRedemptionService.prepare_transaction(candidate))
            for candidate in candidates
        ]
        if dry_run:
            return [
                RedeemExecutionResult(
                    candidate=candidate,
                    executor="relayer",
                    submitted=False,
                    note="dry_run",
                )
                for candidate, _ in prepared
            ]

        if not self.private_key:
            raise RuntimeError("POLY_PRIVATE_KEY or POLYMARKET_PK is required for relayer execution")
        if not (self.builder_api_key and self.builder_api_secret and self.builder_api_passphrase):
            raise RuntimeError("builder API credentials are required for relayer execution")

        try:
            from py_builder_relayer_client.client import RelayClient
            from py_builder_relayer_client.models import OperationType, SafeTransaction
            from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig
        except ImportError as exc:
            raise RuntimeError(
                "Relayer execution requires py-builder-relayer-client and py-builder-signing-sdk"
            ) from exc

        builder_config = BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=self.builder_api_key,
                secret=self.builder_api_secret,
                passphrase=self.builder_api_passphrase,
            )
        )
        client = RelayClient(
            self.relayer_url,
            self.chain_id,
            self.private_key,
            builder_config,
        )
        transactions = [
            SafeTransaction(
                to=prepared_txn.to,
                operation=OperationType.Call,
                data=prepared_txn.data,
                value=prepared_txn.value,
            )
            for _, prepared_txn in prepared
        ]
        response = client.execute(transactions, metadata=f"redeem {len(transactions)} polymarket positions")
        waited = response.wait()
        tx_hash = getattr(response, "transaction_hash", None) or getattr(response, "hash", None)
        transaction_id = getattr(response, "transaction_id", None)
        note = ""
        if isinstance(waited, dict):
            tx_hash = tx_hash or waited.get("transactionHash") or waited.get("transaction_hash")
        elif waited is None:
            note = "submitted_not_confirmed"

        return [
            RedeemExecutionResult(
                candidate=candidate,
                executor="relayer",
                submitted=True,
                tx_hash=tx_hash,
                transaction_id=transaction_id,
                note=note,
            )
            for candidate, _ in prepared
        ]


def write_report_files(audit: RedeemAudit, *, markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(PositionRedemptionService.render_markdown_report(audit))
    json_path.write_text(json.dumps(PositionRedemptionService.render_json_report(audit), indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and redeem settled Polymarket positions")
    parser.add_argument("command", choices=["audit", "redeem"], help="Action to run")
    parser.add_argument("--user", default=default_user_address(), help="Wallet/funder address")
    parser.add_argument("--limit", type=int, default=250, help="Maximum number of positions to fetch")
    parser.add_argument("--size-threshold", type=float, default=0.0, help="Minimum position size to include")
    parser.add_argument("--min-freed-usdc", type=float, default=0.0, help="Ignore candidates below this value")
    parser.add_argument(
        "--include-negative-risk",
        action="store_true",
        help="Include negative-risk markets instead of skipping them",
    )
    parser.add_argument("--submit", action="store_true", help="Actually submit redemption transactions")
    parser.add_argument(
        "--markdown-report",
        default="reports/position_redeem_report.md",
        help="Markdown report output path",
    )
    parser.add_argument(
        "--json-report",
        default="data/position_redeem_report.json",
        help="JSON report output path",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    if not args.user:
        raise SystemExit("wallet address required via --user or POLY_SAFE_ADDRESS/POLYMARKET_FUNDER")

    service = PositionRedemptionService()
    try:
        audit = service.build_audit(
            args.user,
            size_threshold=args.size_threshold,
            limit=args.limit,
            min_freed_capital_usdc=args.min_freed_usdc,
            include_negative_risk=args.include_negative_risk,
        )
        write_report_files(
            audit,
            markdown_path=Path(args.markdown_report),
            json_path=Path(args.json_report),
        )
        print(PositionRedemptionService.render_markdown_report(audit))

        if args.command == "audit":
            return 0

        candidates = [candidate for candidate in audit.candidates if candidate.execution_ready]
        if not candidates:
            print("No execution-ready redeem candidates found.")
            return 0

        executor = RelayerRedemptionExecutor()
        results = executor.execute(candidates, dry_run=not args.submit)
        print(json.dumps([asdict(result) for result in results], indent=2))
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
