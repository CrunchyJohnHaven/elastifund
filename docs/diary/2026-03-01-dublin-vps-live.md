# Day 14: March 1, 2026 — Dublin VPS Goes Live

## What I Did Today

Deployed the full trading system to AWS Lightsail Dublin (eu-west-1). The bot is running as a systemd service on the VPS, scanning markets every 5 minutes, and sending alerts to Telegram.

## Infrastructure

```
VPS: 52.208.155.0 (AWS Lightsail Dublin)
Service: jj-live.service (systemd)
Bot: /home/ubuntu/polymarket-trading-bot/jj_live.py
Dashboard: FastAPI on port 8000 (9 endpoints)
Monitoring: Telegram alerts + journalctl logs
```

The dashboard exposes: `/health`, `/status`, `/metrics`, `/risk`, `/kill`, `/unkill`, `/orders`, `/execution`, `/logs/tail`. The kill switch (`/kill`) cancels all open orders immediately — this is the most important endpoint.

## Why Dublin

Initial assumption: Polymarket infrastructure is in the US, so we should host in the US. Wrong. Deep research revealed Polymarket's CLOB is in AWS London (eu-west-2). Dublin (eu-west-1) is in the same AWS region cluster — roughly 5-10ms latency. London colocation would be marginally faster, but Dublin Lightsail is $5/month vs $50+/month for London EC2. The cost-latency tradeoff favors Dublin at our scale.

We decommissioned the Frankfurt server (161.35.24.142) — it was further from London and cost more.

## What I Learned

Deploying a trading bot to production is 80% safety engineering and 20% actual deployment:

- Kill switch: one API call cancels everything
- Daily loss limit: $10 hard cap, auto-pauses the system
- Per-trade cap: $5 maximum, overrides Kelly if Kelly says more
- Exposure cap: 80% of bankroll maximum, always keep 20% cash
- Cooldown: 3 consecutive losses triggers a 1-hour pause
- Gradual rollout: Week 1 ($1/trade, 3 trades/day), Week 2 ($2, 5 trades), Week 3 ($5, unlimited)

Each escalation requires a manual .env change and systemd restart. The bot cannot promote itself to higher risk levels.

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | $247.51 USDC on Polymarket |
| VPS cost | $5/month |
| Latency to CLOB | 5-10ms |
| Dashboard endpoints | 9 |
| Tests passing | 210 |

---

*Tags: #infrastructure #live-trading*
