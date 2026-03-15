# Edge Promotion Acceptance Criteria

**Version:** 1.0.0
**Last Updated:** 2026-03-05
**Owner:** John Bradley
**Purpose:** Define exact, code-testable acceptance criteria for promoting an edge through IDEA → BACKTEST → PAPER → SHADOW → LIVE. Every gate is a boolean function; every kill-switch is a real-time check.

---

## 1. Metrics Definitions

All metrics are computed per-edge (single strategy variant on a single market category or market set). Where noted, metrics also roll up to portfolio level for kill-switch evaluation.

### 1.1 EV Net of Fees

```
ev_net = (win_rate × avg_win) - ((1 - win_rate) × avg_loss) - avg_fee_per_trade

where:
  avg_win        = mean(payout - entry_cost)  for winning trades
  avg_loss       = mean(entry_cost)           for losing trades (binary → total loss)
  avg_fee_per_trade = mean(entry_price × (1 - entry_price) × fee_rate)
  fee_rate       = Polymarket taker fee rate (currently variable by tier)

# For binary prediction markets specifically:
#   Buying YES at price p:  cost = p,  payout_win = 1.0,  payout_lose = 0.0
#   Buying NO  at price p:  cost = (1-p), payout_win = 1.0, payout_lose = 0.0
#   Taker fee = p * (1-p) * r  (worst at p=0.50)
```

**Unit:** USD per trade.
**Minimum resolution:** Must be computable from `paper_trades.json` and `bot.db` fills table.

### 1.2 Drawdown

```
max_drawdown = max over t of (peak_equity[t] - equity[t]) / peak_equity[t]

where:
  equity[t]      = cash + sum(mark_to_market of open positions at time t)
  peak_equity[t] = max(equity[0..t])
```

**Rolling drawdown** (kill-switch input): computed on a 24h, 7d, and 30d trailing window.

**Unit:** Fraction (0.0–1.0). Display as percentage.

### 1.3 Risk of Ruin Proxy

Estimated probability of drawdown exceeding a fatal threshold (default: 50% of bankroll) within the next N trades.

```
risk_of_ruin ≈ ((1 - edge) / (1 + edge)) ^ (bankroll / unit_bet)

where:
  edge = ev_net / avg_bet_size
  unit_bet = current position size (flat or Kelly-derived)

# Monte Carlo alternative (preferred when N > 100 closed trades):
#   Simulate 10,000 paths of length 500 trades using observed win_rate, avg_win, avg_loss.
#   risk_of_ruin = count(paths where equity < 0.5 × starting) / 10,000
```

**Unit:** Probability (0.0–1.0).

### 1.4 Turnover + Capacity

```
turnover_daily    = count(trades executed per calendar day)
turnover_monthly  = count(trades executed per 30d window)
capital_velocity  = sum(trade_size) / avg_equity  per period
avg_hold_time     = mean(resolution_time - entry_time) for closed trades
capacity_ceiling  = min(market_liquidity / 10, max_position_usd)
                    # Never take >10% of market depth
```

**Unit:** Trades/day, days (hold time), USD (capacity).

### 1.5 Calibration Error (LLM Forecasts)

```
brier_score = mean((forecast_prob - outcome)^2)    # outcome ∈ {0, 1}
ECE         = sum over bins of (bin_weight × |bin_avg_forecast - bin_avg_outcome|)

# Binning: 10 equal-width bins [0–10%, 10–20%, ..., 90–100%]
# Per COMMAND_NODE calibration table format

calibration_error_by_bin[b] = avg_forecast[b] - avg_outcome[b]
max_bin_error               = max(|calibration_error_by_bin[b]|) for all bins with n >= 10
```

**Unit:** Brier score (0.0–1.0, lower is better). ECE (0.0–1.0, lower is better).
**Baseline:** Brier 0.25 = random. Current system: 0.239.

---

## 2. Stage Gates

Each gate is a boolean predicate. An edge **cannot** be promoted unless ALL conditions for the target stage are met. Automated in the `edge_backlog` CLI: `edge promote <id>` runs the gate checks and blocks on failure.

