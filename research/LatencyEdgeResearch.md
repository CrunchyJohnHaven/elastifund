# Your Dublin server is closer to Polymarket than you think

**Polymarket's CLOB matching engine runs in AWS eu-west-2 (London), not in the United States.** Your Dublin (eu-west-1) VPS sits roughly **10–15ms** from the matching engine — already inside the competitive latency band for algorithmic traders. The real problem isn't your server location; it's that you're polling REST every 5 minutes with no WebSocket connections, no real-time price feeds, and no Polygon RPC endpoint. Fixing those three things — all achievable for under $50/month — delivers an order-of-magnitude improvement that dwarfs any server migration. The 500ms taker delay on crypto markets was **removed on February 18, 2026**, meaning taker orders now execute instantly and the competitive landscape has shifted from pure latency arbitrage toward maker-centric market-making strategies.

---

## The geography that changes everything

Multiple independent sources — QuantVPS's infrastructure analysis, LowEndTalk globalping measurements, and community DNS investigation — confirm Polymarket's off-chain CLOB runs on **AWS eu-west-2 (London)**, with **eu-west-1 (Ireland) as backup**. The frontend at polymarket.com sits behind Vercel's anycast CDN, and all API endpoints pass through **Cloudflare's WAF/throttling layer**, but the origin servers processing order matching are in London.

This means the latency map looks very different from what most guides assume:

| Location | Latency to Polymarket CLOB | Notes |
|---|---|---|
| London (eu-west-2) | **<2ms** | Same datacenter region |
| Dublin (eu-west-1) | **5–10ms** | Your current location |
| Amsterdam/Netherlands | **8–12ms** | Best non-geoblocked EU option |
| Zurich | **10–15ms** | Lowest measured by HostHatch testing |
| **New York** | **70–80ms** | Most bot guides wrongly recommend this |
| Chicago | 85–95ms | Worse than staying in Dublin |
| Oregon/US-West | 140–160ms | Completely uncompetitive |

**Your Dublin VPS already has better latency to Polymarket's matching engine than any US-based server.** The 100ms latency you're measuring is likely to a US-based Polygon RPC endpoint, not to the CLOB itself. The "faster bots" beating you on 5-minute crypto candle markets aren't winning because of a closer server — they're winning because they use WebSockets, real-time price feeds, and smarter order timing.

Kalshi's matching engine, by contrast, operates out of **New York City** (~1.14ms from NY4 Equinix). If you need both platforms, you face a geographic split: London for Polymarket, NYC for Kalshi.

---

## Three changes since February 2026 that reshape bot strategy

The competitive landscape shifted dramatically on **February 18, 2026**, when Polymarket silently made three changes that broke most existing bots overnight:

**The 500ms taker delay was removed.** Previously, all taker orders on crypto markets waited 500ms before execution, giving market makers a free cancellation window. Takers now execute instantly against the book. This is the single most important change — it means pure speed on taker execution now matters, but it also means **taker fees were introduced** simultaneously. Peak taker fees reach ~3.15% at 50/50 odds on 15-minute markets and ~1.56% on 5-minute markets. **Maker orders remain at 0% fees** with daily USDC rebates. The strategy imperative is clear: become a maker, not a taker.

**Batch orders expanded to 15 per request** (up from 5), and the sustained order rate is **60 orders/second** with bursts to 500/second. The rate limit architecture uses Cloudflare sliding-window throttling — requests are delayed/queued, not rejected, making it harder to detect when you're being throttled.

**Polymarket US launched** (November 2025) with a separate New York–hosted infrastructure, Ed25519 authentication, and different rate limits (60 req/min on public endpoints). The international and US platforms are now functionally separate systems. If you're trading crypto candle markets on the international platform, the London CLOB is your target.

---

## What actually eats your latency budget

The trade pipeline for a Polymarket crypto candle market bot breaks down into five stages, and the bottleneck is not where most people assume:

**Stage 1 — Observe (currently your worst bottleneck).** You're polling REST every 5 minutes. The Polymarket WebSocket feed (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) delivers order book updates in **~50–100ms**. The RTDS feed (`wss://ws-live-data.polymarket.com`) delivers real-time crypto prices from both Binance and Chainlink sources with sub-second latency. Switching from REST polling to WebSocket subscriptions gives you roughly **a 900ms improvement in data freshness** — this single change matters more than any server migration. The RTDS is particularly valuable because it streams both `crypto_prices` (Binance real-time) and `crypto_prices_chainlink` (oracle prices) simultaneously, letting you see divergence in real time. No authentication is required for RTDS.

