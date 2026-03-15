"""Detector plugin interface.

Every detector must subclass Detector and implement `scan()`.
Detectors are read-only — they observe prices and emit Opportunity objects
but never place orders.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.core.time_utils import utc_now_naive


@dataclass(frozen=True)
class Opportunity:
    """A single detected mispricing opportunity."""

    detector: str  # e.g. "structural"
    kind: str  # e.g. "mutual_exclusivity" or "implication"
    group_label: str  # human-readable group description
    market_ids: tuple[str, ...]  # markets involved
    edge_pct: float  # estimated edge as a percentage (e.g. 5.2 means 5.2%)
    detail: str  # human-readable explanation
    prices: dict[str, float] = field(default_factory=dict)  # market_id -> price
    detected_at: datetime = field(default_factory=utc_now_naive)
    meta: dict = field(default_factory=dict)  # extra data for downstream use


class Detector(ABC):
    """Abstract base class for all detector plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short slug used in DB and logs (e.g. 'structural')."""

    @abstractmethod
    async def scan(
        self,
        markets: list[dict],
    ) -> list[Opportunity]:
        """Scan a batch of markets and return detected opportunities.

        Args:
            markets: List of raw market dicts from the Gamma API.
                     Each dict must contain at minimum:
                       - "id" (condition_id)
                       - "question"
                       - "tokens" (list of token dicts with "token_id" and "price")

        Returns:
            List of Opportunity objects, sorted by edge_pct descending.
        """
