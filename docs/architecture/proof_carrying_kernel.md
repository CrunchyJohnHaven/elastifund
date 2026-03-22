# Proof-Carrying Kernel: Canonical Architecture

**Status:** DEFINITIVE -- this is the system-of-record for decision authority
**Author:** JJ (autonomous)
**Date:** 2026-03-22
**Scope:** All bot/ modules, all execution paths, all learning loops

---

## 0. The Problem This Solves

The repo has 97 Python files in bot/. Eighteen were added in one session.
Multiple modules claim overlapping decision authority:

- `jj_live.py` decides what to trade and how much.
- `enhanced_pipeline.py` runs a 7-phase decision pipeline that also decides what to trade.
- `auto_promote.py` rewrites .env parameters that change what gets traded.
- `parameter_evolution.py` evolves parameters that also change what gets traded.
- `btc_5min_maker.py` runs its own independent execution loop with its own sizing logic.
- `auto_stage_gate.py` promotes capital stages, changing position sizes.

Result: no single proof-to-capital pathway. A learning-layer change (parameter_evolution)
can widen live risk (via auto_promote) without passing through the constraint engine
(agent_constraints) or the kill rules (kill_rules). Capital is deployed without traceable
evidence chains.

The Proof-Carrying Kernel eliminates this by defining exactly four bundles, assigning
every module to exactly one bundle, and enforcing that capital deployment requires a
complete proof chain through all four.

---

## 1. The Four Authoritative Bundles

### 1.1 Evidence Bundle

**Question answered:** "What do we observe about the world right now?"

**Authority:** Produces typed evidence records. NO trade decisions. NO parameter changes.
Evidence records are immutable once emitted -- downstream consumers may discard them,
but never mutate them.

**Proof surface:** Every evidence record carries:
```
EvidenceRecord {
    source_module: str          # e.g. "whale_tracker"
    evidence_type: str          # e.g. "consensus_signal", "book_snapshot", "price_delta"
    timestamp_utc: float        # when observed
    staleness_limit_s: float    # after this many seconds, record is dead
    payload: dict               # source-specific data
    confidence: float           # [0,1] self-assessed reliability
    hash: str                   # SHA-256 of (source_module + timestamp + payload)
}
```

No downstream module may act on evidence that has exceeded its staleness_limit_s.

**Modules in this bundle:**

| Module | Evidence Type | Staleness Limit |
|--------|--------------|-----------------|
| `ensemble_estimator.py` | LLM probability estimate (Platt-calibrated) | 300s |
| `llm_tournament.py` | Multi-model consensus + divergence score | 300s |
| `ws_trade_stream.py` | VPIN + Multi-Level OFI from WebSocket feed | 30s |
| `hawkes_order_flow.py` | Hawkes cascade intensity + self-excitation score | 60s |
| `whale_tracker.py` | Whale alert + consensus signal | 120s |
| `smart_wallet_feed.py` | Smart wallet directional flow | 120s |
| `neg_risk_scanner.py` | Negative-risk arb opportunities | 60s |
| `cross_platform_arb_scanner.py` | Cross-platform price discrepancies | 30s |
| `resolution_sniper.py` | Stale/known-outcome market detection | 600s |
| `vpin_toxicity.py` | Volume-synchronized PIN toxicity score | 30s |
| `momentum_detector.py` | Momentum regime signal | 60s |
| `momentum_streak.py` | Consecutive directional streak count | 60s |
| `wallet_flow_detector.py` | On-chain flow anomalies | 120s |
| `disagreement_signal.py` | Inter-model disagreement magnitude | 300s |
| `lead_lag_engine.py` | Granger-causal cross-market signal | 600s |
| `causal_lead_lag.py` | Causal lead-lag with semantic verification | 600s |
| `spread_capture.py` | Bid-ask spread opportunity | 15s |
| `clob_ws_client.py` | Raw order book snapshots | 10s |
| `gamma_market_cache.py` | Cached market metadata from Gamma API | 3600s |
| `relation_cache.py` | Cached condition-to-market mappings | 3600s |
| `relation_classifier.py` | Market relationship classification | 3600s |
| `semantic_leader_follower.py` | Semantic similarity between market pairs | 1800s |
| `pm_fast_market_registry.py` | Fast-market (sub-24h) registry | 600s |
| `research_rag.py` | Dispatch-archive retrieval context | 7200s |
| `delta_calibrator.py` | BTC delta calibration statistics | 300s |
| `cross_asset_arb.py` | Cross-crypto-asset confirmation signal | 60s |
| `cross_asset_history.py` | Historical cross-asset correlation data | 86400s |
| `cascade_max.py` | Cascade event detection for BTC5 | 60s |
| `multi_asset_arb.py` | Multi-asset directional confirmation | 60s |
| `kalshi_opportunity_scanner.py` | Kalshi market opportunity data | 600s |
| `kalshi_intraday_parity.py` | Kalshi vs Polymarket intraday price parity | 60s |

