#!/usr/bin/env python3
"""Audit and execute Polymarket position merges.

Stream 7 needs three things:
1. Audit the wallet's current mergeable positions.
2. Estimate how much USDC a merge would free.
3. Submit the merge through a supported execution path.

The calldata and contract routing here intentionally mirror the open-source
`poly_merger` utility in `warproxxx/poly-maker`, while preferring Polymarket's
official relayer client when available.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, ROUND_DOWN
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping, Sequence

import requests


DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
DEFAULT_RELAYER_URL = "https://relayer-v2.polymarket.com/"

USDC_DECIMALS = 6
RAW_UNIT = Decimal("1000000")
ZERO_BYTES32 = "0x" + ("00" * 32)

# Contract addresses from Polymarket docs and the open-source poly_merger tool.
COLLATERAL_TOKEN = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

# Function selectors:
# mergePositions(address,bytes32,bytes32,uint256[],uint256) -> 0x9e7212ad
# mergePositions(bytes32,uint256) -> 0xb10c5c17
STANDARD_MERGE_SELECTOR = "9e7212ad"
NEG_RISK_MERGE_SELECTOR = "b10c5c17"

YES_OUTCOMES = {"yes", "y", "buy yes"}
NO_OUTCOMES = {"no", "n", "buy no"}

logger = logging.getLogger("position_merger")


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _strip_0x(value: str) -> str:
    text = str(value or "").strip()
    return text[2:] if text.lower().startswith("0x") else text


def _is_hex(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]+", value))


def normalize_bytes32(value: Any) -> str | None:
    if value is None:
        return None
    stripped = _strip_0x(str(value))
    if len(stripped) != 64 or not _is_hex(stripped):
        return None
    return "0x" + stripped.lower()


def normalize_address(value: Any) -> str | None:
    if value is None:
        return None
    stripped = _strip_0x(str(value))
    if len(stripped) != 40 or not _is_hex(stripped):
        return None
    return "0x" + stripped.lower()


def normalize_binary_outcome(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in YES_OUTCOMES:
        return "YES"
    if text in NO_OUTCOMES:
        return "NO"
    return text.upper()


def to_raw_units(amount: float) -> int:
    quantized = Decimal(str(amount)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    return int((quantized * RAW_UNIT).to_integral_value(rounding=ROUND_DOWN))


def _encode_uint256(value: int) -> str:
    if value < 0:
        raise ValueError("uint256 value cannot be negative")
    return f"{value:064x}"


def _encode_bytes32(value: str) -> str:
    normalized = normalize_bytes32(value)
    if not normalized:
        raise ValueError(f"invalid bytes32 value: {value}")
    return _strip_0x(normalized)


def _encode_address(value: str) -> str:
    normalized = normalize_address(value)
    if not normalized:
        raise ValueError(f"invalid address value: {value}")
    return ("0" * 24) + _strip_0x(normalized)


def build_standard_merge_calldata(condition_id: str, amount_raw: int) -> str:
    parts = [
        STANDARD_MERGE_SELECTOR,
        _encode_address(COLLATERAL_TOKEN),
        _encode_bytes32(ZERO_BYTES32),
        _encode_bytes32(condition_id),
        _encode_uint256(160),  # offset to uint256[] partition payload
        _encode_uint256(amount_raw),
        _encode_uint256(2),  # partition length
        _encode_uint256(1),
        _encode_uint256(2),
    ]
    return "0x" + "".join(parts)


def build_neg_risk_merge_calldata(condition_id: str, amount_raw: int) -> str:
    parts = [
        NEG_RISK_MERGE_SELECTOR,
        _encode_bytes32(condition_id),
        _encode_uint256(amount_raw),
    ]
    return "0x" + "".join(parts)


@dataclass(frozen=True)
class PositionSnapshot:
    user: str
    condition_id: str | None
    market_id: str | None
    token_id: str | None
    opposite_token_id: str | None
    title: str
    outcome: str | None
    size: float
    avg_price: float | None = None
    initial_value: float | None = None
    current_value: float | None = None
    current_price: float | None = None
    cash_pnl: float | None = None
    percent_pnl: float | None = None
    mergeable: bool | None = None
    redeemable: bool | None = None
    negative_risk: bool | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def entry_price(self) -> float | None:
        if self.avg_price is not None:
            return self.avg_price
        if self.initial_value is not None and self.size > 0:
            return self.initial_value / self.size
        return None

    @property
    def mark_price(self) -> float | None:
        if self.current_price is not None:
            return self.current_price
        if self.current_value is not None and self.size > 0:
            return self.current_value / self.size
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2.0
        if self.best_bid is not None:
            return self.best_bid
        if self.best_ask is not None:
            return self.best_ask
        return None


@dataclass(frozen=True)
class MergeCandidate:
    condition_id: str
    title: str
    yes: PositionSnapshot
    no: PositionSnapshot
    merge_size: float
    freed_capital_usdc: float
    negative_risk: bool | None
    execution_ready: bool
    note: str = ""

    @property
    def amount_raw(self) -> int:
        return to_raw_units(self.merge_size)


@dataclass(frozen=True)
class PreparedTransaction:
    to: str
    data: str
    value: str = "0"


@dataclass(frozen=True)
class MergeExecutionResult:
    candidate: MergeCandidate
    executor: str
    submitted: bool
    tx_hash: str | None = None
    transaction_id: str | None = None
    note: str = ""


@dataclass(frozen=True)
class MergeAudit:
    user: str
    positions: tuple[PositionSnapshot, ...]
    candidates: tuple[MergeCandidate, ...]
    generated_at: int

    @property
    def total_freed_capital_usdc(self) -> float:
        return sum(candidate.freed_capital_usdc for candidate in self.candidates)

    @property
    def mergeable_market_count(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True)
class DuplicateOutcomeGroup:
    condition_id: str
    outcome: str
    title: str
    position_count: int
    total_size: float


class PositionMergeService:
    """Audit mergeable positions for a wallet and prepare execution payloads."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
        gamma_pages: int = 20,
        gamma_page_size: int = 100,
        quote_workers: int = 8,
    ) -> None:
        self._session = session or requests.Session()
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.gamma_pages = max(1, int(gamma_pages))
        self.gamma_page_size = max(1, min(100, int(gamma_page_size)))
        self.quote_workers = max(1, int(quote_workers))

    def close(self) -> None:
        self._session.close()

    def fetch_positions(
        self,
        user_address: str,
        *,
        size_threshold: float = 0.0,
        limit: int = 500,
        mergeable_only: bool = False,
        redeemable_only: bool = False,
        enrich_prices: bool = True,
    ) -> list[PositionSnapshot]:
        user_address = normalize_address(user_address)
        if not user_address:
            raise ValueError("user address is required")

        page_limit = min(max(1, int(limit)), 500)
        offset = 0
        positions: list[PositionSnapshot] = []

        while len(positions) < limit:
            params: dict[str, Any] = {
                "user": user_address,
                "limit": min(page_limit, limit - len(positions)),
                "offset": offset,
            }
            if size_threshold > 0:
                params["sizeThreshold"] = size_threshold
            if mergeable_only:
                params["mergeable"] = "true"
            if redeemable_only:
                params["redeemable"] = "true"

            resp = self._session.get(
                f"{DATA_API_BASE}/positions",
                params=params,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json()
            batch = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(batch, list):
                batch = []

            parsed = [self._parse_position(user_address, raw) for raw in batch]
            positions.extend(parsed)

            if len(batch) < params["limit"]:
                break
            offset += len(batch)

        positions = self._resolve_neg_risk_flags(positions)
        if enrich_prices:
            positions = self._enrich_book_quotes(positions)
        return positions

    def build_audit(
        self,
        user_address: str,
        *,
        size_threshold: float = 0.0,
        limit: int = 500,
        mergeable_only: bool = False,
        min_freed_capital_usdc: float = 0.0,
    ) -> MergeAudit:
        positions = self.fetch_positions(
            user_address,
            size_threshold=size_threshold,
            limit=limit,
            mergeable_only=mergeable_only,
        )
        candidates = self.find_merge_candidates(
            positions,
            min_freed_capital_usdc=min_freed_capital_usdc,
        )
        return MergeAudit(
            user=normalize_address(user_address) or user_address,
            positions=tuple(positions),
            candidates=tuple(candidates),
            generated_at=int(time.time()),
        )

    @staticmethod
    def find_merge_candidates(
        positions: Sequence[PositionSnapshot],
        *,
        min_freed_capital_usdc: float = 0.0,
    ) -> list[MergeCandidate]:
        grouped: dict[str, dict[str, list[PositionSnapshot]]] = {}
        for position in positions:
            if not position.condition_id or position.size <= 0:
                continue
            outcome = normalize_binary_outcome(position.outcome)
            if outcome not in {"YES", "NO"}:
                continue
            grouped.setdefault(position.condition_id, {}).setdefault(outcome, []).append(position)

        candidates: list[MergeCandidate] = []
        for condition_id, legs in grouped.items():
            if "YES" not in legs or "NO" not in legs:
                continue

            yes = PositionMergeService._aggregate_leg(legs["YES"])
            no = PositionMergeService._aggregate_leg(legs["NO"])
            merge_size = min(yes.size, no.size)
            if merge_size <= 0 or merge_size + 1e-9 < float(min_freed_capital_usdc):
                continue

            negative_risk = yes.negative_risk
            note = ""
            if negative_risk is None:
                negative_risk = no.negative_risk
            elif no.negative_risk is not None and no.negative_risk != negative_risk:
                negative_risk = None
                note = "neg_risk_conflict"

            has_condition_id = normalize_bytes32(condition_id) is not None
            execution_ready = negative_risk is not None and has_condition_id
            if not execution_ready and not note:
                note = "condition_id_missing" if not has_condition_id else "neg_risk_unresolved"

            candidates.append(
                MergeCandidate(
                    condition_id=condition_id,
                    title=yes.title or no.title,
                    yes=yes,
                    no=no,
                    merge_size=float(merge_size),
                    freed_capital_usdc=float(merge_size),
                    negative_risk=negative_risk,
                    execution_ready=execution_ready,
                    note=note,
                )
            )

        candidates.sort(key=lambda candidate: candidate.freed_capital_usdc, reverse=True)
        return candidates

    @staticmethod
    def find_duplicate_outcome_positions(
        positions: Sequence[PositionSnapshot],
        *,
        min_count: int = 2,
    ) -> list[DuplicateOutcomeGroup]:
        grouped: dict[tuple[str, str], list[PositionSnapshot]] = {}
        for position in positions:
            if not position.condition_id or position.size <= 0:
                continue
            outcome = normalize_binary_outcome(position.outcome)
            if outcome not in {"YES", "NO"}:
                continue
            grouped.setdefault((position.condition_id, outcome), []).append(position)

        duplicates: list[DuplicateOutcomeGroup] = []
        for (condition_id, outcome), group in grouped.items():
            if len(group) < max(2, int(min_count)):
                continue
            duplicates.append(
                DuplicateOutcomeGroup(
                    condition_id=condition_id,
                    outcome=outcome,
                    title=group[0].title,
                    position_count=len(group),
                    total_size=sum(position.size for position in group),
                )
            )

        duplicates.sort(
            key=lambda item: (item.total_size, item.position_count),
            reverse=True,
        )
        return duplicates

    @staticmethod
    def prepare_transaction(candidate: MergeCandidate) -> PreparedTransaction:
        if not candidate.execution_ready:
            raise ValueError(f"merge candidate is not execution ready: {candidate.note or candidate.condition_id}")

        amount_raw = candidate.amount_raw
        if candidate.negative_risk:
            return PreparedTransaction(
                to=NEG_RISK_ADAPTER,
                data=build_neg_risk_merge_calldata(candidate.condition_id, amount_raw),
            )

        return PreparedTransaction(
            to=CONDITIONAL_TOKENS,
            data=build_standard_merge_calldata(candidate.condition_id, amount_raw),
        )

    @staticmethod
    def render_markdown_report(audit: MergeAudit) -> str:
        generated_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(audit.generated_at))
        lines = [
            "# Position Merge Audit",
            "",
            f"- Wallet: `{audit.user}`",
            f"- Generated: {generated_at}",
            f"- Positions scanned: {len(audit.positions)}",
            f"- Mergeable markets: {audit.mergeable_market_count}",
            f"- Total freed capital: ${audit.total_freed_capital_usdc:.2f}",
            "",
        ]

        if not audit.candidates:
            lines.append("No mergeable YES/NO pairs found.")
            return "\n".join(lines) + "\n"

        lines.extend(
            [
                "| Title | Merge Size | YES Size @ Entry/Mark | NO Size @ Entry/Mark | Neg-Risk | Ready |",
                "|---|---:|---|---|---|---|",
            ]
        )
        for candidate in audit.candidates:
            yes_entry = "n/a" if candidate.yes.entry_price is None else f"{candidate.yes.entry_price:.3f}"
            yes_mark = "n/a" if candidate.yes.mark_price is None else f"{candidate.yes.mark_price:.3f}"
            no_entry = "n/a" if candidate.no.entry_price is None else f"{candidate.no.entry_price:.3f}"
            no_mark = "n/a" if candidate.no.mark_price is None else f"{candidate.no.mark_price:.3f}"
            neg_risk = "yes" if candidate.negative_risk else "no" if candidate.negative_risk is False else "unknown"
            ready = "yes" if candidate.execution_ready else f"no ({candidate.note or 'blocked'})"
            lines.append(
                "| "
                f"{candidate.title or candidate.condition_id} | "
                f"${candidate.freed_capital_usdc:.2f} | "
                f"{candidate.yes.size:.2f} @ {yes_entry}/{yes_mark} | "
                f"{candidate.no.size:.2f} @ {no_entry}/{no_mark} | "
                f"{neg_risk} | "
                f"{ready} |"
            )

        return "\n".join(lines) + "\n"

    @staticmethod
    def render_json_report(audit: MergeAudit) -> dict[str, Any]:
        return {
            "wallet": audit.user,
            "generated_at": audit.generated_at,
            "positions": [asdict(position) for position in audit.positions],
            "candidates": [asdict(candidate) for candidate in audit.candidates],
            "summary": {
                "positions_scanned": len(audit.positions),
                "mergeable_markets": audit.mergeable_market_count,
                "freed_capital_usdc": audit.total_freed_capital_usdc,
            },
        }

    @staticmethod
    def _aggregate_leg(positions: Sequence[PositionSnapshot]) -> PositionSnapshot:
        total_size = sum(position.size for position in positions)
        if total_size <= 0:
            return positions[0]

        def weighted(values: Sequence[tuple[float | None, float]]) -> float | None:
            numer = 0.0
            denom = 0.0
            for value, size in values:
                if value is None:
                    continue
                numer += value * size
                denom += size
            return (numer / denom) if denom > 0 else None

        first = positions[0]
        return PositionSnapshot(
            user=first.user,
            condition_id=first.condition_id,
            market_id=first.market_id,
            token_id=first.token_id,
            opposite_token_id=first.opposite_token_id,
            title=first.title,
            outcome=first.outcome,
            size=total_size,
            avg_price=weighted([(position.avg_price, position.size) for position in positions]),
            initial_value=sum(position.initial_value or 0.0 for position in positions) or None,
            current_value=sum(position.current_value or 0.0 for position in positions) or None,
            current_price=weighted([(position.current_price, position.size) for position in positions]),
            cash_pnl=sum(position.cash_pnl or 0.0 for position in positions) or None,
            percent_pnl=weighted([(position.percent_pnl, position.size) for position in positions]),
            mergeable=any(bool(position.mergeable) for position in positions),
            redeemable=any(bool(position.redeemable) for position in positions),
            negative_risk=first.negative_risk
            if all(position.negative_risk == first.negative_risk for position in positions)
            else None,
            best_bid=max((position.best_bid for position in positions if position.best_bid is not None), default=None),
            best_ask=min((position.best_ask for position in positions if position.best_ask is not None), default=None),
            raw=dict(first.raw),
        )

    def _parse_position(self, user_address: str, raw: Mapping[str, Any]) -> PositionSnapshot:
        condition_id = normalize_bytes32(
            raw.get("conditionId")
            or raw.get("condition_id")
            or raw.get("market")
        )
        token_id = normalize_address(
            raw.get("asset")
            or raw.get("assetId")
            or raw.get("asset_id")
        )
        opposite_token_id = normalize_address(
            raw.get("oppositeAsset")
            or raw.get("oppositeAssetId")
            or raw.get("opposite_asset")
        )
        title = str(raw.get("title") or raw.get("question") or raw.get("marketTitle") or "").strip()
        outcome = raw.get("outcome") or raw.get("position")

        return PositionSnapshot(
            user=user_address,
            condition_id=condition_id,
            market_id=str(raw.get("market") or "").strip() or None,
            token_id=token_id,
            opposite_token_id=opposite_token_id,
            title=title,
            outcome=str(outcome).strip() if outcome not in (None, "") else None,
            size=float(raw.get("size") or 0.0),
            avg_price=_as_float(raw.get("avgPrice") or raw.get("averagePrice")),
            initial_value=_as_float(raw.get("initialValue")),
            current_value=_as_float(raw.get("currentValue") or raw.get("value")),
            current_price=_as_float(raw.get("currentPrice") or raw.get("markPrice") or raw.get("price")),
            cash_pnl=_as_float(raw.get("cashPnl")),
            percent_pnl=_as_float(raw.get("percentPnl")),
            mergeable=_as_bool(raw.get("mergeable")),
            redeemable=_as_bool(raw.get("redeemable")),
            negative_risk=_as_bool(
                raw.get("negRisk")
                or raw.get("negativeRisk")
                or raw.get("isNegRisk")
            ),
            raw=dict(raw),
        )

    def _resolve_neg_risk_flags(self, positions: Sequence[PositionSnapshot]) -> list[PositionSnapshot]:
        unresolved = {
            position.condition_id
            for position in positions
            if position.condition_id and position.negative_risk is None
        }
        if not unresolved:
            return list(positions)

        gamma_flags: dict[str, bool] = {}
        for page in range(self.gamma_pages):
            params = {
                "closed": "false",
                "limit": self.gamma_page_size,
                "offset": page * self.gamma_page_size,
            }
            try:
                resp = self._session.get(
                    f"{GAMMA_API_BASE}/markets",
                    params=params,
                    timeout=self.timeout_seconds,
                )
                resp.raise_for_status()
                payload = resp.json()
                batch = payload if isinstance(payload, list) else payload.get("data", [])
                if not isinstance(batch, list):
                    batch = []
            except requests.RequestException as exc:
                logger.warning("gamma_lookup_failed err=%s", exc)
                break

            for market in batch:
                condition_id = normalize_bytes32(
                    market.get("conditionId")
                    or market.get("condition_id")
                    or market.get("market")
                )
                if not condition_id or condition_id not in unresolved:
                    continue
                flag = _as_bool(market.get("negRisk") or market.get("negativeRisk"))
                if flag is not None:
                    gamma_flags[condition_id] = flag
                    unresolved.discard(condition_id)

            if not unresolved or len(batch) < self.gamma_page_size:
                break

        resolved: list[PositionSnapshot] = []
        for position in positions:
            if position.negative_risk is not None or not position.condition_id:
                resolved.append(position)
                continue
            flag = gamma_flags.get(position.condition_id)
            resolved.append(replace(position, negative_risk=flag))
        return resolved

    def _enrich_book_quotes(self, positions: Sequence[PositionSnapshot]) -> list[PositionSnapshot]:
        needs_quotes = [position for position in positions if position.token_id]
        if not needs_quotes:
            return list(positions)

        quotes: dict[str, tuple[float | None, float | None]] = {}
        with ThreadPoolExecutor(max_workers=self.quote_workers) as executor:
            futures = {
                executor.submit(self._fetch_book_quote, position.token_id or ""): position.token_id
                for position in needs_quotes
                if position.token_id
            }
            for future in as_completed(futures):
                token_id = futures[future]
                try:
                    quotes[token_id] = future.result()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.debug("book_fetch_failed token=%s err=%s", token_id, exc)

        enriched: list[PositionSnapshot] = []
        for position in positions:
            if not position.token_id or position.token_id not in quotes:
                enriched.append(position)
                continue
            bid, ask = quotes[position.token_id]
            enriched.append(replace(position, best_bid=bid, best_ask=ask))
        return enriched

    def _fetch_book_quote(self, token_id: str) -> tuple[float | None, float | None]:
        resp = self._session.get(
            CLOB_BOOK_URL,
            params={"token_id": token_id},
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        book = resp.json()
        return self._best_book_price(book.get("bids"), side="bid"), self._best_book_price(book.get("asks"), side="ask")

    @staticmethod
    def _best_book_price(levels: Any, *, side: str) -> float | None:
        prices: list[float] = []
        for level in levels or []:
            if isinstance(level, Mapping):
                price = _as_float(level.get("price"))
            elif isinstance(level, Sequence) and not isinstance(level, (str, bytes, bytearray)) and level:
                price = _as_float(level[0])
            else:
                price = None
            if price is None:
                continue
            if 0.0 <= price <= 1.0:
                prices.append(price)
        if not prices:
            return None
        return max(prices) if side == "bid" else min(prices)


class RelayerMergeExecutor:
    """Execute prepared merge transactions via Polymarket's relayer."""

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
        candidates: Sequence[MergeCandidate],
        *,
        dry_run: bool = True,
    ) -> list[MergeExecutionResult]:
        prepared = [(candidate, PositionMergeService.prepare_transaction(candidate)) for candidate in candidates]
        if dry_run:
            return [
                MergeExecutionResult(
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
        except ImportError as exc:  # pragma: no cover - import path is environment-specific
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
        response = client.execute(transactions, metadata=f"merge {len(transactions)} polymarket positions")
        waited = response.wait()
        tx_hash = getattr(response, "transaction_hash", None) or getattr(response, "hash", None)
        transaction_id = getattr(response, "transaction_id", None)
        note = ""
        if isinstance(waited, Mapping):
            tx_hash = tx_hash or waited.get("transactionHash") or waited.get("transaction_hash")
        elif waited is None:
            note = "submitted_not_confirmed"

        return [
            MergeExecutionResult(
                candidate=candidate,
                executor="relayer",
                submitted=True,
                tx_hash=tx_hash,
                transaction_id=transaction_id,
                note=note,
            )
            for candidate, _ in prepared
        ]


class NodePolyMergerExecutor:
    """Call the external open-source poly_merger script directly."""

    def __init__(self, script_path: str | None = None) -> None:
        configured_path = script_path or os.getenv("POLY_MERGER_SCRIPT")
        self.script_path = Path(configured_path).expanduser() if configured_path else None

    def build_command(self, candidate: MergeCandidate) -> list[str]:
        if self.script_path is None:
            raise RuntimeError("POLY_MERGER_SCRIPT is not configured")
        return [
            "node",
            str(self.script_path),
            str(candidate.amount_raw),
            candidate.condition_id,
            "true" if candidate.negative_risk else "false",
        ]

    def execute(
        self,
        candidates: Sequence[MergeCandidate],
        *,
        dry_run: bool = True,
    ) -> list[MergeExecutionResult]:
        results: list[MergeExecutionResult] = []
        for candidate in candidates:
            command = self.build_command(candidate)
            if dry_run:
                results.append(
                    MergeExecutionResult(
                        candidate=candidate,
                        executor="poly_merger",
                        submitted=False,
                        note="dry_run:" + " ".join(command),
                    )
                )
                continue

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            combined_output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
            tx_hash = None
            match = re.search(r"0x[a-fA-F0-9]{64}", combined_output)
            if match:
                tx_hash = match.group(0)

            results.append(
                MergeExecutionResult(
                    candidate=candidate,
                    executor="poly_merger",
                    submitted=completed.returncode == 0,
                    tx_hash=tx_hash,
                    note=combined_output.strip(),
                )
            )
        return results


class LivePositionMerger:
    """Audit the wallet after each cycle and optionally execute merges."""

    def __init__(
        self,
        *,
        user_address: str | None = None,
        service: PositionMergeService | None = None,
        executor: RelayerMergeExecutor | NodePolyMergerExecutor | None = None,
        min_freed_capital_usdc: float = 0.0,
        auto_submit: bool = False,
        limit: int = 250,
    ) -> None:
        self.user_address = user_address or default_user_address()
        self.service = service or PositionMergeService()
        self.executor = executor
        self.min_freed_capital_usdc = max(0.0, float(min_freed_capital_usdc))
        self.auto_submit = bool(auto_submit)
        self.limit = max(1, int(limit))

    def check_and_merge(self) -> dict[str, Any]:
        if not self.user_address:
            return {
                "checked": False,
                "reason": "user_address_missing",
                "duplicate_groups": 0,
                "candidates_found": 0,
                "submitted": 0,
                "freed_capital_usdc": 0.0,
            }

        audit = self.service.build_audit(
            self.user_address,
            limit=self.limit,
            min_freed_capital_usdc=self.min_freed_capital_usdc,
        )
        duplicates = PositionMergeService.find_duplicate_outcome_positions(audit.positions)
        candidates = list(audit.candidates)
        results: list[MergeExecutionResult] = []
        reason = "audit_only"

        if candidates and self.executor is not None:
            dry_run = not self.auto_submit
            results = list(self.executor.execute(candidates, dry_run=dry_run))
            reason = "submitted" if self.auto_submit else "dry_run"
        elif candidates:
            reason = "executor_unconfigured"
        elif duplicates:
            reason = "duplicate_lots_no_complementary_pair"
        else:
            reason = "no_merge_candidates"

        return {
            "checked": True,
            "reason": reason,
            "duplicate_groups": len(duplicates),
            "duplicates": duplicates,
            "candidates_found": len(candidates),
            "submitted": sum(1 for result in results if result.submitted),
            "freed_capital_usdc": audit.total_freed_capital_usdc,
            "results": results,
        }


def default_user_address() -> str | None:
    """Return the wallet address used for Polymarket data-API position queries.

    Checks POLY_DATA_API_ADDRESS first (the proxy wallet that holds positions),
    then falls back to POLY_SAFE_ADDRESS / POLYMARKET_FUNDER (the signing address).
    These differ when using signature_type=1 (POLY_PROXY): the EOA signs on behalf
    of the proxy wallet, but positions are keyed by the proxy address in the data API.
    """
    return (
        os.getenv("POLY_DATA_API_ADDRESS")
        or os.getenv("POLY_SAFE_ADDRESS")
        or os.getenv("POLYMARKET_FUNDER")
        or os.getenv("POLYMARKET_FUNDER_ADDRESS")
    )


def write_report_files(audit: MergeAudit, *, markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(PositionMergeService.render_markdown_report(audit))
    json_path.write_text(json.dumps(PositionMergeService.render_json_report(audit), indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and execute Polymarket position merges")
    parser.add_argument("command", choices=["audit", "merge"], help="Action to run")
    parser.add_argument("--user", default=default_user_address(), help="Wallet/funder address")
    parser.add_argument("--limit", type=int, default=250, help="Maximum number of positions to fetch")
    parser.add_argument("--size-threshold", type=float, default=0.0, help="Minimum position size to include")
    parser.add_argument("--mergeable-only", action="store_true", help="Request only mergeable positions from the API")
    parser.add_argument("--min-freed-usdc", type=float, default=0.0, help="Ignore candidates below this freed-capital threshold")
    parser.add_argument("--executor", choices=["relayer", "poly_merger"], default="relayer", help="Execution backend for merge command")
    parser.add_argument("--script-path", default=os.getenv("POLY_MERGER_SCRIPT"), help="Path to external poly_merger merge.js")
    parser.add_argument("--submit", action="store_true", help="Actually submit merge transactions")
    parser.add_argument("--markdown-report", default="reports/position_merge_report.md", help="Markdown report output path")
    parser.add_argument("--json-report", default="data/position_merge_report.json", help="JSON report output path")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    if not args.user:
        raise SystemExit("wallet address required via --user or POLY_SAFE_ADDRESS/POLYMARKET_FUNDER")

    service = PositionMergeService()
    try:
        audit = service.build_audit(
            args.user,
            size_threshold=args.size_threshold,
            limit=args.limit,
            mergeable_only=args.mergeable_only,
            min_freed_capital_usdc=args.min_freed_usdc,
        )
        write_report_files(
            audit,
            markdown_path=Path(args.markdown_report),
            json_path=Path(args.json_report),
        )
        print(PositionMergeService.render_markdown_report(audit))

        if args.command == "audit":
            return 0

        candidates = [candidate for candidate in audit.candidates if candidate.execution_ready]
        if not candidates:
            print("No execution-ready merge candidates found.")
            return 0

        if args.executor == "poly_merger":
            executor = NodePolyMergerExecutor(args.script_path)
        else:
            executor = RelayerMergeExecutor()

        results = executor.execute(candidates, dry_run=not args.submit)
        print(json.dumps([asdict(result) for result in results], indent=2))
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
