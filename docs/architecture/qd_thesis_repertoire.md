# Quality-Diversity Thesis Repertoire

**Version:** 1.0.0
**Date:** 2026-03-22
**Author:** JJ (autonomous)
**Status:** Architecture specification — not yet implemented

## 0. Problem Statement

Elastifund tracks 131 strategies but concentrates execution on one: BTC5 maker. When BTC5 underperforms (March 10-11 drawdown, promotion gate FAIL on March 14), there is nothing warmed up and ready to absorb capital. The backlog has 99 strategies in "research pipeline" but no mechanism to keep multiple promising niches alive simultaneously. This is a monoculture failure mode.

The solution borrows from Quality-Diversity optimization (MAP-Elites, OpenEvolve, QDax): maintain a grid of diverse thesis families where each cell is valued not just for fitness but for *behavioral distinctness*. The system funds the strongest executable niche each cycle while preserving weird promising niches that might become dominant under regime change.

---

## 1. Repertoire-Slot Design

### 1.1 Slot Data Structure

Each slot in the repertoire holds one thesis family:

```
ThesisSlot:
  slot_id:              str           # e.g. "crypto_micro_5m_basis_lag"
  niche:                NicheDescriptor
  champion:             ThesisVariant  # best variant currently in this slot
  archive:              list[ThesisVariant]  # past variants (killed, superseded)
  fitness:              SlotFitness
  evidence:             EvidenceQuality
  resource_cost:        ResourceCost
  status:               enum(LIVE, SHADOW, DORMANT, INCUBATING, KILLED)
  last_evaluation_utc:  datetime
  revival_eligible:     bool
  generations:          int           # how many mutation cycles this slot has survived
```

### 1.2 Behavioral Descriptor (NicheDescriptor)

Each slot occupies a unique cell in the MAP-Elites grid. The behavioral descriptor is the tuple that defines *what niche this strategy fills*, independent of its performance:

```
NicheDescriptor:
  market_type:    enum(CRYPTO_MICRO, EVENT_BINARY, WEATHER, CROSS_PLATFORM,
                       COMBINATORIAL, POLITICAL, SPORTS, META_SYSTEM)
  time_horizon:   enum(SUB_MINUTE, MINUTES_5, MINUTES_15, HOURS, DAYS, WEEKS)
  edge_mechanism: enum(BASIS_LAG, INFORMED_FLOW, LLM_CALIBRATION, STRUCTURAL_ARB,
                       ORACLE_TIMING, COPY_TRADE, ENSEMBLE_DISAGREEMENT,
                       SEMANTIC_TRANSFER, REGIME_DETECTION, SELF_IMPROVEMENT)
```

Two strategies with the same (market_type, time_horizon, edge_mechanism) tuple compete within the same cell. Only the fittest variant occupies the champion position; the rest go to the archive or get killed.

Two strategies with *different* descriptor tuples never compete. A mediocre weather strategy does not get replaced by a better crypto strategy. Each niche is preserved independently.

### 1.3 Fitness (SlotFitness)

```
SlotFitness:
  sharpe_ratio:         float   # annualized, post-cost, post-slippage
  profit_factor:        float   # gross_wins / gross_losses
  kelly_fraction:       float   # optimal sizing signal
  max_drawdown_pct:     float   # worst peak-to-trough
  edge_per_trade_usd:   float   # average net edge after all costs
  composite_score:      float   # weighted combination (see 1.3.1)
```

#### 1.3.1 Composite Score Formula

```
composite = (
    0.30 * normalize(sharpe_ratio, clip=[-1, 5]) +
    0.20 * normalize(profit_factor, clip=[0.5, 3.0]) +
    0.20 * normalize(kelly_fraction, clip=[0, 0.25]) +
    0.15 * (1.0 - normalize(max_drawdown_pct, clip=[0, 0.50])) +
    0.15 * normalize(edge_per_trade_usd, clip=[-0.10, 1.00])
)
```

Normalize maps the value linearly to [0, 1] within the clip range.

### 1.4 Evidence Quality

