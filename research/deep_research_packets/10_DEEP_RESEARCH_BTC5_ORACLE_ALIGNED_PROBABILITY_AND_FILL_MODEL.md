# Deep Research Packet 10: BTC5 Oracle-Aligned Probability And Fill Model

**Status:** Canonical BTC5 doctrine supplement for future LLMs.  
**Date:** 2026-03-23  
**Synthesized from:** `/Users/johnbradley/Downloads/deep-research-report (11).md`, current BTC5 code surfaces, [09_CHATGPT_PRO_BTC5_ARCHITECTURE_FOCUS_REPAIR_PACKET.md](./09_CHATGPT_PRO_BTC5_ARCHITECTURE_FOCUS_REPAIR_PACKET.md), and [DISPATCH_112_btc5_down_maker_execution_fix.md](../dispatches/DISPATCH_112_btc5_down_maker_execution_fix.md).

This packet exists to save the parts of the March 23 BTC5 probability-model research that should become durable repo doctrine, while rejecting the parts that would create premature complexity or duplicate older execution guidance.

## 1. Durable Conclusions

### 1.1 Contract truth must be oracle-aligned, not exchange-aligned

Future LLMs should treat BTC5 contract labeling as:

- `DOWN = 1` only when `S1 < S0`
- ties resolve `UP`
- `S0` and `S1` come from the Chainlink BTC/USD settlement stream, not Binance spot

This is not a cosmetic detail. Any BTC5 model trained or reasoned on Binance-only labels is misaligned with the contract we are actually trading.

### 1.2 The correct primary truth surface is Chainlink RTDS, with Binance as auxiliary context

For BTC5:

- Chainlink RTDS should be the primary candle-open, candle-state, and price-to-beat surface
- Binance should remain an auxiliary microstructure and basis signal
- Polymarket book/trade data should remain the execution microstructure surface

Short version:

- Chainlink is the settlement truth
- Binance is context
- Polymarket order book is execution reality

### 1.3 The best first probability model is small, structural, and calibrated

The report's strongest modeling recommendation is also the safest:

1. structural baseline using only oracle-aligned state:
   - delta from open
   - time remaining
   - volatility
2. compact residual model on a small microstructure and time-feature set
3. explicit post-hoc calibration, with beta calibration as the default low-variance choice

Future LLMs should not start BTC5 by hunting a heroic nonlinear model. The first job is reliable calibration on the actual settlement series.

### 1.4 Maker execution requires a separate fill model

Future LLMs should treat maker BTC5 as a two-model problem:

- outcome model: `P(DOWN | state)`
- fill model: `P(fill | state, quote choice)`

And the tradable quantity is not raw `q - p`. It is fill-conditioned expectancy.

Canonical objective:

- estimate `q_fill = P(DOWN | state, quote fills)`
- estimate `f = P(fill | state, quote)`
- optimize `EV_submit = f * (q_fill - p + rebate - cost)`

This is the sharpest addition from the report versus older BTC5 notes.

### 1.5 The default starter window remains T-30s to T-10s

Until the repo measures its own information curve and fill curve cleanly:

- default BTC5 maker quoting window should remain `T-30s` to `T-10s`
- later windows may improve directional certainty but can collapse maker fills
- earlier windows may generate more fills but weaker information

This aligns with DISPATCH 112 and should remain the safe starter doctrine.

### 1.6 The right evaluation lens is bucketed calibration plus filled-trade EV

Future LLMs should evaluate BTC5 by:

- time-to-close buckets
- price buckets
- fill-status buckets
- bucketed calibration error
- filled-trade expectancy
- submitted-order expectancy

Plain hit rate is not enough. Unfilled maker orders and adverse fills can destroy a seemingly good directional model.

## 2. Accepted Repo Integration

These are the ideas from the report that should now be treated as accepted repo doctrine.

### 2.1 Chainlink-first truth plumbing is the next truth upgrade

The current `RTDSTruthFeed` stub in `bot/btc_5min_maker.py` should be understood as incomplete. The target shape is:

- Chainlink price as candle-open and current settlement-aligned state
- Binance price as auxiliary basis and flow context
- explicit staleness checks on both surfaces

Future sessions should not mistake the current stub for finished oracle alignment.

