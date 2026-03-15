# Finance Control Plane

Status: canonical runbook
Last updated: 2026-03-11
Category: canonical runbook
Canonical: yes

**Version:** 1.0.0
**Updated:** 2026-03-10
**Owner:** John Bradley
**Purpose:** Define the operator contract for the personal CFO control plane under `nontrading/finance/`.

---

## Objective

Treat personal cash, subscriptions, tool spend, trading capital, and experiment budgets as one optimization problem.

Primary objective:

`maximize expected_net_value_30d + expected_information_gain_30d`

Default behavior is not “minimize spend.” Default behavior is “spend, cut, or ask” based on expected value, learning value, and policy constraints.

---

## Locked Defaults

| Policy | Value |
|---|---|
| Scope | full personal CFO |
| End-state authority | full budget / treasury autonomy |
| First connected surface | everything financial |
| Default autonomy mode | `shadow` until rollout gates pass |
| Single-action cap | `JJ_FINANCE_SINGLE_ACTION_CAP_USD=250` |
| Monthly net new commitment cap | `JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD=1000` |
| Cash reserve floor | `JJ_FINANCE_MIN_CASH_RESERVE_MONTHS=1` |
| Startup equity treatment | `JJ_FINANCE_EQUITY_TREATMENT=illiquid_only` |

---

## CLI Contract

The finance CLI lives at `nontrading/finance/main.py`.

| Command | Required behavior | Primary outputs |
|---|---|---|
| `sync` | Ingest account, transaction, position, and subscription truth into the finance store | `reports/finance/latest.json` |
| `audit` | Detect recurring spend, duplicate tools, downgrade/cancel candidates, and gaps | `reports/finance/subscription_audit.json` |
| `allocate` | Rank where the next dollar should go across cash, trading, non-trading, tools/data, and cuts, and emit the autoprompt model-budget ladder | `reports/finance/allocation_plan.json`, `reports/finance/model_budget_plan.json` |
| `execute` | Run queued finance actions in `shadow`, `live_spend`, or `live_treasury` mode | `reports/finance/action_queue.json` |

---

## Data Contract

Finance truth uses a separate SQLite database configured by `JJ_FINANCE_DB_PATH`, with `state/jj_finance.db` as the default target for this cycle.

Connected sources for v1:

- bank and card imports from CSV or OFX files under `JJ_FINANCE_IMPORTS_DIR`
- brokerage or manual positions via CSV
- startup equity snapshots via manual JSON
- trading-account truth from existing Polymarket, Kalshi, and runtime artifacts

The finance plane should prefer existing JSON runtime artifacts over inventing new APIs. When a source is missing, emit a machine-readable gap rather than a fabricated balance or category.

---

## Environment Knobs

| Variable | Meaning |
|---|---|
| `JJ_FINANCE_DB_PATH` | path to the SQLite finance truth store |
| `JJ_FINANCE_AUTONOMY_MODE` | one of `shadow`, `live_spend`, `live_treasury` |
| `JJ_FINANCE_SINGLE_ACTION_CAP_USD` | max dollars for one action in this cycle |
| `JJ_FINANCE_MONTHLY_NEW_COMMITMENT_CAP_USD` | max monthly net new commitments in this cycle |
| `JJ_FINANCE_MIN_CASH_RESERVE_MONTHS` | reserve floor in months of burn |
| `JJ_FINANCE_EQUITY_TREATMENT` | deployable-cash treatment for startup equity |
| `JJ_FINANCE_WHITELIST_JSON` | allowed live-treasury destinations |
| `JJ_FINANCE_IMPORTS_DIR` | location of raw finance imports |

---

## Artifact Contract

Required generated artifacts:

- `reports/finance/latest.json`
- `reports/finance/subscription_audit.json`
- `reports/finance/allocation_plan.json`
- `reports/finance/model_budget_plan.json`
- `reports/finance/action_queue.json`
- `reports/agent_workflow_mining/summary.json`

Expected behavior:

- every artifact is timestamped and machine-readable
- missing inputs appear as explicit gaps, not silent omissions
- every live-capable action includes rollback notes and idempotency context
- every allocation output explains why the next dollar was ranked where it was
- `allocate` must keep research/tooling budget recommendations separate from trading-treasury expansion holds when finance policy allows `live_spend` but blocks `live_treasury`

---

## Allocation Policy

Rank dollars across these buckets:

- `keep_in_cash`
- `fund_trading`
- `fund_nontrading`
- `buy_tool_or_data`
- `cut_or_cancel`

Scoring rule:

- rank all candidates (trading and non-trading) by confidence-adjusted score, not raw edge:

  `arr_conf = max(0, expected_arr_uplift_30d) * confidence_score`
  `score = arr_conf + max(0, expected_information_gain_30d)`

- add explicit uncertainty bands to every expected uplift:
  `expected_arr_uplift_30d_robust = expected_arr_uplift_30d * (1 - expected_arr_uplift_30d_uncertainty)`
- include spend-efficiency as primary tie-breaker:
  `spend_efficiency = (expected_arr_uplift_30d + expected_information_gain_30d) / max(1, compute_cost_usd)`
- enforce all finance hard constraints before ranking persistence:
  - one-month cash floor
  - per-action cap
  - monthly commitment cap
  - destination whitelist for live treasury transfers
  - confidence floor (default minimum 0.6 for approve)
