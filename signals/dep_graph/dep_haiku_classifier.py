"""Haiku prompt/parse layer for B-1 dependency classification."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping


ALLOWED_RELATIONS = {
    "A_implies_B",
    "B_implies_A",
    "mutually_exclusive",
    "subset",
    "complementary",
    "independent",
}
ALLOWED_CONSTRAINTS = {
    "P(A)<=P(B)",
    "P(B)<=P(A)",
    "P(A)+P(B)<=1",
    "P(A)+P(B)=1",
    "none",
}

SYSTEM_PROMPT = "You are a strict logical classifier for prediction-market questions. Output must be valid JSON and nothing else."


@dataclass(frozen=True)
class HaikuClassification:
    relation: str
    confidence: float
    reason: str
    tradeable_constraint: str


def build_prompt(market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> str:
    return (
        "You will classify the logical relationship between two binary prediction markets.\n\n"
        "Return ONLY JSON with:\n"
        "{\n"
        '  "relation": one of ["A_implies_B","B_implies_A","mutually_exclusive","subset","complementary","independent"],\n'
        '  "confidence": number from 0.0 to 1.0,\n'
        '  "reason": short <= 25 words,\n'
        '  "tradeable_constraint": one of ["P(A)<=P(B)","P(B)<=P(A)","P(A)+P(B)<=1","P(A)+P(B)=1","none"]\n'
        "}\n\n"
        "Definitions:\n"
        "- A_implies_B: whenever A resolves YES, B must resolve YES.\n"
        "- subset: A and B refer to the same event space but A is strictly narrower than B.\n"
        "- mutually_exclusive: A and B cannot both resolve YES.\n"
        "- complementary: exactly one of A or B must resolve YES.\n"
        "- independent: none of the above can be assumed from the text.\n\n"
        f"Market A:\nQuestion: {market_a.get('question','')}\nDescription: {market_a.get('description','')}\nEnd date: {market_a.get('endDate','')}\n\n"
        f"Market B:\nQuestion: {market_b.get('question','')}\nDescription: {market_b.get('description','')}\nEnd date: {market_b.get('endDate','')}\n\n"
        "Important:\n"
        '- If unsure, choose "independent" with low confidence.\n'
        "- Do not assume real-world correlations; only strict logical/semantic implication/exclusion.\n"
    )


def parse_response(text: str) -> HaikuClassification:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return HaikuClassification("independent", 0.0, "malformed_json", "none")

    if not isinstance(payload, Mapping):
        return HaikuClassification("independent", 0.0, "invalid_payload", "none")

    relation = str(payload.get("relation") or "independent")
    if relation not in ALLOWED_RELATIONS:
        relation = "independent"

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = str(payload.get("reason") or "").strip()[:120] or "no_reason"
    constraint = str(payload.get("tradeable_constraint") or "none")
    if constraint not in ALLOWED_CONSTRAINTS:
        constraint = "none"

    return HaikuClassification(relation, confidence, reason, constraint)


class HaikuDependencyClassifier:
    """Thin classifier wrapper; transport can be HTTP, SDK, or a test stub."""

    def __init__(
        self,
        *,
        model_version: str = "haiku-json-v1",
        transport: Callable[[str, str], str] | None = None,
    ) -> None:
        self.model_version = model_version
        self.transport = transport

    def classify(self, market_a: Mapping[str, Any], market_b: Mapping[str, Any]) -> HaikuClassification:
        prompt = build_prompt(market_a, market_b)
        if self.transport is None:
            return HaikuClassification("independent", 0.0, "transport_not_configured", "none")
        raw = self.transport(SYSTEM_PROMPT, prompt)
        return parse_response(raw)
