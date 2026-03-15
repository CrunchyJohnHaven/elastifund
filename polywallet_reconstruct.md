# Polywallet Reconstruct Packet

| Field | Value |
|---|---|
| File | `polywallet_reconstruct.md` |
| Purpose | Focused deep-research handoff for reconstructing elite Polymarket fast-market wallets |
| Scope | Public-wallet reconstruction in Polymarket 5-minute and 15-minute markets, plus nearby fast crypto lanes when they explain the edge |
| Created | 2026-03-12 |
| Companion root packet | `COMMAND_NODE.md` |
| Important note | This file is a focused research brief, not a replacement for `COMMAND_NODE.md` or `PROJECT_INSTRUCTIONS.md` |

## Mission

We want to identify the most successful public Polymarket accounts operating in 5-minute and 15-minute markets, pull every public artifact we can get, reconstruct their strategies in maximum detail, choose the best-of-breed strategy that is both real and replicable, and then run an autoresearch loop until the residual unexplained behavior is as small as possible.

This is not a generic "find smart wallets" task.
This is a reconstruction task.

The target outcome is:

1. Find the elite fast-market accounts that matter.
2. Separate directional traders from market makers, rebate farmers, inventory managers, hedgers, spread scalpers, and multi-wallet clusters.
3. Reconstruct how they choose markets, when they enter, when they exit, how they size, how they hedge, whether they quote both sides, and what their likely core edge is.
4. Produce a clone-ready strategy packet for the strongest public strategy that fits Elastifund's constraints.

## Honesty Rule For Deep Research

Deep research should aim to return the closest thing to a perfect answer that public evidence allows: exhaustive, source-linked, reproducible, and explicit about what is known, what is inferred, and what remains unknowable without private data.

Do not fake certainty.
Do not give generic strategy fluff.
Do not hide uncertainty behind vague prose.
Do give the most complete answer possible.
Do explicitly call out the unknowns that still block a true "perfect" reconstruction.

## What The Deep Research Agents Must Return

Return one comprehensive report with all of the following:

1. A ranked list of the best Polymarket fast-market wallets, with exact wallet addresses, ranking rationale, and evidence.
2. A wallet dossier for each top candidate:
   wallet, aliases, public profile, market mix, time-window mix, side bias, asset mix, position style, realized PnL surfaces, current inventory style, and likely strategy family.
3. A determination of whether each wallet is primarily:
   directional,
   maker-market-making,
   liquidity-reward optimization,
   latency / lead-lag,
   dual-sided inventory harvesting,
   hedged spread capture,
   copy-trading,
   or some hybrid.
4. A reconstruction of exact or near-exact strategy rules for the best wallet or best wallet cluster.
5. A replication plan for Elastifund:
   what is directly copyable,
   what is inferable but not directly visible,
   what must be simulated,
   and what is probably not worth copying.
6. A list of irreducible unknowns:
   maker/taker ambiguity, hidden quote placement, private infra, multi-wallet ownership, internal hedges, builder incentives, or off-platform signals.
7. An autoresearch loop design:
   hypothesis generation,
   replay,
   fit scoring,
   targeted follow-up queries,
   iteration thresholds,
   and stop criteria.
8. A final recommendation:
   the single best strategy family to pursue first, with explicit confidence and evidence level.

## Core Working Hypothesis

The naive story is:
"Find top wallets in 5-minute / 15-minute markets and copy their direction."

The more serious working hypothesis after the live pull below is:
"At least some of the top fast-market wallets are not simple directional forecasters at all. They appear to run two-sided books, inventory management, spread capture, and possibly maker/rebate harvesting on short-duration crypto markets. The reconstruction target may be quote logic and position management, not simple one-side prediction."

This distinction matters.
If the elite accounts are mostly makers or inventory managers, simple follower-copy logic will underperform badly because public trades arrive after the edge is already expressed.

## Current Live Observations To Anchor The Research

The following observations were pulled live on 2026-03-12 from public Polymarket endpoints.
Treat them as a seed set, not the final answer.

### A. Current Public Crypto Leaderboard Seeds

Live pull source:

- `https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=ALL&orderBy=PNL&limit=10`
- `https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=MONTH&orderBy=PNL&limit=10`
- `https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=WEEK&orderBy=PNL&limit=10`

Notable names appearing near the top:

