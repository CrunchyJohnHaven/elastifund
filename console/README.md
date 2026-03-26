# JJ Command Console

Real-time dashboard for visualizing and controlling the Elastifund autonomous trading self-improvement loop. React + FastAPI + WebSocket frontend connects to the Dublin VPS via SSH, displays hypothesis evolution (FishTank), P&L frontier, Monte Carlo surfaces, filter economics, live VPS logs, and a guidance terminal for human-in-the-loop strategic input. See `CODEX_CONSOLE_SPEC.md` in the repo root for the full build spec.

## Quick Start

```bash
# Frontend (from console/)
npm install
npm run dev          # http://localhost:5173

# Backend (from console/server/)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