### 1.2 Thesis Bundle

**Question answered:** "Given evidence, what specific trade hypothesis do we hold, and how confident are we?"

**Authority:** Produces versioned ThesisRecord objects. A thesis is the ONLY artifact
that can enter the Promotion Bundle. No raw evidence, no ad-hoc signal, no LLM
suggestion bypasses this.

**Proof surface:** Every thesis carries its full evidence chain:
```
ThesisRecord {
    thesis_id: str              # deterministic hash of hypothesis params
    version: int                # increments on any parameter change
    hypothesis: str             # human-readable description
    strategy_class: str         # "btc5_directional" | "event_maker" | "neg_risk" | ...
    evidence_refs: list[str]    # hashes of EvidenceRecords that support this thesis
    calibrated_probability: float
    confidence_interval: tuple[float, float]  # from conformal calibration
    edge_estimate: float        # calibrated_prob - market_price (or vice versa)
    regime_context: str         # "stable" | "transition" | "crisis"
    kill_rule_results: KillResult  # from kill_rules.py -- PASS or specific failure
    created_utc: float
    expires_utc: float          # thesis has a shelf life
}
```

A thesis with `kill_rule_results.passed == False` is dead. It cannot be resurrected
without a new version number and new evidence.

**Modules in this bundle:**

| Module | Role |
|--------|------|
| `enhanced_pipeline.py` | **SOLE THESIS AUTHORITY for event markets.** Runs 7-phase pipeline (calibrate, regime, toxicity, enrich, causal, constrain, decide). Consumes evidence records, emits ThesisRecord. |
| `btc5_core_utils.py` | **SOLE THESIS AUTHORITY for BTC5 markets.** Contains delta/direction/pricing logic. Consumed by btc_5min_maker.py. |
| `btc5_session_policy.py` | Session-level policy (time-of-day, direction bias) for BTC5 theses. Modifies thesis parameters, does not create theses independently. |
| `thesis_foundry.py` | Converts shadow artifacts from multiple lanes into ranked ThesisRecord candidates. |
| `conformal_calibration.py` | Wraps Platt scaling with ACI intervals. Annotates thesis with confidence_interval. Does not create theses. |
| `regime_detector.py` | BOCPD regime detection. Annotates thesis with regime_context. Does not create theses. |
| `ensemble_toxicity.py` | Aggregated toxicity gate. Annotates thesis with toxicity_survived flag. Does not create theses. |
| `kill_rules.py` | **VETO AUTHORITY.** Can kill any thesis. Cannot create or promote theses. |
| `adaptive_platt.py` | Adaptive Platt recalibration. Feeds updated A/B coefficients to thesis pipeline. |
| `adaptive_floor.py` | Adaptive price floor for BTC5. Feeds floor parameter to btc5_core_utils. |
| `symbolic_alpha.py` | GP-evolved alpha expressions. Proposes new thesis parameters via evolved formulas. |
| `synergistic_signals.py` | RL-based signal combination. Proposes optimal signal weights for thesis construction. |
| `combinatorial_integration.py` | Combines multiple strategy signals. Feeds composite signal to thesis pipeline. |
| `lmsr_engine.py` | LMSR pricing model. Provides alternative probability anchor for thesis calibration. |

**Critical constraint:** `enhanced_pipeline.py` and `btc5_core_utils.py` are the only
two modules that may emit a ThesisRecord. All other Thesis Bundle modules are annotators
or parameter feeders. This eliminates the current problem where jj_live.py, btc_5min_maker.py,
and enhanced_pipeline.py all independently decide whether to trade.

### 1.3 Promotion Bundle

**Question answered:** "Has this thesis earned the right to deploy capital?"

**Authority:** The Promotion Bundle is the ONLY path from thesis to execution. It
produces a PromotionTicket -- the single artifact that the execution layer accepts.

**Proof surface:**
```
PromotionTicket {
    ticket_id: str
    thesis_ref: str             # hash of the ThesisRecord
    evidence_refs: list[str]    # inherited from thesis
    constraint_result: ConstraintResult  # from agent_constraints.py
    stage_gate_result: dict     # from auto_stage_gate.py (capital tier)
    position_size_usd: float    # final, post-constraint size
    max_loss_usd: float         # worst-case loss for this position
    execution_mode: str         # "live" | "shadow" | "paper"
    approved_utc: float
    expires_utc: float          # ticket expires if not executed within window
    promotion_path: str         # "standard" | "autoresearch" | "manual_escalation"
}
```

**Modules in this bundle:**

