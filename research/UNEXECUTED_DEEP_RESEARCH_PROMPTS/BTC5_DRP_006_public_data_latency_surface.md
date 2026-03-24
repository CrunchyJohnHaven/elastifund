---
id: BTC5_DRP_006
title: Public-Data Latency Surface for Polymarket, Kalshi, and Alpaca
tool: CHATGPT_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-23
---

# Public-Data Latency Surface for Polymarket, Kalshi, and Alpaca

## Context

Elastifund's current architecture has strong pieces for fast-market work but not yet
the unified public-data edge map needed to turn them into a durable tri-venue system.

What already exists in-repo:

- `bot/btc_5min_maker_core.py` for Polymarket maker-first crypto microstructure
- `bot/wallet_flow_detector.py` for public Polymarket trade-flow intelligence
- `bot/kalshi_intraday_parity.py` and `bot/cross_platform_arb.py` for Kalshi parity
- `bot/strike_desk.py` as a not-yet-fully-wired routing layer
- `bot/event_tape.py`, `bot/proof_types.py`, and `bot/promotion_manager.py` for
  proof-carrying execution discipline
- `docs/architecture/proof_carrying_kernel.md`, `docs/architecture/strike_desk.md`,
  and `docs/architecture/event_sourced_tape.md` defining the intended control plane

What does NOT yet exist:

- a real Alpaca execution or data lane inside the proof-carrying kernel
- a mathematically ranked map of which official/public feeds can create a real
  information-latency edge for small capital
- a unified answer to "which venue should be treated as source truth, which venue
  should be treated as execution venue, and when?"

We need a deep-research answer to one specific question:

**Can public, documented data feeds create a real edge on Polymarket, Kalshi, or
Alpaca before the contract prices fully absorb them, and if so which exact edge has
the best expected value per engineering hour and per dollar of capital?**

## Required External Surfaces To Analyze

Use current official venue docs and only primary sources for mechanics:

- Polymarket market WebSocket / RTDS / market-maker docs
- Kalshi WebSocket and market-data docs
- Alpaca real-time market-data and news docs
- Binance / official exchange docs only if needed as external truth source
- Official macro / weather / government release feeds only if relevant

Do not rely on influencer threads, newsletter summaries, or scraped aggregator claims
unless used strictly as secondary color after primary-source validation.

## Research Questions

1. **Public feed latency map**
   Which public or officially documented feeds are fast enough to matter?
   Compare:
   - Polymarket RTDS vs Polymarket market channel vs Gamma API
   - Kalshi WebSocket vs REST market data
   - Alpaca stock / crypto / options / news streams
   - Official truth feeds such as exchange trades, government releases, or forecast APIs
   Identify realistic latency buckets and whether each feed is signal, routing input,
   or settlement truth.

2. **Source-truth vs execution-venue decomposition**
   For each candidate edge family, determine:
   - what data feed should define fair value
   - which venue is slow or behaviorally wrong
   - whether Alpaca should be a reference venue, a hedge venue, or an execution venue
   - whether the best setup is same-venue maker capture, cross-venue parity, or
     source-truth-to-venue transfer

3. **Small-capital executable opportunity families**
   Rank the best opportunity families for approximately:
   - $1K Polymarket
   - $100 Kalshi
   - $1K Alpaca
   Focus on edges that can start tiny and scale if proven:
   - crypto candle / short-horizon prediction contracts
   - hourly / same-day Kalshi event markets
   - Alpaca-tradable instruments that can serve as fast truth or hedge proxies
   - public-news or official-release reaction windows

4. **Maker-first vs taker-first economics**
   For each venue and edge family, quantify when maker-first is mandatory, when
   taker is justified, and when hybrid routing makes sense.
   We need a mathematical answer, not hand-waving.

5. **Opportunity density**
   Which public-data edges actually recur often enough to matter?
   A beautiful 5% edge that appears once a quarter is not the path.
   Estimate:
   - opportunities per day or week
   - expected notional capacity
   - fill probability
   - capital lockup
   - likely competition intensity

