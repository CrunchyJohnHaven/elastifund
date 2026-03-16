# DISPATCH 110 — Codex Parallel Self-Improving System

**Date:** 2026-03-16
**Priority:** CRITICAL — overnight autonomous execution
**Status:** READY FOR CODEX

---

## Current System State

- **Portfolio:** $1,308 CLOB balance, $1,365 total
- **Win rate:** 15/17 = 88.2% (12/12 = 100% at entry >= 0.90)
- **6 assets live:** BTC, ETH, SOL, BNB, DOGE, XRP (5-min candles)
- **Capital config:** 33% risk fraction, $500 stage caps, $1,308 bankroll
- **Auto-compound:** Cron every 30 min syncing CLOB balance to bankroll
- **Autoresearch:** Every 1h, generating/testing/promoting hypotheses
- **Inline adaptive:** Suppresses losing direction for 1h if trailing WR < 80% on 5+ fills
- **Graduated Kelly:** Ramps risk with N qualifying fills at 0.90+

## Known Blockers (Quantified)

| Blocker | Count (24h) | % of Windows | Impact |
|---------|-------------|--------------|--------|
| skip_bad_book | 153 (BTC) | ~17% | One-sided books, no asks at bid=0.99 |
| skip_delta_too_large | 199 | ~22% | Delta > 0.004 threshold |
| skip_price_outside_guardrails | 132 | ~15% | Entry price outside 0.90-0.95 |
| skip_directional_mode | 91 | ~10% | Direction filter blocking |
| skip_delta_too_small | 110 | ~12% | Delta below minimum |

**Fill rate: ~1.2%** — 11 fills out of ~900 BTC windows. This is the #1 problem.

---

## Instance 1: Karpathy-Style Pricing Evolution Engine

**File:** `bot/pricing_evolution.py` (NEW)
**Modifies:** `bot/autoresearch_loop.py`
**Isolation:** worktree — safe to develop in parallel

### Objective
Replace static price floor/cap tuning with an evolutionary parameter search. Every autoresearch cycle:
1. Generate 5-10 parameter mutations (price floor, cap, delta threshold, direction bias)
2. Score each against the last 24h of fill data using counterfactual replay
3. Promote the highest-scoring mutation to live overrides
4. Track lineage — which parameter sets descended from which

### Implementation

```python
# pricing_evolution.py

@dataclass
class ParameterGenome:
    min_buy_price: float    # [0.85, 0.95]
    max_buy_price: float    # [0.90, 0.98]
    min_delta: float        # [0.0001, 0.005]
    max_delta: float        # [0.002, 0.010]
    direction_mode: str     # "two_sided" | "down_only" | "up_only"
    parent_id: str          # lineage tracking
    generation: int
    fitness: float = 0.0

def mutate(parent: ParameterGenome, mutation_rate=0.1) -> ParameterGenome:
    """Small random perturbation of parent parameters."""
    ...

def crossover(a: ParameterGenome, b: ParameterGenome) -> ParameterGenome:
    """Combine best traits of two genomes."""
    ...

def evaluate_fitness(genome: ParameterGenome, fills: list, skips: list) -> float:
    """
    Counterfactual replay: for each skip window, check if this genome
    would have traded it. For each fill, check if it would have sized differently.
    Return risk-adjusted PnL estimate.
    """
    ...

def evolve_generation(population: list[ParameterGenome], fills, skips) -> list:
    """
    1. Evaluate fitness of all genomes
    2. Select top 3 by fitness
    3. Generate children via mutation + crossover
    4. Return new population of 10
    """
    ...
```

### Integration with autoresearch_loop.py

Add to `run_cycle()`:
```python
from pricing_evolution import evolve_generation, load_population, save_population

population = load_population()  # from data/pricing_population.json
fills, skips = observe_fills_and_skips(hours=24)
new_pop = evolve_generation(population, fills, skips)
save_population(new_pop)

# If best genome fitness > current live fitness by 10%+, promote
best = max(new_pop, key=lambda g: g.fitness)
if best.fitness > current_live_fitness * 1.10:
    promote_genome_to_overrides(best)
```

### Hard Bounds (NEVER violate)
- min_buy_price >= 0.85
- max_buy_price <= 0.98
- risk_fraction <= 0.33
- daily_loss_limit unchanged

### Success Criteria
- Population diversity maintained (>3 distinct genomes)
- At least 1 promotion per 24h
- Fill rate improvement measurable within 48h

---

## Instance 2: Multi-Asset Correlation & Arbitrage Scanner

**File:** `bot/multi_asset_arb.py` (NEW)
**Modifies:** none (standalone scanner, writes to data/)
**Isolation:** worktree

### Objective
Cross-asset signal detection. When BTC dumps, ETH/SOL/BNB often follow 30-120 seconds later. Detect this lead-lag and pre-position.