| Module | Role |
|--------|------|
| `agent_constraints.py` | **CONSTRAINT AUTHORITY.** Evaluates every trade proposal against executable safety rails. Can BLOCK, MODIFY (cap size), or ESCALATE. Sub-millisecond, no I/O. |
| `auto_stage_gate.py` | **CAPITAL TIER AUTHORITY.** Determines current capital stage (e.g., $5/trade vs $10/trade) based on aggregate fill history, win rate, consecutive losses, and balance. |
| `auto_promote.py` | **PARAMETER PROMOTION AUTHORITY.** Promotes shadow hypothesis parameters to live config. Rate-limited (1/24h). Safety-capped (min buy price >= 0.80, max trade <= $25). |
| `autoresearch_loop.py` | Generates and shadow-tests parameter hypotheses. Feeds candidates to auto_promote.py. Does NOT promote directly. |
| `lane_supervisor.py` | Routes thesis candidates to execution lanes (BTC5 live, weather shadow, etc.). Does not size positions or approve capital. |
| `execution_readiness.py` | Pre-flight checks (Polymarket maintenance window, CLOB connectivity). Binary go/no-go. |
| `pricing_evolution.py` | Evolves pricing parameters within autoresearch. Feeds to auto_promote. Does NOT apply changes directly. |

**Critical constraint:** `agent_constraints.py` has VETO power over every PromotionTicket.
No ticket can be issued if the ConstraintEngine returns BLOCK. The constraint engine
runs AFTER auto_stage_gate determines the capital tier, ensuring that a stage promotion
cannot bypass position limits.

**The parameter_evolution firewall:** `parameter_evolution.py` (Learning Bundle) proposes
parameter changes. Those changes flow to `autoresearch_loop.py` (Promotion Bundle) which
shadow-tests them. Only `auto_promote.py` (Promotion Bundle) can apply them to live config,
and only after passing `safety_check()` with immutable caps. This is the firewall that
prevents learning-layer changes from widening live risk.

### 1.4 Learning Bundle

**Question answered:** "What did we learn, and how does it improve future performance?"

**Authority:** Writes to memory stores and proposes parameter changes. NEVER writes to
live config directly. NEVER sizes positions. NEVER places orders.

**Proof surface:**
```
LearningRecord {
    trade_id: str
    thesis_ref: str             # which thesis drove this trade
    ticket_ref: str             # which promotion ticket authorized it
    outcome: str                # "win" | "loss" | "cancelled" | "expired"
    actual_pnl_usd: float
    predicted_edge: float
    actual_edge: float
    reflection: str             # natural-language self-critique
    parameter_proposals: list[dict]  # suggested changes for autoresearch
    calibration_update: dict    # new nonconformity score for conformal calibration
    written_utc: float
}
```

**Modules in this bundle:**

| Module | Role |
|--------|------|
| `reflexion_memory.py` | **EPISODIC MEMORY AUTHORITY.** Stores and retrieves trade reflections via TF-IDF similarity. Feeds context to Evidence Bundle (ensemble_estimator prompt enrichment). |
| `parameter_evolution.py` | **PARAMETER PROPOSAL AUTHORITY.** CMA-ES optimizer that proposes parameter changes. Outputs proposals only -- never applies them. |
| `wallet_reconciliation.py` | **WALLET TRUTH AUTHORITY.** Mirrors on-chain wallet state to SQLite. Provides ground-truth P&L that overrides all local ledger calculations. |
| `fill_tracker.py` | Tracks order fills and outcomes. Feeds to reflexion_memory and wallet_reconciliation. |
| `wallet_poller.py` | Polls wallet balance. Feeds to wallet_reconciliation. |
| `position_merger.py` | Merges fragmented position records. Feeds clean position data to learning pipeline. |
| `position_redeemer.py` | Redeems resolved positions. Feeds outcome data to fill_tracker. |

---

## 2. Execution Layer (Not a Bundle)

The execution layer is a CONSUMER of PromotionTickets. It has no decision authority --
it mechanically converts tickets into orders. If it cannot execute (CLOB down, insufficient
balance, order rejected), it reports failure. It does not re-decide.

| Module | Role |
|--------|------|
| `jj_live.py` | **PRIMARY EXECUTOR for event markets.** Receives PromotionTicket from enhanced_pipeline path. Places post-only maker orders via CLOB. Reports fill/no-fill to Learning Bundle. |
| `jj_live_core.py` | Core execution utilities shared by jj_live.py. |
| `jj_live_runtime_settings.py` | Runtime parameter loading for jj_live.py. |
| `jj_live_signal_sources.py` | Signal source wiring for jj_live.py. Connects Evidence Bundle outputs to enhanced_pipeline input. |
| `btc_5min_maker.py` | **PRIMARY EXECUTOR for BTC5 markets.** Receives PromotionTicket from btc5_core_utils path. Places post-only maker orders at T-10s. Reports fill/no-fill to Learning Bundle. |
| `btc_5min_maker_core.py` | Core execution utilities shared by btc_5min_maker.py. |
| `polymarket_clob.py` | Authenticated CLOB client. Pure I/O -- no decisions. |
| `polymarket_runtime.py` | Runtime helpers (balance check, order status). Pure I/O. |
| `polymarket_fastlane_surface.py` | Fast-path order submission. Pure I/O. |
| `shadow_runner.py` | Shadow execution (paper trading). Same interface as live, no real orders. |
| `hft_shadow_validator.py` | Validates shadow fills against real book state. |

