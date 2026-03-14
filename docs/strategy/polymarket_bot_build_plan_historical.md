# Polymarket Quant Bot — Project Intake & Build Plan

**Date:** March 5, 2026
**Objective Function:** Maximize expected return
**Capital:** $3,000 (live March 10)
**Sprint Window:** March 5–19, 2026

---

## 1. Current State Snapshot

### What Exists (Strong Foundation)

**Repo/Language/Runtime:** Python 3.10+, async-first (asyncio + structlog), FastAPI/Uvicorn for dashboard, SQLAlchemy 2.0 async ORM. ~3,172 lines across 39 modules. No git repo initialized — code lives in a local folder only.

**Core Modules (all functional):**

- **Data Layer** (`src/data/`): Polymarket Gamma + CLOB API integration with rate limiting (100 concurrent), exponential backoff, 60s price cache. Mock feed for paper trading.
- **Broker Layer** (`src/broker/`): Paper broker (slippage + fee simulation) and live Polymarket broker via `py-clob-client`. Live trading is hard-blocked unless `LIVE_TRADING=true`.
- **Strategy Layer** (`src/strategy/`): Three strategies — SMA(5,20) crossover, Claude Haiku sentiment (>5% edge threshold), NOAA weather arbitrage. All use half-Kelly sizing.
- **Risk Layer** (`src/risk/`): Six-layer risk system — kill switch, max position USD, orders/hour rate limit, stale price guard, daily drawdown stop, volatility pause.
- **Engine** (`src/engine/`): Async event loop processing markets in parallel, respecting kill switch and risk checks.
- **Store** (`src/store/`): Full ORM with 5 tables (orders, fills, positions, bot_state, risk_events). 20+ async CRUD methods. SQLite dev / PostgreSQL prod.
- **Dashboard** (`src/app/`): 8+ FastAPI endpoints — health, status, metrics, risk config, kill switch, orders, log tail. Token auth.
- **Backtest System** (`/backtest/`): 532 resolved markets, Claude cache, Monte Carlo simulation, calibration analysis, edge discovery CLI. Results: 64.9% win rate, Brier 0.239.
- **Deployment** : Dockerfile (Alpine Python 3.11), docker-compose (bot + api + postgres), Makefile. Targets Hetzner CX23 ($12/mo).
- **Tests**: 13 test files, 34+ unit tests including a critical live-trading guard test.
- **Extras**: Telegram notifications, NOAA weather client, market scanner (100+ markets/cycle).

**Credentials status:** CLOB API key/secret/passphrase present. Anthropic API key present. Private key slot empty. Wallet exists but unfunded.

### What's Missing vs. Minimum Viable Bot

| Gap | Severity | Notes |
|-----|----------|-------|
| **No git repo** | P0 | Zero version control on 3k+ lines of trading code. Unacceptable for live capital. |
| **Private key not configured** | P0 | Wallet exists but .env has placeholder. Must fund with USDC before March 10. |
| **No continuous data collection** | P0 | 532 resolved markets is a snapshot. No pipeline to ingest newly resolved markets for ongoing calibration. |
| **No limit order support** | P1 | Current broker uses market orders only. Limit orders save ~2% on winning positions — at $3k capital this matters. |
| **No early-exit logic** | P1 | Hold-to-resolution only. No mechanism to exit when edge disappears or better opportunities arise. |
| **No model ensemble** | P1 | Haiku-only signal generation. Haiku + Sonnet ensemble for screening→conviction should improve calibration. |
| **No position rebalancing** | P1 | Static sizing at entry. No rebalancing as market prices move or new information arrives. |
| **No live integration test** | P0 | Paper broker tested, but no end-to-end test with real CLOB (even read-only). |
| **No monitoring/alerting** | P1 | Telegram exists but no structured alerts for drawdown, stale prices, or system errors. |
| **Stale dependency versions** | P2 | `py-clob-client ^0.6.0` and `anthropic ^0.7.0` are old. API breaking changes likely. |

---

## 2. Decisions Needed (Ranked)

These are ranked by "blocks coding now" priority. My recommended defaults are marked with **→**.

### Decision 1: Order Type Strategy
**Context:** Polymarket charges 0% maker / ~2% taker (on winning positions at resolution). At 64.9% win rate on $3k capital, that's ~$39/month in fees on taker vs $0 on maker.
**→ Recommended: Hybrid (limit entry, market exit).** Limit orders for entry capture the 2% savings on most positions. Market orders for exit when edge disappears urgently. This maximizes expected return.
**Implementation cost:** Medium. Need order management (place, monitor, cancel stale limits).

