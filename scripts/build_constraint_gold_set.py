#!/usr/bin/env python3
"""Build a deterministic pair/triple labeling scaffold for B-1 constraint arbitrage."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from itertools import combinations
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.constraint_arb_engine import CandidateGenerator, CandidatePair, build_pair_signature, fetch_gamma_markets
from bot.cross_platform_arb import extract_keywords
from bot.resolution_normalizer import NormalizedMarket, normalize_market


PAIR_BUCKET_ORDER = (
    "implication_candidate",
    "mutual_exclusion_candidate",
    "office_hierarchy_candidate",
    "shared_anchor_candidate",
    "same_event_cluster",
    "control_near_miss",
)
TRIPLE_BUCKET_ORDER = (
    "same_event_triplet",
    "shared_anchor_triplet",
    "control_triplet",
)


@dataclass(frozen=True)
class TripleCandidate:
    markets: tuple[NormalizedMarket, NormalizedMarket, NormalizedMarket]
    triple_signature: str
    sample_bucket: str
    priority: float
    passed_pairs: int
    pairwise: tuple[CandidatePair, CandidatePair, CandidatePair]
    reason_codes: tuple[str, ...]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deterministic_order(seed: int, signature: str, priority: float) -> tuple[float, str]:
    digest = hashlib.sha1(f"{seed}|{signature}".encode("utf-8")).hexdigest()
    return (-priority, digest)


def _load_local_markets(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
        return rows

    payload = json.loads(text)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    raise ValueError(f"Unsupported market payload in {path}")


def load_raw_markets(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str]:
    if args.input_jsonl:
        input_path = Path(args.input_jsonl)
        return _load_local_markets(input_path), f"local:{input_path}"
    rows = fetch_gamma_markets(
        max_pages=int(args.max_pages),
        page_limit=int(args.page_limit),
        include_closed=bool(args.include_closed),
    )
    return rows, "gamma:active"


def _anchor_tokens(market: NormalizedMarket) -> tuple[str, ...]:
    event_tokens = extract_keywords(market.event_id.replace("-", " "))
    question_tokens = extract_keywords(market.question)
    anchors = sorted(event_tokens | set(sorted(question_tokens)[:4]))
    return tuple(anchors[:6])


def _serialize_market(market: NormalizedMarket) -> dict[str, Any]:
    return {
        "market_id": market.market_id,
        "event_id": market.event_id,
        "question": market.question,
        "category": market.category,
        "outcomes": list(market.outcomes),
        "outcome": market.outcome,
        "resolution_key": market.resolution_key,
        "resolution_source": market.profile.source,
        "cutoff_ts": market.profile.cutoff_ts,
        "cutoff_utc": (
            datetime.fromtimestamp(market.profile.cutoff_ts, tz=timezone.utc).isoformat()
            if market.profile.cutoff_ts is not None
            else None
        ),
        "scope_fingerprint": list(market.profile.scope_fingerprint),
        "anchors": list(_anchor_tokens(market)),
    }


def _pair_record(pair: CandidatePair, *, sample_id: str, generated_at: str, source: str) -> dict[str, Any]:
    return {
        "sample_type": "pair",
        "sample_id": sample_id,
        "generated_at_utc": generated_at,
        "source": source,
        "label_status": "pending_human_review",
        "gold_label": None,
        "suggested_label": pair.suggested_label,
        "sample_bucket": pair.sample_bucket,
        "pair_signature": pair.pair_signature,
        "prefilter_passed": pair.passed,
        "prefilter_score": pair.priority,
        "reason_codes": list(pair.reason_codes),
        "prefilter": asdict(pair.features),
        "markets": [
            _serialize_market(pair.market_a),
            _serialize_market(pair.market_b),
        ],
    }


def _triple_record(triple: TripleCandidate, *, sample_id: str, generated_at: str, source: str) -> dict[str, Any]:
    return {
        "sample_type": "triple",
        "sample_id": sample_id,
        "generated_at_utc": generated_at,
        "source": source,
        "label_status": "pending_human_review",
        "gold_label": None,
        "sample_bucket": triple.sample_bucket,
        "triple_signature": triple.triple_signature,
        "priority": triple.priority,
        "passed_pairs": triple.passed_pairs,
        "reason_codes": list(triple.reason_codes),
        "pairwise": [
            {
                "pair_signature": pair.pair_signature,
                "sample_bucket": pair.sample_bucket,
                "suggested_label": pair.suggested_label,
                "prefilter_passed": pair.passed,
                "prefilter_score": pair.priority,
                "reason_codes": list(pair.reason_codes),
            }
            for pair in triple.pairwise
        ],
        "markets": [_serialize_market(market) for market in triple.markets],
    }


def _bucket_targets(total: int, order: Sequence[str]) -> dict[str, int]:
    if total <= 0:
        return {bucket: 0 for bucket in order}
    if order == PAIR_BUCKET_ORDER:
        weights = {
            "implication_candidate": 0.2,
            "mutual_exclusion_candidate": 0.15,
            "office_hierarchy_candidate": 0.1,
            "shared_anchor_candidate": 0.2,
            "same_event_cluster": 0.2,
            "control_near_miss": 0.15,
        }
    else:
        weights = {
            "same_event_triplet": 0.48,
            "shared_anchor_triplet": 0.32,
            "control_triplet": 0.20,
        }

    targets = {bucket: int(total * weights[bucket]) for bucket in order}
    remainder = total - sum(targets.values())
    for bucket in order:
        if remainder <= 0:
            break
        targets[bucket] += 1
        remainder -= 1
    return targets


def select_pairs(
    candidates: Sequence[CandidatePair],
    *,
    target_count: int,
    seed: int,
) -> list[CandidatePair]:
    by_bucket = {bucket: [] for bucket in PAIR_BUCKET_ORDER}
    for pair in candidates:
        by_bucket.setdefault(pair.sample_bucket, []).append(pair)

    for bucket_pairs in by_bucket.values():
        bucket_pairs.sort(key=lambda pair: _deterministic_order(seed, pair.pair_signature, pair.priority))

    selected: list[CandidatePair] = []
    selected_keys: set[str] = set()
    targets = _bucket_targets(target_count, PAIR_BUCKET_ORDER)

    for bucket in PAIR_BUCKET_ORDER:
        for pair in by_bucket.get(bucket, []):
            if len(selected) >= target_count or targets[bucket] <= 0:
                break
            if pair.pair_signature in selected_keys:
                continue
            selected.append(pair)
            selected_keys.add(pair.pair_signature)
            targets[bucket] -= 1

    remainder = sorted(
        [pair for pair in candidates if pair.pair_signature not in selected_keys],
        key=lambda pair: _deterministic_order(seed, pair.pair_signature, pair.priority),
    )
    for pair in remainder:
        if len(selected) >= target_count:
            break
        selected.append(pair)
        selected_keys.add(pair.pair_signature)
    return selected


def _fallback_control_pairs(
    markets: Sequence[NormalizedMarket],
    generator: CandidateGenerator,
    *,
    seen_signatures: set[str],
    limit: int,
) -> list[CandidatePair]:
    controls: list[CandidatePair] = []
    ordered_markets = sorted(markets, key=lambda market: market.market_id)
    for left, right in combinations(ordered_markets, 2):
        pair = generator.score_pair(left, right)
        if pair.passed:
            continue
        if pair.pair_signature in seen_signatures:
            continue
        controls.append(pair)
        seen_signatures.add(pair.pair_signature)
        if len(controls) >= limit:
            break
    return controls


def build_triples(
    markets: Sequence[NormalizedMarket],
    pair_lookup: dict[str, CandidatePair],
    generator: CandidateGenerator,
) -> list[TripleCandidate]:
    triples: dict[str, TripleCandidate] = {}

    by_event: dict[str, list[NormalizedMarket]] = {}
    for market in markets:
        by_event.setdefault(market.event_id, []).append(market)

    for event_id, event_markets in by_event.items():
        if len(event_markets) < 3:
            continue
        for combo in combinations(sorted(event_markets, key=lambda market: market.market_id), 3):
            pairwise = tuple(
                pair_lookup.get(build_pair_signature(left, right)) or generator.score_pair(left, right)
                for left, right in combinations(combo, 2)
            )
            priority = sum(pair.priority for pair in pairwise) / len(pairwise)
            passed_pairs = sum(1 for pair in pairwise if pair.passed)
            signature = hashlib.sha1("|".join(market.market_id for market in combo).encode("utf-8")).hexdigest()
            triples[signature] = TripleCandidate(
                markets=combo,
                triple_signature=signature,
                sample_bucket="same_event_triplet" if passed_pairs >= 2 else "control_triplet",
                priority=float(priority),
                passed_pairs=passed_pairs,
                pairwise=pairwise,
                reason_codes=tuple(sorted({reason for pair in pairwise for reason in pair.reason_codes})),
            )

    by_anchor: dict[str, list[NormalizedMarket]] = {}
    for market in markets:
        for anchor in _anchor_tokens(market):
            by_anchor.setdefault(anchor, []).append(market)

    for anchor, anchor_markets in by_anchor.items():
        if len(anchor_markets) < 3:
            continue
        unique_events = {market.event_id for market in anchor_markets}
        if len(unique_events) < 2:
            continue
        for combo in combinations(sorted(anchor_markets, key=lambda market: market.market_id), 3):
            signature = hashlib.sha1("|".join(market.market_id for market in combo).encode("utf-8")).hexdigest()
            if signature in triples:
                continue
            pairwise = tuple(
                pair_lookup.get(build_pair_signature(left, right)) or generator.score_pair(left, right)
                for left, right in combinations(combo, 2)
            )
            priority = sum(pair.priority for pair in pairwise) / len(pairwise)
            passed_pairs = sum(1 for pair in pairwise if pair.passed)
            if passed_pairs == 0:
                bucket = "control_triplet"
            elif passed_pairs >= 2:
                bucket = "shared_anchor_triplet"
            else:
                continue
            triples[signature] = TripleCandidate(
                markets=combo,
                triple_signature=signature,
                sample_bucket=bucket,
                priority=float(priority + (0.5 if anchor in combo[0].event_id else 0.0)),
                passed_pairs=passed_pairs,
                pairwise=pairwise,
                reason_codes=tuple(sorted({anchor, *(reason for pair in pairwise for reason in pair.reason_codes)})),
            )
    return list(triples.values())


def select_triples(
    candidates: Sequence[TripleCandidate],
    *,
    target_count: int,
    seed: int,
) -> list[TripleCandidate]:
    by_bucket = {bucket: [] for bucket in TRIPLE_BUCKET_ORDER}
    for triple in candidates:
        by_bucket.setdefault(triple.sample_bucket, []).append(triple)

    for bucket_triples in by_bucket.values():
        bucket_triples.sort(key=lambda triple: _deterministic_order(seed, triple.triple_signature, triple.priority))

    selected: list[TripleCandidate] = []
    selected_keys: set[str] = set()
    targets = _bucket_targets(target_count, TRIPLE_BUCKET_ORDER)

    for bucket in TRIPLE_BUCKET_ORDER:
        for triple in by_bucket.get(bucket, []):
            if len(selected) >= target_count or targets[bucket] <= 0:
                break
            if triple.triple_signature in selected_keys:
                continue
            selected.append(triple)
            selected_keys.add(triple.triple_signature)
            targets[bucket] -= 1

    remainder = sorted(
        [triple for triple in candidates if triple.triple_signature not in selected_keys],
        key=lambda triple: _deterministic_order(seed, triple.triple_signature, triple.priority),
    )
    for triple in remainder:
        if len(selected) >= target_count:
            break
        selected.append(triple)
        selected_keys.add(triple.triple_signature)
    return selected


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_sampling_report(
    path: Path,
    *,
    generated_at: str,
    source: str,
    market_count: int,
    raw_count: int,
    candidate_stats: dict[str, int],
    selected_pairs: Sequence[CandidatePair],
    selected_triples: Sequence[TripleCandidate],
    output_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pair_bucket_counts: dict[str, int] = {}
    for pair in selected_pairs:
        pair_bucket_counts[pair.sample_bucket] = pair_bucket_counts.get(pair.sample_bucket, 0) + 1
    triple_bucket_counts: dict[str, int] = {}
    for triple in selected_triples:
        triple_bucket_counts[triple.sample_bucket] = triple_bucket_counts.get(triple.sample_bucket, 0) + 1

    naive_pairs = candidate_stats.get("naive_pairs", 0)
    returned_pairs = candidate_stats.get("returned_pairs", 0)
    reduction_ratio = 0.0 if naive_pairs == 0 else 1.0 - (returned_pairs / naive_pairs)

    lines = [
        "# Constraint Gold Set Sampling Report",
        "",
        f"- Generated at (UTC): {generated_at}",
        f"- Source: {source}",
        f"- Raw markets loaded: {raw_count}",
        f"- Normalized markets retained: {market_count}",
        f"- Output artifact: {output_path}",
        "",
        "## Prefilter Reduction",
        "",
        f"- Naive all-pairs: {naive_pairs}",
        f"- Same-event pairs considered: {candidate_stats.get('same_event_considered', 0)}",
        f"- Blocked pairs considered: {candidate_stats.get('block_pairs_considered', 0)}",
        f"- Unique pairs scored: {candidate_stats.get('unique_pairs_considered', 0)}",
        f"- Passed prefilter: {candidate_stats.get('passed_pairs', 0)}",
        f"- Rejected near-miss pairs: {candidate_stats.get('rejected_pairs', 0)}",
        f"- Candidate reduction vs naive: {reduction_ratio:.2%}",
        "",
        "## Pair Sample",
        "",
        f"- Selected pair records: {len(selected_pairs)}",
    ]
    for bucket in PAIR_BUCKET_ORDER:
        lines.append(f"- `{bucket}`: {pair_bucket_counts.get(bucket, 0)}")

    lines.extend(
        [
            "",
            "## Triple Sample",
            "",
            f"- Selected triple records: {len(selected_triples)}",
        ]
    )
    for bucket in TRIPLE_BUCKET_ORDER:
        lines.append(f"- `{bucket}`: {triple_bucket_counts.get(bucket, 0)}")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Pair records are seeded scaffolds for human verification, not final gold labels.",
            "- Controls are intentionally kept in the sample to measure false-positive pressure before any LLM call.",
            "- Triples are future-research artifacts only; they are included for annotation and chain exploration, not phase-1 trading.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", help="Optional local JSON/JSONL market dump instead of Gamma fetch.")
    parser.add_argument("--include-closed", action="store_true", help="Include closed Gamma markets when fetching live data.")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--page-limit", type=int, default=200)
    parser.add_argument("--pair-count", type=int, default=100)
    parser.add_argument("--triple-count", type=int, default=25)
    parser.add_argument("--candidate-cap", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20260307)
    parser.add_argument("--output", default="data/constraint_gold_set.jsonl")
    parser.add_argument("--report", default="reports/constraint_gold_set_sampling.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated_at = _now_iso()
    raw_rows, source = load_raw_markets(args)
    normalized = [normalize_market(row) for row in raw_rows if isinstance(row, dict)]
    generator = CandidateGenerator()
    candidate_pairs = generator.generate_candidates(
        normalized,
        max_pairs=max(1, int(args.candidate_cap)),
        include_rejected=True,
    )

    seen_signatures = {pair.pair_signature for pair in candidate_pairs}
    if len(candidate_pairs) < int(args.pair_count):
        candidate_pairs.extend(
            _fallback_control_pairs(
                normalized,
                generator,
                seen_signatures=seen_signatures,
                limit=int(args.pair_count) - len(candidate_pairs),
            )
        )

    selected_pairs = select_pairs(candidate_pairs, target_count=int(args.pair_count), seed=int(args.seed))
    pair_lookup = {pair.pair_signature: pair for pair in candidate_pairs}
    triple_candidates = build_triples(normalized, pair_lookup, generator)
    selected_triples = select_triples(triple_candidates, target_count=int(args.triple_count), seed=int(args.seed))

    rows: list[dict[str, Any]] = []
    for idx, pair in enumerate(selected_pairs, start=1):
        rows.append(_pair_record(pair, sample_id=f"pair-{idx:04d}", generated_at=generated_at, source=source))
    for idx, triple in enumerate(selected_triples, start=1):
        rows.append(_triple_record(triple, sample_id=f"triple-{idx:04d}", generated_at=generated_at, source=source))

    output_path = Path(args.output)
    report_path = Path(args.report)
    write_jsonl(output_path, rows)
    write_sampling_report(
        report_path,
        generated_at=generated_at,
        source=source,
        market_count=len(normalized),
        raw_count=len(raw_rows),
        candidate_stats=generator.last_stats,
        selected_pairs=selected_pairs,
        selected_triples=selected_triples,
        output_path=output_path,
    )
    print(f"Wrote {len(selected_pairs)} pairs and {len(selected_triples)} triples to {output_path}")
    print(f"Wrote sampling report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
