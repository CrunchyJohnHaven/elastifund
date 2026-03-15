# Live Trading Scorecard v1 — Implementation Spec

**Version:** 1.0.0
**Date:** 2026-03-05
**Purpose:** Engineer-ready spec for building live trading dashboard endpoints + Telegram summaries. Covers daily/weekly KPIs, edge integrity, risk metrics, and reporting templates.

---

## 1. Data Model Prerequisites

All metrics below assume the following data sources exist and are queryable:

| Source | Location | Fields Needed |
|--------|----------|---------------|
| `bot.db` (SQLite) | VPS `/bot.db` | Orders, Fills, Positions, RiskEvent tables |
| `paper_trades.json` | VPS root | Legacy paper trades (migration needed) |
| `metrics_history.json` | VPS root | Cycle-level metrics snapshots |
| `strategy_state.json` | VPS root | Tuning parameters per cycle |
| Gamma API | `https://gamma-api.polymarket.com` | Market resolution status, current prices |

### New Tables Required

```sql
-- Daily snapshot table (populated by end-of-day cron or on-demand)
CREATE TABLE daily_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE NOT NULL UNIQUE,
    starting_bankroll REAL NOT NULL,
    ending_bankroll REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    gross_exposure REAL NOT NULL DEFAULT 0,
    open_position_count INTEGER NOT NULL DEFAULT 0,
    trades_opened INTEGER NOT NULL DEFAULT 0,
    trades_closed INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    fees_paid REAL NOT NULL DEFAULT 0,
    maker_fills INTEGER NOT NULL DEFAULT 0,
    taker_fills INTEGER NOT NULL DEFAULT 0,
    avg_time_to_resolution_hours REAL,
    kill_events INTEGER NOT NULL DEFAULT 0,
    max_drawdown_pct REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-trade calibration log (one row per signal, whether traded or not)
CREATE TABLE calibration_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    category TEXT,
    side TEXT CHECK(side IN ('YES', 'NO')),
    claude_raw_estimate REAL NOT NULL,
    calibrated_estimate REAL NOT NULL,
    market_price_at_signal REAL NOT NULL,
    edge_at_signal REAL NOT NULL,
    kelly_fraction REAL,
    position_size_usd REAL,
    traded BOOLEAN NOT NULL DEFAULT 0,
    resolution_outcome INTEGER, -- 1=YES, 0=NO, NULL=pending
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Weekly rollup (computed from daily_snapshot)
CREATE TABLE weekly_rollup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    starting_bankroll REAL NOT NULL,
    ending_bankroll REAL NOT NULL,
    total_realized_pnl REAL NOT NULL,
    total_unrealized_pnl REAL NOT NULL,
    total_trades_opened INTEGER NOT NULL,
    total_trades_closed INTEGER NOT NULL,
    win_rate REAL,
    avg_edge_predicted REAL,
    avg_edge_realized REAL,
    total_fees REAL NOT NULL,
    max_drawdown_pct REAL NOT NULL,
    kill_events INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 2. Daily KPIs (Refresh: every cycle + end-of-day snapshot)

### 2.1 P&L Metrics

| Metric | Definition | Endpoint | Computation |
|--------|-----------|----------|-------------|
| **Realized P&L (daily)** | Sum of (payout - cost) for trades resolved today | `GET /metrics/daily` | `SUM(payout - cost) WHERE resolved_date = today` |
| **Unrealized P&L** | Mark-to-market of open positions vs current Gamma price | `GET /metrics/daily` | `SUM((current_gamma_price - entry_price) * shares) for open positions` |
| **Cumulative Realized P&L** | All-time realized | `GET /metrics/cumulative` | Running sum from first trade |
| **Bankroll** | Available cash + unrealized value of open positions | `GET /metrics/daily` | `cash_balance + unrealized_value` |
| **Net P&L (after fees)** | Realized P&L minus all fees and infra cost | `GET /metrics/daily` | `realized_pnl - fees_paid - (infra_daily_cost)` |

### 2.2 Exposure & Position Metrics

| Metric | Definition | Target |
|--------|-----------|--------|
| **Gross Exposure %** | Total USD deployed / bankroll | Should stay < 90% |
| **Open Positions (total)** | Count of unresolved trades | — |
| **Open Positions by Category** | Breakdown: politics, weather, economic, geopolitical, unknown | — |
| **Largest Single Position %** | Max position USD / bankroll | Alert if > 15% |
| **Category Concentration %** | Max category exposure / total exposure | Alert if > 40% |

### 2.3 Execution Metrics

| Metric | Definition | Why It Matters |
|--------|-----------|---------------|
| **Fill Rate** | Fills / orders attempted | Low fill rate = phantom P&L |
| **Maker vs Taker Ratio** | maker_fills / total_fills | Maker saves fees; target >50% maker |
| **Avg Slippage (bps)** | (fill_price - signal_price) / signal_price × 10000 | Backtest assumes 0 slippage |
| **Fee Drag (daily)** | Total taker fees paid today | `SUM(p*(1-p)*r * size)` for taker fills |
| **Fee Drag % of Gross P&L** | fees / gross_realized_pnl | Alert if > 30% |

### 2.4 Timing Metrics

| Metric | Definition | Why It Matters |
|--------|-----------|---------------|
| **Avg Time-to-Resolution** | Mean hours from entry to market resolution, for trades closed today | Capital velocity |
| **Median Time-to-Resolution** | Median of same | Less sensitive to outliers |
| **Capital-Weighted TTR** | Weighted by position size | Shows where capital is stuck |
| **Positions > 30 days open** | Count + total exposure | Stale capital drag |

---

## 3. Edge Integrity Metrics (The Most Important Section)

These metrics answer: "Is our predicted edge real, or are we fooling ourselves?"

### 3.1 Predicted vs Realized Edge

| Metric | Definition | Computation |
|--------|-----------|-------------|
| **Avg Predicted Edge (daily)** | Mean \|calibrated_estimate - market_price\| at entry, for trades opened today | `AVG(edge_at_signal) WHERE traded=1 AND date=today` |
| **Avg Realized Edge (daily)** | Mean (payout_per_dollar - 1) for trades resolved today | `AVG((resolution_payout / cost) - 1) WHERE resolved_date = today` |
| **Edge Decay** | Predicted edge minus realized edge | Positive = overestimating edge |
| **Edge Decay by Category** | Same, grouped by category | Identifies which categories are lying |
| **Edge Decay by Side** | Same, grouped by YES/NO | Detects if NO-bias edge is eroding |

### 3.2 Calibration Integrity

| Metric | Definition | Alert Threshold |
|--------|-----------|----------------|
| **Rolling ECE (50-trade window)** | Expected Calibration Error over last 50 resolved trades | > 0.10 = recalibrate |
| **Brier Score (rolling 50)** | Brier score over last 50 resolved | > 0.24 = warn, > 0.25 = kill non-essential |
| **Reliability Curve R²** | R² of calibrated_estimate vs actual_outcome (binned) | < 0.70 = recalibrate |
| **Overconfidence Index** | Mean(calibrated_estimate - actual_rate) for estimates > 0.60 | > 0.10 = throttle YES-side |

### 3.3 Win Rate Monitoring

| Metric | Window | Backtest Baseline | Alert |
|--------|--------|-------------------|-------|
| **Overall Win Rate** | Rolling 50 trades | 64.9% | < 55% = review, < 50% = throttle |
| **YES Win Rate** | Rolling 30 YES trades | 55.8% | < 45% = pause YES trades |
| **NO Win Rate** | Rolling 30 NO trades | 76.2% | < 65% = review NO sizing |
| **Win Rate by Category** | Rolling 20 per category | Varies | < 50% in any category = pause that category |

---

## 4. Risk Metrics

### 4.1 Drawdown

| Metric | Definition | Threshold |
|--------|-----------|-----------|
| **Current Drawdown %** | (peak_bankroll - current_bankroll) / peak_bankroll | — |
| **Max Drawdown (trailing 7d)** | Maximum drawdown in last 7 calendar days | > 20% = half sizing |
| **Max Drawdown (all-time)** | Maximum drawdown since inception | > 30% = kill switch |
| **Drawdown Duration** | Days since peak bankroll | > 14 days = strategy review |

### 4.2 Kill Switch Events

| Event | Trigger | Action |
|-------|---------|--------|
| **Daily Loss Limit** | Realized loss > MAX_DAILY_DRAWDOWN_USD ($50) | Halt all new trades for 24h |
| **Weekly Loss Limit** | Weekly realized loss > 15% of starting-week bankroll | Half sizing for remainder of week |
| **Consecutive Losses** | 8+ consecutive losses | Pause 6 hours, log for review |
| **Edge Collapse** | Rolling 50-trade win rate < 50% | Halt new trades, alert owner |
| **Calibration Drift** | Rolling ECE > 0.15 | Reduce position sizes by 50% |

### 4.3 Concentration & Correlation

| Metric | Definition | Threshold |
|--------|-----------|-----------|
| **Max Single-Position %** | Largest position / bankroll | > 15% = alert |
| **Max Category Exposure %** | Largest category / total exposure | > 40% = halt new in that category |
| **Correlated Positions Count** | Positions in same category with same directional bet | > 5 = apply 50% haircut on new entries |
| **Effective Diversification Ratio** | Unique categories with open positions / total categories | < 0.3 = warn (too concentrated) |

---

## 5. API Endpoints Spec

All endpoints extend the existing FastAPI dashboard at `src/app/dashboard.py`.

### 5.1 New Endpoints

```
GET /metrics/daily?date=YYYY-MM-DD
  Returns: DailySnapshot object (all Section 2 metrics)
  Default: today

