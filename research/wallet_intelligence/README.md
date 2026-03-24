# Wallet Intelligence Pipeline

Discovers, ranks, and fingerprints the most profitable Polymarket BTC5 traders,
then generates testable trading hypotheses from their observed behavior.

Related brief:
- `research/wallet_intelligence/polywallet_reconstruct.md` for the focused deep-research handoff on elite fast-market wallet reconstruction.

## Pipeline Phases

| Phase | Module | Input | Output |
|-------|--------|-------|--------|
| 0. Seed list bootstrap | `smart_wallet_seed_builder.py` | Leaderboard + seed wallets + co-occurrence trades | `smart_wallets_scored.json` |
| 1. Discovery & Ranking | `wallet_pnl_tracker.py` | Polymarket Data API + Gamma API | `wallet_leaderboard.json` |
| 2. Behavioral Fingerprinting | `behavioral_fingerprint.py` | Phase 1 DB + Binance klines | `wallet_fingerprints.json` |
| 3. Hypothesis Generation | `hypothesis_generator.py` | Phases 1-2 outputs + kill list | `wallet_hypotheses.json` |
| 4. Autoresearch Integration | `hypothesis_generator.convert_to_autoresearch_candidates()` | Phase 3 output | Candidates for `btc5_autoresearch_v2.py` |

## Quick Start

```bash
# Phase 0: Build wallet seed list for wallet-flow consensus monitoring
python research/wallet_intelligence/smart_wallet_seed_builder.py --top-n 50

# Phase 1: Discover wallets and compute PnL (takes ~10-30 min depending on market count)
python research/wallet_intelligence/wallet_pnl_tracker.py --full --max-markets 100

# Phase 2: Fingerprint top 20 wallets
python research/wallet_intelligence/behavioral_fingerprint.py --top-n 20

# Phase 3: Generate hypotheses
python research/wallet_intelligence/hypothesis_generator.py

# Incremental update (run daily)
python research/wallet_intelligence/wallet_pnl_tracker.py --incremental
```

## Data Sources

| Source | API | Auth | Rate Limit | Purpose |
|--------|-----|------|------------|---------|
| Gamma | `gamma-api.polymarket.com` | None | ~200/min | Market discovery |
| Data API | `data-api.polymarket.com` | None | 150/10s | Trade history (takerOnly=false) |
| CLOB API | `clob.polymarket.com` | Poly key | Varies | Order book, account trades |
| Binance | `api.binance.com` | None | 1200/min | BTC price correlation |

## Data Quality Flags

Phase 2 fingerprints carry explicit data quality flags:

- `midpoint_approximated: true` — Historical midpoint estimated from trade price.
  Exact midpoint requires archived WebSocket data (forward-only collection).
- `maker_taker_inferred: true` — Maker/taker classification inferred from price
  position relative to estimated midpoint. Exact attribution requires on-chain
  `OrderFilled` event reconstruction.

## Integration with Autoresearch

Hypotheses from Phase 3 feed directly into the existing autoresearch loop:

```python
from research.wallet_intelligence.hypothesis_generator import (
    generate_hypotheses,
    convert_to_autoresearch_candidates,
)

hypotheses = generate_hypotheses(leaderboard_path, fingerprints_path)
candidates = convert_to_autoresearch_candidates(hypotheses)
# candidates are now in btc5_autoresearch_v2.py-compatible format
```

## Database

SQLite database at `data/wallet_intelligence.db` with three tables:

- `wallet_trades` — Individual trades by wallet (condition_id, side, price, size, timestamp)
- `wallet_profiles` — Aggregated metrics per wallet (PnL, win rate, Sharpe, confidence)
- `market_resolutions` — Market metadata and resolution status

## Last Updated

March 14, 2026 — Initial build (Session: Cowork autoresearch pipeline)
