# Behavioral Fingerprinting v2: Design Specification

**Source**: ChatGPT Pro research session (Prompt 2), March 14, 2026
**Status**: Reference document for implementation

## Architecture: Event-Sourced Fingerprinting Pipeline

Four layers:
- **Layer A**: Raw event store (every websocket payload, API response, subgraph record)
- **Layer B**: Normalized warehouse (market_windows, book_events, wallet_trades, fill_events, spot_ticks, fingerprint_episodes)
- **Layer C**: Feature engine (joins trades to book state, metadata, resolution, spot features)
- **Layer D**: Modeling (fingerprints, episode clustering, mixture estimation, archetype labeling)

## Data Sources

- **Gamma API**: `GET /markets` for BTC5 discovery, `clobTokenIds`, metadata
- **CLOB Market WebSocket**: `book`, `price_change`, `last_trade_price`, `best_bid_ask` events
- **Data API**: `GET /trades` (with `takerOnly=false`), `GET /activity`, `GET /positions`, `GET /closed-positions`
- **Orders Subgraph**: `OrderFilledEvent` with `maker`, `taker`, `makerAssetId`, `takerAssetId`, `transactionHash`
- **Binance**: `btcusdt@trade` for spot BTC feed
- **Proxy wallet normalization**: Gamma public-profile `proxyWallet` field

## Episode-Level Clustering

An episode = one wallet x one BTC5 window. Features per episode:
- first_visible_trade_delay_sec, first_inferred_quote_delay_sec
- trades_per_window, unique_actions_per_window, last_60s_trade_share
- maker_share, taker_share
- signed_distance_to_mid_mean, spread_normalized_distance_mean
- improvement_vs_cross_mean, settlement_edge_signed
- bullish_share, momentum_beta
- hold_to_expiry, median_hold_time_sec
- log_size, size_cv, scale_vs_vol_beta, average_in_rate

Pipeline: winsorize -> robust-scale -> PCA/UMAP -> HDBSCAN/GMM -> label by centroid rules

Suggested archetypes: early_maker, late_sniper, volatility_fader, momentum_taker, rebate_harvester, inventory_hedger

## Strategy Mixture Model

Per wallet: `strategy_mix = {cluster_a: 0.52, cluster_b: 0.31, ...}`

## Regime-Switching Detection

Stratify mixture weights by: vol regime, spread regime, trend regime.
Jensen-Shannon divergence between regime-specific mixtures.
If divergence > threshold: wallet is multi-strategy.

Optional HMM/regime-switching model on episode sequence.

## Feature Computation Details

### Timing
- KS test vs Uniform(0, 300)
- Beta-mixture or dip test for multimodal timing
- Poisson/negative-binomial for trade count per window

### Price Positioning
- signed_distance_to_mid = entry_price - mid_at_entry
- spread_normalized_distance = (entry_price - mid) / spread
- improvement_vs_cross: buy = best_ask - entry_price
- settlement_edge_signed = settlement_price - entry_price
- maker share, taker share, fraction strictly better than crossing

### Directional Bias
- Map: BUY YES = bullish, SELL NO = bullish, BUY NO = bearish, SELL YES = bearish
- momentum_beta via logistic regression
- return_lag_profile: coefficients for 15s, 30s, 60s, 300s BTC returns

### Sizing
- Robust regression: log(size) ~ |mid-0.5| + time_remaining + vol + spread + depth_imbalance
- average_in_rate, pyramid_in_score, staggered_entry_gap_sec

### Signal Correlation
- Trade propensity model with matched controls
- Direction model conditional on trading
- Permutation importance, partial R^2, rank-order correlations

## Statistical Reliability

- Wilson or Bayesian intervals for rates
- Bootstrap CIs for medians and coefficients
- Minimum-sample flags
- Confidence levels: high (>=100 windows, >=80% attributed fills), medium (30-99), low (<30)

## Output JSON Schema

13 sections per wallet: wallet, canonical_wallet, sample, timing_profile, price_positioning, directional_bias, sizing_patterns, inventory_management, signal_correlation, strategy_mix, regime_behavior, plain_english_summary, confidence
