# Elastifund System Architecture: The Truth-Discovery Machine

## Mission Statement

Elastifund is a system whose primary job is to find candidate edges, kill weak ones quickly, prove strong ones under brutal validation, deploy them carefully, and learn from the gap between simulated and live behavior.

The system does not exist to generate trades. It exists to discover truth about whether a repeatable, net-positive trading edge exists in a given market structure. Trading is the test. P&L is the scorecard. But the machine itself is an epistemological engine: it asks questions about market microstructure and demands answers backed by data, mechanism, and live replication.

## Core Principle

**Design the system to disprove itself faster than it can fool itself.**

Every component, every feedback loop, every validation gate is oriented around one insight: backtests lie. Optimizers overfit. LLMs hallucinate alpha. The only reliable signal is a strategy that survives repeated, systematic attempts to kill it and then replicates out-of-sample and in live markets.

The system defaults to skepticism. A strategy is guilty (worthless) until proven innocent (net-positive after all costs, across regimes, with statistical rigor). The burden of proof is on the strategy, not the researcher.

---

## The Validated Net Edge Scorecard

Every strategy is ultimately reduced to a single number:

```
Validated Net Edge = lower_confidence_bound_gross_alpha
                   - all_in_execution_cost
                   - financing_funding
                   - model_error_buffer
                   - tail_risk_penalty
```

A strategy is only interesting if this number is positive. Each component:

| Component | What It Captures |
|-----------|-----------------|
| `lower_confidence_bound_gross_alpha` | The pessimistic (e.g., 5th percentile) estimate of raw signal return, not the point estimate. We use the lower bound because point estimates are where overfit hides. |
| `all_in_execution_cost` | Spread, market impact, fees (maker/taker), slippage, partial fills, cancel-replace costs, and latency tax. Measured from live fills, not assumed. |
| `financing_funding` | Cost of capital, margin requirements, funding rates, roll costs, overnight carry. For prediction markets: opportunity cost of locked capital. |
| `model_error_buffer` | A penalty for model complexity and estimation uncertainty. More parameters = larger buffer. Calibrated from historical model-vs-realized divergence. |
| `tail_risk_penalty` | Expected cost of drawdowns, gap risk, liquidity evaporation, and correlation spikes. Measured via regime-conditional max drawdown and tail VaR. |

If Validated Net Edge <= 0, the strategy is killed regardless of how good the backtest looks.

---

## The Five Proofs (Promotion Requirements)

No strategy advances to live capital without satisfying all five proofs. Missing even one is grounds for rejection or demotion.

### 1. Mechanism Proof

**Question:** Why does this edge exist, and who is on the other side of the trade?

- There must be a believable economic or structural reason the edge persists.
- "It works in backtest" is not a mechanism. "Retail participants systematically overprice momentum continuation in 5-minute crypto candles because they anchor to the last move" is a mechanism.
- The mechanism must explain who pays (the counterparty), why they keep paying (structural reason they cannot or will not adapt), and what would cause the mechanism to stop working (regime change, competition, rule changes).

### 2. Data Proof

**Question:** Is the signal built exclusively from data that was available at decision time?

- Every feature must pass a strict point-in-time availability check.
- No revised data (GDP revisions, restated financials, corrected feeds).
- No future leakage through joins, aggregations, or implicit look-ahead.
- The data pipeline must be auditable: for any historical signal value, you can prove exactly what data was available when the signal was computed.

### 3. Statistical Proof

**Question:** Does the signal survive rigorous out-of-sample testing, multiple-testing corrections, and regime decomposition?

- Out-of-sample performance within a reasonable range of in-sample (no cliff drop).
- Survives Bonferroni or BH correction for the number of hypotheses tested in the same family.
- Positive across at least 2 of 3 macro regimes (trending, mean-reverting, crisis).
- Deflated Sharpe Ratio (DSR) and Probability of Backtest Overfitting (PBO) computed and reported.
- Parameter stability: performance does not collapse under small perturbations of signal parameters.

### 4. Execution Proof

**Question:** Is the strategy still profitable after realistic execution?

