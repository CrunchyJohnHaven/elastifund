#!/usr/bin/env python3
"""Claude Haiku relation classifier with caching and validation tooling."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

try:
    from bot.cross_platform_arb import extract_keywords, normalize_title, title_similarity
except ImportError:  # pragma: no cover - direct script mode
    from cross_platform_arb import extract_keywords, normalize_title, title_similarity  # type: ignore

try:
    from bot.relation_cache import CachedRelation, RelationCache, RelationCacheStats
except ImportError:  # pragma: no cover - direct script mode
    from relation_cache import CachedRelation, RelationCache, RelationCacheStats  # type: ignore

try:
    from bot.resolution_normalizer import NormalizedMarket, normalize_market, normalize_outcome_name
except ImportError:  # pragma: no cover - direct script mode
    from resolution_normalizer import NormalizedMarket, normalize_market, normalize_outcome_name  # type: ignore


logger = logging.getLogger("JJ.relation_classifier")


LLM_RELATION_LABELS = (
    "A_implies_B",
    "B_implies_A",
    "mutually_exclusive",
    "complementary",
    "subset",
    "independent",
    "ambiguous",
)
INTERNAL_RELATION_LABELS = set(LLM_RELATION_LABELS) | {"same_event_sum"}
DEFAULT_PROMPT_VERSION = "relation-haiku-v1"
DEFAULT_DEBATE_PROMPT_VERSION = "relation-haiku-debate-v1"
DEFAULT_MODEL = os.environ.get("RELATION_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
DEFAULT_INPUT_COST_PER_MTOK = float(os.environ.get("RELATION_HAIKU_INPUT_COST_PER_MTOK_USD", "0"))
DEFAULT_OUTPUT_COST_PER_MTOK = float(os.environ.get("RELATION_HAIKU_OUTPUT_COST_PER_MTOK_USD", "0"))

_LABEL_ALIASES = {
    "a_implies_b": "A_implies_B",
    "a_implies_but_not_equivalent": "A_implies_B",
    "b_implies_a": "B_implies_A",
    "mutually_exclusive": "mutually_exclusive",
    "mutual_exclusion": "mutually_exclusive",
    "exclusive": "mutually_exclusive",
    "complementary": "complementary",
    "complement": "complementary",
    "subset": "subset",
    "independent": "independent",
    "none": "independent",
    "ambiguous": "ambiguous",
    "ambiguous_do_not_trade": "ambiguous",
    "same_event_sum": "same_event_sum",
}
_DIRECTIONAL_INVERSION = {
    "A_implies_B": "B_implies_A",
    "B_implies_A": "A_implies_B",
}
_THRESHOLD_RE = re.compile(
    r"(?P<dir>>=|<=|>|<|above|over|below|under|at least|at most)\s*\$?(?P<val>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

BASE_PROMPT = """You classify logical relationships between prediction market contracts.

Return exactly one JSON object with these keys:
- "label"
- "confidence"
- "ambiguous"
- "short_rationale"
- "needs_human_review"

Allowed labels:
- "A_implies_B"
- "B_implies_A"
- "mutually_exclusive"
- "complementary"
- "subset"
- "independent"
- "ambiguous"

Decision rules:
- Use "A_implies_B" only if A resolving YES necessarily forces B resolving YES under the stated source, scope, cutoff, and outcome mapping.
- Use "B_implies_A" symmetrically.
- Use "mutually_exclusive" only if both cannot resolve YES together.
- Use "complementary" only if the pair should partition the same outcome space and sum near 1 under identical scope.
- Use "subset" only if one market is a narrower framing of the other but implication direction is not safe enough for trading.
- Use "independent" when there is no direct logical constraint worth monitoring.
- Use "ambiguous" when the markets look related but source, scope, cutoff, geography, or ontology leave the relation unsafe.

Be skeptical. Similar wording is not enough.

Market A
- question: {question_a}
- category: {category_a}
- resolution_source: {source_a}
- cutoff_utc: {cutoff_a}
- outcomes: {outcomes_a}
- primary_outcome: {outcome_a}

Market B
- question: {question_b}
- category: {category_b}
- resolution_source: {source_b}
- cutoff_utc: {cutoff_b}
- outcomes: {outcomes_b}
- primary_outcome: {outcome_b}

Output JSON only.
"""

DEBATE_PROMPT = """You are resolving a low-confidence prediction-market relation classification.

Return exactly one JSON object with these keys:
- "label"
- "confidence"
- "ambiguous"
- "short_rationale"
- "needs_human_review"

Allowed labels:
- "A_implies_B"
- "B_implies_A"
- "mutually_exclusive"
- "complementary"
- "subset"
- "independent"
- "ambiguous"

