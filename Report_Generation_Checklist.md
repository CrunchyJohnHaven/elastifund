# Monthly Investor Report — Generation Checklist

**Target:** Complete report in under 10 minutes from data pull to finished .docx.
**Template:** `Monthly_Report_March_2026.docx` (use as base, update data each month)
**Generator Script:** `generate_monthly_report.js` (Node.js, uses `docx` package)

---

## Quick-Start (Copy-Paste Workflow)

```
# 1. SSH into VPS and pull data (2 min)
ssh root@161.35.24.142

# 2. Query bot endpoints
curl http://localhost:8000/metrics | python3 -m json.tool > /tmp/metrics.json
curl http://localhost:8000/orders | python3 -m json.tool > /tmp/orders.json
curl http://localhost:8000/status | python3 -m json.tool > /tmp/status.json
curl http://localhost:8000/risk | python3 -m json.tool > /tmp/risk.json

# 3. Pull paper trades and metrics history
cat paper_trades.json | python3 -m json.tool > /tmp/paper_trades.json
cat metrics_history.json | python3 -m json.tool > /tmp/metrics_history.json

# 4. Copy to local machine
scp root@161.35.24.142:/tmp/{metrics,orders,status,risk,paper_trades,metrics_history}.json ~/Desktop/monthly-data/
```

---

## Step-by-Step Instructions

### Step 1: Pull Data from Bot (2 minutes)

| Data Point | Source | Endpoint / File |
|---|---|---|
| Current NAV (cash + positions) | Bot API | `GET /status` → `total_value` |
| Win rate (resolved trades) | Bot API | `GET /metrics` → `win_rate` |
| Total trades entered | Bot API | `GET /metrics` → `total_trades` |
| Winning trades | Bot API | `GET /metrics` → `winning_trades` |
| Losing trades | Bot API | `GET /metrics` → `losing_trades` |
| Realized P&L | Bot API | `GET /metrics` → `realized_pnl` |
| Unrealized P&L | Bot API | `GET /metrics` → `unrealized_pnl` |
| Max drawdown | Bot API | `GET /risk` → `max_drawdown` |
| Current exposure | Bot API | `GET /risk` → `current_exposure` |
| Active positions count | Bot API | `GET /status` → `active_positions` |
| Full order history | Bot API | `GET /orders` → full JSON array |
| Signals per cycle (avg) | VPS file | `metrics_history.json` → average `signals_count` |
| Markets scanned per cycle | VPS file | `metrics_history.json` → average `markets_scanned` |
| Paper trade log | VPS file | `paper_trades.json` → full position list |
| Cycle count | VPS file | `metrics_history.json` → array length |

### Step 2: Calculate Derived Metrics (2 minutes)

Use these formulas (or have the script calculate them):

| Metric | Formula |
|---|---|
| Monthly Return % | `(ending_nav - starting_nav) / starting_nav × 100` |
| Sharpe-equivalent | From Monte Carlo or `(avg_return / std_return) × sqrt(365)` |
| Capital utilization | `current_exposure / total_nav × 100` |
| Avg profit per trade | `realized_pnl / resolved_trades` |
| Best trade | Max single-trade P&L from orders |
| Worst trade | Min single-trade P&L from orders |
| Strategy breakdown | Group orders by `category` field, compute win rate per group |

### Step 3: Update the Report Script (3 minutes)

Open `generate_monthly_report.js` and update these sections:

1. **Title block:** Change month ("March 2026" → "April 2026") and prepared date
2. **Performance Summary table:** Update Starting NAV, Ending NAV, Monthly Return %, Cash Deployed, Cash Remaining
3. **Trade Activity table:** Update Total Positions, Resolved (Wins), Resolved (Losses), Signals per Scan, Best/Worst Trade
4. **Strategy Breakdown table:** Update win rates and trade counts per category from grouped order data
5. **Market Commentary:** Write 2 paragraphs covering:
   - What happened in prediction markets this month (major events, platform changes, volume trends)
   - How our strategy performed relative to those conditions
6. **Risk Metrics table:** Update Max Drawdown, Sharpe, Current Exposure, Position Concentration, Capital Utilization
7. **Outlook section:** Update bullet points for next month's priorities
8. **Appendix trade log:** Replace sample trades with actual top 10 positions + summary row

### Step 4: Generate and Review (2 minutes)

```bash
# Generate the report
node generate_monthly_report.js

# Verify it opens correctly (on Mac)
open Monthly_Report_March_2026.docx

# Or convert to PDF for review
libreoffice --headless --convert-to pdf Monthly_Report_March_2026.docx
```

### Step 5: Final Checks (1 minute)

- [ ] Paper trading banner present (remove when live)
- [ ] All placeholder values replaced with real data
- [ ] Month and date correct in title and header
- [ ] NAV numbers match bot /status endpoint
- [ ] Trade counts match bot /metrics endpoint
- [ ] Disclaimer present at bottom
- [ ] Report is ≤ 4 pages
- [ ] File saved as `Monthly_Report_[Month]_[Year].docx`

---

## Data Source Quick Reference

| Section | Primary Source | Backup Source |
|---|---|---|
| NAV / Performance | `/status`, `/metrics` | `paper_trades.json` (manual calc) |
| Trade Activity | `/orders`, `/metrics` | `paper_trades.json` |
| Strategy Breakdown | `/orders` grouped by category | Manual from trade log |
| Risk Metrics | `/risk` | `metrics_history.json` (calc from history) |
| Market Commentary | Manual (news + platform updates) | — |
| Outlook | Manual (from COMMAND_NODE.md priorities) | Research dispatch task list |
| Appendix Trade Log | `/orders` | `paper_trades.json` |

---

## When We Go Live (Remove Paper Trading)

When transitioning from paper to live trading:

1. Remove the `paperTradingBanner()` call from the script
2. Change all "Paper Trading" labels to "Live Trading"
3. Update the disclaimer to remove "paper trading" language
4. Add fee calculation section (from Quarterly_Report_Template.docx):
   - Beginning NAV, Gross Profit, High-Water Mark, Performance Fee (30%), Net Profit
5. Add benchmark comparison (Polymarket average return or S&P 500)
6. Consider adding equity curve chart (generate from `metrics_history.json`)

---

## Automation Opportunities (Future)

- **Scheduled task:** Use Cowork scheduled task to auto-pull data on the 1st of each month
- **Auto-populate script:** Modify `generate_monthly_report.js` to read directly from VPS JSON files via SSH
- **Chart generation:** Use Python matplotlib to generate equity curves and embed as images
- **Email distribution:** Auto-email report to investor list via SendGrid or similar

---

*Last updated: March 5, 2026*
