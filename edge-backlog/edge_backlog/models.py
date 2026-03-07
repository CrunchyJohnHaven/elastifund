"""Data models for the edge backlog system."""

from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional


class Status(str, Enum):
    IDEA = "IDEA"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    SHADOW = "SHADOW"
    LIVE = "LIVE"

    @classmethod
    def ordered(cls) -> List["Status"]:
        return [cls.IDEA, cls.BACKTEST, cls.PAPER, cls.SHADOW, cls.LIVE]

    def next(self) -> Optional["Status"]:
        order = self.ordered()
        idx = order.index(self)
        return order[idx + 1] if idx + 1 < len(order) else None

    def prev(self) -> Optional["Status"]:
        order = self.ordered()
        idx = order.index(self)
        return order[idx - 1] if idx > 0 else None


@dataclass
class ExperimentResult:
    timestamp: str
    metric: str
    value: float
    notes: str = ""


@dataclass
class Experiment:
    id: str
    name: str
    started: str
    status: str = "running"  # running | completed | failed
    results: List[ExperimentResult] = field(default_factory=list)

    def add_result(self, metric: str, value: float, notes: str = "") -> ExperimentResult:
        r = ExperimentResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            metric=metric,
            value=value,
            notes=notes,
        )
        self.results.append(r)
        return r


@dataclass
class Edge:
    id: str
    name: str
    hypothesis: str
    status: Status
    score: Optional[float] = None
    score_notes: str = ""
    created: str = ""
    updated: str = ""
    tags: List[str] = field(default_factory=list)
    experiments: List[Experiment] = field(default_factory=list)
    history: List[str] = field(default_factory=list)

    def promote(self) -> Status:
        nxt = self.status.next()
        if nxt is None:
            raise ValueError(f"Cannot promote beyond {self.status.value}")
        if nxt == Status.LIVE:
            raise ValueError("LIVE is blocked in no-trade mode")
        old = self.status
        self.status = nxt
        self._log(f"Promoted {old.value} → {nxt.value}")
        return nxt

    def demote(self) -> Status:
        prv = self.status.prev()
        if prv is None:
            raise ValueError(f"Cannot demote below {self.status.value}")
        old = self.status
        self.status = prv
        self._log(f"Demoted {old.value} → {prv.value}")
        return prv

    def set_score(self, score: float, notes: str = "") -> None:
        self.score = score
        self.score_notes = notes
        self._log(f"Scored {score}" + (f": {notes}" if notes else ""))

    def start_experiment(self, name: str) -> Experiment:
        exp = Experiment(
            id=uuid.uuid4().hex[:8],
            name=name,
            started=datetime.now(timezone.utc).isoformat(),
        )
        self.experiments.append(exp)
        self._log(f"Started experiment '{name}' ({exp.id})")
        return exp

    def _log(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        self.history.append(f"[{ts}] {msg}")
        self.updated = ts


class EdgeStore:
    """JSON-file backed storage for edges."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> dict:
        if not self.path.exists():
            return {}
        with open(self.path) as f:
            return json.load(f)

    def _save_all(self, data: dict) -> None:
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def save(self, edge: Edge) -> None:
        data = self._load_all()
        data[edge.id] = _edge_to_dict(edge)
        self._save_all(data)

    def get(self, edge_id: str) -> Edge:
        data = self._load_all()
        if edge_id not in data:
            raise KeyError(f"Edge '{edge_id}' not found")
        return _edge_from_dict(data[edge_id])

    def list_all(self, status: Optional[Status] = None) -> List[Edge]:
        data = self._load_all()
        edges = [_edge_from_dict(v) for v in data.values()]
        if status:
            edges = [e for e in edges if e.status == status]
        edges.sort(key=lambda e: e.created)
        return edges

    def delete(self, edge_id: str) -> None:
        data = self._load_all()
        if edge_id not in data:
            raise KeyError(f"Edge '{edge_id}' not found")
        del data[edge_id]
        self._save_all(data)


def _edge_to_dict(edge: Edge) -> dict:
    d = asdict(edge)
    d["status"] = edge.status.value
    return d


def _edge_from_dict(d: dict) -> Edge:
    d = dict(d)
    d["status"] = Status(d["status"])
    d["experiments"] = [
        Experiment(
            id=e["id"],
            name=e["name"],
            started=e["started"],
            status=e["status"],
            results=[ExperimentResult(**r) for r in e.get("results", [])],
        )
        for e in d.get("experiments", [])
    ]
    return Edge(**d)