| Wallet | Name | All-time crypto rank | Month rank | Week rank | Immediate note |
|---|---|---:|---:|---:|---|
| `0x63ce342161250d705dc0b16df89036c8e5f9ba9a` | `0x8dxd` | 1 | 4 | 4 | Canonical fast-market wallet candidate |
| `0xd0d6053c3c37e727402d84c14069780d360993aa` | `k9Q2mX4L8A7ZP3R` | 4 | 2 | 3 | Strong all-time plus current-period presence |
| `0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9` | `BoneReader` | 15 | 3 | 2 | Current hot wallet with heavy fast-market activity |
| `0x2d8b401d2f0e6937afebf18e19e11ca568a5260a` | `vidarx` | not in sampled all-time top 15 | 5 | 5 | Current-period specialist, heavily BTC-focused |
| `0x1f0ebc543b2d411f66947041625c0aa1ce61cf86` | auto-generated display name | not in sampled all-time top 15 | 6 | 6 | Current-period high-PnL specialist |
| `0x1979ae6b7e6534de9c4539d0c205e582ca637c9d` | auto-generated display name | 5 | not in sampled month top 15 | not in sampled week top 15 | Strong historical fast-market activity |
| `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d` | `gabagool22` | 9 | not in sampled month top 15 | not in sampled week top 15 | Historical fast-market activity |

### B. Fast-Market Screening Result

Screening method used for the first pass:

- pull the recent trade sample for each wallet via `GET /trades?user=<wallet>&limit=500&offset=0&takerOnly=false`
- classify titles containing `Up or Down`, `5m`, `15m`, `5-minute`, `15-minute`
- inspect asset mix and current open-position structure

Seed-screen results:

| Wallet | Recent trade sample | Fast-title share | Asset mix in fast sample | Open-book clue |
|---|---:|---:|---|---|
| `0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9` | 500 | 100% | BTC 411, ETH 34, SOL 33, XRP 22 | dual-sided on 6 of 21 sampled open titles |
| `0xd0d6053c3c37e727402d84c14069780d360993aa` | 500 | 100% | BTC 336, ETH 37, SOL 72, XRP 55 | dual-sided on 24 of 27 sampled open titles |
| `0x63ce342161250d705dc0b16df89036c8e5f9ba9a` | 500 | 100% | BTC 470, ETH 13, SOL 17 | dual-sided on 13 of 13 sampled open titles |
| `0x2d8b401d2f0e6937afebf18e19e11ca568a5260a` | 500 | 100% | BTC 500 | dual-sided on 2 of 2 sampled open titles |
| `0x1f0ebc543b2d411f66947041625c0aa1ce61cf86` | 500 | 100% | BTC 263, ETH 77, SOL 113, XRP 47 | dual-sided on 12 of 16 sampled open titles |

### C. Extremely Important Clue: Dual-Sided Open Positions

This is the first thing deep research should not miss:

- `0x8dxd` appeared dual-sided on `13 / 13` sampled open titles.
- `k9Q2...` appeared dual-sided on `24 / 27` sampled open titles.
- `vidarx` appeared dual-sided on `2 / 2` sampled open titles.
- `0x1f0e...` appeared dual-sided on `12 / 16` sampled open titles.

That strongly suggests the top wallets are not simply expressing a single directional belief per market.

Possible interpretations:

- two-sided market making
- inventory hedging
- spread capture with residual directional skew
- liquidity-reward optimization
- quote replenishment strategy
- temporary two-sided warehousing before one side is unwound
- multi-leg microstructure logic that public trade snapshots only partially reveal

Deep research must treat this as a first-class clue.
Do not reduce these wallets to "they bet Up" or "they bet Down."

### D. Current Wallet Overlap Shows Convergence In The Same Windows

In the live sample, these five wallets all recently touched:

- `Bitcoin Up or Down - March 12, 8:40AM-8:45AM ET`

And several of them overlapped in:

- `Bitcoin Up or Down - March 12, 8AM ET`
- `Ethereum Up or Down - March 12, 8AM ET`
- `Bitcoin Up or Down - March 12, 8:35AM-8:40AM ET`

This means:

- there is likely a common lane or cluster of elite fast-market participation,
- the same titles can become "elite-wallet crowded trades,"
- and current-position overlap can be used as a signal surface, but only if we understand whether the overlap is directional or simply two-sided inventory.

## Most Important Research Questions

