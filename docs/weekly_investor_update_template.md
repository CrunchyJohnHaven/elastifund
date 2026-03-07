# Predictive Alpha Fund — Weekly Investor Update

**Week of:** {week_start} to {week_end}
**Week #:** {week_number} of live trading
**Prepared by:** John Bradley

---

## Summary

{two_sentence_summary}

*Guidance: Plain English. Lead with the outcome (up/down/flat), then one sentence on why. Be conservative. Example: "The fund returned +3.2% this week on 14 resolved trades, bringing cumulative returns to +8.7% since inception. The NO-side edge continues to perform in line with backtest expectations."*

---

## Weekly Performance

| | This Week | Cumulative (Since Inception) |
|---|-----------|------------------------------|
| Starting Bankroll | ${week_start_bankroll} | ${inception_bankroll} |
| Ending Bankroll | ${week_end_bankroll} | — |
| Return | {weekly_return_pct:+.1f}% | {cum_return_pct:+.1f}% |
| Realized P&L | ${weekly_realized:+.2f} | ${cum_realized:+.2f} |
| Fees Paid | ${weekly_fees} | ${cum_fees} |
| Net Return (after fees) | {weekly_net_pct:+.1f}% | {cum_net_pct:+.1f}% |

## Trade Activity

| | This Week | Cumulative |
|---|-----------|-----------|
| Trades Opened | {opened} | {cum_opened} |
| Trades Closed | {closed} | {cum_closed} |
| Win Rate | {weekly_wr:.0%} | {cum_wr:.0%} |
| Avg Profit per Win | ${avg_win:+.2f} | — |
| Avg Loss per Loss | ${avg_loss:.2f} | — |

**Backtest comparison:** The live win rate of {cum_wr:.0%} is {comparison_text} the backtest baseline of 64.9%.

## Edge Integrity (Key Investor Metric)

This section tracks whether our predictive advantage is holding up in live markets.

| Metric | This Week | Trend | Status |
|--------|-----------|-------|--------|
| Predicted Edge | {pred_edge:.1%} | {pred_trend} | — |
| Realized Edge | {real_edge:.1%} | {real_trend} | — |
| Edge Decay | {decay:.1%} | {decay_trend} | {decay_status} |
| Calibration (ECE) | {ece:.3f} | {ece_trend} | {ece_status} |

Interpretation: {edge_interpretation}

*Example: "Predicted edge exceeds realized edge by 3.1%, which is expected — backtest conditions are idealized. The gap is narrowing week-over-week, suggesting the calibration layer is working. No action needed."*

## Risk Status

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Max Drawdown (this week) | {max_dd:.1f}% | 20% | {dd_status} |
| Max Drawdown (all-time) | {max_dd_all:.1f}% | 30% | {dd_all_status} |
| Kill Events | {kills} | 0 ideal | — |
| Position Concentration | {max_cat_pct:.0f}% in {max_cat} | <40% | {conc_status} |
| Capital Deployed | {exposure_pct:.0f}% | <90% | {exp_status} |
| Stale Positions (>30d) | {stale_count} (${stale_usd}) | — | — |

## What's Working

{whats_working}

*Guidance: 1–2 bullet points max. Stick to data. Example: "NO-side trades continue to outperform (73% win rate vs 55% YES), consistent with the structural favorite-longshot bias we identified in backtesting."*

## What We're Watching

{whats_watching}

*Guidance: 1–2 concerns or areas of attention. Be honest but not alarmist. Example: "Fill rates on larger positions ($5+) are lower than expected at 82%. We are investigating whether to cap position sizes or implement limit-order execution."*

## Changes Made This Week

{changes_or_none}

*Guidance: Any parameter changes, code updates, or strategy adjustments. If none, say "No changes to strategy parameters or system configuration this week."*

## Outlook

{outlook_paragraph}

*Guidance: 2–3 sentences. Be measured. Never promise returns. Example: "We are now {N} trades into live validation. The system is performing within the expected range from backtesting, though it is too early to draw statistically meaningful conclusions. We need approximately 100 resolved trades to confirm the backtest edge translates to live markets."*

---

**Reminder:** All returns are net of trading fees. Past performance (including backtested results) does not guarantee future returns. This is a speculative strategy and you should only invest capital you can afford to lose entirely. Questions? Reply to this update or contact John directly.

---

*Update generated from live scorecard data. Reviewed and edited by fund manager before distribution.*
