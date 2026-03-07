#!/usr/bin/env python3
"""Top-level B-1 dependency-graph pipeline and CLI."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from execution.multileg_executor import MultiLegAttempt
from infra.clob_ws import BestBidAskStore
from signals.dep_graph.dep_candidate_pairs import CandidatePair, DepCandidatePairGenerator
from signals.dep_graph.dep_executor import DepExecutionPlanner
from signals.dep_graph.dep_graph_store import DepEdgeRecord, DepGraphStore, question_hash
from signals.dep_graph.dep_haiku_classifier import HaikuDependencyClassifier
from signals.dep_graph.dep_monitor import DepViolation, DepViolationMonitor
from signals.dep_graph.dep_validation import DepValidationHarness
from strategies.a6_sum_violation import parse_clob_token_ids


logger = logging.getLogger("JJ.dependency_graph")

DEFAULT_DB_PATH = Path("data") / "dep_graph.sqlite"
TRADABLE_RELATIONS = frozenset(
    {"A_implies_B", "B_implies_A", "mutually_exclusive", "subset", "complementary"}
)
DEFAULT_CONSTRAINT_BY_RELATION = {
    "A_implies_B": "P(A)<=P(B)",
    "B_implies_A": "P(B)<=P(A)",
    "mutually_exclusive": "P(A)+P(B)<=1",
    "subset": "P(A)<=P(B)",
    "complementary": "P(A)+P(B)=1",
    "independent": "none",
}


def _market_id(row: Mapping[str, Any]) -> str:
    return str(row.get("id") or row.get("market_id") or "").strip()


def _market_question(row: Mapping[str, Any]) -> str:
    return str(row.get("question") or row.get("title") or "").strip()


def _market_category(row: Mapping[str, Any]) -> str:
    return str(row.get("category") or row.get("eventCategory") or "").strip()


def _market_end_date(row: Mapping[str, Any]) -> str | None:
    value = row.get("endDate") or row.get("end_date")
    if value in (None, ""):
        return None
    return str(value)


def _canonical_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    left_key = (_market_id(left), _market_question(left))
    right_key = (_market_id(right), _market_question(right))
    if left_key <= right_key:
        return dict(left), dict(right)
    return dict(right), dict(left)


def _edge_id(a_market_id: str, b_market_id: str, model_version: str) -> str:
    payload = f"{model_version}|{a_market_id}|{b_market_id}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _constraint_for_relation(relation: str, explicit_constraint: str) -> str:
    if explicit_constraint and explicit_constraint != "none":
        return explicit_constraint
    return DEFAULT_CONSTRAINT_BY_RELATION.get(relation, "none")


def _classification_accuracy(summary: Mapping[str, Any]) -> float | None:
    human_labeled = int(summary.get("human_labeled") or 0)
    resolved_labeled = int(summary.get("resolved_labeled") or 0)
    if human_labeled > 0:
        return float(summary.get("accuracy_human") or 0.0)
    if resolved_labeled > 0:
        return float(summary.get("accuracy_resolved") or 0.0)
    return None


def _quote_store_from_rows(rows: Sequence[Mapping[str, Any]]) -> BestBidAskStore:
    store = BestBidAskStore()
    for row in rows:
        token_id = str(row.get("token_id") or row.get("asset_id") or "").strip()
        if not token_id:
            continue
        try:
            best_bid = float(row.get("best_bid"))
            best_ask = float(row.get("best_ask"))
        except (TypeError, ValueError):
            continue
        updated_ts = row.get("updated_ts") or row.get("timestamp")
        store.update(token_id, best_bid=best_bid, best_ask=best_ask, updated_ts=updated_ts)
    return store


def _load_json_payload(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _coerce_markets_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        if isinstance(payload.get("data"), list):
            payload = payload["data"]
        elif isinstance(payload.get("markets"), list):
            payload = [payload]

    if not isinstance(payload, list):
        raise ValueError("markets payload must be a list or an object with a data list")

    markets: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue

        nested_markets = row.get("markets")
        if isinstance(nested_markets, list):
            event_id = str(row.get("id") or row.get("event_id") or row.get("slug") or "").strip()
            for market in nested_markets:
                if not isinstance(market, Mapping):
                    continue
                merged = dict(market)
                if event_id:
                    merged.setdefault("event_id", event_id)
                merged.setdefault("category", row.get("category") or row.get("eventCategory"))
                merged.setdefault("endDate", row.get("endDate"))
                merged.setdefault("resolutionSource", row.get("resolutionSource"))
                merged.setdefault("description", row.get("description") or row.get("rules"))
                merged.setdefault("tags", row.get("tags"))
                markets.append(merged)
            continue

        markets.append(dict(row))

    return [row for row in markets if _market_id(row) and _market_question(row)]


@dataclass(frozen=True)
class DependencyGraphBuildResult:
    market_count: int
    candidate_count: int
    classified_count: int
    cache_hits: int
    tradable_edge_count: int
    edges: tuple[DepEdgeRecord, ...]
    accuracy_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_count": self.market_count,
            "candidate_count": self.candidate_count,
            "classified_count": self.classified_count,
            "cache_hits": self.cache_hits,
            "tradable_edge_count": self.tradable_edge_count,
            "edges": [asdict(edge) for edge in self.edges],
            "accuracy_summary": dict(self.accuracy_summary),
        }


@dataclass(frozen=True)
class DependencyGraphCycleResult:
    build: DependencyGraphBuildResult
    violations: tuple[DepViolation, ...]
    attempts: tuple[MultiLegAttempt, ...]
    classification_accuracy: float | None

    def to_dict(self) -> dict[str, Any]:
        attempt_rows: list[dict[str, Any]] = []
        for attempt in self.attempts:
            attempt_rows.append(
                {
                    "attempt_id": attempt.attempt_id,
                    "strategy_id": attempt.strategy_id,
                    "group_id": attempt.group_id,
                    "state": getattr(attempt.state, "value", str(attempt.state)),
                    "metadata": dict(attempt.metadata),
                    "legs": [
                        {
                            "leg_id": leg.spec.leg_id,
                            "market_id": leg.spec.market_id,
                            "token_id": leg.spec.token_id,
                            "side": leg.spec.side,
                            "price": leg.spec.price,
                            "size": leg.spec.size,
                        }
                        for leg in attempt.legs
                    ],
                }
            )

        return {
            "build": self.build.to_dict(),
            "classification_accuracy": self.classification_accuracy,
            "violations": [
                {
                    "edge_id": violation.edge_id,
                    "relation": violation.relation,
                    "confidence": violation.confidence,
                    "epsilon": violation.epsilon,
                    "violation_mag": violation.violation_mag,
                    "details": dict(violation.details),
                    "legs": [asdict(leg) for leg in violation.legs],
                }
                for violation in self.violations
            ],
            "attempts": attempt_rows,
        }


class DependencyGraphService:
    """Build, validate, and scan the B-1 dependency graph."""

    def __init__(
        self,
        *,
        db_path: str | Path = DEFAULT_DB_PATH,
        candidate_generator: DepCandidatePairGenerator | None = None,
        classifier: HaikuDependencyClassifier | None = None,
        leg_usd_cap: float = 5.0,
        c1: float = 1.5,
        nonatomic_penalty: float = 0.01,
    ) -> None:
        self.store = DepGraphStore(db_path)
        self.validation = DepValidationHarness(self.store)
        self.candidate_generator = candidate_generator or DepCandidatePairGenerator()
        self.classifier = classifier or HaikuDependencyClassifier()
        self.leg_usd_cap = max(0.1, float(leg_usd_cap))
        self.c1 = float(c1)
        self.nonatomic_penalty = float(nonatomic_penalty)

    def build_graph(
        self,
        markets: Sequence[Mapping[str, Any]],
        *,
        min_confidence: float = 0.0,
    ) -> DependencyGraphBuildResult:
        rows = _coerce_markets_payload(list(markets))
        for market in rows:
            self.store.upsert_market_meta(
                market_id=_market_id(market),
                question=_market_question(market),
                category=_market_category(market) or None,
                end_date=_market_end_date(market),
                metadata=market,
            )

        candidate_pairs = self.candidate_generator.generate(rows)
        edges: list[DepEdgeRecord] = []
        cache_hits = 0
        classified_count = 0

        for pair in candidate_pairs:
            market_a, market_b = _canonical_pair(pair.a_market, pair.b_market)
            market_a_id = _market_id(market_a)
            market_b_id = _market_id(market_b)
            if not market_a_id or not market_b_id or market_a_id == market_b_id:
                continue

            a_hash = question_hash(_market_question(market_a))
            b_hash = question_hash(_market_question(market_b))
            cached = self.store.get_cached_edge(
                a_market_id=market_a_id,
                b_market_id=market_b_id,
                model_version=self.classifier.model_version,
                a_question_hash=a_hash,
                b_question_hash=b_hash,
            )
            if cached is not None:
                cache_hits += 1
                edges.append(cached)
                continue

            classification = self.classifier.classify(market_a, market_b)
            edge = DepEdgeRecord(
                edge_id=_edge_id(market_a_id, market_b_id, self.classifier.model_version),
                a_market_id=market_a_id,
                b_market_id=market_b_id,
                relation=classification.relation,
                confidence=classification.confidence,
                constraint=_constraint_for_relation(
                    classification.relation,
                    classification.tradeable_constraint,
                ),
                model_version=self.classifier.model_version,
                a_question_hash=a_hash,
                b_question_hash=b_hash,
                reason=classification.reason,
                metadata={
                    "candidate_score": pair.score,
                    "candidate_features": dict(pair.features),
                    "a_question": _market_question(market_a),
                    "b_question": _market_question(market_b),
                    "tradeable": classification.relation in TRADABLE_RELATIONS,
                },
            )
            self.store.upsert_edge(edge)
            classified_count += 1
            edges.append(edge)

        filtered_edges = tuple(edge for edge in edges if edge.confidence >= float(min_confidence))
        accuracy_summary = self.validation.accuracy_summary(min_confidence=min_confidence)
        tradable_edge_count = sum(1 for edge in filtered_edges if edge.relation in TRADABLE_RELATIONS)
        return DependencyGraphBuildResult(
            market_count=len(rows),
            candidate_count=len(candidate_pairs),
            classified_count=classified_count,
            cache_hits=cache_hits,
            tradable_edge_count=tradable_edge_count,
            edges=filtered_edges,
            accuracy_summary=accuracy_summary,
        )

    def export_review_batch(
        self,
        path: str | Path,
        *,
        limit: int = 50,
        min_confidence: float = 0.7,
    ) -> Path:
        return self.validation.export_review_batch(path, limit=limit, min_confidence=min_confidence)

    def import_review_labels(self, path: str | Path) -> int:
        return self.validation.import_review_labels(path)

    def accuracy_summary(self, *, min_confidence: float | None = None) -> dict[str, Any]:
        return self.validation.accuracy_summary(min_confidence=min_confidence)

    def detect(
        self,
        markets: Sequence[Mapping[str, Any]],
        quote_store: BestBidAskStore,
        *,
        min_confidence: float = 0.7,
    ) -> DependencyGraphCycleResult:
        build = self.build_graph(markets, min_confidence=min_confidence)
        token_map = self._token_map(markets)
        monitor = DepViolationMonitor(
            token_map=token_map,
            c1=self.c1,
            nonatomic_penalty=self.nonatomic_penalty,
        )
        planner = DepExecutionPlanner(leg_usd_cap=self.leg_usd_cap)
        accuracy = _classification_accuracy(build.accuracy_summary)

        violations: list[DepViolation] = []
        attempts: list[MultiLegAttempt] = []
        for edge in build.edges:
            if edge.relation not in TRADABLE_RELATIONS:
                continue
            violation = monitor.compute_violation(
                {
                    "edge_id": edge.edge_id,
                    "a_market_id": edge.a_market_id,
                    "b_market_id": edge.b_market_id,
                    "relation": edge.relation,
                    "confidence": edge.confidence,
                },
                quote_store,
            )
            if violation is None:
                continue
            attempt = planner.build_attempt(violation)
            attempt.metadata["classification_accuracy"] = accuracy
            attempt.metadata["relation_reason"] = edge.reason
            violations.append(violation)
            attempts.append(attempt)

        return DependencyGraphCycleResult(
            build=build,
            violations=tuple(violations),
            attempts=tuple(attempts),
            classification_accuracy=accuracy,
        )

    @staticmethod
    def _token_map(markets: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
        token_map: dict[str, dict[str, str]] = {}
        for market in _coerce_markets_payload(list(markets)):
            market_id = _market_id(market)
            yes_token_id, no_token_id = parse_clob_token_ids(market.get("clobTokenIds"))
            if market_id and yes_token_id and no_token_id:
                token_map[market_id] = {
                    "yes_token_id": yes_token_id,
                    "no_token_id": no_token_id,
                }
        return token_map


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="B-1 dependency graph tools")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--log-level", default="INFO")

    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="Build and cache dependency edges from a markets payload")
    build.add_argument("--markets-json", required=True)
    build.add_argument("--top-k", type=int, default=30)
    build.add_argument("--resolution-window-days", type=int, default=90)
    build.add_argument("--min-entity-overlap", type=int, default=1)
    build.add_argument("--min-score", type=float, default=0.12)
    build.add_argument("--min-confidence", type=float, default=0.0)
    build.add_argument("--output-json", default="")

    review_export = sub.add_parser("review-export", help="Export a manual review batch")
    review_export.add_argument("--output-json", required=True)
    review_export.add_argument("--limit", type=int, default=50)
    review_export.add_argument("--min-confidence", type=float, default=0.7)

    review_import = sub.add_parser("review-import", help="Import labeled review results")
    review_import.add_argument("--input-json", required=True)

    accuracy = sub.add_parser("accuracy", help="Print review accuracy summary")
    accuracy.add_argument("--min-confidence", type=float, default=None)

    scan = sub.add_parser("scan", help="Build edges and convert live quote violations into attempts")
    scan.add_argument("--markets-json", required=True)
    scan.add_argument("--quotes-json", required=True)
    scan.add_argument("--top-k", type=int, default=30)
    scan.add_argument("--resolution-window-days", type=int, default=90)
    scan.add_argument("--min-entity-overlap", type=int, default=1)
    scan.add_argument("--min-score", type=float, default=0.12)
    scan.add_argument("--min-confidence", type=float, default=0.7)
    scan.add_argument("--leg-usd-cap", type=float, default=5.0)
    scan.add_argument("--output-json", default="")
    return parser


def _make_service(args: argparse.Namespace) -> DependencyGraphService:
    generator = DepCandidatePairGenerator(
        top_k=args.top_k if hasattr(args, "top_k") else 30,
        resolution_window_days=args.resolution_window_days if hasattr(args, "resolution_window_days") else 90,
        min_entity_overlap=args.min_entity_overlap if hasattr(args, "min_entity_overlap") else 1,
        min_score=args.min_score if hasattr(args, "min_score") else 0.12,
    )
    return DependencyGraphService(
        db_path=args.db_path,
        candidate_generator=generator,
        leg_usd_cap=getattr(args, "leg_usd_cap", 5.0),
    )


def _emit_payload(payload: Mapping[str, Any], output_json: str = "") -> int:
    rendered = json.dumps(dict(payload), indent=2, sort_keys=True)
    if output_json:
        Path(output_json).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))

    if args.cmd == "review-import":
        service = DependencyGraphService(db_path=args.db_path)
        imported = service.import_review_labels(args.input_json)
        return _emit_payload({"imported": imported})

    if args.cmd == "review-export":
        service = DependencyGraphService(db_path=args.db_path)
        path = service.export_review_batch(
            args.output_json,
            limit=args.limit,
            min_confidence=args.min_confidence,
        )
        return _emit_payload({"output_json": str(path), "limit": args.limit})

    if args.cmd == "accuracy":
        service = DependencyGraphService(db_path=args.db_path)
        return _emit_payload(service.accuracy_summary(min_confidence=args.min_confidence))

    if args.cmd == "build":
        service = _make_service(args)
        markets = _coerce_markets_payload(_load_json_payload(args.markets_json))
        result = service.build_graph(markets, min_confidence=args.min_confidence)
        return _emit_payload(result.to_dict(), args.output_json)

    if args.cmd == "scan":
        service = _make_service(args)
        markets = _coerce_markets_payload(_load_json_payload(args.markets_json))
        quotes_payload = _load_json_payload(args.quotes_json)
        if not isinstance(quotes_payload, list):
            raise ValueError("quotes payload must be a list of token-level best bid/ask rows")
        store = _quote_store_from_rows(quotes_payload)
        result = service.detect(markets, store, min_confidence=args.min_confidence)
        return _emit_payload(result.to_dict(), args.output_json)

    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
