# P0-67: Fee Drag Deep Analysis — Maker vs Taker Optimization
**Tool:** COWORK
**Status:** READY
**Priority:** P0 — Taker fees eat 1–3% of edge. Makers pay 0% + get 20–25% rebate. This changes optimal strategy.
**Expected ARR Impact:** +15–40% from fee elimination alone

## Prompt (paste into Cowork)

```
Read COMMAND_NODE.md in the selected folder for full project context. Also read research/market_making_fees_competitive_landscape_deep_research.md and Fee_Structure_Analysis.docx.

CONTEXT:
Polymarket fee structure (as of March 6, 2026):
- TAKER fee: fee(p) = C * p * feeRate * (p*(1-p))^exp
  - Crypto markets (Mar 6): max 1.56% at p=0.50
  - Sports markets (Feb 18): max 0.44% at p=0.50
  - All other markets: 0% fee (fee-free)
- MAKER fee: ALWAYS 0% + rebates (20% crypto, 25% sports)
- Makers = limit orders that add liquidity
- Takers = market orders or limit orders that immediately fill

OUR CURRENT APPROACH: Taker orders (we cross the spread). This means we pay fees on every trade.

I need a comprehensive analysis as a .docx:

1. FEE DRAG QUANTIFICATION:
   For our 532-market backtest, calculate EXACTLY how much fees cost us:
   - Total fee drag across all 470 trades
   - Average fee per trade (in $ and as % of edge)
   - How many trades would be UNPROFITABLE after fees that were profitable before fees?
   - Fee drag by category (crypto markets vs politics vs weather)
   - Fee drag by price bucket (p near 0.50 = worst fees vs p near 0.10 = minimal fees)

2. MAKER VS TAKER STRATEGY COMPARISON:
   Model two parallel strategies:

   Strategy A (Current — Taker):
   - Immediate fill, guaranteed execution
   - Pays taker fee on every trade
   - No fill risk
   - Simple implementation

   Strategy B (Maker — Limit Orders):
   - Post limit order at better price, wait for fill
   - 0% fee + rebate
   - Fill risk: order might not fill (opportunity cost)
   - Needs: order management, timeout logic, repricing
   - Our bot already has $0.01 price improvement + 60s timeout

   For each at $2K, $10K, $50K capital:
   - Expected annual P&L (using backtest data)
   - Net return after fees
   - Fill rate assumptions (what % of maker orders fill?)
   - Break-even fill rate (at what fill rate does maker = taker returns?)

3. HYBRID STRATEGY DESIGN:
   The optimal approach is probably hybrid:
   - Use maker orders for markets where edge is thin (5–10%) → fee is a larger % of edge
   - Use taker orders for markets where edge is large (>15%) → fee is small vs edge, speed matters
   - Use taker orders for time-sensitive markets (data release imminent)
   - What's the optimal edge threshold for switching maker→taker?

4. FEE-FREE MARKET OPPORTUNITY:
   Currently "all other markets" (not crypto, not sports) have 0% taker fees.
   - What % of our signals come from fee-free markets?
   - Should we HEAVILY bias toward fee-free markets?
   - What's the ARR if we ONLY trade fee-free markets vs mixed?

5. MARKET MAKING P&L MODEL:
   From the deep research: MM returns are $50–200/mo at $1–5K capital.
   - Model: if we dedicate 20% of capital to market making and 80% to directional
   - What's the blended return?
   - Does the MM revenue cover our infrastructure costs ($20/mo VPS+API)?
   - Is MM revenue stable or lumpy?

6. RECOMMENDATIONS TABLE:
   | Capital Level | Recommended Fee Strategy | Expected Fee Savings | Fill Rate Needed |

   With a clear "do this now" recommendation for our current $75→$2,000 capital level.

OUTPUT: Professional .docx with quantified tables, not vague recommendations. Every number should have a formula or assumption behind it.

SOP: After completing this task, UPDATE COMMAND_NODE.md (increment version) and review STRATEGY_REPORT.md fee section for stale numbers.
```
