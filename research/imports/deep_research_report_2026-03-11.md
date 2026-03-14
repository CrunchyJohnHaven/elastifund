# ELASTIFUND COMMAND NOTE v2.0 — Instance-Distributed ARR Improvement Dispatch

Best model for this dispatch: GPT-5.2 Thinking.

## INSTANCE ROSTER (PASTE TARGETS)

* Instance 1 - GPT-5.3-Codex / High - Reconciliation truth repair (wallet↔probe↔runtime contract coherence)
* Instance 2 - GPT-4 / Extra High - BTC5 stage unfreeze (0.49 drag isolation + gate logic arbitration)
* Instance 3 - Claude Code / Sonnet - Microstructure telemetry mining (toxicity→fill-quality→win-rate loop)
* Instance 4 - GPT-4 / Medium - Flywheel self-improvement architecture (DORA-style velocity + evidence contracts)
* Instance 5 - GPT-4 / Medium - Finance allocation execution (capital velocity w/ safe baseline + caps)

## CURRENT TRUTH SNAPSHOT

Machine-truth facts available **in this cycle’s attached packet**:

* Attached wallet-export summary (March 7–11, 2026) reports **479 rows**, **193 markets**, and **+51.556846 USDC** net trading cash flow excluding deposits; buy-side skew is **245 DOWN/NO buys** vs **39 UP/YES buys**. fileciteturn1file0L25-L38
* The same snapshot flags the key “structure” decomposition: **0.50** price bucket is strongest (**+$39.1564**), and **0.49** is the main drag (**-$77.7365**); **DOWN** is still the strongest direction (**+$10.4017**). fileciteturn1file12L21-L26
* Runtime/public contract at **2026-03-11T09:22:17Z** (older within-day artifact) says **launch_posture=blocked**, **execution_mode=shadow**, effective profile **shadow_fast_flow**, wallet reconciliation **reconciled**, but capital accounting delta remains **-157.3178 USD**. fileciteturn2file0L25-L43
* **improvement_velocity.json** generated at **2026-03-11T10:17:15Z** reports:
  * `registry_health.status="healthy"`, `eligible_count=596`, `quote_coverage_ratio=0.9547`, `staleness_breach_count=337`. fileciteturn6file0L6-L22
  * `runtime_summary.launch_posture="clear"` and `service_status="running"`, with `total_trades=185`. fileciteturn6file0L23-L29
  * A **multi-source divergence** inside `total_trades_observations`, including `runtime_observation.runtime.total_trades=0` vs `runtime_truth.runtime.total_trades=185` and `trade_db_total_trades=2`, with `total_trades_source` computed as `max_observed:...`. fileciteturn6file0L29-L44
  * Stage readiness: **recommended_stage=1**, `ready_for_stage_1=true`, `ready_for_stage_2=false`, `ready_for_stage_3=false`, blocked by **trailing_40_live_filled_not_positive** with `trailing_40_live_filled_pnl_usd=-24.0875`; also shows `trailing_12_live_filled_pnl_usd=1.453` and `trailing_120_live_filled_pnl_usd=91.2818`; `order_failed_rate_recent_40=0.025`. fileciteturn6file1L18-L34
  * Control-plane output conflict: `headline.deploy_recommendation="promote"` while the embedded selected forecast deploy recommendation is `shadow_only`. fileciteturn4file5L29-L46 fileciteturn6file2L29-L33
* Polymarket fee/rebate surface (external, current docs) indicates:
  * Certain markets have taker fees “to fund the Maker Rebates Program,” and post-only orders are rejected if they would cross the spread. citeturn0search7turn0search19
  * Maker rebates for crypto markets are explicitly documented (including 5-min crypto and later expansions); changelog notes crypto fee coverage expansion starting **March 6, 2026** (docs). citeturn0search3turn0search11turn0search15
* Current time for the operator (America/New_York) is **06:35:19 AM ET**, which is **03:35:19 AM PT**.  

## DISPATCH PLAN BY INSTANCE

Strategic core (what matters most, based strictly on evidence above):

1) **Your biggest hidden velocity killer is not “strategy alpha,” it’s “truth coherence.”** The system is currently capable of emitting internally conflicting “go/no-go” signals within the same public artifact (e.g., `promote` vs `shadow_only`) while also showing multi-source metric divergence (`runtime_observation` vs `runtime_truth` vs DB). Until this is made impossible-by-construction, you are flying blind at the exact moment you want to scale. fileciteturn6file0L29-L44 fileciteturn4file5L29-L46 fileciteturn6file2L29-L33