GET /metrics/weekly?week_start=YYYY-MM-DD
  Returns: WeeklyRollup object (aggregated from daily snapshots)
  Default: current week

GET /metrics/edge?window=50
  Returns: EdgeIntegrity object (Section 3 metrics)
  Params: window (int, default 50) = rolling trade count

GET /metrics/calibration?window=100
  Returns: CalibrationHealth object (ECE, Brier, reliability curve data, overconfidence index)

GET /metrics/risk
  Returns: RiskDashboard object (all Section 4 metrics)
  Already partially exists — extend with drawdown, concentration, correlation

GET /metrics/scorecard
  Returns: Full scorecard combining daily + edge + risk (single call for Telegram)

POST /metrics/snapshot
  Triggers: Manual daily snapshot creation (also runs via cron at 23:59 UTC)
```

### 5.2 Response Schema (Scorecard)

```json
{
  "date": "2026-03-05",
  "bankroll": {
    "starting": 75.00,
    "current": 82.50,
    "change_pct": 10.0
  },
  "pnl": {
    "realized_today": 3.20,
    "unrealized": 4.30,
    "cumulative_realized": 15.80,
    "fees_today": 0.45,
    "net_today": 2.75
  },
  "positions": {
    "open_count": 28,
    "by_category": {"politics": 12, "weather": 3, "economic": 8, "unknown": 5},
    "gross_exposure_pct": 74.5,
    "largest_position_pct": 8.2
  },
  "execution": {
    "fill_rate": 0.94,
    "maker_ratio": 0.35,
    "avg_slippage_bps": 12,
    "fee_drag_pct": 18.2
  },
  "edge": {
    "predicted_avg": 0.127,
    "realized_avg": 0.089,
    "decay": 0.038,
    "decay_by_side": {"YES": 0.062, "NO": 0.018},
    "rolling_win_rate": 0.63,
    "rolling_yes_wr": 0.54,
    "rolling_no_wr": 0.74
  },
  "calibration": {
    "rolling_ece": 0.082,
    "rolling_brier": 0.221,
    "overconfidence_index": 0.08
  },
  "risk": {
    "current_drawdown_pct": 3.2,
    "max_drawdown_7d_pct": 5.1,
    "max_drawdown_alltime_pct": 5.1,
    "kill_events_today": 0,
    "category_concentration_pct": 34.2,
    "correlated_positions": 3
  },
  "timing": {
    "avg_ttr_hours": 142,
    "median_ttr_hours": 96,
    "positions_over_30d": 2
  }
}
```

---

## 6. Telegram Summary Format

### 6.1 Daily Digest (send at 00:00 UTC)

```
📊 DAILY SCORECARD — {date}

