# Combinatorial Arbitrage Implementation Deep Dive

**Integrated:** 2026-03-07  
**Scope:** A-6 multi-outcome sum violations, B-1 LLM dependency graph  
**Status:** Build-approved for paper deployment planning; live promotion still gated by execution-quality metrics

## Decision

The research is strong enough to justify implementation, but only under the current operational constraints:

- Maker-only execution. No taker fallback.
- WebSocket-first market data. REST is bootstrap and recovery only.
- Hard cap of `$5.00` per leg and `$100` maker bankroll allocation.
- Minimum executable edge of `3%` after execution-risk haircut.
- Immediate rollback discipline on partial baskets.

The repo already contains the right scaffolding. The task is not to start over. The task is to upgrade the existing constraint-arb modules into a production-grade A-6/B-1 stack.

## Repo Mapping

| Research concept | Current repo file | Required upgrade |
|---|---|---|
| A-6 market discovery | `bot/sum_violation_scanner.py` | Switch canonical discovery to Gamma `/events` pagination and grouped event handling |
| Quote ingestion / local book | `bot/ws_trade_stream.py` | Add `market` channel support for `book` + `price_change` events and shared LOB state |
| Sum / graph logic | `bot/constraint_arb_engine.py` | Keep existing violation math, add stricter thresholds, dependency cache, and validation hooks |
| Resolution gating | `bot/resolution_normalizer.py` | Keep as the structural guardrail before any B-1 edge is tradable |
| Inventory / neg-risk routing | `bot/neg_risk_inventory.py` | Extend to support complete-basket merge eligibility and linked-leg bookkeeping |
| Live execution | `bot/jj_live.py` | Add batch multi-leg maker path, linked-leg state machine, cancel/rollback logic |
| Capture stats / persistence | `data/constraint_arb.db` | Reuse existing `graph_edges`, `constraint_violations`, and capture-stat tables before creating new DBs |

## A-6: Multi-Outcome Sum Violation

### Market discovery

Canonical discovery flow:

1. Call `GET https://gamma-api.polymarket.com/events` with `active=true`, `closed=false`, `limit=100`, and paginated `offset`.
2. Keep only events where `len(markets) > 2`.
3. Require every child market to have `enableOrderBook=true`.
4. Extract the YES token from each market's `clobTokenIds`.

Pragmatic repo rule: the current `/markets`-based grouping in `bot/sum_violation_scanner.py` is acceptable for shadow scans, but the production path should move to `/events` so grouped markets are first-class objects instead of inferred.

### Real-time monitoring

The existing REST quote polling is now the bottleneck. Upgrade `bot/ws_trade_stream.py` to support:

