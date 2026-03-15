"""Structural mispricing detector.

Finds two kinds of arbitrage-free violations:

1. **Mutual exclusivity**: Markets sharing the same event (condition_id) must
   have YES prices summing to <= 1.0.  If they sum to > 1.0, there is a
   guaranteed overpricing of at least (sum - 1) across the group.

2. **Implication bounds**: If event A implies event B (manually mapped), then
   price(A) must be <= price(B).  A violation means A is overpriced relative
   to B (or B is underpriced relative to A).

Both checks are purely arithmetic — no ML, no API calls, fully deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

import structlog

from src.detectors.base import Detector, Opportunity

logger = structlog.get_logger(__name__)

DEFAULT_MAPPINGS_PATH = Path(__file__).parent / "mappings" / "implications.json"


def _extract_yes_price(market: dict) -> Optional[float]:
    """Pull the YES-side price from a Gamma API market dict.

    Handles two common payload shapes:
      1. market["tokens"] = [{"outcome": "Yes", "price": 0.65}, ...]
      2. market["outcomePrices"] = "[0.65, 0.35]"  (JSON-encoded string)
    """
    # Shape 1: tokens list
    tokens = market.get("tokens")
    if tokens:
        for tok in tokens:
            outcome = (tok.get("outcome") or "").lower()
            if outcome == "yes":
                try:
                    return float(tok["price"])
                except (KeyError, TypeError, ValueError):
                    pass

    # Shape 2: outcomePrices string
    outcome_prices_raw = market.get("outcomePrices")
    if outcome_prices_raw:
        try:
            prices = json.loads(outcome_prices_raw) if isinstance(outcome_prices_raw, str) else outcome_prices_raw
            if isinstance(prices, list) and len(prices) >= 1:
                return float(prices[0])
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None


class StructuralDetector(Detector):
    """Detects structural mispricings using price-sum arithmetic."""

    def __init__(
        self,
        mappings_path: Union[Path, str, None] = None,
        min_edge_pct: float = 0.5,
    ):
        self._mappings_path = Path(mappings_path) if mappings_path else DEFAULT_MAPPINGS_PATH
        self._min_edge_pct = min_edge_pct
        self._implications: list[dict] = []
        self._load_implications()

    @property
    def name(self) -> str:
        return "structural"

    def _load_implications(self) -> None:
        if not self._mappings_path.exists():
            logger.warning("implications_file_missing", path=str(self._mappings_path))
            return
        try:
            raw = json.loads(self._mappings_path.read_text())
            for group in raw.get("groups", []):
                for imp in group.get("implies", []):
                    if imp.get("if_market") and imp.get("then_market"):
                        self._implications.append({
                            "if_market": imp["if_market"],
                            "then_market": imp["then_market"],
                            "label": group.get("label", ""),
                        })
            logger.info("implications_loaded", count=len(self._implications))
        except Exception as e:
            logger.error("implications_load_error", error=str(e))

    async def scan(self, markets: list[dict]) -> list[Opportunity]:
        opps: list[Opportunity] = []
        opps.extend(self._check_mutual_exclusivity(markets))
        opps.extend(self._check_implications(markets))
        opps.sort(key=lambda o: o.edge_pct, reverse=True)
        return opps

    # ── Mutual Exclusivity ────────────────────────────────────────

    def _check_mutual_exclusivity(self, markets: list[dict]) -> list[Opportunity]:
        """Group markets by condition_id (event). Outcomes within the same event
        are mutually exclusive, so their YES prices must sum to <= 1.0."""
        groups: dict[str, list[dict]] = {}
        for m in markets:
            cid = m.get("condition_id") or m.get("conditionId")
            if not cid:
                continue
            groups.setdefault(cid, []).append(m)

        opps: list[Opportunity] = []
        for cid, group_markets in groups.items():
            if len(group_markets) < 2:
                continue

            prices: dict[str, float] = {}
            for gm in group_markets:
                mid = gm.get("id", gm.get("market_id", ""))
                yes_price = _extract_yes_price(gm)
                if yes_price is not None and mid:
                    prices[mid] = yes_price

            if len(prices) < 2:
                continue

            total = sum(prices.values())
            if total <= 1.0:
                continue

            edge_pct = (total - 1.0) * 100.0
            if edge_pct < self._min_edge_pct:
                continue

            question_sample = group_markets[0].get("question", cid)
            opps.append(Opportunity(
                detector=self.name,
                kind="mutual_exclusivity",
                group_label=f"ME: {question_sample}",
                market_ids=tuple(prices.keys()),
                edge_pct=round(edge_pct, 2),
                detail=(
                    f"YES prices sum to {total:.4f} (>{1.0}). "
                    f"Overpriced by {edge_pct:.2f}% across {len(prices)} outcomes."
                ),
                prices=prices,
                meta={"condition_id": cid, "sum": round(total, 4)},
            ))

        return opps

    # ── Implication Bounds ────────────────────────────────────────

    def _check_implications(self, markets: list[dict]) -> list[Opportunity]:
        """For each manual implication A=>B, check price(A) <= price(B)."""
        if not self._implications:
            return []

        price_map: dict[str, tuple[float, str]] = {}  # condition_id -> (yes_price, market_id)
        for m in markets:
            cid = m.get("condition_id") or m.get("conditionId")
            mid = m.get("id", m.get("market_id", ""))
            if not cid or not mid:
                continue
            yp = _extract_yes_price(m)
            if yp is not None:
                price_map[cid] = (yp, mid)

        opps: list[Opportunity] = []
        for imp in self._implications:
            if_cid = imp["if_market"]
            then_cid = imp["then_market"]
            if if_cid not in price_map or then_cid not in price_map:
                continue

            price_a, mid_a = price_map[if_cid]
            price_b, mid_b = price_map[then_cid]

            if price_a <= price_b:
                continue

            edge_pct = (price_a - price_b) * 100.0
            if edge_pct < self._min_edge_pct:
                continue

            opps.append(Opportunity(
                detector=self.name,
                kind="implication",
                group_label=f"IMP: {imp.get('label', f'{if_cid}->{then_cid}')}",
                market_ids=(mid_a, mid_b),
                edge_pct=round(edge_pct, 2),
                detail=(
                    f"A=>B violation: price(A)={price_a:.4f} > price(B)={price_b:.4f}. "
                    f"Edge {edge_pct:.2f}%."
                ),
                prices={mid_a: price_a, mid_b: price_b},
                meta={
                    "if_condition_id": if_cid,
                    "then_condition_id": then_cid,
                },
            ))

        return opps