### Decision 2: Model Ensemble Architecture
**Context:** Haiku at $0.005/call is cheap but calibration has room to improve. Sonnet at $0.03/call is 6x more expensive but likely better on ambiguous markets.
**→ Recommended: Haiku screen → Sonnet conviction.** Haiku scans all markets (~$0.50/cycle for 100 markets). Top 10 by edge size get Sonnet re-analysis (~$0.30). Total: ~$0.80/cycle vs $3.00/cycle for Sonnet-only. ~$24/month vs $90/month. Better calibration where it matters.
**Implementation cost:** Low. Add a two-pass pipeline in the existing strategy module.

### Decision 3: Early Exit Rules
**Context:** Hold-to-resolution is simpler but locks capital. Active management lets you redeploy capital to higher-edge opportunities.
**→ Recommended: Hold-to-resolution default, exit if edge inverts.** Specifically: exit if Claude re-analysis flips the signal direction (was long, now estimates probability below market price). Don't add arbitrary take-profit/stop-loss — these reduce expected return on binary outcomes.
**Implementation cost:** Low. Add a periodic re-evaluation loop that checks open positions.

### Decision 4: Position Sizing Refinement
**Context:** Current half-Kelly uses a fixed win rate from backtests. Real Kelly should use per-market edge estimates.
**→ Recommended: Per-market Kelly with 0.25x fraction.** Use Claude's probability estimate to compute per-trade Kelly. Quarter-Kelly (not half) for live trading with real money — reduces variance meaningfully with small expected return cost. Max position: $150 (5% of $3k capital).
**Implementation cost:** Low. Modify sizing formula in strategy base.

### Decision 5: Database for Live
**Context:** SQLite works for dev/paper. Live needs PostgreSQL for concurrent access (bot + API + data collector).
**→ Recommended: PostgreSQL via docker-compose (already configured).** The docker-compose.yml already has a postgres service. Just ensure the bot connects to it.
**Implementation cost:** Near zero. Already wired.

### Decision 6: Deployment Target
**Context:** Hetzner CX23 ($12/mo) is already planned. Bot needs to be running 24/7 with monitoring.
**→ Recommended: Defer deployment to Week 2.** Paper trade locally March 5–10, deploy to VPS March 10 when going live. Avoid premature infra debugging.
**Implementation cost:** Low (already has Docker configs).

---

## 3. P0/P1 Build Plan — 2-Week Sprint

### Week 1: March 5–10 (Paper Trading + Critical Fixes)

**Milestone 1 (Day 1, March 5): Foundation**

| Task | Acceptance Criteria |
|------|-------------------|
| Initialize git repo with .gitignore | `git log` shows initial commit with full codebase |
| Update dependencies to latest stable | `py-clob-client`, `anthropic` SDK at current versions, tests pass |
| Wire private key into .env | Bot can authenticate to CLOB API (read-only test) |
| Run full test suite, fix failures | All 34+ tests green |

**Milestone 2 (Days 2–3, March 6–7): Data Pipeline + Model Ensemble**

| Task | Acceptance Criteria |
|------|-------------------|
| Build resolved-market collector | Automated daily fetch of newly resolved markets from Gamma API, appending to `historical_markets.json` |
| Build Haiku→Sonnet two-pass pipeline | Haiku screens N markets, top K by edge get Sonnet re-analysis. Configurable N, K thresholds. |
| Update calibration pipeline | Re-run calibration with Sonnet estimates on existing 532-market dataset. Log Brier score delta. |
| Add per-market Kelly sizing | Sizing uses Claude's probability estimate per trade, 0.25x Kelly fraction, $150 max position |

**Milestone 3 (Days 4–5, March 8–9): Order Management + Paper Validation**

| Task | Acceptance Criteria |
|------|-------------------|
| Implement limit order entry logic | Bot places limit orders at target price, monitors fill status, cancels after configurable TTL |
| Implement edge-inversion exit logic | Periodic re-evaluation of open positions; exit signal when Claude estimate flips |
| Paper trading burn-in (48 hours) | Bot runs on paper for 48h with no crashes, all risk checks functional, Telegram alerts firing |
| Validate paper P&L vs backtest expectations | Paper results within 1 standard deviation of Monte Carlo fan chart |

**Milestone 4 (Day 5, March 10): Go-Live Gate**

| Task | Acceptance Criteria |
|------|-------------------|
| Fund wallet with USDC on Polygon | Wallet balance ≥ $3,000 USDC confirmed on-chain |
| End-to-end live integration test | Place and cancel one real $1 limit order on a liquid market. Confirm order appears on CLOB. |
| Review all risk parameters for $3k capital | Max position $150, max daily drawdown $150, max orders/hour 20, kill switch tested |
| Flip `LIVE_TRADING=true` | Bot begins live trading with full risk controls |

### Week 2: March 11–19 (Live Monitoring + P1 Features)