```
EvidenceQuality:
  sample_size:          int     # number of resolved trades or signals
  statistical_stage:    enum(HYPOTHESIS, EXPLORATORY, PROVISIONAL, VALIDATED)
  p_value:              float   # null hypothesis: edge <= 0
  confidence_interval:  tuple[float, float]  # 95% CI on edge per trade
  data_freshness_hours: float   # hours since last observation
  is_out_of_sample:     bool    # true if validated on data not used for fitting
```

Stage thresholds:
- HYPOTHESIS: sample_size < 30, no statistical test
- EXPLORATORY: 30 <= sample_size < 100, p_value not required
- PROVISIONAL: 100 <= sample_size < 300, p_value < 0.10
- VALIDATED: sample_size >= 300, p_value < 0.05, out-of-sample confirmed

### 1.5 Resource Cost

```
ResourceCost:
  capital_required_usd:     float   # minimum position size to be meaningful
  compute_cycles_per_eval:  int     # CPU-seconds per evaluation cycle
  api_calls_per_cycle:      int     # external API calls (Gamma, CLOB, Kalshi, LLM)
  human_attention_minutes:  float   # estimated engineer time per cycle (target: 0)
  data_latency_seconds:     float   # how fast data must arrive for edge to exist
```

---

## 2. Niche Taxonomy — Required Grid Cells

The following nine niches are mandatory. The system must maintain at least one thesis variant (even if DORMANT or INCUBATING) in each cell at all times. If a cell empties, the mutation engine must generate a seed variant within 24 hours.

### N1: BTC Microstructure / RTDS (5-min crypto price)

```
descriptor: (CRYPTO_MICRO, MINUTES_5, BASIS_LAG)
modules:    bot/btc_5min_maker.py, bot/btc_5min_maker_core.py,
            bot/btc5_core_utils.py, bot/btc5_session_policy.py,
            bot/delta_calibrator.py, bot/hft_shadow_validator.py
status:     LIVE (current champion, $5/trade, promotion gate FAILED)
evidence:   PROVISIONAL (50 closed trades, 51.4% WR, PF 1.01)
key_risk:   Single-session concentration, zero-fill problem on VPS,
            delta threshold too tight for current BTC volatility
```

### N2: Weather / Official-Truth Event Markets

```
descriptor: (WEATHER, HOURS, LLM_CALIBRATION)
modules:    bot/kalshi/*, bot/kalshi_opportunity_scanner.py,
            bot/thesis_foundry.py (weather shadow path)
status:     INCUBATING (shadow mode, no live capital)
evidence:   HYPOTHESIS (R10 rejected NWS rounding, but Kalshi $100 funded)
key_risk:   NWS data resolution too coarse for bracket arb,
            need alternative data sources (ECMWF, GFS ensemble)
```

### N3: Cross-Platform Arbitrage (Polymarket vs Kalshi)

```
descriptor: (CROSS_PLATFORM, HOURS, STRUCTURAL_ARB)
modules:    bot/cross_platform_arb.py, bot/cross_platform_arb_scanner.py,
            bot/kalshi_intraday_parity.py, bot/multi_asset_arb.py
status:     DORMANT (code complete, 29 tests passing, not deployed)
evidence:   HYPOTHESIS (no live or shadow data yet)
key_risk:   Thin liquidity on Kalshi side, settlement timing mismatch,
            regulatory divergence on market availability
```

### N4: Negative Risk / Combinatorial Arbitrage

```
descriptor: (COMBINATORIAL, HOURS, STRUCTURAL_ARB)
modules:    bot/neg_risk_scanner.py, bot/neg_risk_inventory.py,
            bot/negrisk_arb_scanner.py, bot/constraint_arb_engine.py,
            bot/sum_violation_scanner.py, bot/sum_violation_strategy.py,
            bot/combinatorial_integration.py
status:     KILLED (A-6 zero density, March 13) — but cell must not stay empty
evidence:   KILLED at 563 events, 0 executable constructions below 0.95
key_risk:   Market efficiency may have permanently closed this gap,
            but regime change (new neg-risk event types) could reopen it
revival:    Auto-scan monthly for new neg-risk event clusters. If density
            rises above 0.01 (1 executable per 100 events), re-incubate.
```