- Uses observed fill rates from live or paper trading, not assumed 100% fill.
- Accounts for actual spread (not mid-to-mid), queue position, partial fills, and cancel rates.
- Includes all fees at the correct tier (maker vs taker, volume-based).
- Latency modeled from actual system measurements, not assumed zero.
- For maker strategies: accounts for adverse selection (fills happen disproportionately when price moves against you).

### 5. Live Proof

**Question:** Does paper/micro-live trading match the simulator closely enough to trust the signal?

- Paper trading for minimum 50 trades or 7 calendar days (whichever is longer).
- Sim-vs-live divergence < 20% on key metrics (win rate, average P&L per trade, max drawdown).
- If divergence exceeds 20%, the strategy returns to validation. It does not proceed to full capital.
- Micro-live (real money, minimum position size) for an additional validation window before scaling.

---

## The Four Validation Gates

Strategies pass through four increasingly expensive gates. Each gate is designed to catch a different class of false positive.

### Bronze Gate (Cheap Rejection)

**Purpose:** Kill obviously bad ideas before wasting compute on them.

**Cost:** Minutes. Simple checks, no heavy computation.

**Checks:**
- **Leakage scan:** Automated detection of future data in features (join timestamps, aggregation windows, data availability lags).
- **Baseline comparison:** Does the signal beat a naive baseline (buy-and-hold, random, always-predict-base-rate)? If not, reject immediately.
- **Conservative cost filter:** Apply 2x estimated execution costs. If the strategy dies at 2x costs, it will probably die at 1x costs in live.
- **Rolling-window sanity:** Signal must be positive in at least 60% of non-overlapping windows. A strategy that works brilliantly in one period and fails everywhere else is overfit to that period.
- **Sign consistency:** The signal's direction (long/short, over/under) must be consistent with the stated mechanism. If the mechanism says "mean reversion" but the signal is momentum, something is wrong.

### Silver Gate (Full Research Validation)

**Purpose:** Rigorous statistical testing for strategies that survive Bronze.

**Cost:** Hours. Full backtest infrastructure, multiple evaluation passes.

**Checks:**
- **Walk-forward validation:** Expanding or rolling window, never a single train/test split. Minimum 5 folds.
- **Regime decomposition:** Performance broken out by volatility regime, trend regime, and liquidity regime. Must be positive in at least 2 of 3.
- **Per-instrument attribution:** If the strategy trades multiple instruments, it must show alpha in at least 60% of them. A strategy carried by one outlier instrument is fragile.
- **Realistic cost model:** Spread, impact, fees modeled from actual market data (observed spreads, measured impact coefficients), not generic assumptions.
- **Exposure decomposition:** Factor out common risk exposures (market beta, momentum, value, volatility). What remains after factor neutralization? If the answer is "nothing," the strategy is a disguised factor bet, not alpha.

### Gold Gate (False Discovery Defense)

**Purpose:** Guard against the most insidious form of overfitting: the strategy that looks great because you tested 500 variations and picked the winner.

**Cost:** Hours to days. Requires full combinatorial analysis.

**Checks:**
- **Purged and embargoed cross-validation:** Training and test sets separated by a gap (embargo period) to prevent information leakage through serial correlation. Purge overlapping samples from the training set.
- **Locked holdout:** A portion of data (minimum 20%) that is NEVER used for any purpose during research. Touched exactly once, at the end, as the final gate. If it fails on the holdout, the strategy is dead regardless of all other results.
- **Multiple-testing accounting:** Formally track how many hypotheses were tested in this strategy family. Apply Bonferroni, BH, or DSR correction. Report the adjusted p-value, not the raw one.
- **Deflated Sharpe Ratio (DSR):** Adjusts the observed Sharpe for the number of trials, skewness, and kurtosis of returns. A Sharpe of 2.0 after testing 200 strategies is much less impressive than a Sharpe of 2.0 after testing 3.
- **Probability of Backtest Overfitting (PBO):** Combinatorial analysis of performance across data subsets. If >40% of combinations show the strategy is overfit, reject.
- **Parameter stability:** Perturb each signal parameter by +/-10% and +/-20%. If performance falls off a cliff, the strategy is sitting on a fragile optimum and will not survive in live markets.

