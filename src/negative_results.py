"""Negative-results library: what failed, why, and what we learned.

Tracks every killed strategy with its kill reason, lessons learned,
and auto-veto logic. If a strategy family accumulates enough kills,
all remaining variants in that family get deprioritized automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any
import json
import sqlite3
import time
from pathlib import Path


@dataclass
class NegativeResult:
    """Record of a failed strategy and its lessons."""

    result_id: str
    hypothesis_id: str
    hypothesis_name: str
    family: str = ""
    kill_rule: str = ""
    kill_details: str = ""
    what_failed: str = ""
    why_it_failed: str = ""
    what_was_learned: str = ""
    counter_hypotheses: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metrics_at_kill: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NegativeResultsLibrary:
    """SQLite-backed negative-results library with auto-veto logic.

    Stores every killed strategy, tracks kill reasons, and provides
    family-level veto decisions based on accumulated failures.
    """

    # If a family has this many kills, auto-veto all remaining variants
    DEFAULT_FAMILY_KILL_THRESHOLD = 3

    def __init__(self, db_path: str | Path, family_kill_threshold: int = DEFAULT_FAMILY_KILL_THRESHOLD):
        self.db_path = Path(db_path)
        self.family_kill_threshold = family_kill_threshold
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS negative_results (
                result_id TEXT PRIMARY KEY,
                hypothesis_id TEXT NOT NULL,
                hypothesis_name TEXT NOT NULL,
                family TEXT NOT NULL DEFAULT '',
                kill_rule TEXT NOT NULL DEFAULT '',
                kill_details TEXT NOT NULL DEFAULT '',
                what_failed TEXT NOT NULL DEFAULT '',
                why_it_failed TEXT NOT NULL DEFAULT '',
                what_was_learned TEXT NOT NULL DEFAULT '',
                data_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nr_family
                ON negative_results(family);
            CREATE INDEX IF NOT EXISTS idx_nr_kill_rule
                ON negative_results(kill_rule);
            CREATE INDEX IF NOT EXISTS idx_nr_hypothesis
                ON negative_results(hypothesis_id);
            """
        )
        conn.commit()
        conn.close()

    def record(self, result: NegativeResult) -> None:
        """Record a negative result."""
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO negative_results "
            "(result_id, hypothesis_id, hypothesis_name, family, kill_rule, kill_details, "
            "what_failed, why_it_failed, what_was_learned, data_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.result_id,
                result.hypothesis_id,
                result.hypothesis_name,
                result.family,
                result.kill_rule,
                result.kill_details,
                result.what_failed,
                result.why_it_failed,
                result.what_was_learned,
                json.dumps(result.to_dict()),
                result.timestamp,
            ),
        )
        conn.commit()
        conn.close()

    def get(self, result_id: str) -> NegativeResult | None:
        """Retrieve a negative result by ID."""
        conn = self._connect()
        row = conn.execute(
            "SELECT data_json FROM negative_results WHERE result_id = ?",
            (result_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._from_json(row["data_json"])

    def list_by_family(self, family: str) -> list[NegativeResult]:
        """List all negative results for a strategy family."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM negative_results WHERE family = ? ORDER BY timestamp DESC",
            (family,),
        ).fetchall()
        conn.close()
        return [self._from_json(r["data_json"]) for r in rows]

    def list_by_kill_rule(self, kill_rule: str) -> list[NegativeResult]:
        """List all strategies killed by a specific rule."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM negative_results WHERE kill_rule = ? ORDER BY timestamp DESC",
            (kill_rule,),
        ).fetchall()
        conn.close()
        return [self._from_json(r["data_json"]) for r in rows]

    def list_all(self) -> list[NegativeResult]:
        """List all negative results."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM negative_results ORDER BY timestamp DESC"
        ).fetchall()
        conn.close()
        return [self._from_json(r["data_json"]) for r in rows]

    def family_kill_count(self, family: str) -> int:
        """Count kills in a family."""
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM negative_results WHERE family = ?",
            (family,),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    def is_family_vetoed(self, family: str) -> bool:
        """Check if a family has accumulated enough kills to be auto-vetoed."""
        if not family:
            return False
        return self.family_kill_count(family) >= self.family_kill_threshold

    def vetoed_families(self) -> list[str]:
        """List all families that are currently auto-vetoed."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT family, COUNT(*) as cnt FROM negative_results "
            "WHERE family != '' GROUP BY family HAVING cnt >= ?",
            (self.family_kill_threshold,),
        ).fetchall()
        conn.close()
        return [r["family"] for r in rows]

    def kill_rule_summary(self) -> dict[str, int]:
        """Summary of kill counts by rule."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT kill_rule, COUNT(*) as cnt FROM negative_results "
            "WHERE kill_rule != '' GROUP BY kill_rule ORDER BY cnt DESC"
        ).fetchall()
        conn.close()
        return {r["kill_rule"]: r["cnt"] for r in rows}

    def lessons_for_family(self, family: str) -> list[str]:
        """Extract lessons learned for a family (for research context)."""
        results = self.list_by_family(family)
        return [r.what_was_learned for r in results if r.what_was_learned]

    def dead_end_context(self) -> str:
        """Generate context string for research prompts excluding dead ends.

        Returns a summary of vetoed families and their kill reasons,
        suitable for injecting into research prompt context.
        """
        vetoed = self.vetoed_families()
        if not vetoed:
            return ""

        lines = ["VETOED STRATEGY FAMILIES (do not pursue variants):"]
        for family in vetoed:
            kills = self.list_by_family(family)
            rules = list({k.kill_rule for k in kills if k.kill_rule})
            lessons = [k.what_was_learned for k in kills if k.what_was_learned]
            lines.append(f"  - {family}: {len(kills)} kills, rules: {', '.join(rules)}")
            for lesson in lessons[:3]:  # cap at 3 lessons per family
                lines.append(f"    Lesson: {lesson}")

        return "\n".join(lines)

    @staticmethod
    def _from_json(data_json: str) -> NegativeResult:
        d = json.loads(data_json)
        return NegativeResult(**d)