6. **Alpaca-specific role**
   Alpaca is not currently integrated into the repo.
   Determine whether Alpaca should be used primarily for:
   - external truth and feature generation
   - event hedging / proxy positions
   - standalone intraday execution
   - not at all for the first phase
   Give a blunt recommendation.

## Formulas Required

The research must return explicit formulas or cite authoritative ones for:

- **Net edge after costs**
  `net_edge = gross_edge - fees - slippage - latency_penalty - non_fill_penalty`

- **Maker EV**
  `EV_maker = P(fill) * P(win | fill) * payoff - P(fill) * P(loss | fill) * loss - cancel_cost`

- **Taker EV**
  `EV_taker = P(win) * payoff - P(loss) * loss - taker_fee - slippage`

- **Latency value**
  `latency_value = d(price_error)/dt * latency_advantage`
  or a better microstructure-consistent equivalent

- **Opportunity score**
  A ranking formula combining edge magnitude, recurrence, fill probability,
  capacity, implementation effort, and proof risk

- **Route selection**
  A venue-routing rule that decides:
  `route = argmax_venue expected_net_edge(venue, fill_prob, latency, fees, limits)`

- **Capital velocity**
  `capital_velocity = expected_net_pnl / capital_locked_hours`

## Measurable Hypotheses

The research must test these or stronger replacements:

H1. At least one public-data edge family across Polymarket, Kalshi, and Alpaca
    produces a realistic expected net edge of at least 25 bps per executable
    trade after conservative cost assumptions.

H2. At least one edge family recurs often enough to produce meaningful learning
    density: at least 3-5 actionable opportunities per trading day or 20 per week.

H3. Maker-first execution remains superior for at least one Polymarket or Kalshi
    lane even after accounting for non-fill risk.

H4. Alpaca adds more value as a truth or hedge venue than as the first standalone
    alpha venue, OR the opposite; the research must decide.

H5. If no candidate family survives realistic fill-rate and latency assumptions,
    the correct conclusion is "no edge here yet," not forced optimism.

## Required Deliverables

Return all of the following:

1. A ranked table of the top 10 public-data opportunity families across the three
   venues with:
   - mechanism
   - source-truth feed
   - execution venue
   - horizon
   - recurrence estimate
   - capacity estimate
   - primary risks
   - honest P(works)

2. A "best first edge" recommendation with:
   - why it beats the other candidates
   - the minimum viable experiment
   - what data to record on day 1
   - what would kill it quickly

3. A venue-role recommendation:
   - Polymarket = ?
   - Kalshi = ?
   - Alpaca = ?

4. A concrete implementation backlog in repo terms:
   - P0: must build now
   - P1: only if P0 shows signal
   - P2: defer

5. A metric contract for proving the edge:
   - fill rate
   - stale-data rate
   - expected vs realized edge
   - opportunity density
   - capital velocity
   - execution-quality score

## Failure Modes To Address Explicitly

- Public feeds may be too widely known, leaving no residual latency edge
- Maker fill probability may collapse the theoretical edge
- Contract definitions may differ across venues and create false parity
- Alpaca instruments may be poor proxies for prediction contracts
- News and official-release edges may be too fast for retail-grade infrastructure
- Small capital may make the edge real but economically trivial

## Direct Repo Integration Targets

- `bot/btc_5min_maker_core.py`
- `bot/wallet_flow_detector.py`
- `bot/kalshi_intraday_parity.py`
- `bot/cross_platform_arb.py`
- `bot/strike_desk.py`
- `bot/event_tape.py`
- `bot/promotion_manager.py`
- `bot/proof_types.py`
- `docs/architecture/strike_desk.md`
- `docs/architecture/event_sourced_tape.md`

## Hard Constraints

- No illegal, manipulative, or non-compliant tactics
- No private / paywalled proprietary data assumptions unless clearly labeled optional
- No new control plane outside the existing proof-carrying kernel
- Recommendations must be realistic for small capital and high uncertainty
- If the fastest path is "build measurement before risking more money," say so directly