### Platinum Gate (Reality Check)

**Purpose:** Bridge the gap between simulation and reality.

**Cost:** Days to weeks. Requires live market interaction.

**Stages:**
1. **Shadow mode:** Strategy generates signals in real time but does not trade. Compare signal timing and direction to what the execution layer would have done. Check for systematic delays, data feed issues, or signal computation errors that only appear in live conditions.
2. **Paper trading:** Execute on a paper account with realistic fill simulation. Track fill rates, queue position accuracy, and latency. Minimum 50 trades or 7 days.
3. **Micro-live:** Deploy with minimum position size ($1-5 per trade). Real money, real fills, real adverse selection. This is where the truth lives.
4. **Sim-vs-live comparison:** Formally measure the gap between simulated and live performance. Track divergence on: win rate, average P&L, max drawdown, fill rate, average slippage. If any metric diverges by >20%, return to Silver Gate for investigation.

---

## Experiment Lifecycle

Every strategy idea follows a deterministic state machine:

```
Idea --> Scoped --> Implemented --> Backtested --> Validated --> Shadow --> Paper --> Micro-live --> Live --> Retired
```

| State | Entry Criteria | Exit Criteria |
|-------|---------------|---------------|
| **Idea** | Someone (human or agent) proposes a mechanism | Hypothesis card filled out with all required fields |
| **Scoped** | Hypothesis card complete | Data sources identified, implementation plan written |
| **Implemented** | Code written, unit tests passing | Backtest can run end-to-end without errors |
| **Backtested** | Full historical run complete | Bronze Gate passed |
| **Validated** | Silver + Gold Gates passed | All five proofs documented |
| **Shadow** | Shadow mode deployed | 7 days of real-time signal generation, no systematic errors |
| **Paper** | Paper trading live | 50+ trades, sim-vs-paper divergence < 20% |
| **Micro-live** | Real money at minimum size | 50+ trades, paper-vs-live divergence < 20% |
| **Live** | Promoted to production sizing | Continuous monitoring, auto-demotion on drift |
| **Retired** | Performance degrades below threshold | Post-mortem written, kill propagation checked |

**Backward transitions are mandatory.** If a Live strategy's performance drifts below threshold, it returns to Paper (not to Idea). If a Paper strategy's sim-vs-live gap widens, it returns to Validated for investigation.

**No state can be skipped.** A strategy cannot go from Backtested to Live. Every gate exists because a previous shortcut caused a loss.

---

## The Five Feedback Loops

The system learns at five distinct points. Each loop closes a gap between expectation and reality.

### Loop 1: Execution to Data

```
Bot places trade --> fill confirmed --> unified ledger updated --> P&L calculated
```

The unified ledger (`bot/unified_ledger.py`) is the single source of trade truth. Every fill, every reject, every partial fill, every cancel is recorded with microsecond timestamps, venue, strategy ID, and the signal state at the time of the decision.

This loop runs continuously. Latency target: fill-to-ledger < 100ms.

### Loop 2: Data to Research

```
Trade outcomes --> update strategy scores --> re-rank hypothesis backlog
```

As trades resolve, their outcomes update the strategy's running performance metrics (win rate, Sharpe, drawdown, fill rate). These metrics feed back into the hypothesis backlog ranking, promoting strategies that are performing and demoting those that are degrading.

This loop runs daily. The `edge_backlog_ranked.md` is regenerated from current performance data.

### Loop 3: Research to Parameters

```
Hypothesis test completes --> promote or kill --> update live config --> restart service
```

When a hypothesis passes or fails a validation gate, the result propagates to the live configuration. A promotion unlocks a new strategy for shadow/paper/live. A kill removes it from the active roster and triggers kill propagation (see below) to check if related strategies should also be killed.

This loop runs per-experiment. Parameter changes require the Medium or Slow learning speed (see below).

### Loop 4: Parameters to Execution