### Implementation

```python
# multi_asset_arb.py — runs as standalone service

ASSETS = ["btc", "eth", "sol", "bnb", "doge", "xrp"]
BINANCE_SYMBOLS = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT",
    "bnb": "BNBUSDT", "doge": "DOGEUSDT", "xrp": "XRPUSDT"
}

class CorrelationTracker:
    def __init__(self):
        self.price_buffers: dict[str, deque] = {}  # 5-min rolling prices
        self.correlation_matrix: dict[tuple, float] = {}
        self.lead_lag: dict[tuple, float] = {}  # seconds of lead

    def update_price(self, asset: str, price: float, ts: float):
        self.price_buffers[asset].append((ts, price))
        self._recompute_correlations()

    def _recompute_correlations(self):
        """Pearson correlation on 1-min returns, rolling 2h window."""
        ...

    def detect_lead_lag(self, leader: str, follower: str) -> float:
        """Cross-correlation to find optimal lag in seconds."""
        ...

    def generate_signal(self) -> dict | None:
        """
        If BTC moved significantly in last 60s and ETH hasn't yet,
        signal ETH direction = BTC direction with lag adjustment.
        """
        ...

    def write_signals(self):
        """Write to data/cross_asset_signals.json for bot consumption."""
        ...
```

### Service File
```ini
# deploy/multi-asset-arb.service
[Service]
ExecStart=/usr/bin/python3 bot/multi_asset_arb.py --continuous
```

### Integration Point
The 5-min maker bot reads `data/cross_asset_signals.json` at each window. If a cross-asset signal exists for the current asset+direction with confidence > 0.7, it boosts the edge_score (or reduces delta threshold).

### Success Criteria
- Identify at least 3 lead-lag pairs with > 0.6 correlation
- Generate actionable signals for > 5% of windows
- Track signal accuracy independently

---

## Instance 3: Dynamic Binance Delta Calibration

**File:** `bot/delta_calibrator.py` (NEW)
**Modifies:** `config/autoresearch_overrides.json`
**Isolation:** worktree

### Objective
The delta threshold (currently 0.004 max, ~0.0001 min) is static but BTC volatility changes dramatically throughout the day. During Asian session, deltas are tiny. During US open, they're large. A static threshold over-filters during quiet times and under-filters during volatile times.

### Implementation

```python
# delta_calibrator.py

class DeltaCalibrator:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.vol_windows: deque = deque(maxlen=288)  # 24h of 5-min windows

    def compute_rolling_volatility(self, hours=4) -> float:
        """Realized volatility from Binance ticks over last N hours."""
        ...

    def optimal_delta_threshold(self, rolling_vol: float) -> tuple[float, float]:
        """
        Map rolling vol to delta bounds:
        - Low vol (< 0.001): min_delta=0.00005, max_delta=0.002
        - Med vol (0.001-0.003): min_delta=0.0001, max_delta=0.004
        - High vol (> 0.003): min_delta=0.0003, max_delta=0.008
        """
        ...

    def calibrate_and_write(self):
        """Write optimal bounds to env override file."""
        vol = self.compute_rolling_volatility()
        min_d, max_d = self.optimal_delta_threshold(vol)
        # Write to config/autoresearch_overrides.json
        ...
```

### Cron Integration
```
# Run every 30 min, staggered from autoresearch
20,50 * * * * flock -n /tmp/elastifund_delta_cal.lock python3 bot/delta_calibrator.py
```

### Key Insight
skip_delta_too_large (199 windows = 22%) is the #1 blocker. If we widen max_delta during volatile periods, we capture more fills. But only if the fills at wider deltas are still profitable — use counterfactual PnL from existing data to validate.

### Success Criteria
- skip_delta_too_large drops by 30%+ without increasing loss rate
- Delta bounds auto-adjust at least 3x/day
- Counterfactual validation before any live deployment

---

## Instance 4: Auto-Scaling Capital Stage Gate

**File:** `bot/auto_stage_gate.py` (NEW)
**Modifies:** `state/btc5_capital_stage.env`
**Isolation:** worktree

### Objective
Automated capital scaling based on proven performance. Currently we manually set STAGE1/2/3 caps. This should be automatic:
- Hit 20 fills with >60% WR and positive PnL → scale from $500 to $750
- Hit 40 fills with >65% WR → scale to $1000
- Any 5-fill losing streak → scale back 50%
- CLOB balance < 50% of bankroll → emergency halt

### Implementation