### N5: Whale Copy-Trading / Informed Flow

```
descriptor: (EVENT_BINARY, DAYS, COPY_TRADE)
modules:    bot/wallet_flow_detector.py, bot/whale_tracker.py,
            bot/smart_wallet_feed.py, bot/wallet_poller.py
status:     DORMANT (code complete B1, integration pending)
evidence:   EXPLORATORY (80 scored wallets, fast_flow_restart_ready=true)
key_risk:   Front-running risk, whale signal decay as market matures,
            latency disadvantage vs on-chain MEV bots
```

### N6: LLM Ensemble Probability Edge

```
descriptor: (EVENT_BINARY, DAYS, LLM_CALIBRATION)
modules:    bot/llm_ensemble.py, bot/llm_tournament.py,
            bot/ensemble_estimator.py, bot/debate_pipeline.py,
            bot/conformal_calibration.py, bot/adaptive_platt.py
status:     LIVE (D1 deployed, 71.2% WR on 532 markets, Platt calibrated)
evidence:   VALIDATED (532 markets, Brier 0.2134, walk-forward confirmed)
key_risk:   Model degradation as LLM training data includes prediction
            market prices, calibration drift over time
```

### N7: Semantic Leader-Follower

```
descriptor: (EVENT_BINARY, HOURS, SEMANTIC_TRANSFER)
modules:    bot/semantic_leader_follower.py, bot/lead_lag_engine.py,
            bot/causal_lead_lag.py, bot/disagreement_signal.py
status:     INCUBATING (B-1 template engine killed, but causal_lead_lag alive)
evidence:   HYPOTHESIS (Granger causality framework built, no live signals)
key_risk:   Spurious correlations survive statistical tests but fail
            economically, semantic verification adds latency
```

### N8: Resolution Sniping / Oracle Timing

```
descriptor: (CRYPTO_MICRO, SUB_MINUTE, ORACLE_TIMING)
modules:    bot/resolution_sniper.py, bot/resolution_normalizer.py
status:     DORMANT (code built, not tested live)
evidence:   HYPOTHESIS (theoretical edge from Chainlink oracle latency)
key_risk:   Chainlink updates may be too fast for maker execution,
            Polymarket may change resolution mechanics
```

### N9: Architecture-Improvement Cells (Meta-Strategies)

```
descriptor: (META_SYSTEM, WEEKS, SELF_IMPROVEMENT)
modules:    bot/parameter_evolution.py, bot/reflexion_memory.py,
            bot/research_rag.py, bot/symbolic_alpha.py,
            bot/autoresearch_loop.py, bot/auto_stage_gate.py
status:     LIVE (parameter_evolution active on BTC5, autoresearch 1 cycle)
evidence:   EXPLORATORY (1 autoresearch cycle completed, CMA-ES running)
key_risk:   Over-fitting to recent regime, meta-optimization on too-small
            sample sizes, infinite regress (optimizing the optimizer)
```

---

## 3. Mutation/Evaluation Loop

### 3.1 Variant Generation

Three mutation operators run each cycle, inspired by evolutionary QD algorithms:

#### 3.1.1 Parameter Mutation (exploitation)

For each LIVE or SHADOW slot, generate 2-3 parameter variants using the existing `bot/parameter_evolution.py` CMA-ES engine:

```
Input:  champion variant's parameter vector
Output: 2-3 nearby variants (gaussian perturbation, sigma from CMA-ES covariance)
Scope:  thresholds, time-of-day filters, directional biases, sizing fractions
Cost:   near-zero (numeric only)
```

Example for N1 (BTC5): mutate BTC5_MAX_ABS_DELTA from 0.0035 to {0.0040, 0.0050, 0.0060}, mutate hour-of-day filter window, mutate DOWN-only vs bidirectional.

#### 3.1.2 Crossover (structural recombination)

Combine components from two different niches to create a hybrid variant:

```
Input:  two parent slots from different niches
Output: 1 hybrid variant placed in whichever parent's niche it behaviorally matches
Scope:  signal combination (e.g., whale flow + LLM calibration), feature sharing
Cost:   moderate (requires integration testing)
```