```
New config deployed --> service restarts --> trades with new parameters
```

Configuration changes (position sizes, Kelly fractions, volatility scaling parameters, time-of-day filters) are deployed via the `deploy.sh` pipeline. The bot reads its configuration at startup and applies it immediately.

This loop runs on deployment. All parameter changes are version-controlled and auditable.

### Loop 5: Monitoring to Alerting to Intervention

```
Anomaly detected --> alert sent --> auto-adjustment or escalation
```

The execution liveness monitor (`bot/execution_liveness.py`) continuously checks for:
- Unexpected gaps in trading activity
- Fill rate drops below threshold
- Drawdown approaching daily limit
- Sim-vs-live divergence exceeding tolerance
- Data feed staleness or corruption

Auto-adjustments (position size reduction, strategy pause) happen without human intervention. Escalation to John happens only for conditions outside the system's authority (see Prime Directive escalation rules).

---

## Three Learning Speeds

The system adapts at three different timescales, each with different authority and validation requirements.

### Fast Loop (Daily/Intraday)

**What changes:** Volatility scaling, spread/impact estimates, execution aggression, intraday risk limits.

**Authority:** Fully autonomous. No human approval needed.

**Validation:** Changes are bounded (e.g., volatility scalar can move +/-20% per day, not 10x). Bounded changes cannot cause catastrophic loss because the risk limits themselves are set at the Slow Loop level.

**Examples:**
- BTC realized volatility increases 50%. The fast loop scales position sizes down proportionally within the same session.
- Observed spread widens. The fast loop adjusts the minimum edge threshold to avoid negative-EV trades.
- Fill rate drops below 10%. The fast loop pauses order placement until the rate recovers.

### Medium Loop (Weekly)

**What changes:** Signal coefficients, feature weights, ensemble weights, regime classifier thresholds, kill-propagation sweeps.

**Authority:** Autonomous within bounds. Changes that affect capital allocation by more than 25% require John's review.

**Validation:** Walk-forward re-estimation on the latest data. Changes must improve out-of-sample metrics or they are rejected.

**Examples:**
- Weekly re-estimation of the BTC 5-min signal's optimal delta threshold based on the latest 7 days of fills.
- Kill-propagation sweep: a strategy family's flagship is killed; the sweep checks if sibling strategies share the same failed mechanism and kills them too.
- Ensemble weight update: strategy A's allocation increases from 30% to 40% because its recent Sharpe improved relative to strategy B.

### Slow Loop (Monthly, Requires Approval)

**What changes:** New feature families, new models, new execution logic, new markets, new risk parameters.

**Authority:** Requires John's explicit approval. These changes alter the system's fundamental behavior.

**Validation:** Must pass the full Bronze, Silver, Gold, and Platinum gate sequence. No shortcuts.

**Examples:**
- Adding a new prediction market platform (e.g., Kalshi integration).
- Introducing a new signal family (e.g., order flow imbalance features).
- Changing the Kelly fraction from 0.25 to 0.50.
- Expanding from crypto prediction markets to equity prediction markets.

---

## Data Architecture (Five Layers)

Data flows through five layers, each with strict immutability and access rules.

### Layer A: Raw Immutable Store

**Contents:** Original market data feed exactly as received from the venue. WebSocket messages, REST API responses, raw CSV exports.

**Rules:**
- Write-once, never overwrite, never delete.
- Stored with reception timestamp (not event timestamp).
- No transformations, no cleaning, no filtering.
- If the feed sends garbage, the garbage is stored. Cleaning happens in Layer B.

**Purpose:** Reproducibility. Any analysis can be re-run from the original data. If a bug is found in the normalization layer, the raw data is still available to fix it.

### Layer B: Normalized Event Store

**Contents:** Cleaned, typed, and timestamped events derived from Layer A. Trades, quotes, book snapshots, corporate actions, venue status changes, reference data updates.

**Rules:**
- Each event has: event_time, receipt_time, event_type, instrument_id, venue, and payload.
- Normalization code is versioned. When the normalizer changes, old events are NOT retroactively updated. Instead, a new version column is added.
- Deduplication applied (venues sometimes send duplicate messages).