2) **Stage unfreeze is mathematically “close” but currently blocked by short-window variance.** You have `trailing_12` positive and `trailing_120` positive, yet `trailing_40` negative and blocking stage upgrades; that is a canonical signature of (a) a noisy/variance-dominant edge, (b) a regime flip, or (c) attribution mis-bucketing (especially given the known 0.49 drag). fileciteturn6file1L18-L34 fileciteturn1file12L21-L26

3) **Microstructure should be treated as a first-class risk gate, not just a feature.** VPIN is specifically designed to measure order-flow toxicity and liquidity crash risk. If you are maker-only, the enemy is adverse selection; “toxicity-aware quoting” is a direct win-rate lever. citeturn0search0turn0search8turn0search24

4) **You are operating in a fee/rebate regime that is explicitly evolving.** Polymarket’s maker rebate and fee documentation for crypto markets implies “market selection based on rebate economics” is not optional if you want to maximize economic throughput per unit time (velocity). citeturn0search3turn0search11turn0search15turn0search7

### Instance 1 - GPT-5.3-Codex / High

* Objective: Force a single coherent truth lattice so “launch posture,” “order submission,” “deploy recommendation,” and “total trades” cannot contradict without a hard FAIL + repair branch.
* Inputs: `/mnt/data/improvement_velocity.json`; `/mnt/data/ResearchContext.md`; `/mnt/data/COMMAND_NODE.md`; live wallet + the runtime artifacts referenced by precedence rules. fileciteturn1file0L9-L19
* Actions (deterministic steps only):
  1a. Extract a “truth contract” table with these fields: `launch_posture`, `execution_mode`, `effective_profile`, `allow_order_submission`, `deploy_recommendation`, `capital_stage_readiness`, `total_trades`, `trade_db_total_trades`, `wallet_export_freshness_hours`, `probe_freshness_hours`.
  1b. Add a **consistency check** rule: if any of these disagree across sources, set `fund_status=hold`, emit `broken_reason`, and trigger a “repair required” one-next-cycle action, rather than producing mixed posture outputs. Use the existing “max observed” behavior as an explicit flagged failure mode, not a silent merge. fileciteturn6file0L29-L44
  1c. Define explicit precedence inside the artifact: wallet/export for capital cash movement, runtime/probe for posture, registry pull for opportunity shape (mirrors packet precedence). fileciteturn1file0L9-L19
  1d. Mid-sprint audit point: before any integration, verify the artifact is internally consistent by re-parsing it and confirming the rule “exactly one posture outcome exists” (no simultaneous `promote` and `shadow_only`). fileciteturn4file5L29-L46 fileciteturn6file2L29-L33
* Success checks (pass/fail):
  * PASS if “deploy recommendation” cannot be both `promote` and `shadow_only` in the same produced surface.
  * PASS if `total_trades` cannot be computed via `max_observed` without emitting a non-null `broken_reason` and setting a hold/repair branch. fileciteturn6file0L29-L44
  * PASS if stage readiness and posture no longer disagree across the same artifact.
* Required outputs:
  * candidate_delta_arr_bps: +0
  * expected_improvement_velocity_delta: +0.30 cycles/day (from reduced “blocked-by-confusion” downtime)
  * arr_confidence_score: 0.85
  * block_reasons: ["truth_divergence_detected_requires_repair_branch_until_fixed"]
  * finance_gate_pass: true
  * one_next_cycle_action: "Ship a single-source ‘truth lattice’ artifact and hard-fail mixed posture outputs"

### Instance 2 - GPT-4 / Extra High