Operator evidence for these gates should reconcile with:
- `FAST_TRADE_EDGE_ANALYSIS.md` for human-readable current verdicts
- `reports/run_<timestamp>_metrics.json` and `reports/run_<timestamp>_summary.md` for per-run metrics
- `reports/remote_cycle_status.json` and `reports/remote_service_status.json` for live posture machine truth

### 2.1 IDEA → BACKTEST

**Purpose:** Filter noise. Only spend Claude API credits on edges with a plausible thesis.

| # | Criterion | Threshold | How to Test |
|---|-----------|-----------|-------------|
| 1 | Hypothesis documented | Non-empty `hypothesis` field | `len(edge.hypothesis) > 50` |
| 2 | Category assigned | Must have at least one tag from approved list | `edge.tags ∩ APPROVED_CATEGORIES != ∅` |
| 3 | Category not blacklisted | Not in Priority 0 (Crypto, Sports, Fed Rates) | `edge.tags ∩ BLACKLIST == ∅` |
| 4 | Estimated market count | ≥ 20 historical markets available for backtest | Query Gamma API resolved endpoint, count matches |
| 5 | No duplicate | No existing edge with cosine similarity > 0.85 on hypothesis text | Embed + compare against active edges |

**Approved categories:** `politics`, `weather`, `economic`, `geopolitical`, `unknown`, `resolution-rule`, `cross-platform-arb`, `market-making`.
**Blacklisted:** `crypto`, `sports`, `fed-rates`.

### 2.2 BACKTEST → PAPER

**Purpose:** Prove the edge exists in historical data, net of fees, with acceptable variance.

| # | Criterion | Threshold | How to Test |
|---|-----------|-----------|-------------|
| 1 | Sample size | ≥ 50 resolved markets backtested | `len(backtest_results) >= 50` |
| 2 | Win rate | > 55% (all trades) or > 65% (NO-only subset) | Computed from backtest engine output |
| 3 | EV net of fees | > $0.00 per trade | `ev_net > 0` over full sample |
| 4 | EV net of fees (pessimistic) | > $0.00 at 2× current fee rate | Re-run P&L with `fee_rate *= 2` |
| 5 | Brier score | < 0.24 (must beat current system baseline) | `brier_score < 0.24` |
| 6 | Max calibration bin error | < 25% for bins with n ≥ 10 | `max_bin_error < 0.25` |
| 7 | Monte Carlo ruin risk | < 5% at quarter-Kelly sizing | Run 10K-path MC, `P(50% drawdown) < 0.05` |
| 8 | No single-market dependency | No market contributes > 20% of total P&L | `max(market_pnl) / total_pnl < 0.20` |
| 9 | Temporal stability | Positive EV in both first-half and second-half of sample | Split-half validation passes |
| 10 | Edge documented | Experiment recorded with results in `edge_backlog` | `len(edge.experiments) >= 1 and any(e.status == 'completed')` |

### 2.3 PAPER → SHADOW (Live Shadow)

**Purpose:** Confirm the edge survives real-time execution mechanics (latency, fill rates, slippage) without risking capital.

| # | Criterion | Threshold | How to Test |
|---|-----------|-----------|-------------|
| 1 | Paper trading duration | ≥ 14 calendar days | `(now - paper_start_date).days >= 14` |
| 2 | Paper trade count | ≥ 30 closed (resolved) trades | `count(closed_paper_trades) >= 30` |
| 3 | Paper EV net of simulated fees | > $0.00 per trade | Same formula as §1.1, on paper trade data |
| 4 | Paper win rate | Within 10pp of backtest win rate | `abs(paper_wr - backtest_wr) < 0.10` |
| 5 | Signal generation rate | ≥ 1 signal per day on average | `total_signals / trading_days >= 1.0` |
| 6 | No extended signal drought | No gap > 72h without a signal | `max(signal_gap_hours) < 72` |
| 7 | Calibration drift | Brier score < backtest Brier + 0.02 | `paper_brier < backtest_brier + 0.02` |
| 8 | System uptime | ≥ 95% of scan cycles completed | `completed_cycles / expected_cycles >= 0.95` |
| 9 | No kill-switch triggers | Zero kill-switch events during paper period | `count(kill_switch_events) == 0` |
| 10 | Drawdown acceptable | Max paper drawdown < 20% | `max_drawdown < 0.20` |

### 2.4 SHADOW → LIVE