---

## 3. Renderer Layer (Not a Bundle)

Renderers observe system state and produce human-readable output. They have zero
decision authority and zero write access to any proof surface.

| Module | Role |
|--------|------|
| `edge_scan_report.py` | Generates edge scan reports for human review. |
| `elastic_client.py` | Ships telemetry to Elasticsearch. |
| `elastic_dashboards.py` | Dashboard configuration for Kibana. |
| `elastic_ml_setup.py` | ML job setup in Elasticsearch. |
| `apm_setup.py` | Application Performance Monitoring setup. |
| `latency_tracker.py` | Tracks and reports execution latency. |
| `log_config.py` | Logging configuration. |
| `health_monitor.py` | Heartbeat writer for systemd watchdog. |
| `runtime_profile.py` | Profile loading and validation. |
| `dependency_graph.py` | Module dependency analysis. |
| `expanded_scanner.py` | Market scanning report generation. |
| `maker_velocity_blitz.py` | Velocity scoring report. |
| `market_quarantine.py` | Quarantine list management (advisory, not enforced here). |

---

## 4. Retired / Subsumed Modules

These modules had overlapping authority with bundle-authoritative modules. Under the
kernel, their logic is subsumed.

| Module | Disposition |
|--------|-------------|
| `a6_command_router.py` | RETIRED. A-6 strategy killed (DISPATCH, March 13). Dead code. |
| `a6_executor.py` | RETIRED. A-6 strategy killed. |
| `a6_sum_scanner.py` | RETIRED. Subsumed by neg_risk_scanner.py (Evidence Bundle). |
| `b1_executor.py` | RETIRED. B-1 strategy killed (DISPATCH, March 13). Dead code. |
| `b1_monitor.py` | RETIRED. B-1 strategy killed. |
| `b1_template_engine.py` | RETIRED. B-1 strategy killed. |
| `anomaly_consumer.py` | SUBSUMED. Anomaly detection folded into ensemble_toxicity.py. |
| `sum_violation_scanner.py` | SUBSUMED by neg_risk_scanner.py. |
| `sum_violation_strategy.py` | SUBSUMED by neg_risk_scanner.py. |
| `constraint_arb_engine.py` | SUBSUMED by cross_platform_arb_scanner.py. |
| `negrisk_arb_scanner.py` | SUBSUMED by neg_risk_scanner.py. |
| `debate_pipeline.py` | SUBSUMED by llm_tournament.py (same multi-model approach, tournament is newer). |
| `llm_ensemble.py` | SUBSUMED by ensemble_estimator.py. |
| `neg_risk_inventory.py` | SUBSUMED by wallet_reconciliation.py position tracking. |
| `cross_platform_arb.py` | SUBSUMED by cross_platform_arb_scanner.py (scanner is the canonical version). |

---

## 5. Stage-Authority Table (Complete)

Every module, one row, no ambiguity.

```
AUTHORITATIVE = makes decisions that affect capital deployment or system parameters
FEEDER        = provides data to authoritative modules; no decision authority
RENDERER      = displays, logs, or alerts; zero write access to proof surfaces
RETIRED       = dead code, should be deleted
SUBSUMED      = logic folded into another module, should be deleted
```