Process internally:
1. Build the strongest case that the pair has a tradable dependency.
2. Build the strongest case that the pair is independent or too ambiguous.
3. Choose the safer label for live monitoring.

Hard rule: if scope, source, cutoff, or ontology are not clearly aligned, do not force a directional implication.

Market A
- question: {question_a}
- category: {category_a}
- resolution_source: {source_a}
- cutoff_utc: {cutoff_a}
- outcomes: {outcomes_a}
- primary_outcome: {outcome_a}

Market B
- question: {question_b}
- category: {category_b}
- resolution_source: {source_b}
- cutoff_utc: {cutoff_b}
- outcomes: {outcomes_b}
- primary_outcome: {outcome_b}

Base result:
{base_result_json}

Output JSON only.
"""


def _now_ts() -> int:
    return int(time.time())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _compact_text(value: str, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _normalize_relation_label(raw: Any, *, allow_internal: bool = True) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    label = _LABEL_ALIASES.get(normalized)
    if label in LLM_RELATION_LABELS:
        return label
    if allow_internal and label == "same_event_sum":
        return label
    return None


def _cutoff_iso(market: NormalizedMarket) -> str:
    cutoff_ts = market.profile.cutoff_ts
    if cutoff_ts is None:
        return "unknown"
    return datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class RelationResult:
    relation_type: str
    confidence: float
    reason: str
    ambiguous: bool = False
    needs_human_review: bool = False
    short_rationale: str = ""
    source: str = "heuristic"
    prompt_version: str = ""
    cache_hit: bool = False
    model_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    def to_contract(self) -> dict[str, Any]:
        return {
            "label": self.relation_type,
            "confidence": float(max(0.0, min(1.0, self.confidence))),
            "ambiguous": bool(self.ambiguous),
            "short_rationale": _compact_text(self.short_rationale),
            "needs_human_review": bool(self.needs_human_review),
        }


@dataclass(frozen=True)
class RelationPrefilterDecision:
    should_call_model: bool
    reason: str
    similarity: float
    token_overlap: int
    shared_keywords: tuple[str, ...]
    obviously_independent: bool = False


@dataclass(frozen=True)
class ModelCompletion:
    text: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0


class RelationModelAdapter(Protocol):
    def available(self) -> bool:
        ...

    def complete(self, prompt: str, *, prompt_version: str) -> ModelCompletion:
        ...


@dataclass(frozen=True)
class _CanonicalPair:
    market_a: NormalizedMarket
    market_b: NormalizedMarket
    pair_key: str
    flipped: bool

    @classmethod
    def build(cls, market_a: NormalizedMarket, market_b: NormalizedMarket) -> _CanonicalPair:
        sig_a = _market_signature(market_a)
        sig_b = _market_signature(market_b)
        if (sig_a, market_a.market_id) <= (sig_b, market_b.market_id):
            left, right, flipped = market_a, market_b, False
            left_sig, right_sig = sig_a, sig_b
        else:
            left, right, flipped = market_b, market_a, True
            left_sig, right_sig = sig_b, sig_a
        pair_key = f"{left_sig}:{right_sig}"
        return cls(market_a=left, market_b=right, pair_key=pair_key, flipped=flipped)

    def orient(self, result: RelationResult) -> RelationResult:
        if not self.flipped:
            return result
        flipped_label = _DIRECTIONAL_INVERSION.get(result.relation_type, result.relation_type)
        return RelationResult(
            relation_type=flipped_label,
            confidence=result.confidence,
            reason=result.reason,
            ambiguous=result.ambiguous,
            needs_human_review=result.needs_human_review,
            short_rationale=result.short_rationale,
            source=result.source,
            prompt_version=result.prompt_version,
            cache_hit=result.cache_hit,
            model_name=result.model_name,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
        )


@dataclass(frozen=True)
class GoldRelationExample:
    example_id: str
    expected_label: str
    market_a: NormalizedMarket
    market_b: NormalizedMarket
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationValidationReport:
    total_examples: int
    correct_examples: int
    accuracy: float
    confusion_matrix: dict[str, dict[str, int]]
    failure_examples: list[dict[str, Any]]
    cache_stats: RelationCacheStats

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_examples": self.total_examples,
            "correct_examples": self.correct_examples,
            "accuracy": self.accuracy,
            "confusion_matrix": self.confusion_matrix,
            "failure_examples": self.failure_examples,
            "cache_stats": {
                "entries": self.cache_stats.entries,
                "cache_hits": self.cache_stats.cache_hits,
                "cache_misses": self.cache_stats.cache_misses,
                "total_events": self.cache_stats.total_events,
                "hit_rate": self.cache_stats.hit_rate,
                "input_tokens": self.cache_stats.input_tokens,
                "output_tokens": self.cache_stats.output_tokens,
                "estimated_cost_usd": self.cache_stats.estimated_cost_usd,
            },
        }

    def to_markdown(self) -> str:
        lines = [
            "# Relation Classifier Validation",
            "",
            f"- Accuracy: {self.accuracy:.1%} ({self.correct_examples}/{self.total_examples})",
            f"- Cache hit rate: {self.cache_stats.hit_rate:.1%} ({self.cache_stats.cache_hits}/{self.cache_stats.total_events or 1})",
            f"- Estimated model cost: ${self.cache_stats.estimated_cost_usd:.4f}",
            "",
            "## Confusion Matrix",
            "",
            "| expected | predicted | count |",
            "| --- | --- | ---: |",
        ]
        for expected in LLM_RELATION_LABELS:
            row = self.confusion_matrix.get(expected, {})
            for predicted in LLM_RELATION_LABELS:
                count = row.get(predicted, 0)
                if count:
                    lines.append(f"| {expected} | {predicted} | {count} |")
        lines.extend(["", "## Failure Examples", ""])
        if not self.failure_examples:
            lines.append("- None")
            return "\n".join(lines)

        for failure in self.failure_examples:
            lines.append(
                f"- `{failure['example_id']}` expected `{failure['expected_label']}` got "
                f"`{failure['predicted_label']}` ({failure['confidence']:.2f})"
            )
            lines.append(f"  rationale: {failure['short_rationale']}")
        return "\n".join(lines)


def _market_signature(market: NormalizedMarket) -> str:
    payload = {
        "question": normalize_title(market.question),
        "category": market.category,
        "outcomes": [normalize_outcome_name(outcome) for outcome in market.outcomes],
        "outcome": normalize_outcome_name(market.outcome or ""),
        "resolution_key": market.resolution_key,
        "source": market.profile.source,
        "cutoff_ts": market.profile.cutoff_ts,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class ClaudeHaikuAdapter:
    """Thin synchronous Anthropic wrapper with token and cost accounting."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 180,
        input_cost_per_mtok: float = DEFAULT_INPUT_COST_PER_MTOK,
        output_cost_per_mtok: float = DEFAULT_OUTPUT_COST_PER_MTOK,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.input_cost_per_mtok = input_cost_per_mtok
        self.output_cost_per_mtok = output_cost_per_mtok
        self._client = None
        self._init_error = ""

    def available(self) -> bool:
        if self._client is not None:
            return True
        if not self.api_key:
            return False
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on runtime environment
            self._init_error = str(exc)
            return False
        try:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            self._init_error = str(exc)
            return False
        return True

    def complete(self, prompt: str, *, prompt_version: str) -> ModelCompletion:
        if not self.available():
            raise RuntimeError(f"Anthropic client unavailable: {self._init_error or 'missing_api_key_or_sdk'}")

        assert self._client is not None
        start = time.perf_counter()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        parts: list[str] = []
        for block in getattr(response, "content", []):
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        raw_text = "\n".join(parts).strip()

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        estimated_cost_usd = (
            (input_tokens / 1_000_000.0) * self.input_cost_per_mtok
            + (output_tokens / 1_000_000.0) * self.output_cost_per_mtok
        )

        return ModelCompletion(
            text=raw_text,
            model_name=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
        )