* Objective: Unfreeze BTC5 scale gates by isolating the **0.49 drag** and rebuilding stage gates around statistically defensible, regime-aware evidence rather than raw short-window P&L alone.
* Inputs: `/mnt/data/ResearchContext.md` (0.49 drag / 0.50 strength); `/mnt/data/improvement_velocity.json` (trailing windows + stage block); Polymarket order constraints and fee/rebate docs. fileciteturn1file12L21-L26 fileciteturn6file1L18-L34 citeturn0search19turn0search7turn0search3
* Actions (deterministic steps only):
  2a. Define a BTC5 “bucket suppression experiment” spec:
     * Suppress or reprice fills associated with the 0.49 bucket (explicitly tracked as main drag in current probe). fileciteturn1file12L21-L26
     * Keep 0.50 bucket behavior intact (explicit strongest bucket). fileciteturn1file12L21-L26
  2b. Map stage unfreeze requirement to the current gate: stage 2/3 blocked **only** because `trailing_40_live_filled_pnl_usd=-24.0875`. fileciteturn6file1L31-L34
  2c. Replace the single hard gate with a two-layer gate:
     * Layer 1: existing guardrails (fresh probe, low order-failed rate, positive trailing 12). fileciteturn6file1L18-L28
     * Layer 2: Bayesian evidence gate on win-rate/edge with a posterior probability threshold (“P(edge>0) > X”) to reduce variance sensitivity.
  2d. Mid-sprint audit point: build a contradiction table for current posture signals:
     * `headline.deploy_recommendation=promote` vs `selected_forecast.deploy_recommendation=shadow_only` and resolve by rule (e.g., “weakest-link wins”: if any embedded artifact says shadow_only, the composite must not promote). fileciteturn4file5L29-L46 fileciteturn6file2L29-L33
* Success checks (pass/fail):
  * PASS if stage 2 is no longer blocked solely by a single noisy window when longer window and short window disagree (documented exceptions allowed only with explicit risk caps).
  * PASS if 0.49 bucket suppression produces a measurable uplift in the next comparable window and the system can attribute it cleanly (no “wallet vs probe” ambiguity).
* Required outputs:
  * candidate_delta_arr_bps: +650
  * expected_improvement_velocity_delta: +0.15 stage_levels/day (time-to-stage-2 reduction)
  * arr_confidence_score: 0.70
  * block_reasons: ["stage_2_blocked_by_trailing_40_negative", "0.49_bucket_drag_requires_isolation"]
  * finance_gate_pass: true
  * one_next_cycle_action: "Run 0.49 suppression as a bounded A/B and re-evaluate trailing_40 gate with Bayesian confidence"

### Instance 3 - Claude Code / Sonnet

* Objective: Turn microstructure telemetry into a win-rate lever via toxicity-aware quoting (VPIN/OFI gating, staleness control, and adverse-selection detection).
* Inputs: `/mnt/data/improvement_velocity.json` (`staleness_breach_count=337`, `quote_coverage_ratio=0.9547`); VPIN primary sources; Polymarket post-only behavior docs. fileciteturn6file0L6-L22 citeturn0search0turn0search8turn0search19
* Actions (deterministic steps only):
  3a. Define a “fill quality” score per market-time bucket with these components:
     * Toxicity proxy: VPIN percentile (or CDF[VPIN] where available) as a “do-not-quote” gate when high. citeturn0search0turn0search8turn0search24
     * Staleness penalty: any quote coverage achieved with staleness breaches counts as lower quality (because it creates adverse selection and increases rejection risk).
     * Execution correctness: post-only reject rate; post-only rejects are mechanically expected when crossing spread. citeturn0search19
  3b. Create a deterministic recommendation for where to spend compute:
     * If staleness breaches are high (337) despite high quote coverage ratio (0.9547), prioritize **latency + scheduling** fixes over “more signals.” fileciteturn6file0L18-L20
  3c. Mid-sprint audit point: specify a single sanity check:
     * If staleness rises while quote coverage stays high, you are “spraying stale quotes,” which increases adverse selection; treat as an automatic scale-down trigger.
* Success checks (pass/fail):
  * PASS if a toxicity/staleness gate exists that can suppress quoting during toxic regimes without halting the safe baseline entirely.
  * PASS if the system can report “why we did not quote” as explicit block reasons (not silent).
* Required outputs:
  * candidate_delta_arr_bps: +220
  * expected_improvement_velocity_delta: +5.0% win_rate uplift equivalent (via fewer toxic fills) (reported as +0.05)
  * arr_confidence_score: 0.60
  * block_reasons: ["microstructure_gate_not_enforced", "staleness_breaches_high_despite_coverage"]
  * finance_gate_pass: true
  * one_next_cycle_action: "Ship toxicity/staleness gating as a hard pre-trade filter and log reject reasons"

### Instance 4 - GPT-4 / Medium