| # | Module | Bundle | Authority | Decision It Makes |
|---|--------|--------|-----------|-------------------|
| 1 | `enhanced_pipeline.py` | Thesis | AUTHORITATIVE | Sole thesis emitter for event markets |
| 2 | `btc5_core_utils.py` | Thesis | AUTHORITATIVE | Sole thesis emitter for BTC5 markets |
| 3 | `kill_rules.py` | Thesis | AUTHORITATIVE | Veto authority -- can kill any thesis |
| 4 | `agent_constraints.py` | Promotion | AUTHORITATIVE | Constraint enforcement -- BLOCK/MODIFY/ALLOW |
| 5 | `auto_stage_gate.py` | Promotion | AUTHORITATIVE | Capital tier promotion/demotion |
| 6 | `auto_promote.py` | Promotion | AUTHORITATIVE | Parameter promotion to live config |
| 7 | `jj_live.py` | Execution | AUTHORITATIVE | Order placement for event markets |
| 8 | `btc_5min_maker.py` | Execution | AUTHORITATIVE | Order placement for BTC5 markets |
| 9 | `wallet_reconciliation.py` | Learning | AUTHORITATIVE | Wallet truth (overrides all local ledgers) |
| 10 | `reflexion_memory.py` | Learning | AUTHORITATIVE | Episodic memory write/retrieve |
| 11 | `parameter_evolution.py` | Learning | AUTHORITATIVE | Parameter change proposals (NOT application) |
| 12 | `ensemble_estimator.py` | Evidence | FEEDER | LLM probability estimates |
| 13 | `llm_tournament.py` | Evidence | FEEDER | Multi-model tournament consensus |
| 14 | `ws_trade_stream.py` | Evidence | FEEDER | VPIN + OFI from WebSocket |
| 15 | `hawkes_order_flow.py` | Evidence | FEEDER | Hawkes cascade intensity |
| 16 | `whale_tracker.py` | Evidence | FEEDER | Whale consensus signals |
| 17 | `smart_wallet_feed.py` | Evidence | FEEDER | Smart wallet flow |
| 18 | `neg_risk_scanner.py` | Evidence | FEEDER | Negative-risk opportunities |
| 19 | `cross_platform_arb_scanner.py` | Evidence | FEEDER | Cross-platform arb |
| 20 | `resolution_sniper.py` | Evidence | FEEDER | Known-outcome detection |
| 21 | `vpin_toxicity.py` | Evidence | FEEDER | Volume-synced toxicity |
| 22 | `momentum_detector.py` | Evidence | FEEDER | Momentum regime |
| 23 | `momentum_streak.py` | Evidence | FEEDER | Streak count |
| 24 | `wallet_flow_detector.py` | Evidence | FEEDER | On-chain anomalies |
| 25 | `disagreement_signal.py` | Evidence | FEEDER | Model disagreement |
| 26 | `lead_lag_engine.py` | Evidence | FEEDER | Granger-causal signals |
| 27 | `causal_lead_lag.py` | Evidence | FEEDER | Semantic-verified lead-lag |
| 28 | `spread_capture.py` | Evidence | FEEDER | Spread opportunity |
| 29 | `clob_ws_client.py` | Evidence | FEEDER | Raw order book |
| 30 | `gamma_market_cache.py` | Evidence | FEEDER | Market metadata cache |
| 31 | `relation_cache.py` | Evidence | FEEDER | Condition-market mappings |
| 32 | `relation_classifier.py` | Evidence | FEEDER | Market relationship types |
| 33 | `semantic_leader_follower.py` | Evidence | FEEDER | Semantic pair similarity |
| 34 | `pm_fast_market_registry.py` | Evidence | FEEDER | Fast-market registry |
| 35 | `research_rag.py` | Evidence | FEEDER | Dispatch archive retrieval |
| 36 | `delta_calibrator.py` | Evidence | FEEDER | BTC delta stats |
| 37 | `cross_asset_arb.py` | Evidence | FEEDER | Cross-crypto confirmation |
| 38 | `cross_asset_history.py` | Evidence | FEEDER | Historical cross-asset data |
| 39 | `cascade_max.py` | Evidence | FEEDER | BTC5 cascade events |
| 40 | `multi_asset_arb.py` | Evidence | FEEDER | Multi-asset confirmation |
| 41 | `kalshi_opportunity_scanner.py` | Evidence | FEEDER | Kalshi market data |
| 42 | `kalshi_intraday_parity.py` | Evidence | FEEDER | Kalshi-Poly parity |
| 43 | `conformal_calibration.py` | Thesis | FEEDER | Confidence intervals for theses |
| 44 | `regime_detector.py` | Thesis | FEEDER | Regime annotation for theses |
| 45 | `ensemble_toxicity.py` | Thesis | FEEDER | Toxicity annotation for theses |
| 46 | `adaptive_platt.py` | Thesis | FEEDER | Updated Platt coefficients |
| 47 | `adaptive_floor.py` | Thesis | FEEDER | Adaptive price floor |
| 48 | `symbolic_alpha.py` | Thesis | FEEDER | Evolved alpha formulas |
| 49 | `synergistic_signals.py` | Thesis | FEEDER | Optimal signal weights |
| 50 | `combinatorial_integration.py` | Thesis | FEEDER | Composite signal construction |
| 51 | `lmsr_engine.py` | Thesis | FEEDER | LMSR probability anchor |
| 52 | `thesis_foundry.py` | Thesis | FEEDER | Shadow artifact conversion |
| 53 | `btc5_session_policy.py` | Thesis | FEEDER | Session policy params |
| 54 | `autoresearch_loop.py` | Promotion | FEEDER | Shadow-tested hypotheses |
| 55 | `lane_supervisor.py` | Promotion | FEEDER | Lane routing decisions |
| 56 | `execution_readiness.py` | Promotion | FEEDER | Pre-flight go/no-go |
| 57 | `pricing_evolution.py` | Promotion | FEEDER | Evolved pricing params |
| 58 | `fill_tracker.py` | Learning | FEEDER | Fill/outcome data |
| 59 | `wallet_poller.py` | Learning | FEEDER | Balance polling |
| 60 | `position_merger.py` | Learning | FEEDER | Clean position records |
| 61 | `position_redeemer.py` | Learning | FEEDER | Resolved position outcomes |
| 62 | `jj_live_core.py` | Execution | FEEDER | Execution utilities |
| 63 | `jj_live_runtime_settings.py` | Execution | FEEDER | Runtime param loading |
| 64 | `jj_live_signal_sources.py` | Execution | FEEDER | Signal source wiring |
| 65 | `btc_5min_maker_core.py` | Execution | FEEDER | BTC5 execution utilities |
| 66 | `polymarket_clob.py` | Execution | FEEDER | CLOB client (pure I/O) |
| 67 | `polymarket_runtime.py` | Execution | FEEDER | Runtime helpers |
| 68 | `polymarket_fastlane_surface.py` | Execution | FEEDER | Fast-path order submission |
| 69 | `shadow_runner.py` | Execution | FEEDER | Shadow/paper execution |
| 70 | `hft_shadow_validator.py` | Execution | FEEDER | Shadow fill validation |
| 71 | `edge_scan_report.py` | -- | RENDERER | Edge scan reports |
| 72 | `elastic_client.py` | -- | RENDERER | Elasticsearch telemetry |
| 73 | `elastic_dashboards.py` | -- | RENDERER | Kibana dashboards |
| 74 | `elastic_ml_setup.py` | -- | RENDERER | ES ML job config |
| 75 | `apm_setup.py` | -- | RENDERER | APM setup |
| 76 | `latency_tracker.py` | -- | RENDERER | Latency reporting |
| 77 | `log_config.py` | -- | RENDERER | Log configuration |
| 78 | `health_monitor.py` | -- | RENDERER | Heartbeat writer |
| 79 | `runtime_profile.py` | -- | RENDERER | Profile validation |
| 80 | `dependency_graph.py` | -- | RENDERER | Module dependency analysis |
| 81 | `expanded_scanner.py` | -- | RENDERER | Market scan reports |
| 82 | `maker_velocity_blitz.py` | -- | RENDERER | Velocity scoring reports |
| 83 | `market_quarantine.py` | -- | RENDERER | Quarantine list (advisory) |
| 84 | `a6_command_router.py` | -- | RETIRED | A-6 killed |
| 85 | `a6_executor.py` | -- | RETIRED | A-6 killed |
| 86 | `a6_sum_scanner.py` | -- | RETIRED | Subsumed by neg_risk_scanner |
| 87 | `b1_executor.py` | -- | RETIRED | B-1 killed |
| 88 | `b1_monitor.py` | -- | RETIRED | B-1 killed |
| 89 | `b1_template_engine.py` | -- | RETIRED | B-1 killed |
| 90 | `anomaly_consumer.py` | -- | SUBSUMED | Into ensemble_toxicity |
| 91 | `sum_violation_scanner.py` | -- | SUBSUMED | Into neg_risk_scanner |
| 92 | `sum_violation_strategy.py` | -- | SUBSUMED | Into neg_risk_scanner |
| 93 | `constraint_arb_engine.py` | -- | SUBSUMED | Into cross_platform_arb_scanner |
| 94 | `negrisk_arb_scanner.py` | -- | SUBSUMED | Into neg_risk_scanner |
| 95 | `debate_pipeline.py` | -- | SUBSUMED | Into llm_tournament |
| 96 | `llm_ensemble.py` | -- | SUBSUMED | Into ensemble_estimator |
| 97 | `neg_risk_inventory.py` | -- | SUBSUMED | Into wallet_reconciliation |
| 98 | `cross_platform_arb.py` | -- | SUBSUMED | Into cross_platform_arb_scanner |