**Purpose:** Final gate. Shadow = real orders at minimum size ($2) to measure actual execution quality. Only promote when execution metrics confirm the edge persists after slippage and fill-rate friction.

| # | Criterion | Threshold | How to Test |
|---|-----------|-----------|-------------|
| 1 | Shadow duration | ≥ 7 calendar days | `(now - shadow_start_date).days >= 7` |
| 2 | Shadow trade count | ≥ 20 closed trades with real fills | `count(closed_shadow_trades) >= 20` |
| 3 | Fill rate | ≥ 80% of orders filled within 5 minutes | `filled_within_5min / total_orders >= 0.80` |
| 4 | Slippage | Mean slippage < 1.5% of edge | `mean_slippage < 0.015 × mean_edge` |
| 5 | Realized EV | > $0.00 per trade (real P&L) | Computed from `bot.db` fills + resolutions |
| 6 | Paper-to-shadow P&L ratio | Shadow P&L/trade ≥ 60% of paper P&L/trade | `shadow_ev / paper_ev >= 0.60` |
| 7 | Execution latency | 95th percentile order-to-fill < 30 seconds | `p95(fill_time - order_time) < 30s` |
| 8 | No kill-switch triggers | Zero kill-switch events during shadow | `count(kill_switch_events) == 0` |
| 9 | Risk-of-ruin at target sizing | < 2% at planned Kelly fraction | MC simulation at target position size |
| 10 | Manual sign-off | Human review checkbox | `edge.history` contains `HUMAN_APPROVED_LIVE` entry |

**IMPORTANT:** Gate 10 is non-negotiable. No edge goes live without a human reviewing the full evidence package and explicitly approving. The `promote` function in `edge_backlog/models.py` currently blocks `LIVE` promotion — this gate is the unlock condition.

---

## 3. Kill-Switch Criteria

Kill-switches are evaluated **every scan cycle** (300s) on all PAPER, SHADOW, and LIVE edges. When triggered, the system halts new orders for the affected edge immediately and sends a Telegram alert. Existing positions are held to resolution (binary markets cannot be partially exited without selling on the order book).

### 3.1 Slippage Blowout

```python
# Trigger: realized slippage exceeds tolerable fraction of edge
slippage_ratio = mean_slippage_last_20_trades / mean_edge_last_20_trades

KILL if slippage_ratio > 0.30          # Slippage eating >30% of edge
WARN if slippage_ratio > 0.15          # Early warning at 15%
```

**Evaluation window:** Rolling 20 trades.
**Recovery:** Manual review required. Re-enable only after root-cause analysis (liquidity dried up, fee change, bot competition).

### 3.2 Fill-Rate Collapse

```python
# Trigger: orders not getting filled → strategy becoming non-executable
fill_rate_24h = filled_orders_24h / submitted_orders_24h

KILL if fill_rate_24h < 0.50           # <50% fills in 24h
WARN if fill_rate_24h < 0.70           # Early warning at 70%
```

**Evaluation window:** Trailing 24 hours.
**Recovery:** Check Polymarket API status, order book depth, gas prices. May require switching from taker to limit (maker) orders.

### 3.3 Correlation Spike

```python
# Trigger: too many positions in same category resolve same direction → hidden concentration
# Computed on resolved trades in trailing 30d window

category_counts = count(open_positions grouped by category_tag)
max_category_pct = max(category_counts) / sum(category_counts)

KILL if max_category_pct > 0.60        # >60% of positions in one category
WARN if max_category_pct > 0.40        # Early warning at 40%

# Additionally: if >3 positions in same category, apply 50% Kelly haircut (per COMMAND_NODE)
# AND check pairwise outcome correlation on last 50 resolved trades:
outcome_corr = pearsonr(outcomes_category_A, outcomes_category_B)
WARN if any |outcome_corr| > 0.50 on > 10 paired observations
```

**Evaluation window:** 30-day rolling for category concentration; per-resolution for correlation.

### 3.4 Dispute / Time-to-Cash Anomalies

