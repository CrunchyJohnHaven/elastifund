# Strategy Claim Audit: Hcrystallash / 0xomega

**Audit date:** 2026-03-22
**Auditor:** JJ (autonomous audit, no human override)
**Claim source:** External trader claim relayed by John Bradley
**Claimed strategy:** Mean-reversion BTC trading using VWAP, RSI(14), ATR compression, volume exhaustion, MACD divergence, and Hilbert transform

---

## Verified Claims

None. Zero primary-source evidence was found for any claim attributed to "Hcrystallash" or "0xomega."

**Search scope:**
- Full Elastifund repo (`research/`, `docs/`, `bot/`, `scripts/`, `tests/`): no matches for "hcrystallash", "0xomega", or "hilbert"
- `research/dispatches/`: no dispatch references this trader or alias
- Web search for "Hcrystallash" (exact match, quoted): zero relevant results across crypto, trading, and social media indexes
- Web search for "0xomega" + Polymarket: zero relevant results (distinct from known wallet 0x8dxd and other documented bots)
- No Telegram message logs, Discord references, or forum posts found linking either handle to a trading strategy

---

## Unverified Claims

| # | Claim | Status | Notes |
|---|-------|--------|-------|
| 1 | Trader "Hcrystallash" exists as a Polymarket participant | UNVERIFIED | Zero web presence under this handle |
| 2 | "Hcrystallash" is also known as "0xomega" | UNVERIFIED | No linking evidence found |
| 3 | Uses VWAP as a signal component | UNVERIFIED | VWAP is standard; no evidence this trader uses it |
| 4 | Uses RSI(14) as a signal component | UNVERIFIED | RSI(14) is standard; no evidence this trader uses it |
| 5 | Uses ATR compression for entry timing | UNVERIFIED | ATR compression is standard; no evidence this trader uses it |
| 6 | Uses volume exhaustion detection | UNVERIFIED | Concept is standard; no evidence this trader uses it |
| 7 | Uses MACD divergence | UNVERIFIED | MACD divergence is standard; no evidence this trader uses it |
| 8 | Uses Hilbert transform | UNVERIFIED | Hilbert is standard TA (John Ehlers); no evidence this trader uses it |
| 9 | Strategy is mean-reversion on BTC | UNVERIFIED | No trade history, backtest, or PnL evidence |
| 10 | Strategy is profitable | UNVERIFIED | No PnL, wallet address, or leaderboard ranking found |

---

## Inferred (Not Stated)

- The combination of six indicators (VWAP, RSI, ATR, volume exhaustion, MACD, Hilbert) suggests an ensemble/confluence model, not a single-indicator strategy. This is inferred from the claim description, not from any primary source.
- If this strategy exists, it likely targets BTC spot or perpetuals on CEX, not Polymarket binary markets. Polymarket BTC 5-min markets resolve to UP/DOWN binary outcomes and do not have continuous price action where VWAP or Hilbert transform would apply directly. Adapting these indicators to binary prediction markets would require a non-trivial translation layer (e.g., applying indicators to the underlying BTC spot price and mapping to binary position sizing).
- The claim may originate from a Telegram group, Discord server, or private conversation. No public record exists.

---

## Primary Sources

None found. Exhaustive search returned zero primary sources.

**Searches conducted:**
1. Repo grep: `hcrystallash|0xomega|hilbert` across all code and documentation -- no matches for trader names
2. Web: `"Hcrystallash"` -- zero relevant results
3. Web: `"0xomega" Polymarket trader` -- zero relevant results
4. Web: `"0xomega" crypto trader` -- zero relevant results

**For reference only (Hilbert transform as standard TA):**
- John Ehlers, "Rocket Science for Traders" (Wiley, 2001) -- original Hilbert transform application to financial markets
- TrendSpider documentation: https://help.trendspider.com/kb/indicators/hilbert-transform
- StrategyQuant implementation: https://strategyquant.com/codebase/ehlers-hilbert-transform-2/
- TradingView community scripts: https://in.tradingview.com/scripts/hilberttransform/

---

## Missing Proof

For this strategy to be tradeable (or even worth speccing), the following would need to exist:

1. **Wallet address or leaderboard profile** -- Proof that "Hcrystallash" or "0xomega" has traded on Polymarket or any verifiable exchange
2. **Trade history or PnL record** -- Realized returns over a meaningful sample (minimum 50 trades)
3. **Strategy specification** -- Exact entry/exit rules, not just a list of indicator names. How are VWAP, RSI, ATR, volume exhaustion, MACD, and Hilbert combined? What are the thresholds? What is the position sizing logic?
4. **Backtest or forward-test results** -- With timestamps, fill prices, and slippage accounting
5. **Binary market adaptation** -- How these continuous-price indicators map to Polymarket binary UP/DOWN outcomes
6. **Source code or pseudocode** -- Reproducible logic, not marketing language
7. **Identity verification** -- Any evidence linking "Hcrystallash" to "0xomega" or to a real trading record

---

## Conclusions

- **Hcrystallash profile:** UNVERIFIED -- zero web presence, zero repo references, zero leaderboard data
- **"0xomega" trading model:** UNVERIFIED -- zero web presence linking this handle to Polymarket or any trading record
- **Hilbert indicator:** STANDARD TA -- well-documented technique by John Ehlers (2001), implemented in TrendSpider, TradingView, MotiveWave, and StrategyQuant. Not novel. Applicable to continuous price series; non-trivial to adapt to binary prediction markets.
- **Exact fill/execution logic:** UNVERIFIED -- no specification, no code, no pseudocode found
- **Recommendation:** `shadow_only_unresolved`

**Rationale:** Every claim about this strategy is unverified. The trader handle produces zero search results. The alias produces zero search results. The indicator list is plausible (all are standard TA tools) but there is no evidence anyone named Hcrystallash or 0xomega has combined them, traded them, or produced returns with them. Per Elastifund hard rule: no live trading behavior may depend on unverified claims. This strategy stays in `shadow_only_unresolved` until primary-source evidence surfaces.

---

*Audit conducted by JJ. No claims promoted without evidence. No exceptions.*