- `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- Subscription payload with `type="market"` and `assets_ids=[...]`
- Thread-safe `LOB_STATE[token_id] = {best_bid, best_ask, updated_ts}`
- Full `book` snapshot handling plus `price_change` incremental updates

On bootstrap or resync, `GET /book` is still allowed. Handle the known 404 case as a non-fatal condition:

- If the response body contains "No orderbook exists for the requested token id", store `NaN` for that leg.
- Suspend sum validation for the affected event until the WebSocket delivers the first valid quote.

### Signal math

Use executable top-of-book prices:

- Buy basket trigger: `sum(best_ask_yes) < 0.97`
- Sell / unwind trigger: `sum(best_bid_yes) > 1.03`

Do not trade tighter spreads in live mode until capture stats prove otherwise. The 3% buffer is the execution-risk floor, not a suggestion.

### Execution lifecycle

Current repo state:

- `bot/jj_live.py` already enforces `post_only` and initializes the CLOB client with `signature_type=1` and proxy-wallet `funder`.
- What is missing is the multi-leg batch path and linked-leg state management.

Required execution behavior:

1. Submit all legs through the batch order endpoint.
2. Keep order type `GTC` only.
3. Reject any design that mixes `postOnly=true` with `FAK` or `FOK`.
4. Track the basket as one logical unit in `jj_state.json` via a new `linked_legs` structure.
5. If the basket is incomplete after `3000ms`, reprice the remaining edge.
6. If the edge is gone, cancel all resting orders and scratch filled inventory with maker exits at the original entry when possible.

### Capital release

Add a merge helper rather than tying up resolution capital indefinitely.

- Merge only complete baskets.
- Minimum merge threshold: `$20` collateral value.
- Record pre-merge and post-merge capital freed.

Important correction: do not hardcode the address `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` as the Conditional Tokens contract. That address is the Polygon `USDC.e` collateral token. Validate the current CTF contract address at implementation time and keep collateral-token and CTF addresses separate.

## B-1: LLM Dependency Graph

### Candidate pruning

Do not run pairwise LLM classification across the whole active universe. Use a three-stage prefilter:

1. Resolution dates equal or within `72h`
2. Shared Gamma tag or obvious slug/title overlap
3. Embedding cosine similarity `> 0.60`

This should be implemented as an upgrade to the candidate generation path in `bot/constraint_arb_engine.py`, not a separate experimental script.

### Classifier contract

Use Claude Haiku as a deterministic relation classifier with `temperature=0.0`. The output label set should remain small:

- `A_implies_B`
- `B_implies_A`
- `mutually_exclusive`
- `subset`
- `independent`
- `complementary`

Suggested prompt contract:

```text
You are a deterministic logic engine for prediction markets.
Classify the absolute relationship between Market A and Market B.
Use exactly one label:
A_implies_B, B_implies_A, mutually_exclusive, subset, independent, complementary.
Output raw JSON only:
{"relationship":"...", "confidence_score":0.0-1.0, "reasoning":"one sentence"}
Only encode mathematically binding relationships. Ignore plausibility and opinion.
```

### Persistence

Keep the first implementation inside `data/constraint_arb.db` unless write contention becomes real. The repo already has `graph_edges`; use it.

Persist:

- relation label
- confidence
- resolution key
- edge metadata
- validation status

The graph is mostly immutable. Daily processing should be delta-only on new markets.

### Violation monitoring

Default execution threshold: `tau = 0.03`

Live checks:

- `A_implies_B`: trade only when `P_ask(A) > P_bid(B) + tau`
- `mutually_exclusive`: trade only when `P_ask(A) + P_ask(B) > 1.00 + tau`
- `complementary`: trade only when `abs(1 - (P_ask(A) + P_ask(B))) > tau`

Keep initial production scope narrow:

- implication
- mutual exclusion
- complement

Defer long conditional chains until the short-edge categories are validated.

### Validation and halt logic

Before B-1 paper deployment:

- Build a 50-pair manually verified gold set.
- Require `>= 80%` accuracy from the Haiku classifier.

After deployment:

- Run a weekly audit against resolved events.
- Halt B-1 immediately if false-positive rate exceeds `5%`.
- Halt B-1 if more than three consecutive signals lose money due to spread collapse or rollback costs.

## Integration Rules

Signal source assignment:

- Signal Source 5 = A-6 sum violation scanner
- Signal Source 6 = B-1 dependency graph arb

Routing rule:

- Signals 5 and 6 bypass predictive confirmation.
- They still must pass structural gates: resolution normalization, VPIN veto, bankroll cap, linked-leg integrity, and edge-cache validity.

Sizing rule:

- Use execution-risk-adjusted sizing, not directional Kelly.
- Apply the derived fraction to the `$100` maker bankroll.
- Hard truncate at `$5.00` per leg.

## 14-Day Build Sequence

1. Days 1-3: upgrade A-6 discovery to `/events`, add market WebSocket depth handling, and maintain live LOB state.
2. Days 4-5: implement multi-leg batch execution, linked-leg state machine, and rollback timer in `bot/jj_live.py`.
3. Days 6-8: build the B-1 gold set, pruning pipeline, Haiku classifier, and cached graph edge writes.
4. Days 9-10: wire live LOB updates into B-1 violation monitoring with `tau=0.03`.
5. Days 11-12: integrate Signals 5 and 6 into the execution queue, sizing gate, and kill-rule framework.
6. Days 13-14: run shadow mode with realistic fill simulation and publish capture stats.

## Immediate File-Level Task List

- [ ] Replace `/markets` grouping in `bot/sum_violation_scanner.py` with `/events` discovery.
- [ ] Extend `bot/ws_trade_stream.py` from trade stream only to market-depth stream support.
- [ ] Add `LOB_STATE` sharing for A-6 and B-1 consumers.
- [ ] Add explicit 404 bootstrap handling for missing order books.
- [ ] Add batch multi-leg posting to `bot/jj_live.py`.
- [ ] Extend `jj_state.json` schema with `linked_legs`.
- [ ] Add maker-only rollback state machine with `3000ms` timeout.
- [ ] Add merge helper with `$20` minimum threshold and verified contract addresses.
- [ ] Add B-1 candidate pruning and Haiku classification cache to `bot/constraint_arb_engine.py`.
- [ ] Build the 50-pair gold set and resolved-market audit job.
- [ ] Route A-6/B-1 as Signal Sources 5/6 with deterministic bypass semantics.

## Promotion Gates

- A-6: capture ratio must stay `>= 50%` of theoretical over 20 events.
- A-6: zero qualifying events over 4 weeks kills the strategy.
- B-1: gold-set accuracy must remain `>= 80%`.
- B-1: resolved false-positive rate must remain `<= 5%`.
- Global: combined cumulative P&L must be positive after 30 live days or both lanes are shut down.
