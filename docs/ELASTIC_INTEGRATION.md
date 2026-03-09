# Elastic Stack Integration

This is the operator guide for the Elastic layer in Elastifund. The trading bot already has enough moving parts that plain text logs and ad hoc `grep` stop being useful very quickly. The Elastic stack gives the bot a searchable event history, latency traces, dashboard surfaces, and anomaly detection that can feed back into trading decisions.

## Why Elastic Stack For An Autonomous Trading Bot

The core problem is simple: Python logging to files is a black hole. When an agent runs 24/7, evaluates multiple signal sources, sizes with Kelly fractions, routes maker-only orders, and can reject its own ideas with kill rules, you need real-time observability, not post-hoc archaeology.

What Elastic solves for this repo:

- Live signal quality monitoring. We can see which of the six primary signal sources are producing useful decisions and which are degrading in real time.
- Order execution latency tracking. APM shows where time is actually spent on the path from market scan to order placement and fill detection.
- Anomaly detection on order flow. Elastic ML gives us a second line of defense for toxic flow, VPIN spikes, OFI divergence, and liquidity shocks that static thresholds can miss.
- Kill-rule observability. Kibana makes it obvious how close the bot is to daily loss, semantic decay, toxicity, cost-stress, and calibration boundaries.
- Post-mortem capability. When a trade goes wrong, we can reconstruct the exact signal state, order book, risk context, and latency profile that existed at decision time.

## Architecture Overview

```text
Market data APIs / WebSockets
        |
        v
bot/ws_trade_stream.py + bot/lead_lag_engine.py + LLM / debate pipeline
        |
        v
bot/jj_live.py
  |        |         |
  |        |         +--> kill_rules.py
  |        +------------> execution path / fill detection
  v
bot/elastic_client.py
  |--> elastifund-signals
  |--> elastifund-trades
  |--> elastifund-kills
  |--> elastifund-orderbook
  `--> latency / trace-linked events
        |
        v
Elasticsearch <--- Filebeat <--- /var/log/elastifund/bot.json.log
        |
        +--> Kibana dashboards
        +--> APM Server traces
        `--> ML anomaly jobs
                 |
                 v
        bot/anomaly_consumer.py
                 |
                 v
     caution multiplier / order pause / operator review
```

## What Each Component Does

| Component | Role In Elastifund |
|---|---|
| Elasticsearch | Primary observability store for signals, trades, kill events, order book snapshots, latency events, and ML results. |
| Kibana | Operator surface for dashboards, Discover queries, saved searches, and anomaly review. |
| Filebeat | Ships ECS-style JSON logs from `/var/log/elastifund/` into Elasticsearch without coupling bot liveness to log delivery. |
| APM Server | Accepts traces and spans from the Python bot so latency bottlenecks are visible by function, API call, and transaction type. |
| Elastic ML jobs | Detect abnormal VPIN, OFI, spread, signal confidence drift, and kill-rule frequency so risk posture can tighten automatically. |

## Setup Guide

The integration is intentionally boring to start up. The goal is a local, single-node observability stack that can run on one VPS or a strong laptop without changing trading behavior.

1. Install Docker Engine or Docker Desktop and confirm both `docker` and `docker compose` work.
2. Review the Elastic infra files:
   - `infra/docker-compose.elastic.yml`
   - `infra/filebeat.yml`
   - `infra/apm-server.yml`
   - `infra/index_templates/`
3. Start the stack from the repo root:

```bash
bash infra/setup.sh
```

4. Wait for the health loop in `infra/setup.sh` to report that Elasticsearch is healthy.
5. Open Kibana at `http://127.0.0.1:5601`.
6. Pull the generated `elastic` password from the Docker logs, then store it outside the repo or in `.env`.
7. Set the bot-side environment variables when you want telemetry enabled:

```bash
ES_ENABLED=true
ES_HOST=127.0.0.1
ES_PORT=9200
ES_USER=elastic
ES_PASSWORD=...
APM_SERVER_URL=http://127.0.0.1:8200
APM_SERVICE_NAME=elastifund-bot
```

8. Start the bot in paper or live mode as usual. The integration is designed so the trading loop behaves the same way if Elasticsearch is unavailable.
9. Import dashboards with `bot/elastic_dashboards.py` or Kibana Saved Objects once those assets exist under `infra/kibana_dashboards/`.
10. Verify data flow in Kibana Discover by checking the four core indices:
   - `elastifund-trades`
   - `elastifund-signals`
   - `elastifund-kills`
   - `elastifund-orderbook`

## Dashboard Guide

### Trading Overview

[Screenshot placeholder: Kibana dashboard showing trades per hour, win rate, cumulative P&L, and average fill latency.]

Use this when you want the operator answer to one question: is the bot trading cleanly? It should make execution pace, realized hit rate, fill speed, and P&L drift obvious without opening raw documents.

### Signal Quality

[Screenshot placeholder: Kibana dashboard showing signal accuracy by source, calibration curve, and signal-to-trade conversion rate.]

This is the truth surface for the six core signal sources plus the anomaly feedback lane. It should answer which source is confident, which source is actually right, and which source is being filtered out before capital is committed.

### Kill Rule Monitor

[Screenshot placeholder: Kibana dashboard showing kill-rule triggers over time, top firing rules, and current threshold headroom.]

This is the safety dashboard. It is where you look to understand whether the bot is close to a forced pause, drifting into degraded behavior, or repeatedly tripping a specific protection rail.

### Orderbook Health

[Screenshot placeholder: Kibana dashboard showing spread over time, depth heatmap, VPIN series, and OFI divergence.]

This is the market microstructure surface. It is especially useful on fast markets where maker-only execution quality depends on spread regime, queue health, and toxic-flow conditions.

### APM Overview

[Screenshot placeholder: Kibana APM view showing transaction throughput, latency distribution, and error rate across the signal-to-order path.]

Use this to identify bottlenecks in the critical path. If order latency suddenly expands, this is where you determine whether the time was lost in LLM calls, exchange APIs, database writes, or internal orchestration.

### ML Anomaly Monitor

[Screenshot placeholder: Kibana dashboard showing anomaly score timeline, per-market heatmap, and correlation with P&L.]

This is the operator view for source `#7`, the anomaly consumer. It should make clear when the system is reducing size, pausing markets, or flagging signal confidence drift because the distribution changed.

## Performance Impact

The integration is built to be safe first:

- Elasticsearch writes are asynchronous bulk writes with bounded flush intervals, not synchronous per-event blocking calls.
- Every call into Elasticsearch or APM is wrapped in `try/except`. If the stack is down, the bot logs a warning and keeps trading.
- `ES_ENABLED` defaults to false, so the code path is a no-op unless explicitly enabled.
- Filebeat decouples log shipping from bot execution. The bot only writes local JSON logs; Filebeat handles forwarding.
- Elastic is for observability and operator feedback, not for replacing the existing safety rails or the repo's source-of-truth docs.

## Known Limitations

- Elastic ML jobs need a warm-up period and enough history to become useful. Do not expect high-quality anomaly scores on day one.
- A single-node Elasticsearch deployment is correct for development and a small VPS, not for high-availability production claims.
- The first dashboards are operator dashboards, not investor dashboards. They are for debugging, validation, and public honesty.
- If the log path or credentials are wrong, the bot should continue to run, but the dashboards will be stale. Treat stale observability as an operator incident, not a trading feature.
