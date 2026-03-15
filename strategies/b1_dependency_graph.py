"""B-1 dependency graph storage, prompting, and candidate generation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from bot.resolution_normalizer import normalize_market
from strategies.a6_sum_violation import parse_clob_token_ids


ALLOWED_LABELS = {
    "A_implies_B",
    "B_implies_A",
    "mutually_exclusive",
    "subset",
    "complementary",
    "independent",
}


def _tokenize(text: str) -> list[str]:
    return [token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token]


def _cosine_counter(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[token] * right.get(token, 0) for token in left)
    left_norm = sum(value * value for value in left.values()) ** 0.5
    right_norm = sum(value * value for value in right.values()) ** 0.5
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _within_days(left_iso: str | None, right_iso: str | None, *, max_days: int) -> bool:
    if not left_iso or not right_iso:
        return True
    try:
        left = datetime.fromisoformat(left_iso.replace("Z", "+00:00"))
        right = datetime.fromisoformat(right_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    return abs((left - right).total_seconds()) <= max_days * 86400


@dataclass(frozen=True)
class MarketMeta:
    market_id: str
    event_id: str
    question: str
    description: str
    category: str
    subcategory: str
    end_date_iso: str | None
    yes_token_id: str | None
    no_token_id: str | None
    neg_risk: bool
    text_hash: str

    @property
    def semantic_text(self) -> str:
        return "\n".join(part for part in (self.question, self.description, self.category, self.subcategory) if part)


@dataclass(frozen=True)
class PairEdge:
    a_id: str
    b_id: str
    label: str
    confidence: float
    proof: str
    risk_flags: tuple[str, ...]
    prompt_hash: str
    model_version: str
    created_at_ts: int


def hash_market_text(*, question: str, description: str, end_date_iso: str | None) -> str:
    payload = "|".join([question.strip(), description.strip(), str(end_date_iso or "")])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_classifier_prompt(a: MarketMeta, b: MarketMeta) -> str:
    return (
        "System: You are a market-semantics classifier for prediction markets. "
        "Output must be a single JSON object. No markdown.\n\n"
        "User:\n"
        "You will be given two Polymarket markets A and B. Each market resolves YES if its event occurs "
        "under its resolution criteria, otherwise NO.\n"
        "Determine the strongest logical relationship that is ALWAYS true, assuming the resolution criteria "
        "are followed precisely.\n\n"
        "Allowed labels (choose exactly one):\n\n"
        "\"A_implies_B\" (if A resolves YES, B must resolve YES)\n"
        "\"B_implies_A\"\n"
        "\"mutually_exclusive\" (A and B cannot both resolve YES)\n"
        "\"subset\" (A’s YES set is a strict subset of B’s YES set; use when implication is strict but not equivalence)\n"
        "\"complementary\" (exactly one of A or B resolves YES; A and B partition the space)\n"
        "\"independent\" (none of the above always holds)\n"
        "Return JSON with keys:\n\n"
        "\"label\": one of the allowed labels\n"
        "\"confidence\": number 0.0–1.0 (calibrated; 0.8+ only when logically forced by definitions)\n"
        "\"proof\": <=40 words, cite the exact phrase(s) in the market texts that force the relationship; if none, say \"insufficient to prove\".\n"
        "\"risk_flags\": array of strings from {\"ambiguous_terms\",\"time_mismatch\",\"different_resolution_sources\",\"requires_external_knowledge\",\"multi_stage_event\"}\n"
        "Market A:\n\n"
        f"question: {a.question}\n"
        f"description: {a.description}\n"
        f"end: {a.end_date_iso}\n"
        f"category/subcategory: {a.category}/{a.subcategory}\n"
        "Market B:\n\n"
        f"question: {b.question}\n"
        f"description: {b.description}\n"
        f"end: {b.end_date_iso}\n"
        f"category/subcategory: {b.category}/{b.subcategory}\n"
    )


class GraphStore:
    def __init__(self, db_path: str | Path = Path("state") / "arb_graph.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS market (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    question_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pair_edge (
                    a_id TEXT NOT NULL,
                    b_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    proof TEXT NOT NULL,
                    risk_flags_json TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    created_at_ts INTEGER NOT NULL,
                    PRIMARY KEY (a_id, b_id)
                );

                CREATE INDEX IF NOT EXISTS idx_pair_edge_label ON pair_edge(label, confidence);
                """
            )

    def upsert_market(self, market: MarketMeta, *, updated_at_ts: int | None = None) -> None:
        ts = int(updated_at_ts or datetime.now(tz=timezone.utc).timestamp())
        metadata = {
            "market_id": market.market_id,
            "event_id": market.event_id,
            "question": market.question,
            "description": market.description,
            "category": market.category,
            "subcategory": market.subcategory,
            "end_date_iso": market.end_date_iso,
            "yes_token_id": market.yes_token_id,
            "no_token_id": market.no_token_id,
            "neg_risk": market.neg_risk,
            "text_hash": market.text_hash,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market (id, event_id, question_hash, metadata_json, updated_at_ts)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    event_id=excluded.event_id,
                    question_hash=excluded.question_hash,
                    metadata_json=excluded.metadata_json,
                    updated_at_ts=excluded.updated_at_ts
                """,
                (
                    market.market_id,
                    market.event_id,
                    market.text_hash,
                    json.dumps(metadata, sort_keys=True),
                    ts,
                ),
            )
            conn.commit()

    def upsert_edge(self, edge: PairEdge) -> None:
        if edge.label not in ALLOWED_LABELS:
            raise ValueError(f"unsupported label: {edge.label}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pair_edge (
                    a_id, b_id, label, confidence, proof, risk_flags_json,
                    prompt_hash, model_version, created_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(a_id, b_id) DO UPDATE SET
                    label=excluded.label,
                    confidence=excluded.confidence,
                    proof=excluded.proof,
                    risk_flags_json=excluded.risk_flags_json,
                    prompt_hash=excluded.prompt_hash,
                    model_version=excluded.model_version,
                    created_at_ts=excluded.created_at_ts
                """,
                (
                    edge.a_id,
                    edge.b_id,
                    edge.label,
                    float(edge.confidence),
                    edge.proof,
                    json.dumps(list(edge.risk_flags)),
                    edge.prompt_hash,
                    edge.model_version,
                    int(edge.created_at_ts),
                ),
            )
            conn.commit()

    def edge_is_fresh(self, a_id: str, b_id: str, *, prompt_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT prompt_hash FROM pair_edge WHERE a_id = ? AND b_id = ?",
                (a_id, b_id),
            ).fetchone()
        return bool(row and str(row[0]) == prompt_hash)

    def load_edges(self, *, min_confidence: float = 0.0, labels: Iterable[str] | None = None) -> list[PairEdge]:
        query = (
            "SELECT a_id, b_id, label, confidence, proof, risk_flags_json, prompt_hash, model_version, created_at_ts "
            "FROM pair_edge WHERE confidence >= ?"
        )
        params: list[Any] = [float(min_confidence)]
        labels_list = [label for label in (labels or []) if label]
        if labels_list:
            placeholders = ",".join("?" for _ in labels_list)
            query += f" AND label IN ({placeholders})"
            params.extend(labels_list)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        out: list[PairEdge] = []
        for row in rows:
            out.append(
                PairEdge(
                    a_id=str(row[0]),
                    b_id=str(row[1]),
                    label=str(row[2]),
                    confidence=float(row[3]),
                    proof=str(row[4]),
                    risk_flags=tuple(json.loads(row[5]) if row[5] else []),
                    prompt_hash=str(row[6]),
                    model_version=str(row[7]),
                    created_at_ts=int(row[8]),
                )
            )
        return out

    def get_market(self, market_id: str) -> MarketMeta | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM market WHERE id = ?",
                (market_id,),
            ).fetchone()
        if not row:
            return None
        raw = json.loads(row[0])
        return MarketMeta(
            market_id=str(raw.get("market_id")),
            event_id=str(raw.get("event_id")),
            question=str(raw.get("question") or ""),
            description=str(raw.get("description") or ""),
            category=str(raw.get("category") or ""),
            subcategory=str(raw.get("subcategory") or ""),
            end_date_iso=str(raw.get("end_date_iso") or "") or None,
            yes_token_id=str(raw.get("yes_token_id") or "") or None,
            no_token_id=str(raw.get("no_token_id") or "") or None,
            neg_risk=bool(raw.get("neg_risk")),
            text_hash=str(raw.get("text_hash") or ""),
        )


