"""Data models for EdgeCard and Experiment entities."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EdgeStatus(str, Enum):
    BACKLOG = "backlog"
    TESTING = "testing"
    PROMOTED = "promoted"
    DEMOTED = "demoted"


class ExperimentStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass
class EdgeCard:
    """A hypothesis about a tradeable edge on Polymarket."""

    name: str
    hypothesis: str
    source: str = "manual"  # manual | backtest | research | paper
    status: str = EdgeStatus.BACKLOG
    expected_win_rate: Optional[float] = None
    expected_ev_per_trade: Optional[float] = None
    tags: str = ""  # comma-separated
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_row(self) -> tuple:
        return (
            self.id, self.name, self.hypothesis, self.source, self.status,
            self.expected_win_rate, self.expected_ev_per_trade,
            self.tags, self.notes, self.created_at, self.updated_at,
        )

    @classmethod
    def from_row(cls, row: tuple) -> EdgeCard:
        return cls(
            id=row[0], name=row[1], hypothesis=row[2], source=row[3],
            status=row[4], expected_win_rate=row[5],
            expected_ev_per_trade=row[6], tags=row[7], notes=row[8],
            created_at=row[9], updated_at=row[10],
        )


@dataclass
class Experiment:
    """A controlled test of an EdgeCard hypothesis."""

    edge_id: str
    config: str = "{}"  # JSON string of strategy parameters
    status: str = ExperimentStatus.RUNNING
    num_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    updated_at: float = field(default_factory=time.time)

    @property
    def win_rate(self) -> float:
        if self.num_trades == 0:
            return 0.0
        return self.wins / self.num_trades

    @property
    def avg_pnl(self) -> float:
        if self.num_trades == 0:
            return 0.0
        return self.total_pnl / self.num_trades

    def to_row(self) -> tuple:
        return (
            self.id, self.edge_id, self.config, self.status,
            self.num_trades, self.wins, self.losses,
            self.total_pnl, self.max_drawdown, self.notes,
            self.started_at, self.ended_at, self.updated_at,
        )

    @classmethod
    def from_row(cls, row: tuple) -> Experiment:
        return cls(
            id=row[0], edge_id=row[1], config=row[2], status=row[3],
            num_trades=row[4], wins=row[5], losses=row[6],
            total_pnl=row[7], max_drawdown=row[8], notes=row[9],
            started_at=row[10], ended_at=row[11], updated_at=row[12],
        )
