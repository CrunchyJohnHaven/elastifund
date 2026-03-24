# Deep Research Packet 06: Public Data, Tail Calibration, and Alpaca System Design

**Status:** Canonical synthesis packet for future LLMs.
**Date:** 2026-03-23
**Synthesized from:** the tail-mispricing research pass, the public-data latency report saved at `/Users/johnbradley/Downloads/deep-research-report (5).md`, and current repo architecture.

## 1. Durable Conclusions

### 1.1 There is no magical longshot edge

The strongest tail thesis is not “rare things happen more than markets imply.”
The credible edge is the opposite:

- very cheap YES contracts are often overpriced
- the tradeable complement is usually the high-probability side, often NO
- fees, rounding, spread, and rule ambiguity are a larger part of the edge than the headline probability

Future LLMs should frame tail work as a **calibration + execution + rule-parsing**
problem, not as a heroic hunt for 50x lottery tickets.

### 1.2 Polymarket is the best short-horizon execution venue

For small capital and high learning density, the first-priority venue is:

- **Polymarket maker-first execution**
- using **RTDS crypto prices** as public truth
- using the **market WebSocket** as the execution microstructure feed

Short version:

- maker-first is mandatory
- taker-first is mostly fee donation
- stale-quote prevention matters more than trying to be 5 ms faster than everyone

### 1.3 Kalshi is the cleanest first tail-calibration venue

The best first tail experiment is:

- objective-rule Kalshi contracts
- YES prices in the `0.01-0.05` range
- traded as diversified **buy-NO** baskets

Why:

- fee/rounding effects are explicit and modellable
- contract families are broad enough for repeated falsification
- the edge can be killed quickly if posterior lower bounds fall below breakeven

### 1.4 Alpaca is truth/hedge first, not primary alpha first

Alpaca should enter the system in this order:

1. **truth source**
   Use Alpaca equities, crypto, options, and news feeds as external anchors or proxy truth.
2. **hedge venue**
   Use Alpaca to hedge prediction-market exposure only when the contract maps cleanly to a liquid public instrument.
3. **standalone execution venue**
   Defer until the repo has a real Alpaca data/broker lane and measured edge.

### 1.5 IPO posture must be operational, not narrative-only

Important correction for future sessions:

- Alpaca docs say IPO symbols are supported.
- Alpaca can accept **limit orders** prior to a security’s first trade on the exchange.
- After the IPO begins trading, **market orders** are accepted.
- Alpaca exposes an `ipo` attribute on the asset model to flag this state.

This means the repo should treat IPOs as a **watchlist + alerting + limit-order-prep**
lane, not as an impossible venue feature and not as permission to market-buy blind.

## 2. System Role Split

### 2.1 Short-Term Lane

Primary short-term lane:

- Polymarket crypto micro-horizon maker-first quoting
- truth from RTDS
- execution from market WebSocket
- proof from event tape + expected-vs-realized edge decomposition

This is the best candidate for high opportunity density and fast learning.

### 2.2 Medium-Term Lane

Primary medium-term lane:

- Kalshi objective-rule longshot fade
- pre-registered tail bins
- posterior shrinkage
- fee-aware breakeven checks
- diversified NO baskets

This is the cleanest “tail mispricing” proof lane.

### 2.3 Alpaca Lane

Phase 1 Alpaca responsibilities:

- market-data and news anchor
- options-implied reference probability where mapping is clean
- hedge venue for tightly matched contracts
- IPO watchlist and alerting lane

Phase 1 Alpaca is **not** the repo’s primary alpha venue.

## 3. Architecture Integration

### 3.1 Evidence Bundle

Future LLMs should treat these as the target evidence surfaces:

- Polymarket RTDS truth stream
- Polymarket market-channel microstructure
- Kalshi orderbook snapshot/delta and trades
- Alpaca stock/crypto/options/news streams
- IPO calendar / asset-state watchlist events

New helper modules already landed for the tail lane:

- `signals/tail_bins.py`
- `signals/fee_models.py`
- `signals/resolution_risk.py`

### 3.2 Thesis Bundle

Theses should stay narrow and typed:

- `polymarket_crypto_maker_truth_gap`
- `kalshi_objective_longshot_fade`
- `alpaca_reference_probability_anchor`
- `ipo_watch_limit_order_ready`

The repo should prefer many narrow theses over one vague “AI/equities” thesis.

### 3.3 Promotion Bundle

No new approval path should be created.

Tail and Alpaca-related lanes must still pass:

- fee gate
- rule gate
- fill gate
- promotion-ladder stage requirements

For tails specifically, future LLMs should require:

- pre-registered bins
- posterior lower bound above breakeven after fee stress
- objective-rule-only market selection
- discovery/confirmation window separation

### 3.4 Learning Bundle

The learning loop should record:

- expected net edge
- realized net edge
- fee drag vs modeled fee drag
- fill success/failure
- quote staleness
- resolution lag
- dispute/clarification incidents
- hedge mapping error for any Alpaca-linked thesis

## 4. Alerting and IPO Watch Design

The repo already has the right alerting primitives:

- `polymarket-bot/src/telegram.py`
- `bot/polymarket_runtime.py`
- `bot/health_monitor.py`
- `bot/wallet_poller.py`
- timer/service patterns in `deploy/`

Future LLMs should follow this pattern for IPO alerts:

1. poll asset metadata and IPO watch sources on a timer
2. write heartbeat + artifact JSON
3. dedupe and escalate via Telegram only when action is required
4. prepare limit-order-ready tickets, not blind market orders

Telegram is the preferred first delivery mechanism because it already exists and is tested.

## 5. Concrete Repo Implications

### Already added

- `docs/strategy/tail_calibration_harness.md`
- `signals/tail_bins.py`
- `signals/fee_models.py`
- `signals/resolution_risk.py`
- `strategies/kalshi_longshot_fade.py`

### Next code surfaces for future LLMs

- add Alpaca data/broker support through the existing abstractions:
  - `infra/cross_asset_data_plane.py`
  - `polymarket-bot/src/data/base.py`
  - `polymarket-bot/src/broker/base.py`
  - `polymarket-bot/src/engine/loop.py`
- add IPO poller + Telegram alerting
- add Alpaca reference-probability anchors only after a clean mapping is defined
- extend proof artifacts to store tail-bin evidence explicitly

## 6. What Future LLMs Should Not Do

- Do not resurrect simple longshot-buying stories without fee and shrinkage math.
- Do not assume Alpaca is the primary first-alpha venue.
- Do not treat every “same-looking” Kalshi/Polymarket market as rule-identical.
- Do not route real money into IPO narratives without the asset actually being live or flagged as IPO-ready.
- Do not create a second control plane outside the proof-carrying kernel.

## 7. Current Best Working Doctrine

If a future LLM has to choose quickly, use this doctrine:

1. **Short-term**
   Push hardest on Polymarket maker-first public-data microstructure.
2. **Medium-term**
   Prove or kill the Kalshi objective longshot-fade basket.
3. **Alpaca**
   Build truth, hedge, and IPO alerting first.
4. **Tail research**
   Treat it as calibration engineering, not moonshot hunting.
5. **Capital**
   Scale only after proof, not because the theme feels right.