**Stage 2 — Compute (where algorithmic edge lives).** For 5-minute BTC candle markets, the compute step is trivial — compare current Binance price to the candle's open price, assess momentum in the final 30–60 seconds, and decide direction. Python handles this in <1ms. Rust gives you microseconds but doesn't change outcomes at this timescale. The real compute edge is in **what signals you process**, not how fast you process them.

**Stage 3 — Submit (your network latency).** From Dublin to London, your order submission takes ~5–10ms round-trip. From an Amsterdam VPS, ~8–12ms. The order must be EIP-712 signed (adds ~1–5ms depending on implementation) and pass through Cloudflare (adds variable 1–20ms). Total submission latency: **15–35ms** from your current Dublin setup. Moving to London proper saves 5–8ms.

**Stage 4 — Match (Polymarket's server, you can't control this).** The CLOB processes orders FIFO at each price level. No artificial delays remain on crypto markets. The matching engine processes your signed order, validates the signature, checks balances, and attempts to match. This takes an estimated **10–50ms** on Polymarket's side, though exact numbers aren't published.

**Stage 5 — Settle (on-chain, largely irrelevant for CLOB trading).** Settlement happens on Polygon (~2-second block time), but your CLOB order is matched off-chain. You don't need on-chain confirmation to have your order filled. Settlement matters for capital availability and position management, not for trade execution speed.

**The realistic floor latency for a complete observe-to-match cycle from Dublin is approximately 70–150ms.** Moving to London shaves this to 50–120ms. The marginal improvement is real but modest compared to fixing your data ingestion.

---

## Infrastructure options compared honestly

| Provider | Config | Region | Cost/mo | Latency to PM CLOB | Polygon RPC | Kernel Tuning | Best For |
|---|---|---|---|---|---|---|---|
| **Current: AWS Lightsail Dublin** | Unknown | eu-west-1 | ~$10-40 | 5-10ms | None | Limited | Already decent |
| **Hetzner Cloud CCX23** | 4 vCPU, 16GB, dedicated | eu-central (DE) | ~$40 | 12-18ms | Via provider | Limited (VM) | Budget compute |
| **OVH Rise bare metal** | Ryzen 7, 32GB, NVMe | eu-west (IE/UK) | ~$65-75 | 3-10ms | Self-host possible | **Full** | Best value bare metal |
| **AWS EC2 c5.xlarge** | 4 vCPU, 8GB | eu-west-2 (London) | ~$130 | **<2ms** | Via provider | Limited | Minimum latency to CLOB |
| **AWS EC2 c5.large** | 2 vCPU, 4GB | eu-west-2 | ~$65 | **<2ms** | Via provider | Limited | Budget co-location |
| **Vultr High Freq** | 4 vCPU, 8GB, NVMe | Amsterdam | ~$48 | 8-12ms | Via provider | Limited (VM) | Budget EU option |
| **Latitude.sh m4.metal.small** | 6-core, 64GB, NVMe | EU | ~$190 | Varies | Self-host possible | **Full** | Overkill for this use case |
| **QuantVPS** | Trading-optimized | London/Amsterdam | $60-100 | **<5ms** (claimed) | Via provider | Limited | Plug-and-play for Polymarket |

**For Polygon RPC (separate line item):**

| Provider | Tier | Cost/mo | Latency | WebSocket | Rate Limit |
|---|---|---|---|---|---|
| Alchemy Free | Free | $0 | ~30-60ms | Yes | ~3.8M tx/mo |
| Alchemy PAYG | Pay-as-you-go | ~$5-20 | ~30-50ms | Yes | 300 req/s |
| QuickNode Build | Paid | $49 | ~45ms (US), ~74ms (EU) | Yes | Generous |
| Chainstack Growth | Paid | $49 | Competitive | Yes | 600 RPS |
| Self-hosted node | Bare metal required | $0 (included) | **<1ms** (local) | Yes | Unlimited |

---

## The edges that actually work under $500/month

### Oracle latency arbitrage remains the proven money-maker

A trader documented earning **$50,000 in one week** by exploiting the gap between real-time exchange prices and Polymarket's crypto market pricing near candle close. The mechanism: subscribe to Binance WebSocket for BTC/USDT, observe the candle close outcome becoming near-certain in the final 30–60 seconds, and buy the winning outcome on Polymarket before the market fully reprices.

Polymarket's countermeasure — dynamic taker fees — makes this strategy **unprofitable for taker orders** at 50/50 odds. But **maker orders pay 0% fees**. The updated strategy: post aggressive limit orders on the winning side during the final 60 seconds. If someone else takes your liquidity, you earn the spread plus the $1 resolution payout minus your entry price, with zero fees. You shift from racing to take liquidity to positioning to provide it at favorable prices.