Example: combine N5 whale-flow signal with N6 LLM calibration to create a "whale-informed LLM" variant in the N6 cell.

#### 3.1.3 LLM-Guided Search (exploration)

Use the research RAG system (`bot/research_rag.py`) and autoresearch loop (`bot/autoresearch_loop.py`) to propose entirely new thesis variants:

```
Input:  current repertoire state + market regime + recent failures
Output: 0-2 novel thesis variants for empty or underperforming cells
Scope:  new edge hypotheses, new data sources, new market types
Cost:   high (LLM API calls, research time)
Trigger: runs when any cell has been DORMANT > 7 days or KILLED > 30 days
```

The LLM search prompt includes: "Given that niche X has been dormant for Y days and the current market regime is Z, propose a concrete thesis variant that could occupy this cell. The variant must specify: entry signal, exit signal, sizing rule, expected edge magnitude, and minimum data requirements."

### 3.2 Evaluation Pipeline

All variants pass through a four-stage evaluation funnel. Each stage is progressively more expensive and more selective.

```
Stage 1: BACKTEST (cost: minutes, compute only)
  - Historical data replay against resolved markets
  - Minimum 50 signals required to proceed
  - Kill if: Sharpe < 0, profit_factor < 0.8, or max_drawdown > 40%
  - Existing infra: src/strategies/*.py, src/models/*.py

Stage 2: SHADOW TRADE (cost: hours-days, no capital)
  - Paper-trade against live markets using bot/shadow_runner.py
  - Record hypothetical fills, slippage, and timing
  - Minimum 100 shadow trades to proceed
  - Kill if: fill_rate < 10% (maker), or edge_per_trade < $0.01

Stage 3: MICRO-LIVE (cost: days, minimal capital)
  - Deploy with $1-5 per trade, real orders
  - Uses auto_stage_gate.py for position sizing
  - Minimum 50 live fills to proceed
  - Kill if: realized_sharpe < 0.5, or 5 consecutive losses, or PnL < -$25

Stage 4: SCALED LIVE (cost: ongoing, full allocation)
  - Promotion via stage gate (DISPATCH_102 criteria)
  - Capital allocation determined by Resource Auction (Section 4)
  - Continuous monitoring via kill_rules.py
  - Demotion triggers: 3-day rolling Sharpe < 0, drawdown > 20% of allocation
```

### 3.3 Kill Rules

A variant is killed (removed from champion position) when any of these fire:

| Rule | Threshold | Cooldown |
|------|-----------|----------|
| Insufficient signals after 7 days | sample_size < 30 | N/A (permanent for this variant) |
| Negative OOS expected value | edge_per_trade < 0 after costs | Re-test after 30 days |
| Drawdown breach | max_dd > 25% of slot allocation | Immediate demotion to SHADOW |
| Semantic decay | lead-lag coherence < 0.3 | Re-test after regime change |
| Toxicity survival failure | dies in top-decile VPIN | Re-test after 14 days |
| Calibration drift | Platt residual > 0.05 | Recalibrate, re-test |
| Stale data | no new observations in 48 hours | Pause, do not kill |
| Cost stress | fee structure change eliminates edge | Kill unless maker rebate restores it |

A killed variant moves to the slot's archive. The slot itself is NOT killed unless every variant in the archive has been killed AND no new variant can be generated. Even then, the cell remains with status KILLED and revival_eligible=true.

### 3.4 Revival Rules

A killed niche is automatically re-tested when any of these conditions are met:

| Trigger | Action |
|---------|--------|
| Regime change detected (bot/regime_detector.py) | Re-evaluate all KILLED slots in affected market_type |
| New data source becomes available | Re-seed HYPOTHESIS variant in relevant cells |
| 30-day calendar trigger | Run LLM-guided search (3.1.3) for all KILLED cells |
| Fee structure change (e.g., new maker rebate) | Re-evaluate all cost-stress kills |
| New market type appears on platform | Create new cell if no existing niche covers it |
| Cross-niche signal detected | If niche A's signal predicts niche B's edge, revive B |