Deep research should answer these explicitly:

1. Which public wallets truly dominate 5-minute and 15-minute markets after filtering out broader crypto exposure?
2. Are the top PnL wallets actually directional traders, market makers, or some hybrid?
3. How much of their edge appears to come from:
   market selection,
   quote placement,
   inventory management,
   fee/rebate optimization,
   lead-lag with Binance / Chainlink / RTDS,
   or crowding / flow-following?
4. Are the top wallets individually independent, or are some likely part of the same operator cluster?
5. Do they systematically hold both sides at once?
6. If they hold both sides, when do they open both, when do they lean one way, and when do they flatten?
7. Are their biggest realized wins coming from:
   directional resolution,
   spread capture,
   reward farming,
   intrawindow price oscillation,
   or end-of-window inventory cleanup?
8. Do the best accounts specialize by:
   asset,
   time window,
   time of day,
   volatility regime,
   or market subtype?
9. What parts of their strategy are directly observable from public data?
10. What parts must be inferred from order book context, timing, and pattern repetition?
11. What is the simplest cloneable version with the highest expected fidelity?
12. Which account or cluster is the best "best-of-breed" target for Elastifund to learn from first?

## Official Polymarket Public Data Surfaces To Use

Use the official documentation pages as the technical anchor and the live endpoints as the data source.
When field semantics are ambiguous, trust the official docs over casual interpretation of the returned field names.

### 1. Leaderboard And Discovery