- keep candidate batches ordered even when one candidate is blocked by policy:
  blocked candidates must still appear with explicit `decision: deny/ask` and lock-reason(s)

The allocator should read current BTC5 truth from runtime reports and JJ-N truth from the existing non-trading pipeline surfaces before ranking new deployments.

### Confidence-Weighted Non-Trading ARR Scoring

For non-trading candidates, allocator scoring must apply funnel-level confidence and failed-step learning.

Per candidate:

1. Track Bayesian Beta state per step `s` in the JTN chain:
   `lead -> qualification -> offer -> payout`.
2. For each step:
   - maintain `(α_s, β_s)` from historical successes/failures,
   - compute `p_s = α_s / (α_s + β_s)`.
3. Path confidence:
   `confidence_path = Π p_s`.
4. Confidence-adjusted value:
   - `arr_conf = expected_arr_delta * confidence_path`
   - `velocity_conf = expected_improvement_velocity * confidence_path`
5. Learning penalty from failed steps in the last N cycles:
   `penalty = 0.15 * recent_failed_step_share`.
6. Final allocation score:
   `score = arr_conf + velocity_conf - penalty`.

Minimum gates:

- Reject non-trading recommendations when `confidence_path < 0.6` unless explicitly overridden.
- Emit confidence and gate status into `reports/finance/allocation_plan.json` and `reports/finance/action_queue.json`.
- Penalize repeatedly failing stages until remediation is logged and re-tested.

## Allocation Ranking and Handoff Ledger Contract

Every ranking run must emit a single per-batch ledger in `reports/finance/latest.json`:

- each candidate must include:
  - `candidate_id`
  - `lane` (`trading`, `nontrading`, `tools`, `cut_or_cancel`)
  - `action_key`
  - `expected_arr_uplift_30d`
  - `confidence_score`
  - `compute_cost_usd`
  - `spend_efficiency_ratio`
  - `confidence_interval` (`lower`, `expected`, `upper`)
  - `expected_information_gain_30d`
  - `request_usd`
- each ledger entry must include a hard `decision`:
  - `approve`
  - `deny`
  - `ask`
- each entry must include at least one `decision_reason` and `policy_checks` block with:
  - `reserve_floor_pass`
  - `single_action_cap_pass`
  - `monthly_commitment_cap_pass`
  - `whitelist_destination_pass`
  - `wallet_truth_check_pass`

Handoff rule:

- only `approve` entries may leave finance gating.
- `deny` entries must include a remediation action so the next cycle can recover automatically.
- `ask` entries must include `ask_amount_usd` and `ask_reason` and only emit when expected information gain or ARR uplift exceeds the best alternative deployment with confidence-adjusted score.

---

## Resource Ask Policy

The finance plane must actively ask for:

- more capital
- tools
- data
- compute
- experiment budget

Emit an ask whenever the expected 30-day net value or expected information gain is positive and the ask is more valuable than the next-best use of cash.

Each ask should include:

- `ask_type`
- `amount_usd`
- `why_now`
- `expected_lift`
- `confidence`
- `rollback`
- `blocking_cost_of_inaction`

Default behavior is no longer “stay lean.” If the system is under-resourced, the artifact should say so explicitly.

---

## Staged Autonomy

Rollout order is fixed:

1. `shadow`
2. `live_spend`
3. `live_treasury`

Gate rules:

- stay in `shadow` until transaction-classification precision is `>=95%` and snapshot reconciliation is `>=99%` on fixtures and imported samples
- `live_spend` may cancel subscriptions and buy tools up to configured caps
- `live_treasury` may transfer funds only to destinations listed in `JJ_FINANCE_WHITELIST_JSON`

Hard constraints:

- no unwhitelisted destinations
- no open-ended browser automation
- no action above configured caps
- every transfer needs an idempotency key, cooldown, rollback note, and full telemetry

---

## Metrics Contract

Required finance metrics:

- `free_cash_after_floor`
- `subscription_burn_monthly`
- `cut_candidates_monthly`
- `capital_ready_to_deploy_usd`
- `active_experiment_budget_usd`
- `resource_asks`
- `expected_information_gain_velocity`

Interpretation rules:

- startup equity is illiquid unless policy changes
- `capital_ready_to_deploy_usd` is not gross cash; it is post-floor deployable cash
- `resource_asks` are part of the metrics surface, not side-channel notes
- every metric should disclose whether it is observed, inferred, or missing

---

## Workflow Mining

`reports/agent_workflow_mining/summary.json` feeds this control plane. Repeated finance or trading workflows should become scripts, skills, or AGENTS guidance if they materially reduce context waste or operator latency.

This output is not a generic context doc. It is evidence for:

- prompt cleanup
- script creation
- skill creation
- repeated resource asks caused by tooling gaps

---

## Verification Contract

Required test scenarios for this control plane:

- import and normalize mixed financial sources into one finance snapshot
- recurring/subscription detection and duplicate-tool classification
- allocator respects the one-month cash floor, `$250` action cap, and `$1,000` monthly cap
- equity marked illiquid never counts as deployable cash
- executor rejects unwhitelisted or oversized transfers
- `shadow`, `live_spend`, and `live_treasury` mode transitions enforce the fixed rollout gates
- finance report generation stays stable with missing sources and emits machine-readable gaps rather than silent fabrication