### 2.2 BTC5 decision artifacts should log structural and execution decomposition

The BTC5 learning loop should persist, at minimum:

- oracle delta from open
- time remaining
- oracle volatility estimate
- baseline probability `q_base`
- calibrated probability `q_model`
- fill-conditioned probability `q_fill`
- predicted fill probability `f`
- join/improve flag
- queue-ahead proxy
- Binance-vs-Chainlink basis
- time bucket and minute-of-hour bucket

That logging should land before major model complexity lands.

### 2.3 Deribit IV data is a logging feature, not a trade trigger yet

The newly deployed Deribit IV feed belongs in the BTC5 dataset as explanatory context first.

Future LLMs should:

- log it
- correlate it
- only promote it into trade filters after offline evidence survives

Do not let the presence of a live IV feed turn into premature feature enthusiasm.

### 2.4 Autoresearch should optimize calibration and fill-conditioned EV, not only skip counts

The autoresearch loop should gradually shift from "reduce skips" to:

- improve bucketed calibration
- improve fill-rate realism
- improve filled-trade EV
- reject parameter moves that merely increase activity without improving economics

DISPATCH 112 remains correct that skip-starvation matters. This packet sharpens what "better" means after fills begin.

## 3. Deferred Or Rejected Ideas

These ideas may be interesting later, but they should not become primary doctrine now.

### 3.1 Do not jump straight to nonlinear models

LightGBM, boosted trees, or ensembles may help later, but future sessions should not deploy them into BTC5 until:

- the diffusion-style baseline is live
- the residual logistic model is live
- walk-forward calibration proves the simpler stack is leaving measurable edge behind

### 3.2 Do not use Binance as a proxy label

Binance belongs in features, not labels.

Any future shortcut that computes BTC5 win/loss from Binance-only open/close should be treated as wrong for live doctrine, even if it is convenient for quick backtests.

### 3.3 Do not trade on raw directional probability without fill conditioning

A maker rule like "buy whenever `q > price`" is incomplete.

Future LLMs should treat raw `q - p` rules as acceptable only for degraded-mode logging or toy baselines, not for canonical BTC5 execution logic.

### 3.4 Do not overfit to academic-seeming calibration machinery too early

Venn-Abers, conformal wrappers, and heavier uncertainty methods are not the next bottleneck.

The next bottlenecks are:

- settlement truth alignment
- fill replay
- adverse-selection measurement
- bucketed calibration logging

## 4. Implementation Order For Future Sessions

Future LLMs should implement this report in the following order:

1. **Truth plumbing**
   Make BTC5 candle state Chainlink-first and retain Binance as basis/microstructure context.
2. **Feature logging**
   Persist structural baseline inputs, fill-model inputs, and bucket IDs into BTC5 decision rows.
3. **Baseline model**
   Add the diffusion-style baseline and evaluate it by time-to-close bucket.
4. **Residual model + calibration**
   Add a compact regularized logistic residual model and beta-calibrate it on rolling holdout slices.
5. **Fill replay + fill model**
   Learn queue/fill probability and fill-conditioned outcome adjustments from logged and replayed data.
6. **Promotion discipline**
   Promote only on positive filled-trade economics after calibration and fill realism both survive.

## 5. Repo Touchpoints

The main existing touchpoints for this doctrine are:

- `bot/btc_5min_maker.py`
- `bot/btc5_core_utils.py`
- `scripts/run_btc5_autoresearch_cycle_core.py`
- `research/dispatches/DISPATCH_110: RTDS Latency Surface Measurement Harness`
- `research/dispatches/DISPATCH_112_btc5_down_maker_execution_fix.md`
- `research/deep_research_packets/09_CHATGPT_PRO_BTC5_ARCHITECTURE_FOCUS_REPAIR_PACKET.md`

This packet is not a second control plane. It is the canonical saved summary of how the March 23 BTC5 probability-model report changes the design doctrine.

## 6. What Future LLMs Should Say In One Sentence

If a future session needs the shortest possible BTC5 modeling doctrine, use this:

**Model the contract on Chainlink truth, trade it as a maker-only fill-conditioned EV problem, start with a calibrated structural baseline plus a small residual model, and log everything before adding complexity.**
