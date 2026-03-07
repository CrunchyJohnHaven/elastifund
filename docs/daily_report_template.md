# Predictive Alpha Fund — Daily Summary

**Date:** {date}
**Day:** {day_number} of live trading
**Prepared by:** Automated system (reviewed by J. Bradley)

---

## Today in One Sentence

{one_sentence_summary}

*Example: "Quiet day — 3 trades resolved (2 wins, 1 loss), bankroll up 1.2%, no risk alerts."*

---

## Performance

| Metric | Today | Cumulative |
|--------|-------|-----------|
| Starting Bankroll | ${starting_bankroll} | — |
| Ending Bankroll | ${ending_bankroll} | — |
| Change | {daily_change_pct:+.1f}% | {cum_change_pct:+.1f}% since inception |
| Realized P&L | ${realized_today:+.2f} | ${cum_realized:+.2f} |
| Unrealized P&L | ${unrealized} | — |
| Fees Paid | ${fees_today} | ${cum_fees} |
| Net P&L (after fees) | ${net_today:+.2f} | ${cum_net:+.2f} |

## Trades

| | Opened | Closed | Wins | Losses | Win Rate |
|---|--------|--------|------|--------|----------|
| Today | {opened} | {closed} | {wins} | {losses} | {daily_wr:.0%} |
| Rolling 50 | — | — | {r50_wins} | {r50_losses} | {r50_wr:.1%} |

**Backtest baseline win rate: 64.9%.** Today's rolling rate is {above_below} baseline.

## Edge Check

| | Predicted | Realized | Decay |
|---|----------|----------|-------|
| Overall | {pred_edge:.1%} | {real_edge:.1%} | {decay:.1%} |
| YES side | {pred_yes:.1%} | {real_yes:.1%} | {decay_yes:.1%} |
| NO side | {pred_no:.1%} | {real_no:.1%} | {decay_no:.1%} |

Interpretation: {edge_interpretation}

*Example: "Edge decay is 3.8% — within normal range. NO-side edge holding strong."*

## Calibration

| Metric | Value | Status |
|--------|-------|--------|
| Rolling ECE (50) | {ece:.3f} | {ece_status} |
| Rolling Brier (50) | {brier:.3f} | {brier_status} |
| Overconfidence Index | {oci:.3f} | {oci_status} |

## Risk

| Metric | Value | Status |
|--------|-------|--------|
| Current Drawdown | {dd_pct:.1f}% | {dd_status} |
| Max Drawdown (7d) | {max_dd_7d:.1f}% | — |
| Open Positions | {open_positions} | — |
| Gross Exposure | {exposure_pct:.0f}% | {exposure_status} |
| Kill Events Today | {kills} | — |
| Consecutive Losses | {consec_losses} | {consec_status} |

## Position Breakdown

| Category | Positions | Exposure | Avg Edge | Win Rate |
|----------|-----------|----------|----------|----------|
| Politics | {pol_n} | ${pol_exp} | {pol_edge:.1%} | {pol_wr:.0%} |
| Weather | {wx_n} | ${wx_exp} | {wx_edge:.1%} | {wx_wr:.0%} |
| Economic | {econ_n} | ${econ_exp} | {econ_edge:.1%} | {econ_wr:.0%} |
| Geopolitical | {geo_n} | ${geo_exp} | {geo_edge:.1%} | {geo_wr:.0%} |
| Unknown | {unk_n} | ${unk_exp} | {unk_edge:.1%} | {unk_wr:.0%} |

## Alerts & Actions

{alerts_list_or_none}

*Example: "No alerts today." or "⚠️ Politics category concentration at 42% — approaching 40% threshold. Consider pausing new politics entries."*

---

## Honest Assessment

{honest_paragraph}

*Guidance: Write 2–3 sentences. Be conservative. Flag anything concerning. Do not spin. If it was a bad day, say so. If the strategy is working, say "consistent with backtest expectations" — never "crushing it."*

---

*Report auto-generated from `/metrics/scorecard` endpoint. Manual review by fund manager before distribution.*