* Objective: Build a flywheel architecture that makes improvement velocity measurable and optimizable (DORA-style “Four Keys” applied to trading + ops).
* Inputs: `/mnt/data/02_ARCHITECTURE.md` (six-layer architecture + truth surfaces); DORA/Four Keys references; `/mnt/data/improvement_velocity.json` (cycle counts/velocity). fileciteturn6file16L15-L26 citeturn0search5turn0search1turn0search25
* Actions (deterministic steps only):
  4a. Translate DORA “Four Keys” into Elastifund control metrics:
     * Deployment Frequency → “strategy config deployments/day” (including profile/threshold changes).
     * Lead Time for Changes → “time from hypothesis → first 12 live fills” (matches existing realized window concept). fileciteturn6file1L31-L34
     * Change Failure Rate → “fraction of changes that push trailing_40 negative or trigger kill rules.”
     * MTTR → “time from blocker detection (truth divergence, launch mismatch) to restored stage-1 baseline.”
     (DORA definitions: lead time/change failure rate/MTTR/deploy frequency are standard software delivery performance metrics, and they correlate with higher organizational performance.) citeturn0search5turn0search1turn0search25
  4b. Implement the rule “no stale artifact may silently halt all execution” as a control-plane invariant:
     * If registry is healthy: proceed.
     * If registry broken: fallback to direct market pulls; keep baseline running; emit a visible hold/repair branch.
  4c. Mid-sprint audit point: define one dashboard slice per key metric and a “single pane of truth” pointer (artifact path + timestamp).
* Success checks (pass/fail):
  * PASS if every cycle outputs the Four Keys analog metrics and they can be compared across cycles.
  * PASS if “blockers” have explicit MTTR measurement (start/end timestamps, not narrative).
* Required outputs:
  * candidate_delta_arr_bps: +80
  * expected_improvement_velocity_delta: +0.25 experiments/day (more safe deployments)
  * arr_confidence_score: 0.75
  * block_reasons: ["velocity_metrics_not_explicitly_optimized"]
  * finance_gate_pass: true
  * one_next_cycle_action: "Publish DORA-style trading ops metrics and enforce MTTR as a first-class target"

### Instance 5 - GPT-4 / Medium

* Objective: Increase capital deployment velocity while guaranteeing at least one safe baseline stays live under finance caps and stage gates.
* Inputs: Finance control plane caps; current stage readiness (`recommended_stage=1`, stage 2/3 blocked); current wallet/capital indicators in the packet. fileciteturn1file4L30-L37 fileciteturn6file1L18-L34
* Actions (deterministic steps only):
  5a. Lock a “safe baseline capital posture”:
     * Stage-1 only until the stage-block is removed (explicitly blocked by trailing_40 negative). fileciteturn6file1L31-L34
  5b. Define a “finance gate pass” checklist:
     * Per-action cap $250, monthly net-new commitments $1,000, reserve floor 1 month (policy). fileciteturn1file4L30-L37
     * If a change requires paid tools or more compute, it must include expected ARR impact + information gain as required by the aggressive capital policy. fileciteturn2file10L1-L1
  5c. Mid-sprint audit point: confirm no action would cause “all execution lanes stop”:
     * If trading is blocked, route to a permitted lane (e.g., evidence hardening / reconciliation) rather than going idle (policy mandate). fileciteturn1file6L13-L17
* Success checks (pass/fail):
  * PASS if at least one baseline lane can run whenever gates are green, and blockers route execution elsewhere rather than stopping the system.
  * PASS if any spend/action is explicitly within caps with recorded rationale.
* Required outputs:
  * candidate_delta_arr_bps: +0
  * expected_improvement_velocity_delta: +0.20 cycles/day (less idle time under blockers)
  * arr_confidence_score: 0.80
  * block_reasons: ["capital_stage_readiness_hold", "finance_caps_require_explicit_rationale_for_spend"]
  * finance_gate_pass: true
  * one_next_cycle_action: "Keep stage_1 baseline live; approve only spend/actions with quantified velocity+info-gain ROI"

## 20-MINUTE RUN WINDOW

Window length: 20 minutes (operator timeboxed). Start time is specified in PT first, then ET.

* T+0 (03:40 PT / 06:40 ET): Run Instance 1 “truth lattice” extraction; declare pass/fail on internal artifact coherence (no mixed posture).
* T+5 (03:45 PT / 06:45 ET): Instance 2 produces the 0.49 suppression + stage gate arbitration decision package (go/no-go criteria explicitly tied to `trailing_40` block).
* T+10 (03:50 PT / 06:50 ET): Instance 3 outputs the toxicity/staleness gating spec (including when to halt quoting without halting baseline).
* T+15 (03:55 PT / 06:55 ET): Instance 4 + 5 finalize flywheel metrics + finance gate checklist for next cycle, ensuring a safe baseline posture remains runnable under hold states.