class DependencyGraphBuilder:
    """Category/time-pruned graph builder with cache-aware pair classification."""

    def __init__(self, graph_store: GraphStore | None = None) -> None:
        self.graph_store = graph_store or GraphStore()

    def refresh_markets(self, raw_markets: Iterable[Mapping[str, Any]]) -> list[MarketMeta]:
        out: list[MarketMeta] = []
        for raw_market in raw_markets:
            norm = normalize_market(raw_market)
            yes_token_id, no_token_id = parse_clob_token_ids(raw_market.get("clobTokenIds"))
            meta = MarketMeta(
                market_id=norm.market_id,
                event_id=norm.event_id,
                question=norm.question,
                description=str(raw_market.get("description") or raw_market.get("rules") or ""),
                category=str(raw_market.get("category") or raw_market.get("eventCategory") or ""),
                subcategory=str(raw_market.get("subcategory") or raw_market.get("eventSubcategory") or ""),
                end_date_iso=str(raw_market.get("endDate") or raw_market.get("end_date") or "") or None,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                neg_risk=bool(norm.profile.is_neg_risk),
                text_hash=hash_market_text(
                    question=norm.question,
                    description=str(raw_market.get("description") or raw_market.get("rules") or ""),
                    end_date_iso=str(raw_market.get("endDate") or raw_market.get("end_date") or "") or None,
                ),
            )
            self.graph_store.upsert_market(meta)
            out.append(meta)
        return out

    def build_candidate_pairs(self, markets: list[MarketMeta], *, top_k: int = 20, max_day_gap: int = 180) -> list[tuple[MarketMeta, MarketMeta]]:
        by_bucket: dict[tuple[str, str], list[MarketMeta]] = {}
        for market in markets:
            key = (market.category.lower(), market.subcategory.lower())
            by_bucket.setdefault(key, []).append(market)

        pairs: list[tuple[MarketMeta, MarketMeta]] = []
        seen: set[tuple[str, str]] = set()
        for bucket_markets in by_bucket.values():
            tokenized = {market.market_id: Counter(_tokenize(market.semantic_text)) for market in bucket_markets}
            for market in bucket_markets:
                scored: list[tuple[float, MarketMeta]] = []
                for other in bucket_markets:
                    if other.market_id == market.market_id:
                        continue
                    if not _within_days(market.end_date_iso, other.end_date_iso, max_days=max_day_gap):
                        continue
                    score = _cosine_counter(tokenized[market.market_id], tokenized[other.market_id])
                    if score <= 0.0:
                        continue
                    scored.append((score, other))
                scored.sort(key=lambda row: row[0], reverse=True)
                for _, other in scored[: max(1, int(top_k))]:
                    key = tuple(sorted((market.market_id, other.market_id)))
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append((market, other))
        return pairs

    def should_classify_pair(self, a: MarketMeta, b: MarketMeta) -> tuple[bool, str]:
        prompt_hash = hashlib.sha1(build_classifier_prompt(a, b).encode("utf-8")).hexdigest()
        return (not self.graph_store.edge_is_fresh(a.market_id, b.market_id, prompt_hash=prompt_hash), prompt_hash)