**Purpose:** A uniform event interface that downstream systems can consume without knowing the raw feed format.

### Layer C: Point-in-Time Master

**Contents:** Universe membership, symbol mappings, event calendars, market metadata. All point-in-time correct.

**Rules:**
- Every record has valid_from and valid_to timestamps.
- A query for "what markets were active on March 10 at 14:00 UTC" returns the answer as of that moment, not as of today.
- Symbol changes, market closures, rule changes are all tracked with their effective dates.

**Purpose:** Prevents survivorship bias and look-ahead bias in research. The universe you could have traded on a historical date is not the same as the universe available today.

### Layer D: Feature Store

**Contents:** Derived signals and features computed from Layers A-C.

**Rules:**
- Every feature record has: observation_time (when the feature was computed), availability_time (when the data was actually available to compute it), instrument_id, feature_name, feature_version, and value.
- observation_time <= availability_time always. A feature cannot be "available" before the data it depends on arrives.
- Feature code is versioned. When the computation changes, a new version is created. Old versions remain queryable for backtest reproducibility.

**Purpose:** The feature store is the interface between research and execution. Both the backtester and the live signal generator read from the same feature definitions, ensuring consistency.

### Layer E: Frozen Training Snapshots

**Contents:** Versioned, immutable snapshots of the feature store at specific points in time, used for model training and validation.

**Rules:**
- Once frozen, a snapshot is never modified.
- Each snapshot records: creation_date, feature_version, date_range, instruments_included, and a hash of the data.
- Models trained on a snapshot record the snapshot ID. This enables full reproducibility: given the same snapshot and the same code, the same model is produced.

**Purpose:** Prevents the subtle form of overfitting where the training data silently changes between experiments (e.g., because a bug fix in the feature code retroactively altered historical values).

---

## Hypothesis Card Template

Every strategy idea, before any code is written, must be documented in a hypothesis card. This forces the researcher (human or agent) to think through the mechanism before falling in love with a backtest.

### Required Fields

| Field | Description |
|-------|-------------|
| `hypothesis_name` | Short, descriptive name (e.g., "BTC 5-min DOWN bias during Asian hours") |
| `market_universe` | Which markets/instruments this applies to |
| `horizon` | Expected holding period and signal decay rate |
| `economic_mechanism` | Who is on the other side? Why do they keep paying? What stops this from being arbitraged away? |
| `signal_definition` | Precise mathematical or algorithmic definition of the signal. No ambiguity. |
| `execution_style` | Maker/taker, order type, timing, position sizing approach |
| `expected_costs` | Estimated spread, fees, impact, slippage. Source for estimates. |
| `risk_exposures` | What market factors is this exposed to? (Directional, volatility, correlation, liquidity) |
| `failure_modes` | How could this strategy lose money even if the signal is real? (Execution risk, regime change, competition, data issues) |
| `validation_plan` | Specific steps to validate: which gates, which data splits, what minimum sample size |
| `retirement_criteria` | Concrete conditions under which this strategy should be killed (e.g., "Win rate below 48% over 200 trades", "Max drawdown exceeds 3x initial estimate") |

### Optional Fields

| Field | Description |
|-------|-------------|
| `related_hypotheses` | Links to sibling strategies in the same mechanism family |
| `kill_propagation_group` | If this hypothesis is killed, which others should be re-examined? |
| `data_requirements` | Specific feeds, APIs, or datasets needed |
| `estimated_capacity` | How much capital can this strategy absorb before impact degrades the edge? |
| `competitive_landscape` | Who else might be trading this? How crowded is it? |

---

## Agent Roles

The system is designed for multi-agent operation. Each agent has a defined role, clear inputs and outputs, and explicit boundaries.