class RelationClassifier:
    """Heuristics first, Claude Haiku second, debate only for low-confidence pairs."""

    def __init__(
        self,
        *,
        cache: RelationCache | None = None,
        cache_path: str | Path = Path("data") / "relation_cache.db",
        model_adapter: RelationModelAdapter | None = None,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        debate_prompt_version: str = DEFAULT_DEBATE_PROMPT_VERSION,
        low_confidence_threshold: float = 0.72,
        ambiguous_similarity: float = 0.65,
        prefilter_min_similarity: float = 0.42,
        prefilter_min_token_overlap: int = 1,
        resolution_window_hours: float = 72.0,
        enable_debate_fallback: bool = False,
        debate_fallback: Callable[[NormalizedMarket, NormalizedMarket], RelationResult | None] | None = None,
        max_debate_calls: int = 25,
    ) -> None:
        self.cache = cache or RelationCache(cache_path)
        self.model_adapter = model_adapter or ClaudeHaikuAdapter()
        self.prompt_version = prompt_version
        self.debate_prompt_version = debate_prompt_version
        self.low_confidence_threshold = low_confidence_threshold
        self.ambiguous_similarity = ambiguous_similarity
        self.prefilter_min_similarity = prefilter_min_similarity
        self.prefilter_min_token_overlap = max(0, int(prefilter_min_token_overlap))
        self.resolution_window_hours = max(1.0, float(resolution_window_hours))
        self.enable_debate_fallback = bool(enable_debate_fallback or debate_fallback is not None)
        self.debate_fallback = debate_fallback
        self.max_debate_calls = max(0, int(max_debate_calls))
        self._debate_calls = 0

    def reset_debate_budget(self) -> None:
        self._debate_calls = 0

    def metrics_snapshot(self) -> dict[str, Any]:
        stats = self.cache.stats()
        return {
            "prompt_version": self.prompt_version,
            "debate_prompt_version": self.debate_prompt_version,
            "cache_entries": stats.entries,
            "cache_hits": stats.cache_hits,
            "cache_misses": stats.cache_misses,
            "cache_hit_rate": stats.hit_rate,
            "estimated_cost_usd": stats.estimated_cost_usd,
            "debate_calls_used": self._debate_calls,
            "debate_calls_remaining": max(0, self.max_debate_calls - self._debate_calls),
        }

    def classify(self, market_a: NormalizedMarket, market_b: NormalizedMarket) -> RelationResult:
        heuristic = self._heuristic_relation(market_a, market_b)
        if heuristic is not None:
            return heuristic

        prefilter = self.prefilter(market_a, market_b)
        if not prefilter.should_call_model:
            return RelationResult(
                relation_type="independent",
                confidence=0.92 if prefilter.obviously_independent else 0.8,
                reason=prefilter.reason,
                ambiguous=False,
                needs_human_review=False,
                short_rationale="Heuristic prefilter found no dependency worth an LLM call.",
                source="prefilter",
            )

        canonical = _CanonicalPair.build(market_a, market_b)
        base_result = self._classify_with_prompt(
            canonical=canonical,
            prompt_version=self.prompt_version,
            prompt_template=BASE_PROMPT,
        )
        oriented_base = canonical.orient(base_result)

        if not self._should_run_debate(oriented_base, prefilter):
            return oriented_base

        debate_result = self._classify_with_debate(canonical, base_result)
        if debate_result is None:
            return oriented_base
        if debate_result.confidence >= oriented_base.confidence or oriented_base.ambiguous:
            return debate_result
        return oriented_base

    def prefilter(self, market_a: NormalizedMarket, market_b: NormalizedMarket) -> RelationPrefilterDecision:
        shared_keywords = tuple(sorted(extract_keywords(market_a.question) & extract_keywords(market_b.question)))
        similarity = title_similarity(normalize_title(market_a.question), normalize_title(market_b.question))
        token_overlap = len(shared_keywords)
        same_category = market_a.category == market_b.category
        same_source = market_a.profile.source == market_b.profile.source and market_a.profile.source != "unknown"
        window_aligned = self._within_resolution_window(market_a, market_b)

        if similarity < 0.25 and token_overlap == 0:
            return RelationPrefilterDecision(
                should_call_model=False,
                reason="prefilter_low_similarity",
                similarity=similarity,
                token_overlap=token_overlap,
                shared_keywords=shared_keywords,
                obviously_independent=True,
            )

        if not window_aligned and similarity < 0.78:
            return RelationPrefilterDecision(
                should_call_model=False,
                reason="prefilter_resolution_window_miss",
                similarity=similarity,
                token_overlap=token_overlap,
                shared_keywords=shared_keywords,
                obviously_independent=True,
            )

        if same_category and window_aligned and (
            similarity >= self.prefilter_min_similarity or token_overlap >= self.prefilter_min_token_overlap
        ):
            return RelationPrefilterDecision(
                should_call_model=True,
                reason="prefilter_same_category",
                similarity=similarity,
                token_overlap=token_overlap,
                shared_keywords=shared_keywords,
            )

        if same_source and window_aligned and token_overlap >= self.prefilter_min_token_overlap:
            return RelationPrefilterDecision(
                should_call_model=True,
                reason="prefilter_same_source",
                similarity=similarity,
                token_overlap=token_overlap,
                shared_keywords=shared_keywords,
            )

        if similarity >= self.ambiguous_similarity:
            return RelationPrefilterDecision(
                should_call_model=True,
                reason="prefilter_high_similarity",
                similarity=similarity,
                token_overlap=token_overlap,
                shared_keywords=shared_keywords,
            )

        return RelationPrefilterDecision(
            should_call_model=False,
            reason="prefilter_no_anchor",
            similarity=similarity,
            token_overlap=token_overlap,
            shared_keywords=shared_keywords,
            obviously_independent=True,
        )

    def _classify_with_prompt(
        self,
        *,
        canonical: _CanonicalPair,
        prompt_version: str,
        prompt_template: str,
        base_result: RelationResult | None = None,
    ) -> RelationResult:
        cached = self.cache.get(canonical.pair_key, prompt_version)
        if cached is not None:
            self.cache.record_event(
                pair_key=canonical.pair_key,
                prompt_version=prompt_version,
                model=cached.source,
                cache_hit=True,
            )
            return self._result_from_cached(cached, cache_hit=True)

        prompt = self._render_prompt(canonical.market_a, canonical.market_b, prompt_template, base_result=base_result)
        if self.model_adapter.available():
            completion = self.model_adapter.complete(prompt, prompt_version=prompt_version)
            self.cache.record_event(
                pair_key=canonical.pair_key,
                prompt_version=prompt_version,
                model=completion.model_name,
                cache_hit=False,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                estimated_cost_usd=completion.estimated_cost_usd,
                latency_ms=completion.latency_ms,
            )
            parsed = self._parse_model_output(completion.text)
            if parsed is not None:
                self.cache.put(
                    pair_key=canonical.pair_key,
                    prompt_version=prompt_version,
                    response=parsed,
                    source=completion.model_name,
                    metadata={"latency_ms": completion.latency_ms},
                )
                return self._result_from_contract(
                    parsed,
                    reason="haiku_model",
                    source="haiku",
                    prompt_version=prompt_version,
                    cache_hit=False,
                    model_name=completion.model_name,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    estimated_cost_usd=completion.estimated_cost_usd,
                )
            logger.warning("Relation classifier parse failure for %s", canonical.pair_key)

        if self.debate_fallback is not None:
            fallback = self.debate_fallback(canonical.market_a, canonical.market_b)
            if fallback is not None:
                return self._normalize_result(fallback, reason="debate_fallback", source="debate")

        return RelationResult(
            relation_type="ambiguous",
            confidence=0.25,
            reason="model_unavailable",
            ambiguous=True,
            needs_human_review=True,
            short_rationale="No reliable model output was available for this pair.",
            source="fallback",
            prompt_version=prompt_version,
        )

    def _classify_with_debate(
        self,
        canonical: _CanonicalPair,
        base_result: RelationResult,
    ) -> RelationResult | None:
        cached = self.cache.get(canonical.pair_key, self.debate_prompt_version)
        if cached is not None:
            self.cache.record_event(
                pair_key=canonical.pair_key,
                prompt_version=self.debate_prompt_version,
                model=cached.source,
                cache_hit=True,
            )
            return canonical.orient(self._result_from_cached(cached, cache_hit=True))

        if self.debate_fallback is not None and not self.model_adapter.available():
            debated = self.debate_fallback(canonical.market_a, canonical.market_b)
            if debated is None:
                return None
            return canonical.orient(self._normalize_result(debated, reason="debate_fallback", source="debate"))

        if not self.enable_debate_fallback or not self.model_adapter.available():
            return None
        if self.max_debate_calls and self._debate_calls >= self.max_debate_calls:
            return None

        self._debate_calls += 1
        result = self._classify_with_prompt(
            canonical=canonical,
            prompt_version=self.debate_prompt_version,
            prompt_template=DEBATE_PROMPT,
            base_result=base_result,
        )
        return canonical.orient(result)

    def _render_prompt(
        self,
        market_a: NormalizedMarket,
        market_b: NormalizedMarket,
        prompt_template: str,
        *,
        base_result: RelationResult | None = None,
    ) -> str:
        base_result_json = ""
        if base_result is not None:
            base_result_json = json.dumps(base_result.to_contract(), sort_keys=True)

        return prompt_template.format(
            question_a=market_a.question,
            category_a=market_a.category,
            source_a=market_a.profile.source,
            cutoff_a=_cutoff_iso(market_a),
            outcomes_a=", ".join(market_a.outcomes) or "unknown",
            outcome_a=market_a.outcome or "unknown",
            question_b=market_b.question,
            category_b=market_b.category,
            source_b=market_b.profile.source,
            cutoff_b=_cutoff_iso(market_b),
            outcomes_b=", ".join(market_b.outcomes) or "unknown",
            outcome_b=market_b.outcome or "unknown",
            base_result_json=base_result_json,
        )

    def _parse_model_output(self, raw: str | Mapping[str, Any]) -> dict[str, Any] | None:
        data: Mapping[str, Any] | None = None
        if isinstance(raw, Mapping):
            data = raw
        else:
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, Mapping):
                data = parsed
        if data is None:
            return None

        label = _normalize_relation_label(data.get("label"), allow_internal=False)
        if label is None:
            return None

        confidence = max(0.0, min(1.0, _safe_float(data.get("confidence"), 0.0)))
        ambiguous = _safe_bool(data.get("ambiguous"), default=(label == "ambiguous"))
        needs_human_review = _safe_bool(data.get("needs_human_review"), default=ambiguous or confidence < 0.55)
        short_rationale = _compact_text(str(data.get("short_rationale") or ""))

        return {
            "label": label,
            "confidence": confidence,
            "ambiguous": ambiguous,
            "short_rationale": short_rationale,
            "needs_human_review": needs_human_review,
        }

    def _result_from_cached(self, cached: CachedRelation, *, cache_hit: bool) -> RelationResult:
        return self._result_from_contract(
            cached.response,
            reason="cache_hit",
            source=cached.source,
            prompt_version=cached.prompt_version,
            cache_hit=cache_hit,
        )

    def _result_from_contract(
        self,
        contract: Mapping[str, Any],
        *,
        reason: str,
        source: str,
        prompt_version: str,
        cache_hit: bool,
        model_name: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> RelationResult:
        label = _normalize_relation_label(contract.get("label"), allow_internal=False) or "ambiguous"
        confidence = max(0.0, min(1.0, _safe_float(contract.get("confidence"), 0.0)))
        ambiguous = _safe_bool(contract.get("ambiguous"), default=(label == "ambiguous"))
        return RelationResult(
            relation_type=label,
            confidence=confidence,
            reason=reason,
            ambiguous=ambiguous,
            needs_human_review=_safe_bool(contract.get("needs_human_review"), default=ambiguous),
            short_rationale=_compact_text(str(contract.get("short_rationale") or "")),
            source=source,
            prompt_version=prompt_version,
            cache_hit=cache_hit,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

    def _normalize_result(self, result: RelationResult, *, reason: str, source: str) -> RelationResult:
        label = _normalize_relation_label(result.relation_type, allow_internal=True) or "ambiguous"
        return RelationResult(
            relation_type=label,
            confidence=max(0.0, min(1.0, result.confidence)),
            reason=reason,
            ambiguous=result.ambiguous or label == "ambiguous",
            needs_human_review=result.needs_human_review or label == "ambiguous",
            short_rationale=_compact_text(result.short_rationale),
            source=source,
            prompt_version=result.prompt_version,
            cache_hit=result.cache_hit,
            model_name=result.model_name,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
        )

    def _should_run_debate(self, result: RelationResult, prefilter: RelationPrefilterDecision) -> bool:
        if not self.enable_debate_fallback:
            return False
        if prefilter.obviously_independent:
            return False
        if result.relation_type == "independent" and result.confidence >= 0.9:
            return False
        return result.ambiguous or result.confidence < self.low_confidence_threshold

    def _heuristic_relation(self, market_a: NormalizedMarket, market_b: NormalizedMarket) -> RelationResult | None:
        if market_a.event_id == market_b.event_id:
            return RelationResult(
                relation_type="same_event_sum",
                confidence=0.97,
                reason="same_event",
                short_rationale="Markets share the same event grouping and belong in the sum scanner, not B-1.",
                source="heuristic",
            )

        threshold_rel = self._threshold_implication(market_a.question, market_b.question)
        if threshold_rel is not None:
            relation_type, reason = threshold_rel
            return RelationResult(
                relation_type=relation_type,
                confidence=0.88,
                reason=reason,
                short_rationale="Threshold ordering creates a deterministic implication.",
                source="heuristic",
            )

        lexical_rel = self._lexical_implication(market_a.question, market_b.question)
        if lexical_rel is not None:
            relation_type, confidence = lexical_rel
            return RelationResult(
                relation_type=relation_type,
                confidence=confidence,
                reason="lexical_implication",
                short_rationale="One market adds predicates to the other while preserving the same event anchor.",
                source="heuristic",
            )

        if self._mutual_exclusion(market_a.question, market_b.question):
            return RelationResult(
                relation_type="mutually_exclusive",
                confidence=0.8,
                reason="negation_or_binary_opposites",
                short_rationale="The question pair encodes opposing states that cannot both resolve YES.",
                source="heuristic",
            )
        return None

    def _within_resolution_window(self, market_a: NormalizedMarket, market_b: NormalizedMarket) -> bool:
        cutoff_a = market_a.profile.cutoff_ts
        cutoff_b = market_b.profile.cutoff_ts
        if cutoff_a is None or cutoff_b is None:
            return True
        delta_hours = abs(cutoff_a - cutoff_b) / 3600.0
        return delta_hours <= self.resolution_window_hours

    @staticmethod
    def _threshold_implication(question_a: str, question_b: str) -> tuple[str, str] | None:
        match_a = _THRESHOLD_RE.search(question_a.lower())
        match_b = _THRESHOLD_RE.search(question_b.lower())
        if not match_a or not match_b:
            return None

        dir_a, val_a = match_a.group("dir"), float(match_a.group("val"))
        dir_b, val_b = match_b.group("dir"), float(match_b.group("val"))

        base_a = _THRESHOLD_RE.sub("", question_a.lower())
        base_b = _THRESHOLD_RE.sub("", question_b.lower())
        similarity = title_similarity(normalize_title(base_a), normalize_title(base_b))
        if similarity < 0.7:
            return None

        above_dirs = {">", ">=", "above", "over", "at least"}
        below_dirs = {"<", "<=", "below", "under", "at most"}

        if dir_a in above_dirs and dir_b in above_dirs:
            if val_a > val_b:
                return ("A_implies_B", "higher_threshold_implies_lower")
            if val_b > val_a:
                return ("B_implies_A", "higher_threshold_implies_lower")

        if dir_a in below_dirs and dir_b in below_dirs:
            if val_a < val_b:
                return ("A_implies_B", "lower_ceiling_implies_higher_ceiling")
            if val_b < val_a:
                return ("B_implies_A", "lower_ceiling_implies_higher_ceiling")
        return None

    @staticmethod
    def _lexical_implication(question_a: str, question_b: str) -> tuple[str, float] | None:
        tokens_a = extract_keywords(question_a)
        tokens_b = extract_keywords(question_b)
        if not tokens_a or not tokens_b:
            return None
        if tokens_a < tokens_b and len(tokens_b) - len(tokens_a) >= 1:
            return ("B_implies_A", 0.72)
        if tokens_b < tokens_a and len(tokens_a) - len(tokens_b) >= 1:
            return ("A_implies_B", 0.72)
        return None

    @staticmethod
    def _mutual_exclusion(question_a: str, question_b: str) -> bool:
        qa = question_a.lower()
        qb = question_b.lower()
        neg_markers = [("win", "lose"), ("yes", "no"), ("above", "below"), ("over", "under")]
        return any((left in qa and right in qb) or (left in qb and right in qa) for left, right in neg_markers)

    def validate_gold_set(
        self,
        gold_set_path: str | Path,
        *,
        failure_limit: int = 10,
    ) -> RelationValidationReport:
        examples = load_gold_set(gold_set_path)
        confusion = {
            expected: {predicted: 0 for predicted in LLM_RELATION_LABELS}
            for expected in LLM_RELATION_LABELS
        }

        correct = 0
        failures: list[dict[str, Any]] = []
        for example in examples:
            result = self.classify(example.market_a, example.market_b)
            predicted = _normalize_relation_label(result.relation_type, allow_internal=False) or "ambiguous"
            confusion.setdefault(example.expected_label, {label: 0 for label in LLM_RELATION_LABELS})
            confusion[example.expected_label][predicted] = confusion[example.expected_label].get(predicted, 0) + 1
            if predicted == example.expected_label:
                correct += 1
                continue
            if len(failures) < failure_limit:
                failures.append(
                    {
                        "example_id": example.example_id,
                        "expected_label": example.expected_label,
                        "predicted_label": predicted,
                        "confidence": result.confidence,
                        "short_rationale": result.short_rationale,
                        "question_a": example.market_a.question,
                        "question_b": example.market_b.question,
                    }
                )

        total = len(examples)
        accuracy = float(correct / total) if total else 0.0
        return RelationValidationReport(
            total_examples=total,
            correct_examples=correct,
            accuracy=accuracy,
            confusion_matrix=confusion,
            failure_examples=failures,
            cache_stats=self.cache.stats(),
        )


def _build_market_from_row(
    market_payload: Mapping[str, Any] | None,
    *,
    fallback_prefix: str,
    defaults: Mapping[str, Any],
) -> NormalizedMarket:
    row = dict(defaults)
    row.update(dict(market_payload or {}))
    row.setdefault("market_id", f"{fallback_prefix}-market")
    row.setdefault("event_id", row["market_id"])
    row.setdefault("question", "")
    row.setdefault("category", "politics")
    row.setdefault("outcomes", ["Yes", "No"])
    row.setdefault("outcome", "Yes")
    row.setdefault("resolutionSource", "Associated Press")
    row.setdefault("endDate", "2026-11-03T23:59:00Z")
    row.setdefault("rules", f"Resolves using {row['resolutionSource']}.")
    return normalize_market(row)


def _example_id_from_row(row: Mapping[str, Any], market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> str:
    explicit = row.get("example_id") or row.get("pair_id") or row.get("id")
    if explicit:
        return str(explicit)
    question_a = str(market_a.get("question") or "")
    question_b = str(market_b.get("question") or "")
    seed = f"{normalize_title(question_a)}|{normalize_title(question_b)}"
    return seed[:80]


def load_gold_set(path: str | Path) -> list[GoldRelationExample]:
    examples: list[GoldRelationExample] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, Mapping):
                raise ValueError(f"Gold-set line {line_no} is not a JSON object")

            label = (
                row.get("label")
                or row.get("expected_label")
                or row.get("gold_label")
            )
            expected_label = _normalize_relation_label(label, allow_internal=False)
            if expected_label is None:
                raise ValueError(f"Gold-set line {line_no} has invalid label: {label!r}")

            market_a_payload = row.get("market_a")
            market_b_payload = row.get("market_b")
            if not isinstance(market_a_payload, Mapping):
                market_a_payload = {
                    "market_id": row.get("market_a_id") or f"gold-{line_no}-a",
                    "event_id": row.get("event_a_id") or row.get("market_a_id") or f"gold-{line_no}-event-a",
                    "question": row.get("question_a") or row.get("title_a") or "",
                    "category": row.get("category") or row.get("category_a") or "politics",
                    "outcomes": row.get("outcomes_a") or ["Yes", "No"],
                    "outcome": row.get("outcome_a") or "Yes",
                    "resolutionSource": row.get("resolution_source") or row.get("resolution_source_a") or "Associated Press",
                    "endDate": row.get("end_date") or row.get("end_date_a") or "2026-11-03T23:59:00Z",
                    "rules": row.get("rules_a") or row.get("rules") or "Resolves using Associated Press.",
                }
            if not isinstance(market_b_payload, Mapping):
                market_b_payload = {
                    "market_id": row.get("market_b_id") or f"gold-{line_no}-b",
                    "event_id": row.get("event_b_id") or row.get("market_b_id") or f"gold-{line_no}-event-b",
                    "question": row.get("question_b") or row.get("title_b") or "",
                    "category": row.get("category") or row.get("category_b") or "politics",
                    "outcomes": row.get("outcomes_b") or ["Yes", "No"],
                    "outcome": row.get("outcome_b") or "Yes",
                    "resolutionSource": row.get("resolution_source") or row.get("resolution_source_b") or "Associated Press",
                    "endDate": row.get("end_date") or row.get("end_date_b") or "2026-11-03T23:59:00Z",
                    "rules": row.get("rules_b") or row.get("rules") or "Resolves using Associated Press.",
                }

            market_a = _build_market_from_row(market_a_payload, fallback_prefix=f"gold-{line_no}-a", defaults={})
            market_b = _build_market_from_row(market_b_payload, fallback_prefix=f"gold-{line_no}-b", defaults={})
            example_id = _example_id_from_row(row, market_a_payload, market_b_payload)
            metadata = {
                key: value
                for key, value in dict(row).items()
                if key not in {"label", "expected_label", "gold_label", "market_a", "market_b"}
            }
            examples.append(
                GoldRelationExample(
                    example_id=example_id,
                    expected_label=expected_label,
                    market_a=market_a,
                    market_b=market_b,
                    metadata=metadata,
                )
            )
    return examples


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Relation classifier utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate", help="Validate classifier output against a gold set")
    validate.add_argument("--gold-set", required=True)
    validate.add_argument("--cache-path", default="data/relation_cache.db")
    validate.add_argument("--output-json", default="")
    validate.add_argument("--output-md", default="")
    validate.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    validate.add_argument("--debate-prompt-version", default=DEFAULT_DEBATE_PROMPT_VERSION)
    validate.add_argument("--debate-fallback", action="store_true")
    validate.add_argument("--low-confidence-threshold", type=float, default=0.72)
    validate.add_argument("--failure-limit", type=int, default=10)
    validate.add_argument("--log-level", default="INFO")
    return parser


def _cmd_validate(args: argparse.Namespace) -> int:
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))
    classifier = RelationClassifier(
        cache_path=args.cache_path,
        prompt_version=args.prompt_version,
        debate_prompt_version=args.debate_prompt_version,
        low_confidence_threshold=float(args.low_confidence_threshold),
        enable_debate_fallback=bool(args.debate_fallback),
    )
    report = classifier.validate_gold_set(args.gold_set, failure_limit=int(args.failure_limit))
    payload = report.to_dict()

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(report.to_markdown(), encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "validate":
        return _cmd_validate(args)
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