**Authority count:** 11 AUTHORITATIVE modules. 59 FEEDERs. 13 RENDERERs. 15 RETIRED/SUBSUMED.

---

## 6. Event/Data-Flow Diagram

```
                           MARKET DATA (Polymarket CLOB, Binance, Kalshi)
                                          |
                  ========================|========================
                  |           EVIDENCE BUNDLE            |
                  |                                              |
                  |  clob_ws_client -----> ws_trade_stream       |
                  |  gamma_market_cache    vpin_toxicity          |
                  |  whale_tracker         smart_wallet_feed      |
                  |  neg_risk_scanner      resolution_sniper      |
                  |  cross_platform_arb_scanner                   |
                  |  ensemble_estimator    llm_tournament         |
                  |  momentum_detector     hawkes_order_flow      |
                  |  lead_lag_engine       causal_lead_lag        |
                  |  delta_calibrator      cascade_max            |
                  |  research_rag          disagreement_signal    |
                  |                                              |
                  |  Output: EvidenceRecord[]                    |
                  ================================================
                                          |
                                          | EvidenceRecord[]
                                          v
                  ================================================
                  |            THESIS BUNDLE              |
                  |                                              |
                  |  EVENT PATH:           BTC5 PATH:            |
                  |  enhanced_pipeline <-- btc5_core_utils <--   |
                  |    |                     |                    |
                  |    +-- conformal_cal     +-- session_policy   |
                  |    +-- regime_detector   +-- adaptive_floor   |
                  |    +-- ensemble_toxicity +-- symbolic_alpha   |
                  |    +-- synergistic_sig                        |
                  |    +-- combinatorial                          |
                  |                                              |
                  |  kill_rules.py -----> VETO on any thesis     |
                  |                                              |
                  |  Output: ThesisRecord (with KillResult)      |
                  ================================================
                                          |
                                          | ThesisRecord
                                          | (must have kill_rules.passed == True)
                                          v
                  ================================================
                  |           PROMOTION BUNDLE            |
                  |                                              |
                  |  agent_constraints.py --> BLOCK / MODIFY     |
                  |          |                                    |
                  |          v                                    |
                  |  auto_stage_gate.py --> capital tier          |
                  |          |                                    |
                  |          v                                    |
                  |  execution_readiness.py --> go / no-go       |
                  |          |                                    |
                  |          v                                    |
                  |  Output: PromotionTicket                     |
                  |  (size capped, constraints enforced,         |
                  |   evidence chain intact)                     |
                  |                                              |
                  |  AUTORESEARCH SIDECAR:                       |
                  |  autoresearch_loop --> auto_promote           |
                  |  (shadow test --> safety_check --> .env)      |
                  |  (rate-limited: 1 promotion / 24h)           |
                  |  (caps: min_buy >= 0.80, max_trade <= $25)   |
                  ================================================
                                          |
                                          | PromotionTicket
                                          v
                  ================================================
                  |          EXECUTION LAYER              |
                  |                                              |
                  |  EVENT:  jj_live.py                          |
                  |            polymarket_clob.py (I/O)          |
                  |                                              |
                  |  BTC5:   btc_5min_maker.py                   |
                  |            polymarket_clob.py (I/O)          |
                  |                                              |
                  |  SHADOW: shadow_runner.py                    |
                  |                                              |
                  |  Output: ExecutionResult (fill/reject/error) |
                  ================================================
                                          |
                                          | ExecutionResult
                                          v
                  ================================================
                  |           LEARNING BUNDLE             |
                  |                                              |
                  |  fill_tracker.py -------> outcome data       |
                  |  wallet_reconciliation -> wallet truth       |
                  |  position_redeemer -----> resolved P&L       |
                  |  reflexion_memory ------> episodic critique  |
                  |  parameter_evolution ---> param proposals    |
                  |          |                                    |
                  |          | proposals (NOT direct changes)     |
                  |          v                                    |
                  |  [Back to Promotion Bundle:                  |
                  |   autoresearch_loop for shadow testing]       |
                  |                                              |
                  |  [Back to Evidence Bundle:                   |
                  |   reflexion_memory context in next           |
                  |   ensemble_estimator prompt]                  |
                  ================================================
                                          |
                       +------------------+------------------+
                       |                                     |
                       v                                     v
              Promotion Bundle                      Evidence Bundle
              (param proposals                      (reflexion context
               enter shadow test)                    enriches next estimate)
```

