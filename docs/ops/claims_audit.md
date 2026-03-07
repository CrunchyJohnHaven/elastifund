# Claims Audit — Investor Materials

**Date:** 2026-03-05
**Documents Audited:** `INVESTOR_REPORT.md`, `STRATEGY_REPORT.md`
**Standard:** Investor-safe, internally consistent, defensible under scrutiny

---

## Red Flag List (Must-Fix Before Sharing)

These items could expose the fund to legal liability, investor complaints, or credibility damage. Fix all before any document leaves your hands.

### RED FLAG #1: Ensemble Claimed as Existing (INVESTOR_REPORT.md)

**Location:** "How the System Works" section, step 2
**Current text:** "An AI ensemble (Claude, GPT, Grok) estimates the true probability of each event"
**Problem:** The ensemble does not exist. Only Claude Haiku is implemented. Claiming an ensemble exists is a material misrepresentation.
**Fix:** "An AI model (Claude) estimates the true probability of each event, without seeing the market price. A multi-model ensemble (adding GPT and Grok) is in development."

**Location:** Infrastructure table
**Current text:** "AI models: Claude Haiku, GPT-4o-mini, Grok-2 (ensemble)"
**Fix:** "AI models: Claude Haiku (primary). Multi-model ensemble (GPT-4o-mini, Grok-2) planned."

### RED FLAG #2: Position Sizing Inconsistency

**Location:** INVESTOR_REPORT.md Infrastructure table
**Current text:** "Position sizing: Half-Kelly criterion"
**Problem:** COMMAND_NODE.md and the actual code (`src/sizing.py`) implement quarter-Kelly. Half-Kelly overstates the risk exposure.
**Fix:** "Position sizing: Quarter-Kelly criterion (0.25×)"

### RED FLAG #3: "Learn" Step Claimed But Not Implemented

**Location:** INVESTOR_REPORT.md, "How the System Works" step 5
**Current text:** "Learn — Performance data continuously feeds back to improve calibration"
**Problem:** No continuous learning loop exists. Calibration is a static temperature-scaling table from the 532-market backtest. Claiming continuous learning is false.
**Fix:** "Monitor — Performance data is logged and reviewed to validate calibration. The system does not currently self-update; recalibration is manual and periodic."

### RED FLAG #4: 0.0% Probability of Total Loss — Unqualified

**Location:** INVESTOR_REPORT.md, Executive Summary and Monte Carlo section
**Current text:** "Probability of total loss: 0.0% (10,000 Monte Carlo simulations)"
**Problem:** This is based on backtest parameters fed into a simulation. It does not account for execution risk, platform failure, regulatory action, or systematic model failure. Presenting "0.0% loss probability" without heavy qualification is dangerously misleading for investors.
**Fix:** "Probability of total loss in simulation: 0.0% under backtest assumptions (10,000 Monte Carlo paths). Note: This simulation assumes backtest win rates persist, ignores execution risk, platform risk, and regulatory risk. Actual loss probability is non-zero. Investors should assume total loss of capital is possible."

### RED FLAG #5: ARR Projections Without Fee Impact

**Location:** INVESTOR_REPORT.md and STRATEGY_REPORT.md — ARR tables
**Problem:** Neither document adjusts ARR projections for the Feb 18, 2026 taker fee change. The STRATEGY_REPORT mentions taker fees in risk factors but the ARR tables still use pre-fee numbers. COMMAND_NODE.md confirms "taker fee awareness" is implemented but the backtest P&L ($280, $0.60/trade) was computed at simulated 0.50 entry without taker fee deductions.
**Fix:** Re-run backtest with taker fees applied. Until then, add caveat: "ARR projections do not yet incorporate Polymarket taker fees introduced February 18, 2026. Fees of approximately p×(1-p)×r per trade will reduce net returns. Updated projections pending."

---

## Line-Item Recommended Edits

### INVESTOR_REPORT.md

