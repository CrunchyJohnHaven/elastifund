#!/usr/bin/env python3
"""Build the 50-pair B-1 gold set for relation classifier validation.

Fetches active Polymarket markets, generates candidate pairs, classifies
relations via the relation classifier, and selects 50 diverse pairs spanning
all relation types. Outputs:
  - data/b1_gold_set.json
  - research/b1_gold_set_candidates.md
  - reports/b1_classifier_tuning.md  (confidence threshold analysis)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.constraint_arb_engine import CandidateGenerator, CandidatePair, fetch_gamma_markets
from bot.relation_classifier import RelationClassifier, RelationResult
from bot.resolution_normalizer import NormalizedMarket, normalize_market

logger = logging.getLogger("JJ.build_b1_gold_set")

# Desired distribution of relation types in the gold set
RELATION_TARGETS = {
    "A_implies_B": 10,
    "B_implies_A": 10,
    "mutually_exclusive": 10,
    "complementary": 5,
    "subset": 5,
    "independent": 10,
}

TOTAL_GOLD_SET = 50


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_market(market: NormalizedMarket) -> dict[str, Any]:
    return {
        "market_id": market.market_id,
        "event_id": market.event_id,
        "question": market.question,
        "category": market.category,
        "outcomes": list(market.outcomes),
        "outcome": market.outcome,
        "resolution_key": market.resolution_key,
    }


def fetch_and_normalize(
    *,
    max_pages: int = 5,
    page_limit: int = 200,
) -> list[NormalizedMarket]:
    """Fetch markets from Gamma API and normalize."""
    logger.info("Fetching markets from Gamma API (max_pages=%d, page_limit=%d)", max_pages, page_limit)
    raw = fetch_gamma_markets(max_pages=max_pages, page_limit=page_limit)
    logger.info("Fetched %d raw markets", len(raw))
    normalized = [normalize_market(row) for row in raw if isinstance(row, dict)]
    logger.info("Normalized %d markets", len(normalized))
    return normalized


def classify_pairs(
    pairs: Sequence[CandidatePair],
    classifier: RelationClassifier,
    *,
    max_classify: int = 100,
) -> list[dict[str, Any]]:
    """Classify up to max_classify candidate pairs and return results."""
    results: list[dict[str, Any]] = []
    sorted_pairs = sorted(pairs, key=lambda p: -p.priority)[:max_classify]

    for idx, pair in enumerate(sorted_pairs, 1):
        logger.info(
            "Classifying pair %d/%d: %s vs %s",
            idx,
            len(sorted_pairs),
            pair.market_a.question[:60],
            pair.market_b.question[:60],
        )
        result = classifier.classify(pair.market_a, pair.market_b)
        results.append({
            "market_a": pair.market_a,
            "market_b": pair.market_b,
            "pair_signature": pair.pair_signature,
            "candidate_score": pair.priority,
            "sample_bucket": pair.sample_bucket,
            "classification": result,
        })

    return results


def select_gold_set(
    classified: list[dict[str, Any]],
    *,
    target_count: int = TOTAL_GOLD_SET,
) -> list[dict[str, Any]]:
    """Select target_count pairs with diverse relation type coverage."""
    by_relation: dict[str, list[dict[str, Any]]] = {}
    for entry in classified:
        rel = entry["classification"].relation_type
        by_relation.setdefault(rel, []).append(entry)

    # Sort each bucket by descending confidence
    for entries in by_relation.values():
        entries.sort(key=lambda e: -e["classification"].confidence)

    selected: list[dict[str, Any]] = []
    selected_sigs: set[str] = set()

    # Phase 1: Fill targets per relation type
    for relation, target in RELATION_TARGETS.items():
        bucket = by_relation.get(relation, [])
        added = 0
        for entry in bucket:
            if added >= target or len(selected) >= target_count:
                break
            if entry["pair_signature"] in selected_sigs:
                continue
            selected.append(entry)
            selected_sigs.add(entry["pair_signature"])
            added += 1

    # Phase 2: Fill remaining slots from any relation type
    remaining = [e for e in classified if e["pair_signature"] not in selected_sigs]
    remaining.sort(key=lambda e: -e["classification"].confidence)
    for entry in remaining:
        if len(selected) >= target_count:
            break
        selected.append(entry)
        selected_sigs.add(entry["pair_signature"])

    return selected


def build_gold_set_json(
    gold_set: list[dict[str, Any]],
    *,
    generated_at: str,
) -> list[dict[str, Any]]:
    """Serialize gold set to JSON-friendly format."""
    records: list[dict[str, Any]] = []
    for idx, entry in enumerate(gold_set, 1):
        cls: RelationResult = entry["classification"]
        records.append({
            "pair_id": idx,
            "market_a_id": entry["market_a"].market_id,
            "market_b_id": entry["market_b"].market_id,
            "market_a_title": entry["market_a"].question,
            "market_b_title": entry["market_b"].question,
            "classified_relation": cls.relation_type,
            "confidence": round(cls.confidence, 4),
            "short_rationale": cls.short_rationale,
            "source": cls.source,
            "cache_hit": cls.cache_hit,
            "human_label_placeholder": None,
            "labeled": False,
            "generated_at": generated_at,
            "market_a": _serialize_market(entry["market_a"]),
            "market_b": _serialize_market(entry["market_b"]),
        })
    return records


def write_gold_set_json(records: list[dict[str, Any]], path: Path) -> None:
    """Write gold set JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    logger.info("Wrote %d gold set records to %s", len(records), path)