---

## 7. Invariants (The Rules That Cannot Be Broken)

### 7.1 Proof Chain Completeness

Every dollar deployed must trace to:
1. At least one non-expired EvidenceRecord (with valid hash)
2. Exactly one ThesisRecord that references those evidence hashes
3. A KillResult with `passed == True` on that thesis
4. Exactly one PromotionTicket with a ConstraintResult showing `allowed == True`
5. An ExecutionResult linking back to that ticket

If any link is missing, the trade is invalid. Post-hoc audit can flag trades
that violated this chain.

### 7.2 Learning-to-Risk Firewall

The path from Learning Bundle to live risk is:

```
parameter_evolution (Learning)
    --> autoresearch_loop (Promotion) [shadow test required]
        --> auto_promote (Promotion) [safety_check() with immutable caps]
            --> .env parameter change
```

There is NO shorter path. `parameter_evolution` cannot write to .env.
`autoresearch_loop` cannot apply parameters without `auto_promote`.
`auto_promote` cannot exceed its immutable caps (min_buy >= 0.80, max_trade <= $25,
1 promotion per 24 hours).

### 7.3 Single-Writer Per Decision

| Decision | Sole Writer |
|----------|-------------|
| "Should we trade this market?" | enhanced_pipeline.py (events) or btc5_core_utils.py (BTC5) |
| "Is this thesis dead?" | kill_rules.py |
| "How much capital?" | agent_constraints.py (caps) + auto_stage_gate.py (tier) |
| "Place the order" | jj_live.py (events) or btc_5min_maker.py (BTC5) |
| "What actually happened?" | wallet_reconciliation.py |
| "What should we change?" | parameter_evolution.py (proposes) + auto_promote.py (applies) |