💰 Bankroll: ${current} ({change_pct:+.1f}%)
   Realized: ${realized_today:+.2f} | Unrealized: ${unrealized:+.2f}
   Fees: -${fees_today:.2f} | Net: ${net_today:+.2f}

📈 Edge Health
   Win Rate (50): {rolling_wr:.1%} (base: 64.9%)
   Predicted Edge: {pred:.1%} → Realized: {real:.1%} (decay: {decay:.1%})
   YES WR: {yes_wr:.1%} | NO WR: {no_wr:.1%}

📐 Calibration
   ECE: {ece:.3f} | Brier: {brier:.3f}

⚠️ Risk
   Drawdown: {dd_pct:.1f}% | Max 7d: {max_dd_7d:.1f}%
   Kill events: {kills}

📦 Positions: {open} open ({exposure_pct:.0f}% deployed)
   {cat_breakdown}
   Avg TTR: {ttr_hours:.0f}h | Stale (>30d): {stale}

{alerts_section}
```

### 6.2 Alert Messages (send immediately)

| Alert | Message |
|-------|---------|
| Kill switch triggered | `🚨 KILL SWITCH: {reason}. All trading halted.` |
| Win rate below 55% | `⚠️ Win rate {wr:.1%} (50-trade) below 55% threshold. Review.` |
| Calibration drift | `⚠️ ECE {ece:.3f} > 0.10. Calibration drift detected. Sizes halved.` |
| Drawdown > 20% | `🔴 Drawdown {dd:.1f}%. Sizing halved.` |
| 8 consecutive losses | `⚠️ 8 consecutive losses. Paused 6h.` |

---

## 7. Weekly KPI Rollup

Computed from `daily_snapshot` table every Sunday at 23:59 UTC.

| Metric | Computation |
|--------|-------------|
| Weekly Realized P&L | SUM(realized_pnl) for the week |
| Weekly Unrealized Delta | ending_unrealized(Sunday) - ending_unrealized(prev Sunday) |
| Weekly Net Return % | (ending_bankroll - starting_bankroll) / starting_bankroll |
| Trades Opened / Closed | SUM of daily counts |
| Weekly Win Rate | total_wins / total_closed |
| Avg Daily Fee Drag % | AVG(fee_drag_pct) |
| Predicted vs Realized Edge (weekly) | AVG(predicted_edge) vs AVG(realized_edge) |
| Max Drawdown (weekly) | MAX(daily max_drawdown_pct) |
| Calibration Trend | ECE this week vs last week (direction arrow) |
| Capital Velocity | total_resolved_usd / avg_bankroll (higher = capital turning faster) |

---

## 8. Private External Reporting Boundary

Private investor and legal materials are intentionally kept outside this repo.

This spec governs live operational scorecards only. If you later prepare external reporting artifacts, treat them as a separate private workflow and do not route routine coding work toward them from this repo.

---

*This spec is complete. An engineer can implement the schema, endpoints, and Telegram integration directly from this document.*
