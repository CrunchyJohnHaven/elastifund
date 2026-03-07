# Prediction Market Fund – Legal & Regulatory Research

## 1. Legal Entity (Structure)

Small private investment pools are typically formed as pass-through entities (no corporate tax). Common choices are LLCs or limited partnerships (LPs), often taxed as partnerships.

An LLC taxed as a partnership is often simplest for a small fund — it offers liability protection, flexible management, and lets you issue K-1s to investors. An LP with an LLC as general partner can also work, but a straight LLC is easier for a tiny pool.

In any case you'd file IRS Form 1065 and issue K-1s to investors. Avoid a general partnership (GP), which would expose investors to personal liability. The tax treatment is the same for LLC or LP partnerships.

---

## 2. Regulation: CFTC vs SEC vs States

**CFTC (primary regulator):** The CFTC treats event-based binary options (yes/no bets on future events) as swaps under the Commodity Exchange Act. In 2022 the CFTC fined Polymarket $1.4M for operating an unregistered "event-based binary options" trading platform. The CFTC now generally requires event contracts to trade on a registered exchange (e.g. a Designated Contract Market). Any fund trading Kalshi or Polymarket contracts is trading CFTC-governed derivatives.

**SEC:** If a prediction contract's payoff is tied to a regulated security, it could fall under SEC jurisdiction. Standalone event-betting contracts (e.g. political outcomes) are not traditional "securities" and fall under CFTC.

**State gambling laws:** Many states view prediction markets as gambling. CFTC Reg. 40.11 explicitly preserves state power over sports betting or other unlawful events. States (NY, NJ, IL, etc.) have moved to ban or license sports or political betting contracts. Fund managers should be aware of state gaming laws — e.g. Nevada requires a sportsbook license for sports-event contracts. This is an unsettled area of law with federal/state conflicts being litigated.

**Polymarket:** Polymarket was targeted by the CFTC for operating without registration. It agreed to cease US services and wind down non-compliant contracts. By late 2025 Polymarket had obtained a CFTC-approved setup for US trading. Prediction markets are CFTC-regulated commodities unless specifically tied to regulated securities.

---

## 3. Exemptions (Offering Securities)

For a tiny fund raising from friends/family, the primary federal exemption is **Regulation D, Rule 506(b)**:

- **Unlimited accredited investors.** An accredited investor is generally anyone with >$1M net worth or $200K income per year.
- **Up to 35 non-accredited investors.** All non-accredited participants must be financially sophisticated and given full disclosure.
- **No general solicitation.** You cannot publicly advertise the fund. Invitations must be to people you already know.
- **Form D filing.** File SEC Form D within 15 days of first sale (no SEC review, just notice). States are preempted from registration but can impose filing/fees.

Rule 506(c) allows general solicitation but all investors must be accredited (and you must verify accreditation). For small friends/family pools, 506(b) is usual.

**Investment Company Act:** To avoid registering as a mutual fund, rely on private fund exemptions — typically Section 3(c)(1) if <100 total investors, or 3(c)(7) if all are qualified purchasers. A tiny friends/family fund under 100 owners automatically qualifies under 3(c)(1).

---

## 4. Tax Treatment of Prediction Market Gains

The IRS has not issued specific guidance on prediction market gains. Possible treatments:

- **Gambling income:** Profits taxed as ordinary income. Losses only deductible as an itemized deduction up to winnings; new laws limit deductions to 90% of winnings starting 2026. Unfavorable.
- **Capital gains:** If contracts are seen as capital assets, net gain/loss treatment applies. Short-term gains taxed as ordinary; long-term at 0–20%. More favorable.
- **Section 1256 (futures) treatment:** Event contracts on a qualified board or exchange may fall under IRC §1256 — 60% long-term / 40% short-term regardless of holding period, marked-to-market at year-end. Requires CFTC-listed contracts; unclear if IRS recognizes Polymarket as qualifying.