- Docs: [Trader leaderboard rankings](https://docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings)
- Live example:

```bash
curl -s 'https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=ALL&orderBy=PNL&limit=100' | jq '.'
curl -s 'https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=MONTH&orderBy=PNL&limit=100' | jq '.'
curl -s 'https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=WEEK&orderBy=PNL&limit=100' | jq '.'
```

Use these to build the seed universe.
Do not trust only one time window.

### 2. Wallet Trades

- Docs: [Trades for a user or markets](https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets)
- Live example:

```bash
WALLET='0x63ce342161250d705dc0b16df89036c8e5f9ba9a'
curl -s "https://data-api.polymarket.com/trades?user=${WALLET}&limit=500&offset=0&takerOnly=false" | jq '.[0]'
```

This is the primary public event stream for wallet-level reconstruction.
Pull all pages.
Store raw JSON.

Important fields visible in the live payload:

- `proxyWallet`
- `timestamp`
- `conditionId`
- `type`
- `size`
- `usdcSize`
- `transactionHash`
- `price`
- `asset`
- `side`
- `outcomeIndex`
- `title`
- `slug`
- `eventSlug`
- `outcome`
- `name`
- `pseudonym`

### 3. Current Positions

- Docs: [Current positions for a user](https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user)
- Live example:

```bash
curl -s "https://data-api.polymarket.com/positions?user=${WALLET}&limit=500&offset=0" | jq '.[0]'
```

This is critical for reconstructing current inventory structure and dual-sided behavior.

Important live fields:

- `size`
- `avgPrice`
- `initialValue`
- `currentValue`
- `cashPnl`
- `realizedPnl`
- `curPrice`
- `redeemable`
- `mergeable`
- `title`
- `eventSlug`
- `outcome`
- `outcomeIndex`
- `endDate`

### 4. Closed Positions

- Docs: [Closed positions for a user](https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user)
- Live example:

```bash
curl -s "https://data-api.polymarket.com/closed-positions?user=${WALLET}&limit=50&offset=0" | jq '.[0]'
```

Use this for realized PnL attribution and to rank historically successful windows and assets.
Expect to paginate in smaller increments than `/trades`.

### 5. User Activity

- Docs: [User activity](https://docs.polymarket.com/api-reference/core/get-user-activity)
- Live example:

```bash
curl -s "https://data-api.polymarket.com/activity?user=${WALLET}&limit=500&offset=0" | jq '.[0]'
```

This can contain profile metadata plus chronological activity detail.

### 6. Total Value

- Docs: [Total value of a user's positions](https://docs.polymarket.com/api-reference/core/get-total-value-of-a-users-positions)
- Live example:

```bash
curl -s "https://data-api.polymarket.com/value?user=${WALLET}" | jq '.'
```

Use this as a current-scale clue, not a full accounting model.

### 7. Total Markets Traded

- Docs: [Total markets a user has traded](https://docs.polymarket.com/api-reference/misc/get-total-markets-a-user-has-traded)
- Live example:

```bash
curl -s "https://data-api.polymarket.com/traded?user=${WALLET}" | jq '.'
```

Use carefully.
Verify actual semantics from docs before relying on the returned field names.

### 8. Market Positions And Holders

- Docs: [Positions for a market](https://docs.polymarket.com/api-reference/core/get-positions-for-a-market)
- Docs: [Top holders for markets](https://docs.polymarket.com/api-reference/core/get-top-holders-for-markets)
- Live example for holders:

```bash
CONDITION_ID='0xd917fce71ec23636d043b29cefeec27ac0d8e8225cb623783fe5e43857f9c7ec'
TOKEN_ID='14596990499423732859337296361482695086581499245682150484245082885154436213928'
curl -s "https://data-api.polymarket.com/holders?market=${CONDITION_ID}&limit=20&offset=0" | jq '.'
```

Use these to identify crowding, overlap, and whether elite wallets are on the same side at the same time.

### 9. Order Book

- Docs: [Order book](https://docs.polymarket.com/api-reference/market-data/get-order-book)
- Live example:

```bash
curl -s "https://clob.polymarket.com/book?token_id=${TOKEN_ID}" | jq '.'
```

This is necessary for maker/taker inference, quote placement modeling, and spread-capture reconstruction.

### 10. WebSocket And RTDS

- Docs: [Market WSS](https://docs.polymarket.com/api-reference/wss/market)
- Docs: [RTDS overview](https://docs.polymarket.com/market-data/websocket/rtds)

Use these to reconstruct:

- quote timing,
- book updates,
- price change cadence,
- external crypto reference timing,
- and likely lead-lag behavior.

### 11. Rate Limits

- Docs: [Rate limits](https://docs.polymarket.com/api-reference/rate-limits)

Respect rate limits.
Build paginators and backoff.
Do not make the research fragile by blasting the API.

### 12. Accounting Snapshot Zip

- Docs: [Download an accounting snapshot zip of CSVs](https://docs.polymarket.com/api-reference/misc/download-an-accounting-snapshot-zip-of-csvs)

If available without privileged auth for the relevant public surface, use it.
If it requires ownership or auth, note it and move on.
Do not block the project on this.

## Secondary Data Surfaces That Matter

These are not optional if we want serious reconstruction.

### A. Gamma Market Metadata

Use `https://gamma-api.polymarket.com/markets` and `https://gamma-api.polymarket.com/events` to enrich:

- market titles,
- event titles,
- categories,
- close windows,
- asset mapping,
- and token IDs.

The repo already uses this heavily.

### B. On-Chain / Subgraph Context

Use these when public REST data is not enough to explain behavior:

- official Polymarket subgraph references in repo docs
- Polygon event surfaces from `docs/strategy/smart_wallet_build_spec.md`
- contract addresses in `docs/strategy/system_design_research_v1_0_0_background.md`

Relevant verified contract addresses already documented in-repo:

- Conditional Tokens: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- CTF Exchange: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
- NegRisk CTF Exchange: `0xC5d563A36AE78145C45a50134d48A1215220f80a`
- NegRisk Adapter: `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296`

### C. External Crypto Reference Data

For fast-market reconstruction, enrich with:

- Binance spot price stream
- Polymarket RTDS crypto streams
- Chainlink / resolution timing where relevant

Without external price context, we cannot tell whether the wallet is:

- reacting to momentum,
- making markets around volatility,
- or harvesting intrawindow reversion.

### D. Academic / Analytic Context

Use these for priors, not as substitutes for wallet-specific evidence:

- [IMDEA / arXiv arbitrage paper](https://arxiv.org/abs/2508.03474)
- [jbecker.dev Polymarket analysis archive](https://web.archive.org/web/20260227054444/https://www.jbecker.dev/research/polymarket/)

These help frame what has already been observed in the broader market, but the wallet-by-wallet reconstruction must stand on direct data.

## Local Repo Surfaces To Reuse

Do not reinvent the whole pipeline.
The repo already contains useful primitives.

### Existing wallet-flow and fast-market surfaces

- `bot/wallet_flow_detector.py`
- `docs/strategy/smart_wallet_build_spec.md`
- `scripts/run_signal_source_audit.py`
- `bot/pm_fast_market_registry.py`
- `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md`
- `research/deep_research_output.md`
- `docs/strategy/system_design_research_v1_0_0_background.md`

### Existing schema ideas already in repo

`bot/wallet_flow_detector.py` already defines:

- `wallet_trades`
- `wallet_scores`

And it already assumes:

- public `data-api.polymarket.com/trades`
- crypto-fast classification
- wallet scoring
- consensus detection

That is a useful starting point, but for this project it is not enough.
We need a richer reconstruction layer.

## Recommended Research Data Model

If the deep research agents materialize intermediate data, use a schema like this:

### Raw tables

- `wallet_leaderboard_snapshots`
- `wallet_trades_raw`
- `wallet_positions_current_raw`
- `wallet_closed_positions_raw`
- `wallet_activity_raw`
- `market_metadata_raw`
- `market_holders_raw`
- `orderbook_snapshots_raw`
- `external_price_snapshots_raw`

### Normalized tables

- `wallets`
- `markets`
- `wallet_market_entries`
- `wallet_market_exits`
- `wallet_inventory_states`
- `wallet_side_overlap`
- `wallet_asset_mix_daily`
- `wallet_window_mix_daily`
- `wallet_pnl_by_window`
- `wallet_pnl_by_asset`
- `wallet_overlap_graph`
- `wallet_cluster_candidates`

### Hypothesis tables

- `strategy_hypotheses`
- `hypothesis_backtests`
- `hypothesis_fit_scores`
- `hypothesis_unexplained_residuals`

## Concrete Extraction Protocol

### Phase 1: Seed Universe

1. Pull crypto leaderboard snapshots for `ALL`, `MONTH`, and `WEEK`.
2. Union the top `100` wallets from each snapshot.
3. Tag all wallets with:
   all-time rank,
   month rank,
   week rank,
   userName,
   xUsername if present,
   and whether they are currently hot or only historically important.
4. For each wallet, pull a recent trade sample and score fast-market purity:
   percentage of sampled trades in 5-minute and 15-minute titles.
5. Drop obvious non-fast generalists from the first-pass target set.
6. Keep both:
   elite current operators,
   and elite historical operators.

### Phase 2: Pull Full Wallet Histories

For each selected wallet:

1. Pull all `/trades` pages.
2. Pull all `/closed-positions` pages.
3. Pull all `/positions` pages.
4. Pull all `/activity` pages.
5. Pull `/value`.
6. Pull `/traded`.
7. Pull relevant `/holders` and market-level overlap data for the wallet's most active titles.

Do not rely on only one endpoint.
Different endpoints reveal different pieces of the same strategy.

### Phase 3: Normalize Fast Markets

For every title / market:

1. Parse asset:
   BTC, ETH, SOL, XRP, other.
2. Parse window size:
   5-minute, 15-minute, hourly, intraday, threshold, range.
3. Parse exact time window.
4. Map `conditionId`, `eventSlug`, `slug`, `asset token ids`, and `endDate`.
5. Join Gamma metadata.
6. Attach external price path and market microstructure context if possible.

### Phase 4: Reconstruct Position Behavior

For each wallet and each market:

1. Sequence all trades chronologically.
2. Infer position accumulation and reduction.
3. Detect whether the wallet:
   opened one side only,
   opened both sides,
   flipped sides,
   laddered in,
   or laddered out.
4. Measure time from market open to first action.
5. Measure time from first action to last action.
6. Measure proximity of fills to market resolution.
7. Estimate holding period distribution.
8. Estimate whether the wallet was likely quoting or crossing.

### Phase 5: Test Strategy Families

For each wallet, explicitly test these hypotheses:

1. Pure directional momentum:
   buys the side aligned with recent Binance move.
2. Mean-reversion fade:
   leans against short-lived spikes.
3. Two-sided market making:
   accumulates both sides within the same window.
4. Inventory-skewed market making:
   quotes both sides but ends net biased.
5. Liquidity-reward optimization:
   quote placement appears more important than direction.
6. Lead-lag trading:
   entries track external price movement before Polymarket fully reprices.
7. Crowding / consensus copying:
   follows other elite wallets once a cluster forms.
8. Cross-asset hedge logic:
   offsets BTC with ETH / SOL / XRP.
9. Time-of-day regime specialization:
   only active in certain hour blocks.
10. Multi-wallet cluster strategy:
    same operator or coordinated behavior across addresses.

### Phase 6: Score Reconstruction Quality

For each hypothesis, score:

- market selection fit
- entry timing fit
- side fit
- size fit
- exit fit
- PnL similarity
- ability to explain dual-sided holdings
- ability to explain overlap with peer elite wallets

The best hypothesis is not the prettiest one.
It is the one that explains the largest share of actual behavior with the smallest unexplained residual.

## High-Value Signals To Measure

Deep research should compute these, not just describe them:

1. Fast-market purity:
   percent of trades and PnL in 5-minute and 15-minute titles.
2. Asset specialization:
   BTC vs ETH vs SOL vs XRP mix.
3. Time-window specialization:
   5-minute vs 15-minute vs hourly.
4. Side bias:
   Up vs Down preference.
5. Dual-sided inventory rate:
   how often both outcomes are held in the same title.
6. Title crowding score:
   overlap with other elite wallets.
7. Entry delay:
   seconds after market open until first position.
8. Exit delay:
   seconds before or after resolution until flatten.
9. Position size distribution:
   average, median, tail size.
10. Concentration:
    how many titles carried concurrently.
11. Quote-likeness clues:
    frequent alternating fills, repeated small clips, both-side presence.
12. Directional conviction clues:
    one-sided accumulation, sparse opposite-side inventory, hold-through-resolution.
13. Rebate-harvest clues:
    many small fills around mid, frequent both-side inventory, flattened residuals.
14. Lead-lag clues:
    actions systematically align with external price before Polymarket fully reprices.
15. Cluster correlation:
    repeated synchronous entries across multiple elite wallets.

## Do Not Miss These Specific Strategy Clues

### 1. Both-sides-on-the-same-title is not noise

If a wallet repeatedly carries both `Up` and `Down` on the same 5-minute or 15-minute market, that is an enormous clue.
It likely means the strategy is about quote flow, spread capture, or inventory recycling, not simple forecasting.

### 2. Large realized wins do not prove directional forecasting

A wallet can show large closed-position PnL while still being a maker or hybrid maker.
Do not infer direction-only alpha from realized PnL alone.

### 3. Current positions may reveal the engine more clearly than closed positions

Closed positions tell you what won.
Current positions often reveal how the engine actually operates.

### 4. A wallet that looks copyable may not be copyable

If the public edge comes from hidden resting quotes, queue position, rebate economics, or better latency, blindly following fills will likely lose.

### 5. The best wallet to learn from may not be the highest PnL wallet

The best reconstruction target is the wallet with the best mix of:

- real edge,
- clear public footprint,
- high fast-market purity,
- stable behavior,
- and plausible replicability.

That may or may not be `0x8dxd`.

## Suggested Wallet Triage Framework

Rank candidate wallets using a weighted score:

- `25%` fast-market purity
- `20%` current-period strength
- `15%` historical durability
- `15%` replicability of public footprint
- `10%` clarity of strategy family
- `10%` overlap relevance with other elites
- `5%` fit with Elastifund's existing maker/wallet-flow infrastructure

Then produce three buckets:

1. Primary reconstruction targets
2. Secondary comparison targets
3. Ignore / low-value targets

Important:
the wallet with the strongest evidence of a real edge may not be the wallet with the highest direct copyability.
For example, a wallet like `0x8dxd` may be the best evidence wallet for understanding the fast-market meta while still being a worse first clone target than a simpler specialist with cleaner directional or inventory behavior.

## Example Command Bundle

This is the minimum useful acquisition loop:

```bash
mkdir -p tmp/polywallet/raw

# 1. Seed leaderboards
curl -s 'https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=ALL&orderBy=PNL&limit=100' \
  > tmp/polywallet/raw/leaderboard_crypto_all.json
curl -s 'https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=MONTH&orderBy=PNL&limit=100' \
  > tmp/polywallet/raw/leaderboard_crypto_month.json
curl -s 'https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=WEEK&orderBy=PNL&limit=100' \
  > tmp/polywallet/raw/leaderboard_crypto_week.json

# 2. Pull one wallet deeply
WALLET='0x63ce342161250d705dc0b16df89036c8e5f9ba9a'
curl -s "https://data-api.polymarket.com/trades?user=${WALLET}&limit=500&offset=0&takerOnly=false" \
  > "tmp/polywallet/raw/${WALLET}_trades_page0.json"
curl -s "https://data-api.polymarket.com/positions?user=${WALLET}&limit=500&offset=0" \
  > "tmp/polywallet/raw/${WALLET}_positions_page0.json"
curl -s "https://data-api.polymarket.com/closed-positions?user=${WALLET}&limit=50&offset=0" \
  > "tmp/polywallet/raw/${WALLET}_closed_positions_page0.json"
curl -s "https://data-api.polymarket.com/activity?user=${WALLET}&limit=500&offset=0" \
  > "tmp/polywallet/raw/${WALLET}_activity_page0.json"
curl -s "https://data-api.polymarket.com/value?user=${WALLET}" \
  > "tmp/polywallet/raw/${WALLET}_value.json"
curl -s "https://data-api.polymarket.com/traded?user=${WALLET}" \
  > "tmp/polywallet/raw/${WALLET}_traded.json"
```

Then paginate until exhaustion.
Persist the raw payloads.

## The Autoresearch Loop We Actually Want

This should not be a one-shot report.
It should be a loop.

### Loop structure

1. Pull data.
2. Rank wallets.
3. Propose 3-8 strategy hypotheses per wallet.
4. Replay those hypotheses against the actual wallet timeline.
5. Measure fit.
6. Identify the biggest unexplained behaviors.
7. Ask the next research wave only the questions that reduce those unexplained behaviors.
8. Repeat until one of the following is true:
   the strategy is reconstructed well enough to clone,
   the residual unknowns are structural and not worth chasing,
   or another wallet is a better target.

### Stop criteria for a "good enough" reconstruction

The reconstructed strategy is good enough when it can explain most of:

- which titles are selected,
- which side is favored when there is a lean,
- why both sides are sometimes held,
- when positions are opened,
- when positions are flattened,
- and where the majority of realized PnL comes from.

### What counts as failure

If the research returns only:

- "top wallets buy fast markets,"
- "copy them when they agree,"
- or generic advice without exact evidence,

then it has failed.

## Recommended Answer Format For Deep Research

Ask deep research to return the answer in this exact structure:

1. `Executive answer`
   best wallet, best strategy family, cloneability, confidence.
2. `Ranked wallet table`
   top 10-20 wallets with evidence.
3. `Wallet dossiers`
   one subsection per top wallet.
4. `Reconstruction findings`
   what the wallet is actually doing.
5. `Best-of-breed strategy`
   explicit strategy rules and why this is the top target.
6. `Clone plan`
   how Elastifund should implement or emulate it.
7. `Autoresearch next loop`
   exact follow-up questions and data pulls.
8. `Unknowns and blockers`
   what still cannot be known publicly.

Require tables, exact wallet addresses, exact endpoint recipes, and explicit evidence tags.

## Things Deep Research Should Explicitly Avoid

1. Do not over-index on social-media lore.
2. Do not assume highest all-time PnL means easiest strategy to copy.
3. Do not assume a wallet is directional just because closed positions are directional.
4. Do not ignore two-sided inventory.
5. Do not assume public trade history reveals maker/taker role cleanly.
6. Do not confuse "traded this market" with "had conviction on this side."
7. Do not stop at leaderboards.
8. Do not give a generic smart-wallet copy-trading answer.

## Why This Matters For Elastifund Specifically

This repo already has:

- a wallet-flow detector,
- a fast-market registry,
- maker-first execution posture,
- microstructure research,
- and a direct interest in 5-minute and 15-minute crypto markets.

If the elite-wallet edge is mainly:

- directional crowd-following,
  then we should improve wallet consensus detection.
- market making / two-sided inventory,
  then we should reconstruct quote behavior and maker economics.
- lead-lag,
  then we should emphasize RTDS, Binance, and timing.
- hybrid,
  then the winning implementation may be:
  maker-first quote logic plus wallet-informed directional skew.

The answer changes the architecture.
That is why this research should be treated as a high-value design input, not just competitive curiosity.

## Final Instruction To Deep Research

Return the strongest possible reconstruction packet, not a lightweight overview.

We want:

- exact wallets,
- exact evidence,
- exact strategy hypotheses,
- exact reasons those hypotheses do or do not fit,
- exact recommendations for the best wallet or cluster to model,
- and the clearest possible path from public data to a clone-ready strategy.

If a perfect reconstruction is not fully possible from public data, say exactly why, quantify the gap, and still produce the best partial reconstruction with the highest evidence density possible.