Revival does NOT skip evaluation stages. A revived variant enters at Stage 1 (BACKTEST) and must survive the full funnel again.

---

## 4. Resource Auction Logic

### 4.1 Capital Allocation

The total trading capital is split into three pools:

```
EXPLOIT_POOL:      70% of capital — allocated to LIVE slots by fitness rank
EXPLORE_POOL:      20% of capital — allocated to SHADOW and MICRO-LIVE slots
RESERVE_POOL:      10% of capital — uninvested cash buffer (drawdown protection)
```

These ratios are the default. They shift based on system confidence:

```
if avg_slot_sharpe > 2.0:    # high confidence regime
    EXPLOIT = 75%, EXPLORE = 20%, RESERVE = 5%
elif avg_slot_sharpe < 0.5:  # low confidence regime
    EXPLOIT = 50%, EXPLORE = 25%, RESERVE = 25%
else:                         # normal regime
    EXPLOIT = 70%, EXPLORE = 20%, RESERVE = 10%
```

### 4.2 Exploit Pool Auction

Within the EXPLOIT_POOL, capital is allocated proportionally to composite fitness, with caps:

```
For each LIVE slot s:
    raw_share[s] = composite_score[s] / sum(composite_score for all LIVE slots)
    capped_share[s] = min(raw_share[s], MAX_SINGLE_NICHE_SHARE)

# Redistribute excess from capping
excess = sum(max(0, raw_share[s] - MAX_SINGLE_NICHE_SHARE) for all s)
uncapped_slots = [s for s in LIVE if raw_share[s] < MAX_SINGLE_NICHE_SHARE]
for s in uncapped_slots:
    capped_share[s] += excess * (raw_share[s] / sum(raw_share[u] for u in uncapped_slots))

allocation[s] = EXPLOIT_POOL * capped_share[s]
```

**MAX_SINGLE_NICHE_SHARE = 0.40** (no single niche gets more than 40% of exploit capital, i.e., 28% of total capital). This is the anti-monoculture constraint. Even if BTC5 has a Sharpe of 5.0 and everything else is mediocre, it caps at 40% of the exploit pool.

At current capital ($390.90):
- Exploit pool: $273.63
- Max single niche: $109.45
- Explore pool: $78.18
- Reserve: $39.09

### 4.3 Explore Pool Auction

The EXPLORE_POOL is allocated by *information value*, not fitness. The goal is to maximize the rate at which INCUBATING and SHADOW slots reach PROVISIONAL evidence:

```
For each non-LIVE slot s:
    info_value[s] = (
        0.40 * niche_uniqueness[s] +        # how different is this from LIVE slots
        0.30 * (1 / data_freshness_hours) +  # staler data = higher priority
        0.20 * prior_promise[s] +            # best historical fitness before kill
        0.10 * cheapness[s]                  # inverse of resource cost
    )

allocation[s] = EXPLORE_POOL * (info_value[s] / sum(info_value))
```

**niche_uniqueness** is the Hamming distance of the slot's NicheDescriptor from the nearest LIVE slot's descriptor. A weather strategy when all LIVE slots are crypto gets uniqueness = 3 (all three descriptor axes differ). This biases exploration toward *structurally different* strategies.

### 4.4 Compute and Attention Allocation

Compute and LLM API budgets follow the same 70/20/10 split but with different caps:

```
LLM API calls per day (budget: ~$5/day at current rates):
  EXPLOIT slots: up to 50 calls/day each (calibration, ensemble, debate)
  EXPLORE slots: up to 20 calls/day each (hypothesis generation, shadow eval)
  META slots:    up to 30 calls/day (autoresearch, parameter evolution)

Compute cycles (CPU-seconds per hour):
  EXPLOIT slots: unlimited (they generate revenue)
  EXPLORE slots: capped at 300 CPU-sec/hour each
  META slots:    capped at 600 CPU-sec/hour total
```

### 4.5 Anti-Concentration Rules (The March 15 Problem)

The system that existed on March 15 had 100% of capital and attention on BTC5. These rules prevent that from recurring:

1. **Minimum niche count:** At least 2 slots must be LIVE or SHADOW at all times. If only 1 slot is LIVE and 0 are SHADOW, the system must promote the highest-fitness DORMANT slot to SHADOW within 24 hours.