Automating trades doesn't by itself change taxation — the nature of the contract is what matters. Funds often hope for capital gain or 1256 treatment. Track all trades carefully and consult a tax advisor.

---

## 5. Minimum-Viable Setup (Friends/Family Fund)

For a very small fund ($10K–$100K):

- **Entity:** Form a single multi-member LLC (or LP) taxed as a partnership.
- **Offering:** Rely on Reg D 506(b) private placement. Only solicit people you personally know. File Form D.
- **CFTC Exemptions:** CFTC Rule 4.13 provides an exemption for "family, friends, and small" pools. File a simple notice with NFA claiming exemption. Criteria: all participants are relatives or ≤10 friends/colleagues with sufficient net worth, total pool assets under $500K.
- **Investment Adviser:** SEC threshold for mandatory adviser registration is $150M AUM. At $100K–$500K you're far below that. CFTC CTA rules allow exemption if advising ≤15 persons.
- **Practical Steps:** Create an LLC, draw up a simple PPM or subscription agreements, sell membership interests via 506(b), start trading. Keep good records, file Form D, provide K-1s.

---

## 6. Profit-Sharing (Fees & Carry)

Classic model: management fee + performance fee ("2 and 20" = 2% of AUM + 20% of profits). Smaller/newer funds often charge 1–2% management and 15–20% performance.

**High-water marks** are standard: performance fees charged only on net new profits above any prior peak. This aligns interests by ensuring investors don't pay carry on recovery from losses.

For a tiny friends fund, something like 1% + 15–20% with a high-water mark is reasonable. Whatever you choose, put it in writing. Detail fee calculation (quarterly or annual) and any hurdle rate.

---

## 7. Precedents (Other Funds)

No well-known public examples of a small fund created solely to trade Polymarket or similar prediction markets. Large trading firms (Jump Trading, Susquehanna) provide liquidity on Kalshi/Polymarket and have taken equity stakes, but within proprietary trading operations — not as outside pooled funds. Goldman Sachs has a team looking into prediction markets.

Setting up a small, private fund focused on prediction markets would be breaking new ground. Proceed cautiously and watch CFTC, SEC, and platform developments.

---

## 8. Risk Disclosures (Backtest/Hypothetical Performance)

Under SEC Marketing Rule 206(4)-1, any performance data must be presented carefully:

- **Hypothetical disclaimer:** Clearly label all backtested or simulated results as hypothetical.
- **No guarantees:** Include "Past or model performance is not indicative of future results. Investors may lose money."
- **Gross vs Net performance:** If showing gross returns, must also show net returns with equal prominence.
- **Time periods:** Performance claims must cover required periods (1-, 5-, and 10-year or life-of-fund).
- **Methodology disclosure:** Describe how results were generated, assumptions, expenses, slippage.
- **No cherry-picking:** Don't present only best trades without full portfolio context.

Always mark figures as hypothetical, disclose small sample size, lack of live track record, and high risk of loss. Include standard SEC disclosure language. Never promise returns.

---

## 9. Related Research Documents

For market strategy, competitive landscape, and academic forecasting research, see:

- **`polymarket-llm-bot-research.md`** — GPT-4.5 deep research: market category rankings, academic literature (Halawi et al., Clinton & Huang, Karger et al.), competitive landscape (OpenClaw, Dysrupt Labs, PolyScripts), data feed recommendations
- **`research_dispatch/P0_32_market_competitive_deep_research_GPT45.md`** — Integration summary showing which documents were updated from this research
- **`research_dispatch/P0_26_llm_vs_prediction_markets_RESEARCH.md`** — 9-paper academic synthesis on LLM forecasting vs prediction markets
- **`Competitive_Landscape_Market_Analysis.docx`** — Full competitive analysis with win rate benchmarking and moat analysis
- **`STRATEGY_REPORT.md`** — Live strategy report with backtest results, system architecture, and research-driven improvements