| # | Section | Current Wording | Recommended Wording | Severity |
|---|---------|----------------|---------------------|----------|
| 1 | Exec Summary "Estimated annual return" | "+269% to +1,124% depending on capital and trade frequency" | "+269% to +1,124% in backtested simulations. Live returns will differ. These projections do not yet account for taker fees, slippage, or fill rate limitations." | High |
| 2 | "How it works" step 2 | "An AI ensemble (Claude, GPT, Grok)" | "An AI model (Claude) estimates the true probability... A multi-model ensemble is planned but not yet implemented." | High (Red Flag #1) |
| 3 | "How it works" step 5 | "Learn — Performance data continuously feeds back" | "Monitor — Performance data is logged for periodic manual review and recalibration." | High (Red Flag #3) |
| 4 | "Why This Works" bullet 1 | "Speed — AI analyzes markets 24/7, catching mispricings before human traders" | "Scale — AI evaluates hundreds of markets simultaneously, identifying statistical patterns across categories" — Remove speed claim; we are not faster than arbitrage bots. | Medium |
| 5 | Academic Validation paragraph | "Forecasting Research Institute projects LLM-superforecaster parity by November 2026, validating the thesis that AI can generate genuine forecasting alpha" | Remove "validating" — a projection is not validation. Replace with: "...suggesting that AI forecasting capabilities are rapidly improving." | Medium |
| 6 | "The NO Bias Advantage" | "betting NO wins 76% of the time" | "In our 532-market backtest, betting NO won 76.2% of the time. This is consistent with the well-documented favorite-longshot bias, though live validation is pending." | Medium |
| 7 | Monte Carlo table | "Probability of total loss: 0.0%" | Add footnote: "Under backtest assumptions only. Does not model execution risk, platform failure, or regulatory events. Actual loss of principal is possible." | High (Red Flag #4) |
| 8 | "Best strategy win rate: 83.1%" | No qualification | Add: "(backtested on 160 filtered trades; smaller sample size means higher variance)" | Medium |
| 9 | Risk Factor #5 | "Monte Carlo simulations show 0% probability of total loss" | "Monte Carlo simulations show 0% probability of total loss under backtest assumptions. These simulations do not model platform risk, regulatory risk, or systematic model failure." | High |
| 10 | Infrastructure table | "Half-Kelly criterion" | "Quarter-Kelly criterion (0.25×)" | High (Red Flag #2) |
| 11 | Infrastructure table | "Claude Haiku, GPT-4o-mini, Grok-2 (ensemble)" | "Claude Haiku (primary). Multi-model ensemble planned." | High (Red Flag #1) |
| 12 | Fund Terms "Reporting" | "Monthly performance summary" | "Monthly performance summary with daily Telegram updates available" | Low |
| 13 | Missing entirely | No mention of taker fees | Add Risk Factor #11: "Trading Fees. Polymarket introduced taker fees on February 18, 2026 (fee = p×(1-p)×r). These fees reduce net edge on every trade, particularly near p=0.50 where fees are highest. Our system accounts for fees in trade signals, but backtested returns were computed before this fee structure existed." | High (Red Flag #5) |
| 14 | Missing entirely | No mention of execution limitations | Add Risk Factor #12: "Execution Limitations. The system has not yet completed any live trades. All performance data is from backtesting with simulated fills at idealized prices. Live execution will face slippage, partial fills, and order book depth constraints that may materially reduce returns." | High |

### STRATEGY_REPORT.md

| # | Section | Current Wording | Recommended Wording | Severity |
|---|---------|----------------|---------------------|----------|
| 1 | Position Sizing header | "Research Complete — Pending Integration" | "LIVE — Quarter-Kelly implemented in src/sizing.py" (per COMMAND_NODE.md) | Medium — contradicts COMMAND_NODE |
| 2 | "Current parameters" position size | "$2.00" | "Quarter-Kelly (avg ~$10 at $75 bankroll)" per COMMAND_NODE | Medium — stale |
| 3 | Risk Factor #2 | "Brier score of 0.239 means Claude's probability estimates are barely better than a coin flip for calibration" | Accurate, keep. | OK |
| 4 | Risk Factor #8 | "Polymarket taker fees eat 1-3% of edge on crypto/sports markets" | Expand: "...on crypto/sports markets. Fees apply to ALL taker trades: fee = p×(1-p)×r. At p=0.50, the breakeven edge is ~3.13%. This structurally favors limit-order (maker) strategies." | Medium |
| 5 | Architecture diagram | "TRADE: Paper trader ($2/position)" | Update to reflect Kelly sizing | Low |

---

## Tightened Risk Factors Section (Draft for INVESTOR_REPORT.md)

Replace the current Risk Factors section with the following:

---

**Risk Factors**

Investors should carefully consider the following risks before investing. This is a speculative investment. You should only invest money you can afford to lose entirely.

**1. No Live Trading Track Record.** All performance data presented in this document is from backtesting against historical data with simulated trade execution. The system has not yet completed live trades with real capital beyond a $75 seed. Backtested returns do not account for slippage, partial fills, order book depth limitations, or execution timing. Live returns will differ materially from backtested results and could be substantially worse.

**2. AI Model Risk.** The system relies on a single AI model (Claude Haiku) for probability estimation. This model's Brier score of 0.239 is only marginally better than random (0.25), meaning its raw probability estimates are poorly calibrated. The profitable trading signal comes from directional bias and post-hoc calibration, not from precise probability estimation. If the model's directional accuracy degrades, the strategy will fail.

**3. Calibration Overfit Risk.** The temperature-scaling calibration layer was fitted to 532 historical markets. This calibration may not generalize to future markets, different categories, or changing market dynamics. There is no continuous recalibration mechanism — calibration is reviewed manually.

**4. Favorite-Longshot Bias Dependency.** Approximately 76% of the strategy's edge comes from betting NO (against unlikely events). This structural bias is well-documented in academic literature, but it could erode as AI-powered trading bots proliferate on the platform. If the NO-side win rate drops below 65%, the strategy's profitability is significantly impaired.

**5. Trading Fee Impact.** Polymarket introduced taker fees on February 18, 2026, calculated as p×(1-p)×r per trade. Fees are highest near p=0.50 (where many of our trades occur) and can consume 1–3% of edge per trade. Backtested returns were computed before this fee structure and may overstate net profitability.

**6. Platform Risk.** Polymarket is a crypto-native prediction market built on Polygon. It faces regulatory uncertainty (the CFTC took enforcement action in 2022), potential technical failures, and liquidity crises. The fund has no diversification across platforms.

**7. Liquidity and Capacity Constraints.** The strategy works best at small scale. At $75, positions are small enough to fill easily. At $10,000+, fill rates may decline and slippage may increase. The fund's capacity is limited by Polymarket's order book depth.

**8. Regulatory and Tax Uncertainty.** The legal status of prediction market trading in the US is evolving. Tax treatment of gains is unsettled — possible classifications include gambling income (ordinary rates + no loss offset), capital gains, or Section 1256 contracts. Changes in regulation could restrict or prohibit trading entirely.

**9. Competitive Pressure.** The prediction market bot ecosystem is intensifying rapidly. Institutional players (Susquehanna), AI agent frameworks (OpenClaw, reportedly $115K in one week), and open-source bots are proliferating. Only approximately 0.5% of Polymarket users earn more than $1,000. The fund must continuously improve to maintain any edge.

**10. Concentration Risk.** The strategy operates on a single platform (Polymarket), using a single AI model (Claude), with capital concentrated in binary prediction markets. There is no diversification by asset class, geography, or strategy type.

**11. Capital Lock-up and Resolution Timing.** Many prediction markets do not resolve for weeks or months. Capital deployed in long-dated markets is locked and unavailable for new opportunities. At current parameters, the system deploys up to 90% of bankroll, leaving minimal reserves.

**12. Technology and Operational Risk.** The system runs on a single cloud server. Server failures, API outages, network disruptions, or software bugs could cause missed trades, incorrect execution, or data loss. There is no redundancy or failover infrastructure.

---

*This audit is complete. All "High" severity items must be addressed before sharing any document with investors or prospective investors. "Medium" items should be addressed before formal distribution. "Low" items are recommended improvements.*