2. **Correlation cap:** If two LIVE slots have a return correlation > 0.70 over their shared observation window, they are treated as one slot for allocation purposes. The weaker one gets demoted to SHADOW.

3. **Regime diversity:** At least one LIVE or SHADOW slot must have market_type != CRYPTO_MICRO. The system cannot be 100% crypto.

4. **Staleness penalty:** A LIVE slot whose data_freshness_hours > 72 gets its composite score halved for allocation purposes. This prevents a stale-but-historically-good strategy from hoarding capital.

5. **Drawdown redistribution:** When a LIVE slot hits a 15% drawdown, 50% of its allocation moves to the RESERVE_POOL for 48 hours before being re-auctioned.

---

## 5. Integration with Existing Infrastructure

### 5.1 Module Mapping

| QD Component | Existing Module | Gap |
|-------------|----------------|-----|
| Repertoire storage | None | New: `data/qd_repertoire.json` |
| Niche descriptors | `edge_backlog_ranked.md` (manual) | New: structured NicheDescriptor in each slot |
| Fitness evaluation | `bot/kill_rules.py`, `bot/auto_stage_gate.py` | Extend: add composite score computation |
| Parameter mutation | `bot/parameter_evolution.py` | Ready: CMA-ES already implemented |
| Shadow evaluation | `bot/shadow_runner.py` | Ready: needs wiring to repertoire |
| LLM-guided search | `bot/autoresearch_loop.py`, `bot/research_rag.py` | Extend: target empty/killed cells |
| Regime detection | `bot/regime_detector.py` | Ready: needs revival trigger wiring |
| Lane supervision | `bot/lane_supervisor.py`, `bot/thesis_foundry.py` | Extend: replace per-lane logic with per-cell logic |
| Capital allocation | `bot/jj_live.py` (hardcoded) | New: auction logic replaces hardcoded sizing |
| Kill rules | `bot/kill_rules.py` | Ready: add slot-level demotion logic |

### 5.2 Artifact Structure

```
data/qd_repertoire.json          # Master repertoire state (read/written each cycle)
data/qd_auction_log.jsonl        # Append-only log of every allocation decision
data/qd_variant_archive/         # One JSON per killed variant (forensic record)
reports/qd_diversity_report.json  # Per-cycle diversity metrics
```

### 5.3 Cycle Timing

```
Every 30 minutes:  LIVE slots execute (existing scan loop)
Every 6 hours:     SHADOW slots evaluate (shadow_runner batch)
Every 24 hours:    Mutation cycle (generate variants, run Stage 1 backtests)
Every 7 days:      Full repertoire audit (check all cells, trigger revivals)
Every 30 days:     LLM-guided search for KILLED cells
```

---

## 6. Success Metrics

The repertoire is healthy when:

| Metric | Target | Current (March 22) |
|--------|--------|-------------------|
| Cells with LIVE or SHADOW status | >= 3 | 2 (N1 BTC5 LIVE, N6 LLM LIVE) |
| Cells with INCUBATING or better | >= 5 | 3 (N1, N6, N9) |
| Empty cells (no variant at all) | 0 | 0 (all seeded) |
| Max single-niche capital share | <= 40% | ~95% (BTC5 dominates) |
| Explore pool utilization | >= 50% | ~0% (no shadow trading) |
| Variants evaluated per week | >= 10 | ~1 (autoresearch) |
| Mean time from HYPOTHESIS to PROVISIONAL | <= 14 days | unknown |
| Regime-change revival coverage | 100% of KILLED cells checked | 0% |

The first implementation milestone is reaching 3 LIVE-or-SHADOW slots and <50% capital concentration in any single niche. At current capital ($390.90), that means no single strategy controls more than ~$110.

---

*This document defines the repertoire architecture. Implementation requires: (1) `data/qd_repertoire.json` schema and persistence, (2) auction logic in a new `bot/qd_auction.py`, (3) wiring mutation operators to existing modules, (4) cycle scheduler integration. Estimated: 3-5 engineering sessions.*
