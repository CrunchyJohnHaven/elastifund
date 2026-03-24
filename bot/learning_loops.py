"""
Learning Loops -- Three-speed self-improvement framework.

Fast loop (daily/intraday): Safe recalibrations that are fully reversible.
  - Volatility scaling updates
  - Spread/impact estimate refresh
  - Execution aggression bands
  - Risk limits tied to liquidity state
  - Skip threshold auto-adjustment based on recent fill rate

Medium loop (weekly): Controlled model refresh with rollback capability.
  - Coefficient updates (Platt A/B recalibration)
  - Feature re-estimation
  - Ensemble weight refresh
  - Regime classifier refresh
  - BTC5 parameter autoresearch integration
  - Kill-propagation sweep

Slow loop (monthly/manual): Architecture changes requiring full validation.
  - New feature families
  - New model classes
  - New execution logic
  - New market/universe
  - New portfolio constraints
  - These go through Bronze -> Silver -> Gold -> Platinum gates

Key principle: slow-loop changes go back through the full validation stack.
Never allow 'self-improvement' to mean 'the model can silently redesign production.'
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Callable
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class LoopSpeed(Enum):
    FAST = "fast"      # daily/intraday
    MEDIUM = "medium"  # weekly
    SLOW = "slow"      # monthly, requires full validation


@dataclass
class LoopAction:
    """A single action that can be executed within a learning loop."""
    name: str
    speed: LoopSpeed
    description: str
    execute: Optional[Callable] = None
    last_run: str = ""
    last_result: str = ""
    enabled: bool = True
    requires_approval: bool = False  # Slow loop requires human approval


@dataclass
class LoopResult:
    """Result of executing a loop action, with rollback support."""
    action_name: str
    speed: str
    success: bool
    timestamp: str
    changes_made: List[str] = field(default_factory=list)
    metrics_before: Dict = field(default_factory=dict)
    metrics_after: Dict = field(default_factory=dict)
    rollback_data: str = ""  # JSON snapshot for rollback
    notes: str = ""


class LearningLoopManager:
    """
    Manages three learning speeds for continuous self-improvement.

    Fast loop: Safe, reversible recalibrations (daily)
    Medium loop: Controlled model refresh (weekly)
    Slow loop: Architecture changes requiring full validation (manual)

    Key principle: Slow-loop changes go back through the full validation stack.
    Never allow 'self-improvement' to mean 'the model can silently redesign production.'
    """

    # Intervals between runs for each speed tier
    INTERVALS = {
        LoopSpeed.FAST: timedelta(hours=24),
        LoopSpeed.MEDIUM: timedelta(days=7),
        LoopSpeed.SLOW: timedelta(days=30),
    }

    def __init__(self, state_dir: str = "state/learning_loops"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.state_dir / "loop_history.db")
        self._init_db()
        self.actions: Dict[str, LoopAction] = {}
        self._register_default_actions()

    def _init_db(self):
        """Initialize SQLite database for loop run history."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS loop_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_name TEXT NOT NULL,
                speed TEXT NOT NULL,
                success INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                changes_json TEXT DEFAULT '[]',
                metrics_before_json TEXT DEFAULT '{}',
                metrics_after_json TEXT DEFAULT '{}',
                rollback_data TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_loop_action ON loop_runs(action_name);
            CREATE INDEX IF NOT EXISTS idx_loop_time ON loop_runs(timestamp);
        """)
        conn.commit()
        conn.close()

    def _register_default_actions(self):
        """Register the standard set of loop actions across all three speeds."""
        # --- Fast loop actions ---
        self.register_action(LoopAction(
            name="volatility_scaling",
            speed=LoopSpeed.FAST,
            description="Update volatility estimates from recent market data",
        ))
        self.register_action(LoopAction(
            name="spread_impact_refresh",
            speed=LoopSpeed.FAST,
            description="Recalculate spread and market impact from recent fills",
        ))
        self.register_action(LoopAction(
            name="skip_threshold_adjust",
            speed=LoopSpeed.FAST,
            description="Auto-adjust skip thresholds based on recent fill rate",
        ))
        self.register_action(LoopAction(
            name="risk_limit_update",
            speed=LoopSpeed.FAST,
            description="Adjust risk limits based on current liquidity state",
        ))

        # --- Medium loop actions ---
        self.register_action(LoopAction(
            name="platt_recalibration",
            speed=LoopSpeed.MEDIUM,
            description="Recalibrate Platt scaling coefficients A/B",
        ))
        self.register_action(LoopAction(
            name="regime_classifier_refresh",
            speed=LoopSpeed.MEDIUM,
            description="Refresh regime detection parameters",
        ))
        self.register_action(LoopAction(
            name="btc5_param_integration",
            speed=LoopSpeed.MEDIUM,
            description="Integrate BTC5 autoresearch findings into main config",
        ))
        self.register_action(LoopAction(
            name="kill_propagation_sweep",
            speed=LoopSpeed.MEDIUM,
            description="Check if any strategy should be killed based on new data",
        ))
        self.register_action(LoopAction(
            name="negative_results_update",
            speed=LoopSpeed.MEDIUM,
            description="Update negative results library with recent failures",
        ))

        # --- Slow loop actions (require approval) ---
        self.register_action(LoopAction(
            name="new_feature_family",
            speed=LoopSpeed.SLOW,
            description="Add new feature family to signal generation",
            requires_approval=True,
        ))
        self.register_action(LoopAction(
            name="new_model_class",
            speed=LoopSpeed.SLOW,
            description="Introduce new model architecture",
            requires_approval=True,
        ))
        self.register_action(LoopAction(
            name="new_market_universe",
            speed=LoopSpeed.SLOW,
            description="Expand to new market or venue",
            requires_approval=True,
        ))

    def register_action(self, action: LoopAction):
        """Register a loop action. Overwrites if name already exists."""
        self.actions[action.name] = action

    def get_due_actions(self, speed: LoopSpeed) -> List[LoopAction]:
        """Get actions that are due to run based on their speed and last run time."""
        interval = self.INTERVALS[speed]
        now = datetime.now(timezone.utc)
        due = []

        for action in self.actions.values():
            if action.speed != speed or not action.enabled:
                continue
            if not action.last_run:
                due.append(action)
                continue
            last = datetime.fromisoformat(action.last_run)
            if now - last >= interval:
                due.append(action)

        return due

    def record_run(self, result: LoopResult):
        """Record a loop execution result to the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO loop_runs (action_name, speed, success, timestamp,
                    changes_json, metrics_before_json, metrics_after_json,
                    rollback_data, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.action_name, result.speed, int(result.success),
                result.timestamp, json.dumps(result.changes_made),
                json.dumps(result.metrics_before), json.dumps(result.metrics_after),
                result.rollback_data, result.notes,
            ))
            conn.commit()

            # Update last_run on the action
            if result.action_name in self.actions:
                self.actions[result.action_name].last_run = result.timestamp
                self.actions[result.action_name].last_result = (
                    "success" if result.success else "failed"
                )

            logger.info(
                "Loop run recorded: %s (%s) -> %s",
                result.action_name, result.speed,
                "OK" if result.success else "FAIL",
            )
        finally:
            conn.close()

    def get_run_history(
        self, action_name: Optional[str] = None, limit: int = 50
    ) -> list:
        """Get recent loop run history, optionally filtered by action name."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if action_name:
                rows = conn.execute(
                    "SELECT * FROM loop_runs WHERE action_name = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (action_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM loop_runs ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _run_loop(self, speed: LoopSpeed) -> List[LoopResult]:
        """Execute all due actions for a given speed tier."""
        due = self.get_due_actions(speed)
        results = []
        for action in due:
            logger.info("Running %s-loop action: %s", speed.value, action.name)
            result = LoopResult(
                action_name=action.name,
                speed=speed.value,
                success=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
                notes=f"Executed: {action.description}",
            )
            if action.execute:
                try:
                    action.execute()
                except Exception as e:
                    result.success = False
                    result.notes = f"Failed: {e}"
                    logger.error(
                        "%s-loop action %s failed: %s", speed.value, action.name, e
                    )
            self.record_run(result)
            results.append(result)
        return results

    def run_fast_loop(self) -> List[LoopResult]:
        """Execute all due fast-loop actions. Safe to run daily."""
        return self._run_loop(LoopSpeed.FAST)

    def run_medium_loop(self) -> List[LoopResult]:
        """Execute all due medium-loop actions. Safe to run weekly."""
        return self._run_loop(LoopSpeed.MEDIUM)

    def check_slow_loop_candidates(self) -> List[LoopAction]:
        """Return slow-loop actions that are due. These require human approval."""
        return [a for a in self.get_due_actions(LoopSpeed.SLOW) if a.requires_approval]
