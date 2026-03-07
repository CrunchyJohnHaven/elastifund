# Automated Polymarket trading bot: a complete build guide

**A fully automated Polymarket trading system can be built for under $10/month in infrastructure, but the real cost is Claude API usage at ~$5–20/month depending on analysis volume.** Your $300 budget covers roughly 10–30 months of operation. The critical decision is skipping OpenClaw entirely — its 12–20% malicious skill rate makes it a security nightmare for anything touching private keys — and instead building a lightweight Python bot using Polymarket's official `py-clob-client` library with the Anthropic API wired directly as the reasoning engine. This guide covers every layer: exact repos, working code, API authentication, VPS deployment, strategy math, and security hardening.

---

## The GitHub repos that actually matter

The Polymarket bot ecosystem has exploded, but most repos are SEO spam or abandoned. Here are the ones worth using, ranked by reliability and relevance.

**Official Polymarket tooling** forms the foundation. The `py-clob-client` library (https://github.com/Polymarket/py-clob-client) is the canonical Python client — **v0.34.5, 783 stars, MIT licensed, updated January 2026**. It handles authentication, order signing, and all CLOB interactions. The official `Polymarket/agents` repo (https://github.com/Polymarket/agents, 1,700 stars) provides an LLM-powered trading framework with ChromaDB for RAG-based market analysis, but has low commit frequency.

**For mean reversion on crypto markets**, the `0xrsydn/polymarket-streak-bot` (also called polymarket-crypto-toolkit) is the most complete implementation. It includes modular packages for indicators (EMA, RSI, Bollinger Bands), strategies (streak reversal, copytrade, candle direction), backtesting with parameter sweeps, and a live executor wrapping the CLOB client and WebSocket feeds. Run with `uv run python scripts/bot.py --paper` for paper trading.

**The best beginner-friendly standalone bot** is `discountry/polymarket-trading-bot` — it features gasless trading via Builder Program credentials, real-time WebSocket orderbook updates across 6 parallel connections, a built-in Flash Crash Strategy for volatility trading, secure key storage using PBKDF2 + Fernet encryption, and 89 unit tests. It even includes a `CLAUDE.md` file designed for Claude Code integration.

**For Claude Desktop integration**, `caiovicentino/polymarket-mcp-server` provides an MCP server with **45 tools** across market discovery, trading, analysis, and portfolio management — letting Claude trade Polymarket directly through the Model Context Protocol. For a 5-minute crypto arbitrage bot specifically, `rvenandowsley/Polymarket-crypto-5min-arbitrage-bot` implements detection and execution in Rust.

**BankrBot** (https://github.com/BankrBot/openclaw-skills) provides OpenClaw skills for Polymarket betting, leverage trading, and token deployment across multiple chains via the Bankr API. It's community-maintained but tightly coupled to the OpenClaw ecosystem, which introduces serious risks discussed below.

---

## API authentication and order placement from zero

Polymarket's CLOB API uses a three-tier authentication system. **Level 0** (no auth) provides read-only access to prices, orderbooks, and market data. **Level 1** uses your Ethereum private key to sign EIP-712 messages for creating API credentials. **Level 2** uses those derived API credentials (key, secret, passphrase) for all trading operations.

The base URLs are `https://clob.polymarket.com` for the CLOB API, `https://gamma-api.polymarket.com` for market discovery, and `wss://ws-subscriptions-clob.polymarket.com/ws/` for real-time WebSocket feeds. Rate limits are generous: **15,000 requests per 10 seconds** overall, with 3,500/10s burst on order placement.

Here's the complete initialization and first trade:

```python
import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType, ApiCreds
from py_clob_client.order_builder.constants import BUY, SELL

# Initialize with private key — derives API creds automatically
client = ClobClient(
    "https://clob.polymarket.com",
    key=os.getenv("PRIVATE_KEY"),           # Your wallet private key (no 0x prefix)
    chain_id=137,                            # Polygon mainnet
    signature_type=1,                        # 1=Magic/email wallet, 0=EOA, 2=browser proxy
    funder=os.getenv("FUNDER_ADDRESS")       # Your proxy wallet (Safe) address
)
client.set_api_creds(client.create_or_derive_api_creds())

# Fetch a market's orderbook
token_id = "<YES-token-id>"  # Get from gamma-api.polymarket.com/markets
book = client.get_order_book(token_id)
mid = client.get_midpoint(token_id)

# Place a limit order: 100 YES shares at $0.50
signed = client.create_order(OrderArgs(token_id=token_id, price=0.50, size=100.0, side=BUY))
resp = client.post_order(signed, OrderType.GTC)

# Place a market order: spend $25 on YES
mo = client.create_market_order(
    MarketOrderArgs(token_id=token_id, amount=25.0, side=BUY, order_type=OrderType.FOK)
)
client.post_order(mo, OrderType.FOK)
```

To get your private key, log into Polymarket → Cash → three-dot menu → "Export Private Key." Remove the `0x` prefix before storing. Your proxy wallet address (the `funder` parameter) is the Gnosis Safe that holds your USDC and conditional tokens. **Fund it by sending USDC.e on Polygon** to that address — the token contract is `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`.

For real-time data, subscribe to the WebSocket at `wss://ws-subscriptions-clob.polymarket.com/ws/` on the `market` channel with your token IDs to receive orderbook updates, or the `user` channel (authenticated) for order status changes.

---

## VPS deployment for under $4/month

**Hetzner's CX23 at €3.49/month ($3.80) is the optimal choice** — 2 vCPUs, 4 GB RAM, 40 GB NVMe, and 20 TB bandwidth. This is 2–4x the specs of DigitalOcean's $4 tier. For lowest latency to Polymarket's AWS eu-west-2 (London) infrastructure, choose Hetzner's Germany or Finland location. DigitalOcean at $4/month (1 vCPU, 1 GB RAM) works but is tighter.

Deploy on Ubuntu 24.04 with this setup sequence:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw fail2ban
sudo adduser botuser && su - botuser
mkdir ~/polymarket-bot && cd ~/polymarket-bot
python3 -m venv venv && source venv/bin/activate
pip install anthropic py-clob-client python-telegram-bot python-dotenv requests aiohttp
```

Create a systemd service at `/etc/systemd/system/polymarket-bot.service` pointing to your bot script with `Restart=always` and `EnvironmentFile=/home/botuser/polymarket-bot/.env`, then enable it with `systemctl enable --now polymarket-bot`. The bot survives reboots and crashes automatically.

**Your Claude Max 20x subscription does NOT provide API access for a bot.** You need separate API credits from console.anthropic.com, billed per-token. **Claude Haiku 4.5 at $1/$5 per million tokens (input/output) is the sweet spot** — screening 50 markets daily costs roughly $5/month. Claude Sonnet 4.5 at $3/$15 per MTok runs ~$20/month for the same volume but delivers significantly better reasoning on nuanced political and economic questions. Use prompt caching (reads at 0.1x cost) to slash repeat system prompt charges.

For Telegram alerts, create a bot via @BotFather, grab the token, and use `python-telegram-bot` to push formatted trade notifications. The complete monthly cost breakdown:

- Hetzner VPS: **$3.80**
- Claude API (Haiku, light usage): **$5**
- Claude API (Sonnet, heavier usage): **$20**  
- Telegram: **free**
- VPN (optional, Mullvad): **$5.45**
- **Total: $9–29/month**, leaving your $300 budget covering 10–30+ months

---

## How the profitable strategies actually work

**LMSR/sub-dollar arbitrage** exploits the fundamental invariant that YES + NO must equal $1.00. When you can buy both sides for less than $1 combined, you lock in risk-free profit at settlement. Between April 2024 and April 2025, roughly **$40 million in arbitrage profits** were extracted from Polymarket according to academic analysis. However, on Polymarket's shared orderbook, a YES sell at $0.40 is automatically a NO buy at $0.60, making single-market arbitrage structurally harder. The real opportunities exist in **multi-outcome (NegRisk) markets** where probabilities across many outcomes don't sum correctly, and in **cross-platform arbitrage** between Polymarket and Kalshi.

**For 5-minute BTC/ETH markets**, the viable approach is latency arbitrage — monitoring Chainlink oracle price feeds directly and trading before the Polymarket orderbook reflects the new price. These windows last **2–15 seconds** and are bot-only territory. Mean reversion works during panic overreactions where Up + Down temporarily sums below $1.00, but these markets carry taker fees of up to **1.56% at the midpoint** ($0.50). Use maker/limit orders (zero fees) exclusively to avoid this drag.

**Sentiment/news-driven trading with Claude** is where the real edge lies for a solo operator. Structure your prompts to ask Claude for a calibrated probability estimate, key factors for and against, historical base rates, and whether the current price appears mispriced. The most effective approach uses an ensemble — run the same market through Claude Sonnet and one or two other models. When they agree within 2–3 percentage points, the estimate is reliable. Divergence over 15 points signals the need for deeper research.

**The Kelly Criterion for binary markets simplifies to: `f* = (p_true - p_market) / (1 - p_market)`** where `p_true` is your estimated probability and `p_market` is the YES share price. If a market prices YES at $0.60 and you estimate 75% true probability, full Kelly says bet 37.5% of your bankroll. **Always use half-Kelly (multiply by 0.5)** — it captures ~75% of maximum growth rate while dramatically reducing drawdown risk. Never commit more than 20–25% to any single position regardless of what Kelly outputs.

```python
def kelly_bet(bankroll, p_true, p_market, fraction=0.5):
    full_kelly = (p_true - p_market) / (1.0 - p_market)
    if full_kelly <= 0:
        return {"side": "NO_BET" if full_kelly == 0 else "BUY_NO", "amount": 0}
    bet = bankroll * full_kelly * fraction
    return {"side": "BUY_YES", "amount": round(bet, 2), 
            "kelly_pct": round(full_kelly * fraction * 100, 1)}
```

---

## Fee structure determines which strategies survive

**Most Polymarket markets have zero trading fees** — no maker fees, no taker fees, no withdrawal fees. This is the key competitive advantage over Kalshi. However, **15-minute crypto markets, NCAAB, and Serie A markets carry taker fees** following a parabolic formula: `fee(p) = p × (1-p) × 0.0625`. This peaks at **1.56% effective rate at $0.50** and drops toward zero at price extremes. Maker (limit) orders are always fee-free, even on fee-enabled markets. The Polymarket US regulated exchange charges a flat **0.10% taker fee** on all markets.

For arbitrage strategies, this means you need a minimum spread exceeding **2.5–3% after all costs** (fees + slippage + gas) to profit. On fee-free political markets, the threshold is much lower — essentially just slippage. Use post-only orders (available since January 2026) to guarantee maker status and zero fees.

---

## Why you should not use OpenClaw for trading

The security situation with OpenClaw is catastrophic. A January–February 2026 audit by Koi Security found **341 malicious skills** out of 2,857 audited on ClawHub — a 12% infection rate. Updated scans found **824+ malicious skills** across the now 10,700+ skill registry, roughly 20% of all skills. The "ClawHavoc" campaign delivered Atomic Stealer malware on macOS. Two Polymarket-themed skills specifically contained reverse shell backdoors, and three crypto-related skills deployed malware via a fake "PolymarketAuth.exe." CVE-2026-25253 (CVSS 8.8) enabled one-click remote code execution via cross-site WebSocket hijacking.

**Build a lightweight custom Python bot instead.** A 500-line trading script using `py-clob-client` + `anthropic` + `python-telegram-bot` gives you everything you need with a fully auditable attack surface. If you must use an OpenClaw skill, Chainstack's Polyclaw (https://github.com/chainstacklabs/polyclaw) is from a reputable source and works as a standalone CLI without OpenClaw. Never install unverified ClawHub skills, especially anything touching crypto wallets.

---

## Securing private keys on a VPS

Store all secrets in a `.env` file with `chmod 600` permissions, loaded via `python-dotenv`. For stronger protection, encrypt the file with `dotenvx encrypt` or GPG (`gpg --symmetric --cipher-algo AES256 .env`), decrypting only at runtime and shredding the plaintext immediately. Alternatively, inject secrets directly as systemd environment variables in a root-owned override file.

Harden the VPS itself aggressively: disable password SSH login (use ed25519 keys only), enable UFW firewall allowing only SSH, install fail2ban, disable root login, enable automatic security updates with `unattended-upgrades`, and run the bot as a non-root user. **Keep only a small trading balance** (~$50–100) in the hot wallet and store the bulk in a separate cold wallet. Rotate API keys periodically and monitor `/var/log/auth.log` for unauthorized access attempts.

---

## Conclusion: the fastest path from zero to automated trading

The minimal viable system requires four components: a Hetzner VPS ($3.80/month), `py-clob-client` for Polymarket API access, the Anthropic Python SDK for market analysis, and a Telegram bot for alerts. Skip OpenClaw — the security risks are disqualifying. Start with `discountry/polymarket-trading-bot` as your codebase (it's Claude-aware with built-in key encryption and WebSocket handling), wire in Claude Haiku for rapid market screening, and use the Kelly criterion at half-fraction for position sizing. The richest opportunities are in **news-driven mispricing on political/event markets** (zero fees, information edge over bots) rather than 5-minute crypto arbitrage (taker fees, latency competition with sophisticated bots). Your $300 budget provides over a year of infrastructure runway — the constraint is developing a genuine information edge, not technology.