```python
# Trigger: markets taking too long to resolve or resolving via dispute (unexpected outcome)

avg_hold_time_30d = mean(resolution_time - entry_time) for trades closed in last 30d
disputed_rate_30d = count(disputed_resolutions) / count(resolutions)
capital_locked_pct = sum(open_position_cost) / total_equity

KILL if disputed_rate_30d > 0.10       # >10% of resolutions disputed
KILL if capital_locked_pct > 0.90      # >90% of capital locked in open positions
WARN if avg_hold_time_30d > 30 days    # Avg hold time exceeding 30 days
WARN if capital_locked_pct > 0.75      # >75% capital locked
```

**Recovery for disputes:** Review `resolution_rule_edge_playbook.md` scoring criteria. If dispute rate spikes, the market category may have ambiguous resolution criteria; demote the edge back to PAPER for re-evaluation.

### 3.5 Drawdown Breach (Portfolio-Level)

```python
# In addition to per-edge drawdown checks, portfolio-level hard stop

KILL_ALL if portfolio_drawdown_24h > 0.15    # 15% portfolio drawdown in 24h
KILL_ALL if portfolio_drawdown_7d  > 0.25    # 25% portfolio drawdown in 7d
WARN     if portfolio_drawdown_24h > 0.08    # 8% in 24h → reduce position sizes by 50%
```

**This is the "pull the plug" switch.** Maps to the existing `/kill` endpoint on the FastAPI dashboard.

### 3.6 Calibration Degradation (LLM-Specific)

```python
# Trigger: Claude's forecast quality degrading over time (model updates, market regime change)

rolling_brier_50 = brier_score(last 50 resolved forecasts)
baseline_brier   = stored backtest brier score

KILL if rolling_brier_50 > 0.25            # Worse than random
WARN if rolling_brier_50 > baseline_brier + 0.03  # Drifting 3pp above baseline
```

**Recovery:** Re-run calibration on recent data. May require re-fitting temperature scaling or switching Claude model version.

---

## 4. Audit Log Schema

Every event in the system produces a structured JSON log entry. Logs are append-only and written to both `bot.db` (SQLite `audit_log` table) and a daily JSONL file (`logs/audit_YYYY-MM-DD.jsonl`).

### 4.1 Core Fields (Present on Every Entry)

```json
{
  "event_id":    "uuid-v4",
  "timestamp":   "2026-03-05T14:32:01.123Z",
  "event_type":  "TRADE_OPEN | TRADE_CLOSE | GATE_CHECK | GATE_PASS | GATE_FAIL | KILL_TRIGGER | KILL_WARN | PROMOTE | DEMOTE | CALIBRATION | SYSTEM | MANUAL_OVERRIDE",
  "edge_id":     "abc123",
  "edge_status": "IDEA | BACKTEST | PAPER | SHADOW | LIVE",
  "severity":    "INFO | WARN | CRITICAL",
  "actor":       "bot | human | scheduler",
  "message":     "Human-readable description",
  "data":        {}
}
```

### 4.2 Event-Specific `data` Payloads

#### TRADE_OPEN
```json
{
  "market_id":        "0x...",
  "market_question":  "Will X happen by Y?",
  "token_id":         "0x...",
  "side":             "BUY_YES | BUY_NO",
  "entry_price":      0.35,
  "position_size_usd": 2.00,
  "claude_estimate":  0.22,
  "calibrated_estimate": 0.25,
  "market_price":     0.35,
  "edge_pct":         0.10,
  "fee_estimate_usd": 0.045,
  "kelly_fraction":   0.25,
  "category":         "politics",
  "order_id":         "ord_...",
  "fill_time_ms":     1200,
  "slippage_pct":     0.005
}
```

#### TRADE_CLOSE
```json
{
  "market_id":        "0x...",
  "order_id":         "ord_...",
  "outcome":          "WIN | LOSS | DISPUTED | VOIDED",
  "entry_price":      0.35,
  "resolution_price": 1.00,
  "pnl_gross_usd":    0.65,
  "fee_usd":          0.045,
  "pnl_net_usd":      0.605,
  "hold_time_hours":  72.5,
  "was_disputed":     false,
  "resolution_source": "Official AP call"
}
```