**Milestone 5 (Days 6–8, March 11–13): Monitoring + Ops**

| Task | Acceptance Criteria |
|------|-------------------|
| Deploy to Hetzner VPS via docker-compose | Bot + API + Postgres running, health check passing, auto-restart on failure |
| Structured Telegram alerts | Alerts for: new position, position exit, daily P&L summary, drawdown warning, kill switch trigger, system error |
| Dashboard hardening | Auth token rotated, HTTPS via Caddy/nginx reverse proxy, rate limiting on API |
| Daily automated calibration report | Cron job compares live performance to backtest predictions, logs drift |

**Milestone 6 (Days 9–12, March 14–17): Performance Optimization**

| Task | Acceptance Criteria |
|------|-------------------|
| Market selection refinement | Filter markets by liquidity depth (min $5k order book), time-to-resolution (7–90 days), and category performance |
| Multi-market portfolio optimization | Correlation-aware position sizing — reduce allocation to correlated markets |
| Backtest on fresh resolved markets | Run backtest on markets resolved since original 532-market dataset. Compare win rate and calibration. |
| Cost analysis | Log and analyze: Claude API costs per trade, slippage vs expected, fill rate on limit orders |

**Milestone 7 (Days 13–14, March 18–19): Sprint Review**

| Task | Acceptance Criteria |
|------|-------------------|
| Performance report (Week 1 live) | Actual P&L, win rate, Sharpe, max drawdown vs projections |
| Calibration audit | Claude estimates vs outcomes on live trades. Brier score on live data. |
| System reliability report | Uptime, error rate, alert frequency, order fill rate |
| Sprint 2 backlog groomed | Prioritized list of improvements based on live performance data |

### Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Polymarket API breaking changes (py-clob-client outdated) | High | Critical | Pin working version, test against live API on Day 1, have rollback plan |
| Wallet compromise (private key exposure) | Low | Critical | Key in .env only (never committed), .gitignore enforced, single-purpose wallet with limited funds |
| Claude API calibration drift | Medium | High | Daily calibration monitoring, automatic pause if Brier score degrades >20% from baseline |
| Liquidity crunch (can't exit positions) | Medium | High | Position size caps ($150), prefer markets with >$5k order book depth |
| Smart contract / resolution dispute | Low | High | Diversify across 10+ uncorrelated markets, max 5% capital per position |
| VPS downtime | Low | Medium | Docker auto-restart, health check endpoint, Telegram alert on heartbeat miss |
| Overfitting to historical data | Medium | High | Out-of-sample validation on newly resolved markets, walk-forward analysis |
| Regulatory action against Polymarket | Low | Critical | Monitor news, keep withdrawal path clear, no more than risk-tolerant capital deployed |

### Audit Checkpoints

| Checkpoint | When | What to Verify |
|-----------|------|---------------|
| **Pre-paper** | March 8 | All tests pass, risk parameters set, paper broker functional |
| **Pre-live** | March 10 | 48h paper burn-in clean, wallet funded, integration test passed, risk params reviewed |
| **Day 1 live** | March 11 | First real trades executed correctly, P&L tracking accurate, alerts working |
| **Day 3 live** | March 13 | Calibration on track, no unexpected losses, fill rate acceptable |
| **Week 1 review** | March 17 | Full performance review, decide whether to increase/decrease capital allocation |
| **Sprint close** | March 19 | Comprehensive report, Sprint 2 planning |

---

## 4. Interfaces Draft

### 4.1 Data Ingest Interface

```python
class DataFeed(ABC):
    """Market data provider. Already exists in src/data/base.py."""

    @abstractmethod
    async def get_market(self, market_id: str) -> MarketState:
        """Fetch current state for a single market."""

    @abstractmethod
    async def get_markets(self, filters: MarketFilter) -> list[MarketState]:
        """Fetch filtered list of active markets."""

    @abstractmethod
    async def get_orderbook(self, token_id: str) -> OrderBook:
        """Fetch order book depth for a token."""

# NEW: Resolved market collector
class ResolvedMarketCollector:
    """Fetches newly resolved markets for ongoing calibration."""

    async def collect_since(self, since: datetime) -> list[ResolvedMarket]:
        """Fetch markets resolved after `since` timestamp."""

    async def append_to_dataset(self, markets: list[ResolvedMarket]) -> int:
        """Append to historical_markets.json, return count added."""

    async def run_daily(self) -> None:
        """Cron-callable: collect, append, trigger recalibration."""
```

**Data flow:** Gamma API → `ResolvedMarketCollector` → `historical_markets.json` → Calibration pipeline → Updated win rates → Sizing parameters

### 4.2 Signal Interface

```python
@dataclass
class Signal:
    market_id: str
    token_id: str
    direction: Literal["BUY", "SELL"]
    confidence: float          # Claude's probability estimate (0-1)
    edge: float                # confidence - market_price (or market_price - confidence for SELL)
    model_used: str            # "haiku", "sonnet", "ensemble"
    reasoning: str             # One-line rationale from Claude

class Strategy(ABC):
    """Signal generator. Already exists in src/strategy/base.py."""

    @abstractmethod
    async def evaluate(self, market: MarketState) -> Signal | None:
        """Return a Signal if edge detected, None otherwise."""

# NEW: Ensemble strategy
class EnsembleStrategy(Strategy):
    """Two-pass: Haiku screen → Sonnet conviction."""

    async def screen(self, markets: list[MarketState]) -> list[Signal]:
        """Haiku pass: return all markets with |edge| > screen_threshold."""

    async def convict(self, candidates: list[Signal]) -> list[Signal]:
        """Sonnet pass on top-K candidates. Updates confidence and edge."""

    async def evaluate(self, market: MarketState) -> Signal | None:
        """Single-market evaluation (uses Haiku only for speed)."""
```

**Signal flow:** Markets → Haiku screen (all markets) → Top K by edge → Sonnet conviction → Final signals with updated confidence → Sizing

### 4.3 Sizing Interface

```python
@dataclass
class PositionSize:
    market_id: str
    token_id: str
    direction: Literal["BUY", "SELL"]
    size_usd: float            # Dollar amount to risk
    limit_price: float         # Target entry price for limit order
    kelly_fraction: float      # Actual Kelly fraction used
    edge: float                # Edge at time of sizing
    max_loss: float            # Worst case loss (size_usd if market resolves against)

class Sizer:
    """Position sizing engine. Replaces fixed half-Kelly."""

    def __init__(self, capital: float, kelly_multiplier: float = 0.25,
                 max_position_pct: float = 0.05, max_position_usd: float = 150.0):
        ...

    def size(self, signal: Signal, current_positions: list[Position]) -> PositionSize | None:
        """Compute position size using per-market Kelly.

        Returns None if:
        - Edge below minimum threshold
        - Would exceed max position size
        - Would exceed portfolio concentration limits
        - Correlated exposure too high
        """

    def kelly_optimal(self, win_prob: float, payout_ratio: float) -> float:
        """f* = (p * b - q) / b where p=win_prob, q=1-p, b=payout_ratio"""
```

**Sizing flow:** Signal (with confidence) → Kelly formula → Apply 0.25x multiplier → Cap at $150 / 5% of capital → Check portfolio constraints → PositionSize

### 4.4 Execution Interface

```python
class Broker(ABC):
    """Order execution. Already exists in src/broker/base.py."""

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """Place an order (limit or market)."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Check fill status of an order."""

# NEW: Order manager (wraps broker with lifecycle management)
class OrderManager:
    """Manages limit order lifecycle: place → monitor → fill/cancel."""

    async def submit(self, size: PositionSize) -> str:
        """Place limit order, return order_id. Log to DB."""

    async def monitor_fills(self) -> list[Fill]:
        """Check all open orders for fills. Update DB."""

    async def cancel_stale(self, max_age: timedelta) -> int:
        """Cancel unfilled orders older than max_age. Return count."""

    async def exit_position(self, position: Position, urgency: str) -> OrderResult:
        """Exit a position. urgency='normal' uses limit, 'urgent' uses market."""

# Execution modes (controlled by LIVE_TRADING env var)
# - read_only:  Fetch data, generate signals, log what WOULD trade. No orders.
# - paper:      PaperBroker simulates fills with slippage model.
# - live:       PolymarketBroker places real orders on CLOB. All risk checks enforced.
```

**Execution flow:** PositionSize → OrderManager.submit() → Limit order on CLOB → monitor_fills() loop → Fill recorded in DB → Position tracked → Re-evaluation loop → Exit if edge inverts

---

## 5. Remaining Questions

Only what I truly need before coding starts:

1. **Signature type:** Your .env shows `SIGNATURE_TYPE=2` (browser proxy / Safe wallet). The CLOB client code defaults to type 1 (EOA). Which wallet type are you using? This determines authentication flow and is a blocker for live trading.

2. **USDC source:** Do you have USDC on Polygon already, or do you need to bridge from Ethereum/CEX? This affects the March 10 go-live date if bridging takes time.

3. **Concurrent market limit:** The scanner checks 100+ markets per cycle. With $3k capital and $150 max position, that's a max of 20 simultaneous positions. Is that the right ceiling, or do you want to concentrate into fewer, higher-conviction bets?

---

*This document is the single source of truth for Sprint 1. All milestone acceptance criteria are binary pass/fail. If any P0 task fails its criteria, the go-live date slips.*