def write_gold_set_markdown(records: list[dict[str, Any]], path: Path) -> None:
    """Write human-readable gold set table for review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# B-1 Gold Set Candidates",
        "",
        f"Generated: {records[0]['generated_at'] if records else 'N/A'}",
        f"Total pairs: {len(records)}",
        "",
        "## Instructions for John",
        "",
        "Review each pair below. For each, confirm or correct the `classified_relation`",
        "by updating `human_label_placeholder` in `data/b1_gold_set.json`.",
        "Set `labeled: true` when verified.",
        "",
        "## Relation Distribution",
        "",
    ]

    counts = Counter(r["classified_relation"] for r in records)
    for rel, count in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{rel}**: {count}")

    lines.extend(["", "## Pair Table", ""])
    lines.append("| # | Relation | Conf | Market A | Market B | Rationale |")
    lines.append("|---|----------|------|----------|----------|-----------|")

    for r in records:
        a_title = r["market_a_title"][:50] + ("..." if len(r["market_a_title"]) > 50 else "")
        b_title = r["market_b_title"][:50] + ("..." if len(r["market_b_title"]) > 50 else "")
        rationale = (r["short_rationale"] or "")[:60]
        lines.append(
            f"| {r['pair_id']} "
            f"| {r['classified_relation']} "
            f"| {r['confidence']:.2f} "
            f"| {a_title} "
            f"| {b_title} "
            f"| {rationale} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote gold set markdown to %s", path)


def run_threshold_analysis(
    classified: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Analyze classifier accuracy vs confidence threshold.

    Without human labels, we report:
    - Distribution of confidence scores
    - Pair counts at each threshold
    - Recommended production threshold

    With human labels (future), precision/recall can be computed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    confidences = [e["classification"].confidence for e in classified]
    if not confidences:
        output_path.write_text("# Classifier Tuning Report\n\nNo classified pairs available.\n", encoding="utf-8")
        return

    thresholds = [round(0.50 + i * 0.05, 2) for i in range(10)]  # 0.50 to 0.95
    relation_counts_total = Counter(e["classification"].relation_type for e in classified)

    lines = [
        "# B-1 Classifier Confidence Threshold Tuning",
        "",
        f"Total classified pairs: {len(classified)}",
        f"Mean confidence: {sum(confidences) / len(confidences):.3f}",
        f"Median confidence: {sorted(confidences)[len(confidences) // 2]:.3f}",
        f"Min confidence: {min(confidences):.3f}",
        f"Max confidence: {max(confidences):.3f}",
        "",
        "## Overall Relation Distribution",
        "",
    ]
    for rel, count in sorted(relation_counts_total.items(), key=lambda x: -x[1]):
        lines.append(f"- {rel}: {count} ({100 * count / len(classified):.1f}%)")

    lines.extend([
        "",
        "## Threshold Analysis",
        "",
        "| Threshold | Pairs Retained | % Retained | Relation Types | Notes |",
        "|-----------|---------------|------------|----------------|-------|",
    ])

    recommended_threshold = 0.70  # default
    for threshold in thresholds:
        retained = [e for e in classified if e["classification"].confidence >= threshold]
        n_retained = len(retained)
        pct = 100 * n_retained / len(classified) if classified else 0
        rel_types = len(set(e["classification"].relation_type for e in retained))
        notes = ""
        if n_retained < 10:
            notes = "Too few pairs"
        elif rel_types < 3:
            notes = "Low type diversity"
        elif pct < 30:
            notes = "Aggressive filter"

        lines.append(
            f"| {threshold:.2f} | {n_retained} | {pct:.1f}% | {rel_types} | {notes} |"
        )

    # Find recommended threshold: highest threshold where we keep 50%+ and 4+ types
    for threshold in reversed(thresholds):
        retained = [e for e in classified if e["classification"].confidence >= threshold]
        n_retained = len(retained)
        rel_types = len(set(e["classification"].relation_type for e in retained))
        if n_retained >= len(classified) * 0.4 and rel_types >= 4:
            recommended_threshold = threshold
            break

    lines.extend([
        "",
        "## Recommendation",
        "",
        f"**Recommended production threshold: {recommended_threshold:.2f}**",
        "",
        "Rationale: This is the highest confidence threshold that retains 40%+",
        "of classified pairs while maintaining 4+ distinct relation types.",
        "",
        "Note: Without human labels, precision/recall cannot be computed.",
        "Once John reviews the gold set (sets `labeled: true` and fills",
        "`human_label_placeholder`), re-run this analysis for proper",
        "precision vs. recall curves.",
        "",
        "## Next Steps",
        "",
        "1. John reviews `data/b1_gold_set.json` — confirms or corrects each relation label",
        "2. Re-run with `--labels` flag to compute precision/recall at each threshold",
        "3. Set production threshold where precision > 90% AND recall > 70%",
    ])

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote classifier tuning report to %s", output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=5, help="Gamma API pages to fetch")
    parser.add_argument("--page-limit", type=int, default=200, help="Markets per page")
    parser.add_argument("--max-classify", type=int, default=100, help="Max pairs to classify")
    parser.add_argument("--gold-set-size", type=int, default=50, help="Target gold set size")
    parser.add_argument("--output-json", default="data/b1_gold_set.json")
    parser.add_argument("--output-md", default="research/b1_gold_set_candidates.md")
    parser.add_argument("--tuning-report", default="reports/b1_classifier_tuning.md")
    parser.add_argument("--input-jsonl", default="", help="Local market JSON instead of Gamma fetch")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    generated_at = _now_iso()

    # Step 1: Get markets
    if args.input_jsonl:
        raw = json.loads(Path(args.input_jsonl).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "data" in raw:
            raw = raw["data"]
        markets = [normalize_market(row) for row in raw if isinstance(row, dict)]
    else:
        markets = fetch_and_normalize(max_pages=args.max_pages, page_limit=args.page_limit)

    if len(markets) < 10:
        logger.error("Too few markets (%d) to build gold set", len(markets))
        return 1

    # Step 2: Generate candidate pairs
    generator = CandidateGenerator()
    candidates = generator.generate_candidates(markets, max_pairs=4000, include_rejected=True)
    passed = [c for c in candidates if c.passed]
    logger.info(
        "Generated %d candidate pairs (%d passed prefilter)",
        len(candidates),
        len(passed),
    )

    if len(passed) < 10:
        logger.warning("Few passed pairs (%d), using all candidates", len(passed))
        passed = candidates

    # Step 3: Classify pairs
    classifier = RelationClassifier()
    classified = classify_pairs(passed, classifier, max_classify=args.max_classify)
    logger.info("Classified %d pairs", len(classified))

    # Step 4: Select gold set
    gold_set = select_gold_set(classified, target_count=args.gold_set_size)
    logger.info("Selected %d gold set pairs", len(gold_set))

    # Step 5: Write outputs
    records = build_gold_set_json(gold_set, generated_at=generated_at)
    write_gold_set_json(records, Path(args.output_json))
    write_gold_set_markdown(records, Path(args.output_md))

    # Step 6: Threshold analysis
    run_threshold_analysis(classified, Path(args.tuning_report))

    # Summary
    counts = Counter(r["classified_relation"] for r in records)
    print(f"\nB-1 Gold Set Summary ({len(records)} pairs):")
    for rel, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {rel}: {count}")
    print(f"\nOutputs:")
    print(f"  Gold set JSON: {args.output_json}")
    print(f"  Gold set MD:   {args.output_md}")
    print(f"  Tuning report: {args.tuning_report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