#### GATE_CHECK / GATE_PASS / GATE_FAIL
```json
{
  "from_stage":   "BACKTEST",
  "to_stage":     "PAPER",
  "criteria": [
    {"name": "sample_size",    "threshold": 50,   "actual": 87,    "passed": true},
    {"name": "win_rate",       "threshold": 0.55, "actual": 0.649, "passed": true},
    {"name": "ev_net",         "threshold": 0.00, "actual": 0.60,  "passed": true},
    {"name": "brier_score",    "threshold": 0.24, "actual": 0.239, "passed": true},
    {"name": "ruin_risk",      "threshold": 0.05, "actual": 0.00,  "passed": true},
    {"name": "temporal_stability", "threshold": true, "actual": true, "passed": true}
  ],
  "all_passed": true
}
```

#### KILL_TRIGGER / KILL_WARN
```json
{
  "kill_type":    "SLIPPAGE_BLOWOUT | FILL_RATE_COLLAPSE | CORRELATION_SPIKE | DISPUTE_ANOMALY | DRAWDOWN_BREACH | CALIBRATION_DEGRADATION",
  "threshold":    0.30,
  "actual_value": 0.35,
  "window":       "20_trades | 24h | 7d | 30d",
  "action_taken": "HALT_NEW_ORDERS | REDUCE_SIZE_50PCT | KILL_ALL | WARN_ONLY",
  "positions_affected": 5,
  "telegram_sent": true
}
```

#### PROMOTE / DEMOTE
```json
{
  "from_stage":   "PAPER",
  "to_stage":     "SHADOW",
  "gate_result":  "... (embedded GATE_CHECK payload)",
  "approved_by":  "human | auto",
  "notes":        "All criteria met. 14-day paper run, 42 closed trades, 68% win rate."
}
```

#### CALIBRATION
```json
{
  "brier_score":       0.239,
  "ece":               0.082,
  "bin_errors":        {"0-10": 0.107, "10-20": -0.03, "...": "..."},
  "sample_size":       532,
  "temperature_scale": 1.15,
  "model_version":     "claude-haiku-3-20260301"
}
```

### 4.3 SQLite Table DDL

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    event_id    TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,          -- ISO-8601 UTC
    event_type  TEXT NOT NULL,
    edge_id     TEXT,                   -- nullable for SYSTEM events
    edge_status TEXT,
    severity    TEXT NOT NULL DEFAULT 'INFO',
    actor       TEXT NOT NULL DEFAULT 'bot',
    message     TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}',  -- JSON blob
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_edge_id ON audit_log(edge_id);
CREATE INDEX idx_audit_event_type ON audit_log(event_type);
CREATE INDEX idx_audit_severity ON audit_log(severity);
```

### 4.4 Retention & Access

- **Hot storage:** SQLite `audit_log` table — last 90 days.
- **Cold storage:** Daily JSONL files in `logs/` — indefinite retention.
- **Query interface:** FastAPI endpoint `GET /logs/audit?edge_id=&event_type=&since=&until=&severity=`.
- **Telegram alerts:** CRITICAL severity events fire immediately. WARN events batch every 6 hours.

---

## 5. Implementation Checklist

Integration points with existing codebase:

1. **`edge_backlog/models.py`** — Add gate-check methods to `Edge.promote()`. Currently blocks LIVE unconditionally; replace with gate evaluation.
2. **`polymarket-bot/src/store/models.py`** — Add `AuditLog` SQLAlchemy model matching §4.3 DDL.
3. **`polymarket-bot/src/risk/`** — Implement kill-switch evaluators (§3.1–3.6) as async checks called every engine loop cycle.
4. **`polymarket-bot/src/engine/loop.py`** — Wire kill-switch checks into the main loop. Emit `KILL_TRIGGER` / `KILL_WARN` audit events.
5. **`polymarket-bot/src/app/dashboard.py`** — Add `/logs/audit` endpoint. Extend `/risk` to include current kill-switch status for all active edges.
6. **`backtest/engine.py`** — Output gate-compatible metrics (Brier, bin errors, win rate, EV net) in a structured format that the gate checker can consume.
7. **`polymarket-bot/src/telegram.py`** — Route CRITICAL audit events to Telegram immediately.

---

*This document is the acceptance-criteria source of truth for edge promotion. All thresholds are initial values derived from the 532-market backtest and current system parameters. Thresholds should be re-calibrated quarterly or after any material system change (fee structure, model version, strategy variant).*