**Infrastructure required:** Any VPS with WebSocket support (~$10/month) plus Binance WebSocket feed (free) plus Polymarket CLOB WebSocket and RTDS (free). **Your current Dublin setup can do this today** with code changes alone.

### The RTDS dual-stream divergence is the most underexploited edge

Polymarket provides its own Real-Time Data Stream with **two separate crypto price sources**: `crypto_prices` (Binance real-time) and `crypto_prices_chainlink` (Chainlink oracle data). By subscribing to both simultaneously, you see the exact divergence between the "truth" (Binance spot) and the oracle price that drives resolution. When these diverge significantly near candle close, the resolution outcome is highly predictable.

The RTDS also streams `market_resolved` events the instant resolution is finalized. No authentication required. No rate limits mentioned in documentation. This is **Polymarket handing you the oracle lag data** in a WebSocket feed, and most bot operators aren't using it because it's barely documented.

**Infrastructure required:** Zero additional cost. Connect to `wss://ws-live-data.polymarket.com` and subscribe to both topics.

### Cross-platform Polymarket–Kalshi arbitrage exploits different resolution sources

Polymarket hourly BTC markets resolve using **Binance BTC/USDT** candle data. Kalshi uses its own price sources. Different data sources mean different resolution prices for nominally the "same" event, especially near the strike price. When the BTC hourly candle close sits near the boundary, one platform may resolve "Up" while the other resolves differently. Open-source arbitrage bots exist on GitHub for this exact strategy.

The catch: you need capital pre-loaded on both platforms, and the geographic split (London CLOB for Polymarket, NYC for Kalshi) means one leg always has higher latency. Reported returns of **12–20% monthly** are unverified but the structural mechanism is sound. Windows typically last 2–15 minutes before other bots close them.

**Infrastructure required:** Two VPS locations or accept asymmetric latency. Capital of $5K+ on each platform.

### Order flow analysis reveals informed trading

Polymarket's WebSocket market channel streams every executed trade with price, size, side, and millisecond timestamps. Sudden large trades (>$5K) in one direction on crypto candle markets often signal informed flow — someone who knows the candle is closing in a particular direction. By detecting these patterns in real time and placing maker orders in the same direction, you effectively copy-trade the informed participants.

Cross-reference with Binance spot price movement for confirmation: if a large "Up" buy on Polymarket coincides with BTC moving up on Binance, the signal is genuine. If the Polymarket trade occurs without corresponding spot movement, it's likely noise.

**Infrastructure required:** Same WebSocket setup, zero additional cost.

---

## The edges that don't work (honest assessment)

**Chainlink DON node observation is a dead end.** Individual oracle node observations circulate on a private P2P network and are not publicly visible before the aggregated report hits the chain. Chainlink's OCR architecture explicitly prevents pre-aggregation observation.

**Polygon mempool watching has a 2-second window that's too narrow.** While services like Blocknative offer Polygon mempool access, the 2-second block time means you'd need to detect the Chainlink `transmit()` call and act within a single block. For 5-minute candle markets, the resolution data is already deterministic before the oracle transaction — you don't need mempool access; you just need Binance's WebSocket feed.

**Kernel bypass networking (DPDK, io_uring) is overkill.** These technologies save 20–50 microseconds per packet. Polymarket operates on timescales of tens to hundreds of milliseconds. The bottleneck is Cloudflare's processing and the CLOB's matching speed, not your kernel's packet handling.

**FPGA/GPU acceleration provides no meaningful edge.** The compute required for crypto candle market decisions is trivial — comparing two price numbers. ML-based signal generation could use GPU acceleration, but the signal-to-noise ratio in 5-minute candles is too low for complex models to outperform simple heuristics.

**CDN propagation exploitation doesn't apply.** WebSocket connections bypass Cloudflare's content caching entirely. CDN propagation delays affect static content, not real-time API responses.

---

## The recommended build for under $500/month

**Option A: Maximum edge, minimum spend (~$70–120/month)**

This is what I'd actually recommend. It prioritizes the high-impact changes over marginal latency improvements.

| Component | Choice | Monthly Cost |
|---|---|---|
| **Compute** | Keep Dublin Lightsail OR upgrade to AWS EC2 c5.large in eu-west-2 (London) | $10–65 |
| **Polygon RPC** | Alchemy free tier (3.8M tx/mo, WebSocket included) | $0 |
| **Exchange data** | Binance WebSocket (free) | $0 |
| **Total** | | **$10–65** |