### Literature Agent
**Input:** Academic papers, blog posts, market structure reports, exchange rule changes.
**Output:** Structured summaries with relevance scores and potential hypothesis seeds.
**Boundary:** Reads and summarizes only. Does not propose strategies directly (that is the Hypothesis Agent's job).

### Hypothesis Agent
**Input:** Literature summaries, market data anomalies, failed strategy post-mortems.
**Output:** Completed hypothesis cards with all required fields.
**Boundary:** Proposes ideas with mechanisms. Does not implement or test them.

### Data Agent
**Input:** Hypothesis cards, data availability questions.
**Output:** Data source recommendations, leakage risk assessments, point-in-time feasibility reports.
**Boundary:** Advises on data. Does not write strategy code.

### Implementation Agent
**Input:** Approved hypothesis cards with validation plans.
**Output:** Strategy modules with tests, integrated into the codebase.
**Boundary:** Writes code and tests. Does not evaluate whether the strategy works (that is the Validation Agent's job).

### Validation Agent
**Input:** Implemented strategies ready for backtesting.
**Output:** Gate reports (Bronze, Silver, Gold) with pass/fail decisions and supporting evidence.
**Boundary:** Runs validation. Does not modify strategy code. If a strategy fails, it returns to the Implementation Agent with specific failure reasons.

### Red-Team Agent
**Input:** Strategies that have passed Gold Gate.
**Output:** Attack reports documenting any discovered leakage, hidden factor bets, execution fantasy, or regime dependence.
**Boundary:** Adversarial analysis only. Tries to break the strategy. If it succeeds, the strategy returns to Validation with the failure documented.

### Post-Trade Analyst
**Input:** Live trading data, sim-vs-live comparison reports.
**Output:** Divergence analysis, root cause identification, parameter adjustment recommendations.
**Boundary:** Analyzes live performance. Does not modify live code (that requires going through the proper deployment pipeline).

### Report Agent
**Input:** All of the above.
**Output:** Strategy dossiers, weekly summaries, public-facing research reports, website content.
**Boundary:** Writes documentation. Ensures every claim traces to data.

---

## Anti-Overfitting Non-Negotiables

These are not guidelines. They are hard rules. Violating any one of them invalidates the result.

1. **Default assumption: the backtest is lying until proven otherwise.** Every backtest result is treated as a hypothesis about the future, not evidence of the future. The system's job is to disprove it.

2. **Never optimize on annualized return alone.** ARR is the easiest metric to game (leverage, concentration, look-ahead). Always require risk-adjusted metrics (Sharpe, Sortino, Calmar) alongside raw return, and always at the lower confidence bound.

3. **Never accept a result without a mechanism story.** "It works" is not sufficient. "It works because retail participants in crypto prediction markets systematically underweight mean reversion in 5-minute windows" is a mechanism. The mechanism must predict when the edge will stop working.

4. **Never use revised or non-point-in-time data.** GDP is revised. Earnings are restated. Reference data changes. If your backtest uses data that was not available at the time the trading decision would have been made, the backtest is invalid.

5. **Always track how many trials were attempted.** If you tested 100 variations and report the best one, your p-value is 100x worse than you think. The system formally tracks trial count per hypothesis family and applies multiple-testing corrections.

6. **Never auto-deploy LLM-written code without review.** The Implementation Agent writes code. A human or the Validation Agent reviews it before it touches live capital. LLMs are excellent at generating plausible-looking bugs.

7. **Never scale position size before paper/live match is established.** A strategy running at $5/trade tells you something. A strategy running at $500/trade tells you something different (impact, adverse selection, fill rate changes). Scale gradually and re-validate at each size tier.

8. **Never keep a strategy alive because of one great historical period.** A strategy that made 80% of its backtest profit in March 2020 is not a strategy. It is a bet that March 2020 will happen again. Regime decomposition catches this.

---

## Key Infrastructure

| Component | Location | Purpose |
|-----------|----------|---------|
| Unified Ledger | `bot/unified_ledger.py` | Single source of trade truth. Every fill, reject, cancel recorded with timestamps and strategy ID. |
| Promotion Gate | `src/promotion_gate.py` | Implements the 5-proof validation framework. Blocks deployment of strategies that fail any proof. |
| Hypothesis Cards | `src/hypothesis_card.py` | Structured strategy proposals with all required fields. Enforces mechanism-first thinking. |
| Experiment Registry | `src/experiment_registry.py` | Lifecycle state machine tracking every strategy from Idea to Retired. No state skipping. |
| Negative Results | `src/negative_results.py` | Formal documentation of what failed and why. Prevents re-testing known-dead ideas. |
| Kill Propagation | `src/kill_propagation.py` | When a strategy is killed, checks if related strategies (same mechanism family) should also be killed. |
| Learning Loops | `bot/learning_loops.py` | Implements fast/medium/slow parameter adaptation with appropriate authority levels. |
| Fill Callback | `bot/fill_callback.py` | Execution-to-research feedback. Every fill triggers ledger update, P&L recalculation, and strategy score update. |
| Execution Liveness | `bot/execution_liveness.py` | Continuous monitoring of trading activity, fill rates, drawdowns, and data feed health. |
| BTC 5-Min Maker | `bot/btc_5min_maker.py` | Primary live strategy: 5-minute BTC candle direction prediction on Polymarket. |
| Deploy Pipeline | `scripts/deploy.sh` | Automated deployment to Dublin VPS with config validation and service restart. |
| Autoresearch Loop | `scripts/run_btc5_autoresearch_loop.py` | Automated hypothesis generation, testing, and promotion for BTC5 strategy family. |

---

## Mechanism Families (Research Starting Points)

These are the eight broad categories of market inefficiency that the system searches within. Each family has a structural reason to exist and a known set of failure modes.

### 1. Forced Flows
**Mechanism:** Participants who must trade regardless of price (index rebalances, margin calls, regulatory requirements, ETF creation/redemption).
**Edge:** Predictable price pressure from non-discretionary flows.
**Failure mode:** Competition from other flow predictors erodes the edge. Venues change rebalance mechanics.

### 2. Inventory Pressure
**Mechanism:** Market makers or dealers holding unwanted inventory must offload it, creating predictable price pressure.
**Edge:** Identifying when a market maker is long/short inventory and trading the expected mean reversion.
**Failure mode:** Inventory signals are noisy. Multiple market makers obscure the aggregate picture.

### 3. Event Underreaction/Overreaction
**Mechanism:** Markets systematically misprice the probability or magnitude of events (earnings, policy decisions, geopolitical events).
**Edge:** Calibrated probability estimates that are more accurate than market-implied probabilities.
**Failure mode:** The market may be correctly pricing information you do not have. Overconfidence in your probability estimate.

### 4. Residual Mean Reversion
**Mechanism:** After controlling for fundamental factors, short-term price dislocations revert. Caused by temporary liquidity shocks, overreaction to noise, or mechanical stop-loss cascades.
**Edge:** Trading the reversion after the dislocation.
**Failure mode:** Not all dislocations revert. Some are the beginning of a fundamental repricing.

### 5. State-Dependent Momentum
**Mechanism:** Momentum works in some market states (trending, high-conviction) and fails in others (mean-reverting, choppy). A regime classifier can select when to apply momentum.
**Edge:** Conditional momentum that avoids whipsaw periods.
**Failure mode:** Regime classifiers are themselves subject to overfitting. The regime you identify may not persist.

### 6. Cross-Asset Lead-Lag
**Mechanism:** Information flows between related markets at different speeds. Liquid markets lead illiquid ones. Futures lead cash. Options lead stock.
**Edge:** Trading the lagging asset in the direction of the leading asset's move.
**Failure mode:** Lead-lag relationships are unstable and reverse. Latency competition is fierce.

### 7. Funding/Roll/Carry Distortions
**Mechanism:** The cost of holding positions (funding rates, futures roll, carry) creates predictable returns that are not pure risk premia.
**Edge:** Harvesting carry when the funding distortion is large relative to risk.
**Failure mode:** Carry strategies have negative skew. They earn small amounts consistently and lose large amounts rarely. The tail risk is real.

### 8. Volatility Regime Transitions
**Mechanism:** Volatility is persistent and mean-reverting. Transitions between low-vol and high-vol regimes are somewhat predictable and create opportunities in options, prediction markets, and volatility-sensitive strategies.
**Edge:** Positioning for regime transitions before they are fully priced.
**Failure mode:** Timing regime transitions is hard. Being early is the same as being wrong.

---

## Dashboards (Four Required Views)

The system must maintain four dashboards that provide real-time visibility into its operation. These are not nice-to-haves. They are operational requirements.

### 1. Research Dashboard

**Purpose:** Where is the research pipeline? What is working? What is dying?

**Key metrics:**
- Hypothesis count by lifecycle state (Idea, Scoped, Implemented, Backtested, Validated, Shadow, Paper, Live, Retired)
- Kill rate by gate (what percentage of strategies die at Bronze, Silver, Gold, Platinum?)
- Mechanism family health (which families are producing survivors? which are dead?)
- Time-in-state (how long do strategies sit at each gate? bottlenecks?)
- Trial count tracking (how many hypotheses tested per family? multiple-testing budget consumed?)

### 2. Validation Dashboard

**Purpose:** Are our validation methods working? Are we catching overfitting?

**Key metrics:**
- DSR and PBO for every strategy that passed Silver Gate
- Regime decomposition results (performance by market state)
- Live-vs-sim divergence for every strategy in Shadow/Paper/Live
- Parameter stability heatmaps (how sensitive is each strategy to parameter perturbation?)
- Historical gate accuracy (of strategies we promoted, how many later failed in live? false positive rate)

### 3. Live Operations Dashboard

**Purpose:** What is the system doing right now?

**Key metrics:**
- Current positions and exposures by strategy and instrument
- Order flow: placed, filled, rejected, cancelled, partially filled
- Real-time P&L by strategy
- Slippage tracking (expected vs actual fill price)
- Kill-switch state (armed, tripped, reason)
- Data feed health (latency, staleness, error rate)
- System resource utilization (CPU, memory, network, disk)

### 4. Strategy Health Dashboard

**Purpose:** Are deployed strategies still healthy?

**Key metrics:**
- Expected vs realized alpha (is the strategy delivering what validation predicted?)
- Performance drift detection (rolling Sharpe, rolling win rate with confidence bands)
- Decay half-life estimate (how quickly is the edge decaying?)
- Capacity utilization (how much of the estimated capacity is being used?)
- Correlation with other deployed strategies (are we more concentrated than we think?)
- Auto-demotion triggers (which strategies are close to their retirement criteria?)

---

## Appendix: Design Rationale

### Why "Truth-Discovery Machine" and Not "Trading System"

Most trading systems are designed to maximize P&L. This system is designed to maximize the accuracy of its beliefs about what generates P&L. The distinction matters because a P&L-maximizing system will overfit, overtrade, and eventually blow up. A truth-maximizing system will sometimes choose not to trade because it has not yet proven that trading is the right action.

The system makes money as a side effect of being correct about market microstructure. It loses money as a signal that its beliefs were wrong. Both outcomes are information. The system's job is to extract the maximum information from both.

### Why Five Proofs Instead of One

A single validation metric (e.g., Sharpe ratio) can be gamed. Five orthogonal proofs are much harder to game simultaneously. A strategy that has a great Sharpe but no mechanism story is probably overfit. A strategy with a great mechanism but poor execution is probably theoretical. Requiring all five proofs forces strategies to be robust across multiple dimensions.

### Why Four Gates Instead of Pass/Fail

A single pass/fail gate creates a binary decision at one point in time. Four sequential gates create a funnel that allocates research resources efficiently. Cheap checks happen first (Bronze), expensive checks happen only for survivors. This prevents the system from wasting weeks on full validation of ideas that could have been rejected in minutes.

### Why Three Learning Speeds

A system that adapts too quickly will overfit to noise. A system that adapts too slowly will miss regime changes. Three speeds allow different types of parameters to adapt at their natural timescale. Volatility changes daily (fast loop). Signal coefficients change weekly (medium loop). The set of markets we trade changes monthly (slow loop). Matching adaptation speed to parameter timescale is a fundamental design principle.
