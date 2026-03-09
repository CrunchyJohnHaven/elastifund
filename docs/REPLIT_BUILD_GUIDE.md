# Replit Build Guide

This guide covers the practical ways to run the Elastifund stack on Replit with the Elastic integration. The short version is:

- if Docker is available, run a reduced local Elastic stack and keep the bot in paper mode
- if Docker is not available, use Elastic Cloud and let Replit run only the Python processes

Do not treat Replit as the permanent home for live trading or for durable Elasticsearch storage. It is a convenient demo, teaching, and operator-surface environment.

## What You Need First

- A fork of the repo
- Python 3.12 available in the Repl
- Replit Secrets configured instead of committing `.env`
- Enough memory for at least one Python process plus a reduced Elasticsearch node

Recommended Secrets when running Elastic locally:

```text
ES_ENABLED=true
ES_HOST=127.0.0.1
ES_PORT=9200
ES_USER=elastic
ES_PASSWORD=...
APM_SERVER_URL=http://127.0.0.1:8200
APM_SERVICE_NAME=elastifund-bot
PAPER_TRADING=true
```

Add the normal Polymarket, Kalshi, Anthropic, OpenAI, and Telegram secrets only if the workflow you are demonstrating actually needs them.

## Option A: Replit With Docker Available

### 1. Boot The Repo

```bash
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
python3 scripts/quickstart.py --prepare-only
```

### 2. Use A Reduced Elastic Footprint

Replit memory is usually the hard constraint, not CPU. For a demo or educational build, lower the Elasticsearch heap to 512 MB and avoid exposing Elasticsearch itself publicly.

Sample override file:

```yaml
services:
  elasticsearch:
    environment:
      ES_JAVA_OPTS: "-Xms512m -Xmx512m"
  kibana:
    ports:
      - "127.0.0.1:5601:5601"
  apm-server:
    ports:
      - "127.0.0.1:8200:8200"
```

Run:

```bash
docker compose \
  -f infra/docker-compose.elastic.yml \
  -f infra/docker-compose.elastic.replit.yml \
  up -d
```

If you do not want a second compose file, edit the heap setting directly before the session and restore it later.

### 3. Start The Bot

```bash
source .venv/bin/activate
PAPER_TRADING=true python3 bot/jj_live.py
```

### 4. Forward Ports Carefully

- Publish Kibana on port `5601`
- Keep Elasticsearch on `9200` private to the Repl
- Keep APM on `8200` private unless you have a specific reason to expose it

If you need to show Kibana publicly, make sure authentication is on and do not paste credentials into repo files or markdown screenshots.

## Option B: Replit Without Docker

This is the more durable option for public demos because it moves the heavy state out of Replit.

### 1. Create An Elastic Cloud Trial Deployment

Use the free trial deployment as the backend for:

- Elasticsearch
- Kibana
- APM

### 2. Point The Bot At Elastic Cloud

Use Replit Secrets for the cloud endpoint and credentials:

```text
ES_ENABLED=true
ES_HOST=<your-elastic-cloud-host>
ES_PORT=443
ES_USER=elastic
ES_PASSWORD=...
APM_SERVER_URL=<your-apm-endpoint>
APM_SERVICE_NAME=elastifund-bot
```

If your branch later adds an explicit scheme variable, prefer `https`. On the interface defined for the Elastic integration, the core requirement is that the host, port, user, and password resolve to the cloud deployment.

### 3. Run Only The Python Side In Replit

```bash
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
PAPER_TRADING=true python3 bot/jj_live.py
```

This path is the cleanest way to demo dashboards on Replit without asking Replit to also carry a local Elasticsearch node.

## Replit-Specific Constraints

### Memory Limits

- Default to a `512m` Elasticsearch heap on Replit.
- Keep the bot in paper mode while validating the observability layer.
- Prefer Elastic Cloud if you want both Kibana and the trading bot to stay responsive under load.

### Port Forwarding

- Kibana is the only port that usually needs to be visible in the browser.
- Elasticsearch should stay private. It is an internal service, not a public API for the demo.
- If you do expose Kibana, do it behind Elastic auth and treat every screenshot as public.

### Secrets Handling

- Use Replit Secrets for `ES_PASSWORD`, API keys, and tokens.
- Do not write generated Elastic passwords or APM tokens into tracked files.
- Keep `.env` local only when developing outside Replit.

### Persistence

- Replit storage is fine for a demo, not for durable Elasticsearch history.
- If the observability history matters, use Elastic Cloud or export snapshots regularly.

## Suggested `.replit` Configuration

The exact shape varies by Replit template, but this is a workable baseline:

```toml
entrypoint = "README.md"
modules = ["python-3.12"]
run = "bash -lc 'source .venv/bin/activate && PAPER_TRADING=true python3 bot/jj_live.py'"
hidden = [".git", ".venv", "data", "logs", "reports", "state"]

[nix]
channel = "stable-24_05"
```

If you are running Docker inside the Repl, replace `run` with a small bootstrap script that starts the Elastic containers first and the bot second.

## What You’ll See

When the integration is wired correctly, the Replit demo should show:

- Kibana Discover receiving documents in `elastifund-signals`, `elastifund-trades`, `elastifund-kills`, and `elastifund-orderbook`
- the Trading Overview dashboard updating as paper trades and fills are recorded
- the Signal Quality dashboard showing which sources are being acted on and which are being skipped
- structured JSON logs landing through Filebeat instead of only scrolling past in a terminal
- APM transactions for the signal evaluation cycle, order placement path, and external API calls
- after enough history exists, anomaly jobs that can raise caution or pause a market

## Recommended Demo Story

The strongest public Replit demo is not "look, Elasticsearch runs in a browser tab." It is:

1. a market event comes in
2. the bot produces signal documents
3. a trade decision is recorded
4. latency is visible in APM
5. Kibana shows the same event from the operator point of view

That is the educational payoff. The point is to make the system inspectable.