**What to run on it:**
- Polymarket CLOB WebSocket subscription for order book data on all active crypto candle markets
- Polymarket RTDS subscription for both `crypto_prices` (Binance) and `crypto_prices_chainlink` (Chainlink) feeds
- Binance WebSocket for direct BTC/ETH/SOL spot price feeds
- Python bot using `py-clob-client` v0.34+ (with fee handling) or Rust `rs-clob-client` for signing-critical paths
- Maker order placement logic targeting the final 60 seconds of each candle period

**Kernel/network tuning (even on Lightsail):**
- Set `TCP_NODELAY` on all WebSocket connections
- Use persistent WebSocket connections with 8-second heartbeat (below Polymarket's 10-second requirement)
- Pin bot process to a single CPU core to avoid context switches
- Implement automatic WebSocket reconnection — Polymarket's WS endpoint has a known silent-freeze bug

**Expected end-to-end latency:** 70–150ms (Dublin) or 50–120ms (London EC2)

**Option B: Competitive bare metal (~$120–175/month)**

| Component | Choice | Monthly Cost |
|---|---|---|
| **Compute** | OVH Rise bare metal in Ireland/UK (~Ryzen 7, 32GB, NVMe) | $65–75 |
| **Polygon RPC** | QuickNode Build tier (lowest measured latency, 99.99% SLA) | $49 |
| **Exchange data** | Binance WebSocket (free) | $0 |
| **Total** | | **$114–124** |

Full kernel tuning capability. Custom kernel with `CONFIG_HZ=1000`, busy-polling on network sockets, CPU isolation for trading thread. Likely saves 5–15ms over a VM but doesn't change which strategies are viable.

**Option C: Dual-platform with Kalshi (~$200–350/month)**

| Component | Choice | Monthly Cost |
|---|---|---|
| **EU server** | AWS EC2 c5.large eu-west-2 | $65 |
| **US server** | Hetzner CCX13 Ashburn or OVH Rise Vint Hill | $20–75 |
| **Polygon RPC** | Alchemy PAYG | $5–20 |
| **Total** | | **$90–160** |

EU server handles Polymarket; US server handles Kalshi. Cross-platform arbitrage logic runs on both, communicating via internal messaging.

---

## Expected returns: an honest assessment

With **$10K trading capital** on Polymarket crypto candle markets, here's the realistic math:

The oracle latency arbitrage with maker orders is the highest-EV strategy. If you're posting maker orders on the winning side during the final 60 seconds of 5-minute candles, and your prediction accuracy is 70% (achievable by reading the Binance price trend), your expected value per trade is roughly: (0.70 × average_payout) – (0.30 × average_loss). With typical entry prices of $0.55–0.65 on the winning side, **each correct trade yields $0.35–0.45/share**, each incorrect trade loses $0.55–0.65/share. At 70% accuracy with $100 per trade across 50+ opportunities daily, the gross edge is approximately **$200–500/day** before accounting for liquidity constraints, fill rates, and competition.

**The constraint is not infrastructure — it's fill rate.** Maker orders must be taken by someone else. In thin 5-minute markets, getting $100+ filled consistently in the final 60 seconds is far from guaranteed. Realistic expected income with $10K capital is probably **$50–150/day** with heavy variance, assuming you're competing against ~5–10 other bots running similar strategies.

**The diminishing returns curve is steep.** Going from REST polling to WebSockets (free) captures ~80% of the available infrastructure edge. Moving from Dublin to London (~$55/month additional) captures another ~10%. Bare metal with kernel tuning (~$65–75/month) captures maybe ~5%. Everything beyond that is noise drowned out by Cloudflare's variable processing time and the CLOB's matching latency.

The infrastructure investment that produces the highest ROI is unambiguously **$0/month in infrastructure changes + rewriting your bot to use WebSockets, RTDS, and maker orders.** The marginal value of the next dollar spent on infrastructure is far lower than the marginal value of improving your signal quality and order placement timing.

## Conclusion

The counterintuitive finding here is that your Dublin VPS is already in the right neighborhood. The bots outpacing you on 5-minute crypto candles aren't running on $500/month bare metal — they're running WebSocket connections to Polymarket's RTDS feed, reading Binance prices in real time, and posting maker orders during the critical final window of each candle. The infrastructure gap between your current setup and "competitively viable" is roughly **$0–65/month** in additional spend, plus a significant code rewrite. The gap between "competitively viable" and "dominant" is not closeable with infrastructure alone at any price point under $500/month — that gap is closed by better signals, better timing models, and better execution logic. Spend your $500 budget on two months of cheap London EC2 time, a Polygon RPC subscription, and dedicate the rest to building the algorithmic layer that turns commodity infrastructure into edge.