## DONE CONDITIONS

A cycle is DONE only if all conditions below are met:

* A single coherent “truth lattice” exists: no simultaneous `promote` and `shadow_only`, and no silent `max_observed` merges without a flagged broken reason. fileciteturn6file0L29-L44 fileciteturn4file5L29-L46
* Stage gate decision is explicit: either (a) stage remains 1 with documented blockers (**trailing_40_live_filled_not_positive**), or (b) stage gate logic is updated with a statistically defensible method and explicit risk caps. fileciteturn6file1L31-L34
* Bucket strategy decision is explicit: either (a) 0.49 is suppressed/repriced as an experiment, or (b) it remains live with an evidence-based justification despite being called out as main drag. fileciteturn1file12L21-L26
* Telemetry gating spec is shipped: toxicity/staleness gating has concrete pass/fail rules tied to observed staleness breach telemetry. fileciteturn6file0L18-L20
* Each instance provides:
  * a file change log (files created/modified/folders touched) and
  * a test confirmation statement (what was run, pass/fail, timestamp).

## FAILSAFE AND ROLLBACK RULES

Failsafe rules (hard constraints):

* If any truth divergence is detected (posture/recommendation/trade counts), force `fund_status=hold` and route to repair; do **not** silently “best-effort merge.” fileciteturn6file0L29-L44
* If stage upgrade is blocked, do not escalate capital; keep Stage 1 baseline only, consistent with current stage readiness (`recommended_stage=1`, stage 2/3 false). fileciteturn6file1L18-L34
* If staleness breaches rise while quote coverage remains high, treat as a “toxic quoting regime” and scale down quoting aggressiveness rather than scaling up exposure. fileciteturn6file0L18-L20
* Post-only order behavior is mechanical: if post-only would cross the spread, it is rejected; do not interpret rejections as “market failure,” interpret as “pricing too aggressive.” citeturn0search19
* No stale artifact may silently halt all execution:
  * If trading lanes are blocked, reroute to reconciliation/evidence lanes rather than going idle (baseline “always attempt + always reconcile + always retry” mandate). fileciteturn1file6L13-L17

Rollback rules (how to revert safely):

* Any gating change (bucket suppression, toxicity thresholds, stage gate logic) must be behind a single config toggle with a default “revert to last known Stage 1 safe baseline.”
* If a new rule causes global holds without a clear repair action, revert immediately and pin a “repair required” branch with a 1-cycle retry schedule.
* Finance rollback: any spend/action that would exceed $250 per action or $1,000 monthly net-new must be automatically prevented (not merely warned). fileciteturn1file4L30-L37

Output Integrity Review

* Clarity: This dispatch separates (a) **truth coherence**, (b) **stage gating**, (c) **microstructure telemetry**, and (d) **flywheel velocity metrics** into isolated, auditable workstreams tied to explicit evidence.
* Logic: The plan treats the documented contradictions and short-window gate block as the primary throughput limiter (not “find new alpha first”), aligning with the packet’s stated bottleneck shift toward launch-contract/attribution drift. fileciteturn2file0L55-L62 fileciteturn6file0L29-L44
* Fallback resilience: Hard FAIL + repair branches prevent silent drift, and Stage 1 baseline is preserved whenever permitted by gates.
* Test completeness: Done conditions explicitly require test/run confirmations and change logs per instance; no “it should work” merges.

Operator Questions (answer only what you can; do not execute beyond this guidance)

1) Which artifact should be treated as “the live truth” for launch posture **right now**: the older within-day packet stating `launch_posture=blocked` or the newer `improvement_velocity.json` stating `launch_posture=clear`? (This is resolvable by checking the live wallet + the latest `reports/runtime_truth_latest.json` on the VPS.) fileciteturn2file0L29-L43 fileciteturn6file0L23-L29
2) Do you want 0.49 bucket suppression to be a **hard ban** (no quotes) or a **repricing rule** (quote deeper/wider) for the first experiment cycle? fileciteturn1file12L21-L26
3) Confirm whether we are allowed to treat “trade_db_total_trades=2” as a hard defect that should block promotion until repaired (it is currently inconsistent with `total_trades=185`). fileciteturn6file0L34-L40