```python
# auto_stage_gate.py

SCALE_RULES = [
    {"min_fills": 20, "min_wr": 0.60, "min_pnl": 0.0, "max_trade": 750},
    {"min_fills": 40, "min_wr": 0.65, "min_pnl": 10.0, "max_trade": 1000},
    {"min_fills": 80, "min_wr": 0.65, "min_pnl": 50.0, "max_trade": 1500},
]

SCALE_DOWN_RULES = [
    {"consecutive_losses": 5, "scale_factor": 0.50},
    {"trailing_20_wr_below": 0.45, "scale_factor": 0.50},
    {"balance_below_pct": 0.50, "action": "halt"},
]

class AutoStageGate:
    def __init__(self, db_paths: list[str], env_path: str):
        ...

    def evaluate(self) -> dict:
        """Check all rules against current performance."""
        fills = self._aggregate_fills()  # across all 6 DBs
        wr = self._compute_win_rate(fills)
        pnl = self._compute_pnl(fills)
        consecutive_losses = self._consecutive_losses(fills)

        # Check scale-up
        for rule in SCALE_RULES:
            if len(fills) >= rule["min_fills"] and wr >= rule["min_wr"] and pnl >= rule["min_pnl"]:
                new_max = rule["max_trade"]

        # Check scale-down
        for rule in SCALE_DOWN_RULES:
            if consecutive_losses >= rule.get("consecutive_losses", 999):
                new_max = int(current_max * rule["scale_factor"])
            ...

        return {"action": "scale_up/down/hold", "new_max_trade": new_max}

    def apply(self, decision: dict):
        """Write to capital_stage.env."""
        ...
```

### Cron Integration
```
# Run every hour, after autoresearch
30 * * * * flock -n /tmp/elastifund_stage_gate.lock python3 bot/auto_stage_gate.py
```

### Safety Rails
- NEVER exceed bankroll * risk_fraction (currently ~$430)
- NEVER scale up more than 2x in a single step
- Emergency halt if balance drops below 50% of bankroll
- All changes logged to data/stage_gate_log.json

### Success Criteria
- Auto-scales at least once within 48h of deployment
- No manual intervention needed for capital allocation
- Emergency halt triggers correctly (test with simulated balance drop)

---

## Instance 5: Overnight Health Monitor & Alert System

**File:** `scripts/health_monitor.py` (NEW)
**Isolation:** worktree

### Objective
While John sleeps, the system needs to self-monitor and alert on anomalies. Write to a log file that can be checked in the morning.

### Implementation

```python
# health_monitor.py — runs every 15 min via cron

CHECKS = [
    ("bot_alive", check_all_bots_running),        # systemctl is-active
    ("fills_flowing", check_recent_fills),          # any fill in last 2h?
    ("balance_stable", check_balance_not_dropping), # no >20% drop
    ("no_stuck_orders", check_no_old_open_orders),  # orders not stuck >10min
    ("db_growing", check_db_row_count_increasing),  # windows being recorded
    ("cron_running", check_cron_jobs_recent),        # backfill, compound ran
]

def run_health_check() -> dict:
    results = {}
    for name, check_fn in CHECKS:
        try:
            ok, detail = check_fn()
            results[name] = {"ok": ok, "detail": detail}
        except Exception as e:
            results[name] = {"ok": False, "detail": str(e)}

    # Write to data/health_report.json
    ...

    # If any check fails, write ALERT to /tmp/elastifund_alerts.log
    failures = [k for k, v in results.items() if not v["ok"]]
    if failures:
        alert(f"HEALTH CHECK FAILURES: {failures}")

    return results
```

### Cron
```
*/15 * * * * python3 scripts/health_monitor.py >> /tmp/health_monitor.log 2>&1
```

---

## Execution Priority

| Instance | Name | Impact | Risk | Run Order |
|----------|------|--------|------|-----------|
| 3 | Delta Calibrator | HIGH — fixes #1 blocker | LOW | First |
| 5 | Health Monitor | MEDIUM — overnight safety | NONE | First (parallel) |
| 1 | Pricing Evolution | HIGH — continuous improvement | LOW | Second |
| 4 | Auto Stage Gate | MEDIUM — capital scaling | MEDIUM | Third |
| 2 | Multi-Asset Arb | MEDIUM — new signal source | LOW | Last |

## File Inventory for Codex

```
NEW FILES:
  bot/pricing_evolution.py        — Instance 1
  bot/multi_asset_arb.py          — Instance 2
  bot/delta_calibrator.py         — Instance 3
  bot/auto_stage_gate.py          — Instance 4
  scripts/health_monitor.py       — Instance 5

MODIFIED FILES:
  bot/autoresearch_loop.py        — Instance 1 integration
  config/autoresearch_overrides.json — Instances 1, 3 write target

SERVICE FILES (if needed):
  deploy/multi-asset-arb.service  — Instance 2

CRON ADDITIONS:
  */15 health_monitor
  20,50 delta_calibrator
  30 auto_stage_gate
```

---

*Generated by JJ — 2026-03-16 01:40 UTC*