No two modules make the same decision. If you find a code path where two modules
both decide the same thing, that is a bug.

### 7.4 Staleness Enforcement

Evidence records carry `staleness_limit_s`. The Thesis Bundle must check
`time.time() - evidence.timestamp_utc < evidence.staleness_limit_s` before
incorporating any evidence. Stale evidence is discarded, not used with a warning.

### 7.5 Thesis Expiration

ThesisRecords carry `expires_utc`. A thesis that has expired cannot enter the
Promotion Bundle. This prevents stale theses from executing during market regime
changes.

### 7.6 PromotionTicket Expiration

PromotionTickets carry `expires_utc`. The execution layer rejects expired tickets.
This prevents a ticket approved under one market condition from executing under
a different condition minutes later.

---

## 8. Migration Path (What Changes in Code)

This architecture does NOT require rewriting all 97 modules. It requires wiring
changes at the boundaries:

### Phase 1: Proof Surface Types (Week 1)
Create `bot/proof_types.py` with:
- `EvidenceRecord` dataclass
- `ThesisRecord` dataclass
- `PromotionTicket` dataclass
- `ExecutionResult` dataclass
- `LearningRecord` dataclass
- Hash computation and validation functions

### Phase 2: Evidence Standardization (Week 1-2)
Modify each Evidence Bundle module to emit `EvidenceRecord` instead of raw dicts.
This is a wrapper change -- the internal logic of each module stays the same.

### Phase 3: Thesis Consolidation (Week 2)
Modify `enhanced_pipeline.py` to:
- Accept `EvidenceRecord[]` instead of calling evidence modules directly
- Emit `ThesisRecord` instead of raw decision dicts
- Require `kill_rules.py` result before emitting

Modify `btc5_core_utils.py` similarly for the BTC5 path.

### Phase 4: Promotion Gate (Week 2-3)
Create `bot/promotion_gate.py` that:
- Accepts a `ThesisRecord`
- Runs `agent_constraints.py`
- Checks `auto_stage_gate.py` for capital tier
- Checks `execution_readiness.py` for go/no-go
- Emits `PromotionTicket` or rejects with reason

Wire `jj_live.py` and `btc_5min_maker.py` to accept only `PromotionTicket`.

### Phase 5: Learning Feedback (Week 3)
Wire `fill_tracker.py` to emit `LearningRecord` with thesis_ref and ticket_ref.
Wire `reflexion_memory.py` to consume `LearningRecord`.
Wire `parameter_evolution.py` to consume `LearningRecord`.

### Phase 6: Dead Code Removal (Week 3-4)
Delete 15 RETIRED/SUBSUMED modules listed in Section 4. Remove all imports.

---

## 9. How This Makes Money Faster

This architecture is not aesthetic. It is economic.

**Problem 1: Zero-fill on BTC5.** The VPS has 302 rows, all skips. 54% are
`skip_delta_too_large`. The parameter_evolution module has been proposing wider
delta thresholds, but the autoresearch loop has not been shadow-testing them
because the promotion path is unclear. Under the kernel, the path is explicit:
parameter_evolution proposes -> autoresearch_loop shadow-tests -> auto_promote
applies if shadow PnL is positive. Time to first fill: days, not weeks.

**Problem 2: Enhanced pipeline not connected to execution.** The 7-phase pipeline
in enhanced_pipeline.py produces decisions, but jj_live.py also produces its own
decisions using a simpler path. Under the kernel, enhanced_pipeline.py is the SOLE
thesis emitter for event markets. jj_live.py is a pure executor. The better pipeline
immediately drives all event-market trades.

**Problem 3: Learning loop is open.** Reflexion memory writes reflections but nothing
reads them systematically before the next estimate. Under the kernel, the Evidence
Bundle's ensemble_estimator.py is required to query reflexion_memory.py for context
before every estimate. Past mistakes directly reduce future mistakes.

**Problem 4: No audit trail for parameter changes.** auto_promote.py logs promotions,
but there is no proof chain from the evidence that motivated the change. Under the
kernel, every parameter change traces back through: LearningRecord -> parameter
proposal -> autoresearch shadow test -> promotion with safety_check. If a parameter
change loses money, you can trace exactly which learning record triggered it.

---

## 10. What This Document Does Not Cover

- Network protocol details (WebSocket schemas, REST endpoints)
- Deployment orchestration (systemd units, deploy.sh)
- Website/public content pipeline
- Kalshi-specific execution path (not yet built)
- Multi-asset expansion beyond BTC5 (deferred until BTC5 fills are flowing)

Those are implementation details. This document covers decision architecture.

---

*This is the system-of-record. If module behavior contradicts this document,
the module is wrong.*
