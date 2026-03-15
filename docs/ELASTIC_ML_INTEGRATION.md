# Elastic ML Integration

This module adds Elastic anomaly-detection jobs on top of the `elastifund-orderbook`, `elastifund-signals`, and `elastifund-kills` indices. The goal is not to replace the existing kill rules. The goal is to catch order-flow and signal-quality regime shifts that static thresholds will miss.

## What The Jobs Detect

| Job | Index | Detector | Why it exists |
| --- | --- | --- | --- |
| `elastifund-vpin-anomaly` | `elastifund-orderbook` | `high_mean(vpin)` by `market_id` | Flags sudden toxicity spikes that often mean informed flow is taking over. |
| `elastifund-spread-anomaly` | `elastifund-orderbook` | `high_mean(spread_bps)` by `market_id` | Flags liquidity gaps before maker orders get trapped in a widening spread. |
| `elastifund-ofi-divergence` | `elastifund-orderbook` | `high_mean(ofi)` and `low_mean(ofi)` by `market_id` | Flags one-sided order-flow imbalance that can front-run large moves. |
| `elastifund-signal-confidence-drift` | `elastifund-signals` | `low_mean(confidence)` by `signal_source` | Flags when a signal family is degrading instead of silently letting it decay in production. |
| `elastifund-kill-rule-frequency` | `elastifund-kills` | `high_count` by `kill_rule` | Flags system-stress periods where safety rails are firing more often than normal. |

All five jobs are defined in [bot/elastic_ml_setup.py](bot/elastic_ml_setup.py).

## How It Feeds Back Into Trading

The runtime consumer lives in [bot/anomaly_consumer.py](bot/anomaly_consumer.py) and is wired into [bot/jj_live.py](bot/jj_live.py).

- VPIN or OFI anomaly above the runtime score threshold reduces position size by `anomaly_score / 100`.
- Spread anomaly pauses new order placement for the affected `market_id` for a bounded cooldown window.
- Signal-confidence drift does not hard-stop trading. It raises a warning and flags the source for human review.
- Kill-rule frequency anomaly emits a critical log because it usually means the system is under stress, not that one market is misbehaving.

This is intentionally asymmetric. Toxic flow and spread blowouts change execution behavior immediately. Signal drift changes operator attention first.

## Setup

1. Start Elasticsearch and ensure the `elastifund-orderbook`, `elastifund-signals`, and `elastifund-kills` indices are receiving data.
2. Export Elastic credentials in the same shell the bot will use.
3. Run:

```bash
python3 bot/elastic_ml_setup.py setup
```

4. Inspect job status:

```bash
python3 bot/elastic_ml_setup.py status
```

5. Inspect recent anomaly summaries:

```bash
python3 bot/elastic_ml_setup.py summaries --lookback 24h --min-score 75
```

6. Enable the runtime feedback loop:

```bash
export ELASTIC_ML_ENABLED=true
export ELASTIC_ML_SCORE_THRESHOLD=75
python3 bot/jj_live.py --continuous
```

## Tuning Guide

### Bucket Span

- Keep `5m` on VPIN, spread, and OFI unless the orderbook feed is materially sparser than expected.
- Keep `1h` on signal confidence and kill frequency until there is enough history to justify shorter windows.
- If jobs are too noisy, widen `bucket_span` before lowering the score threshold.

### Runtime Score Threshold

- `75` is the default trading threshold because it is aggressive enough to catch sharp regime changes without reacting to every cold-start blip.
- Lower it if you want earlier warnings and are comfortable with more false positives.
- Raise it if the bot is over-throttling markets that are still executable.

### Pause And Hold Windows

- `ELASTIC_ML_MARKET_PAUSE_SECONDS` controls how long spread anomalies block fresh orders.
- `ELASTIC_ML_CAUTION_HOLD_SECONDS` controls how long VPIN and OFI anomalies keep size suppressed.
- Shorten those windows only if the market routinely mean-reverts faster than the current hold time.

## Known Limitations

- Cold start is real. Fresh jobs do not know "normal" yet, so early scores should be treated as provisional.
- These jobs need steady event flow. Sparse markets will not produce stable baselines quickly.
- The runtime consumer is best-effort by design. If Elasticsearch or the ML API is down, trading continues without ML feedback.
- A high anomaly score is not a directional edge. It is an execution-quality warning or a model-health warning.
