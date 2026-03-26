# JJ Command Console

Real-time trading dashboard for the Elastifund autonomous trading system.

## Architecture

- **Frontend**: React 18 + TypeScript + Vite + Tailwind + Canvas2D
- **Backend**: FastAPI + WebSocket + APScheduler
- **Bridge**: Cloudflare Tunnel connects Replit frontend to local backend

## Local Development

```bash
./start.sh
# Opens frontend at http://localhost:5173, backend at http://localhost:8000
```

## Replit Deployment

1. **On your Mac** -- start the backend and tunnel:
   ```bash
   cd console
   ./start.sh          # starts backend on :8000
   ./tunnel.sh          # exposes :8000 via Cloudflare Tunnel
   ```

2. **Copy the tunnel URL** (e.g., `https://abc-xyz.trycloudflare.com`)

3. **In Replit** -- set Secrets:
   - `VITE_API_URL` = `https://abc-xyz.trycloudflare.com/api`
   - `VITE_WS_URL` = `wss://abc-xyz.trycloudflare.com`

4. **Run** on Replit -- it builds the frontend and serves at your Replit URL

## Screens

| Screen | What it shows |
|:---|:---|
| Tank | Hypothesis FishTank -- Canvas2D orbital visualization |
| P&L | Cumulative P&L frontier + cohort progress |
| Monte Carlo | Parameter heatmap surface |
| Filters | Filter economics waterfall |
| VPS | Service status + live log stream |
| Guide | Human-in-the-loop guidance terminal |
