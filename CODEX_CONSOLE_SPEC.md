# JJ Command Console — Codex Build Spec

## What This Is

Build instructions for an ElastiTune-inspired real-time dashboard that visualizes and controls Elastifund's autonomous trading self-improvement loop. The console runs locally on John's Mac, connects to the Dublin VPS via SSH, and provides a single interface to watch, guide, and control the entire system.

## Reference Codebase

`/Users/johnbradley/Desktop/ElastiTune` — a React + FastAPI + WebSocket dashboard for Elasticsearch search optimization. We are adapting its architecture (FishTank Canvas, real-time event streaming, dark theme, Zustand state management) for trading self-improvement visualization.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    JJ Command Console (React SPA)               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  TopBar: System Health │ P&L │ Active Loops │ VPS Status  │  │
│  ├──────────┬────────────────────────────┬───────────────────┤  │
│  │          │                            │                   │  │
│  │  Left    │   Main Canvas              │   Right Rail      │  │
│  │  Rail    │   (mode-dependent)         │   (contextual)    │  │
│  │          │                            │                   │  │
│  │  Modes:  │   1. Hypothesis FishTank   │   Feed:           │  │
│  │  - Tank  │   2. P&L Frontier Graph    │   - Experiments   │  │
│  │  - P&L   │   3. Monte Carlo Surface   │   - Mutations     │  │
│  │  - Monte │   4. Filter Economics      │   - Safety events │  │
│  │  - Filtr │   5. VPS Live Console      │   - Deploy log    │  │
│  │  - VPS   │                            │                   │  │
│  │  - Guide │   6. Guidance Terminal     │   Controls:       │  │
│  │          │      (John's input)        │   - Kill switch   │  │
│  │          │                            │   - Promote       │  │
│  │          │                            │   - Deploy        │  │
│  │          │                            │   - Pause loop    │  │
│  └──────────┴────────────────────────────┴───────────────────┘  │
│  BottomBar: Cohort Progress [████░░░░░░] 12/50 fills           │
└─────────────────────────────────────────────────────────────────┘
         │
         │  WebSocket (bidirectional)
         │  REST (commands, config)
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              JJ Backend (FastAPI + Uvicorn)                     │
│  ├─ /ws/live          Live event stream                        │
│  ├─ /ws/autoresearch  Autoresearch cycle stream                │
│  ├─ /api/cohort       Validation cohort status                 │
│  ├─ /api/health       System health snapshot                   │
│  ├─ /api/deploy       Trigger deploy to VPS                    │
│  ├─ /api/kill         Kill switch (disable strategy)           │
│  ├─ /api/promote      Force-promote a mutation                 │
│  ├─ /api/guidance     Submit human guidance to next cycle      │
│  ├─ /api/montecarlo   Trigger Monte Carlo run                  │
│  ├─ /api/filters      Filter economics data                   │
│  └─ SchedulerDaemon   Runs all loops on cadence               │
│       ├─ Autoresearch every 6h                                │
│       ├─ Adaptive floor every 2h                              │
│       ├─ Monte Carlo daily                                    │
│       ├─ Health snapshot every 5min                           │
│       ├─ Cohort report every 15min                            │
│       └─ VPS liveness check every 1min                        │
└──────────────┬─────────────────────┬────────────────────────────┘
               │                     │
     ┌─────────▼──────────┐  ┌──────▼──────────────────┐
     │  Local SQLite DBs  │  │  VPS (Dublin)           │
     │  ├─ btc_5min_maker │  │  ├─ jj-live.service    │
     │  ├─ jj_trades      │  │  ├─ btc-5min-maker     │
     │  └─ experiments    │  │  ├─ wallet state       │
     └────────────────────┘  └─────────────────────────┘
```

## Tech Stack

### Frontend (copy ElastiTune choices exactly)
- react 18.2.0
- react-router-dom 6.28.0
- typescript 5.6.3
- vite 5.4.10
- zustand 5.0.1 (state management — NOT redux)
- recharts 2.13.0 (charts)
- d3-scale, d3-color, d3-interpolate 3.x (low-level viz)
- framer-motion 11.11.17 (animations)
- lucide-react 0.454.0 (icons)
- tailwindcss 3.4.14 (styling)
- clsx 2.1.1 + tailwind-merge 2.5.4 (utility CSS)

### Backend
- fastapi 0.115.5
- uvicorn[standard] 0.32.0
- websockets 13.1
- orjson 3.10.11 (fast JSON serialization)
- asyncssh 2.x (SSH tunnel to VPS — preferred over paramiko for async)
- apscheduler 3.10.x (cron-like scheduling daemon)
- numpy 2.1.3
- scipy 1.14.1
- httpx 0.27.2

## File Structure

```
/Users/johnbradley/Desktop/Elastifund/console/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── postcss.config.js
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── routes.tsx
│   ├── lib/
│   │   ├── socket.ts              # WebSocket client (adapt from ElastiTune)
│   │   ├── api.ts                 # REST client
│   │   └── format.ts              # Number/date formatting
│   ├── store/
│   │   └── useAppStore.ts         # Zustand store
│   ├── types/
│   │   ├── events.ts
│   │   ├── cohort.ts
│   │   ├── hypothesis.ts
│   │   └── system.ts
│   ├── components/
│   │   ├── TopBar.tsx
│   │   ├── BottomBar.tsx
│   │   ├── LeftRail.tsx
│   │   ├── RightRail.tsx
│   │   ├── canvas/
│   │   │   ├── HypothesisTank.tsx  # FishTank clone for hypotheses
│   │   │   ├── MonteCarloSurface.tsx
│   │   │   └── canvasUtils.ts
│   │   ├── charts/
│   │   │   ├── PnLFrontier.tsx
│   │   │   ├── WinRateChart.tsx
│   │   │   ├── FilterEconomics.tsx
│   │   │   └── CohortProgress.tsx
│   │   ├── feeds/
│   │   │   ├── ExperimentFeed.tsx
│   │   │   ├── MutationFeed.tsx
│   │   │   ├── SafetyFeed.tsx
│   │   │   └── DeployLog.tsx
│   │   ├── controls/
│   │   │   ├── KillSwitch.tsx
│   │   │   ├── PromoteButton.tsx
│   │   │   ├── DeployButton.tsx
│   │   │   └── GuidanceTerminal.tsx
│   │   └── screens/
│   │       ├── TankScreen.tsx
│   │       ├── PnLScreen.tsx
│   │       ├── MonteCarloScreen.tsx
│   │       ├── FilterScreen.tsx
│   │       ├── VPSScreen.tsx
│   │       └── GuideScreen.tsx
│   └── theme/
│       └── colors.ts
├── server/
│   ├── main.py
│   ├── config.py
│   ├── scheduler.py
│   ├── routes/
│   │   ├── health.py
│   │   ├── cohort.py
│   │   ├── deploy.py
│   │   ├── guidance.py
│   │   ├── montecarlo.py
│   │   └── filters.py
│   ├── ws/
│   │   ├── live_stream.py
│   │   └── autoresearch_stream.py
│   ├── services/
│   │   ├── vps.py
│   │   ├── db.py
│   │   ├── autoresearch.py
│   │   ├── montecarlo.py
│   │   └── deployer.py
│   └── models/
│       ├── events.py
│       └── state.py
└── README.md
```

## Theme (Dark Mode — Match ElastiTune)

```typescript
export const theme = {
  bg: '#05070B',
  bgElevated: '#0B0F15',
  bgPanel: '#101520',
  border: 'rgba(255,255,255,0.08)',
  borderHover: 'rgba(255,255,255,0.15)',
  textPrimary: '#EEF3FF',
  textSecondary: '#9AA4B2',
  textMuted: '#5A6478',

  // Hypothesis states
  idle: 'rgba(154, 164, 178, 0.7)',
  testing: 'rgba(77, 163, 255, 0.9)',
  promoted: 'rgba(74, 222, 128, 0.9)',
  killed: 'rgba(251, 113, 133, 0.9)',
  incumbent: 'rgba(254, 197, 20, 0.9)',
  warning: 'rgba(251, 191, 36, 0.9)',

  // P&L
  profit: '#4ADE80',
  loss: '#FB7185',
  neutral: '#9AA4B2',

  // Elastic brand (subtle accents only)
  elasticBlue: '#0B64DD',
  teal: '#48EFCF',
}
```

## WebSocket Event Protocol

```typescript
// Server → Client
type SystemEvent =
  | { type: 'snapshot'; payload: SystemSnapshot }
  | { type: 'fill.live'; payload: FillRecord }
  | { type: 'fill.resolved'; payload: FillResolution }
  | { type: 'hypothesis.created'; payload: Hypothesis }
  | { type: 'hypothesis.tested'; payload: HypothesisResult }
  | { type: 'hypothesis.promoted'; payload: Promotion }
  | { type: 'hypothesis.killed'; payload: KillRecord }
  | { type: 'mutation.promoted'; payload: MutationState }
  | { type: 'mutation.reverted'; payload: RevertRecord }
  | { type: 'safety.breach'; payload: SafetyEvent }
  | { type: 'cohort.checkpoint'; payload: CohortReport }
  | { type: 'health.tick'; payload: HealthSnapshot }
  | { type: 'montecarlo.progress'; payload: MCProgress }
  | { type: 'montecarlo.complete'; payload: MCResult }
  | { type: 'deploy.status'; payload: DeployStatus }
  | { type: 'vps.log'; payload: LogLine }
  | { type: 'ping' }

// Client → Server
type ClientCommand =
  | { type: 'kill'; payload: { strategy: string } }
  | { type: 'promote'; payload: { hypothesis_id: string } }
  | { type: 'deploy'; payload: { profile: string } }
  | { type: 'guidance'; payload: { text: string; scope: string } }
  | { type: 'montecarlo.run'; payload: MCConfig }
  | { type: 'subscribe'; payload: { channels: string[] } }
```

## Screen Specifications

### Screen 1: Hypothesis FishTank

Adapt ElastiTune's `FishTankCanvas.tsx` (1,053 lines of Canvas2D).

**Mapping:**
- ElastiTune "persona" → Elastifund "hypothesis"
- ElastiTune "experiment" → Elastifund "backtest evaluation"
- ElastiTune "nDCG delta" → Elastifund "shadow P&L delta"

**Node behavior:**
- Radius from center = fitness score (closer = better)
- Color = status: idle (gray), testing (blue beam animation), promoted (green glow), killed (red fade-out), incumbent (gold pulse)
- Size = age (older hypotheses are slightly larger)
- New hypotheses spawn at outer ring with entrance animation
- Killed hypotheses fade and drift outward before disappearing
- Promoted hypothesis migrates to center with celebratory ripple
- Click any node → right rail shows full hypothesis detail (parameters, shadow P&L, win rate, kill reason if applicable)
- Beams animate from node to center when backtest is running

**Data source:** `data/autoresearch_results.json` + live events from autoresearch cycle

### Screen 2: P&L Frontier

Recharts line chart with multiple series.

**Lines:**
1. Running-best hypothesis P&L (the frontier — monotonically non-decreasing)
2. Actual live P&L (from wallet/DB)
3. Cohort-only P&L (post-fix, DOWN-only)
4. Monte Carlo 95% confidence band (shaded)

**Markers:**
- Diamond: promotion event
- X: safety kill
- Circle: cohort checkpoint (10, 20, 30, 50)

**X-axis:** Calendar time or experiment number (toggle)
**Y-axis:** Cumulative USD

**This is the most important view.** If the frontier isn't going up, the system isn't learning.

### Screen 3: Monte Carlo Surface

Heatmap (D3 + Canvas2D) or Recharts heatmap.

**Axes:** X = price floor (0.40-0.55), Y = hour-of-day ET (0-23)
**Color:** Expected P&L per cell (green = profitable, red = losing)
**Overlay:** Current parameters as crosshair
**Interaction:** Click cell to see detailed Monte Carlo stats
**Trigger:** Run on demand via button, or on daily schedule

**Data source:** `reports/btc5_monte_carlo/` output files

### Screen 4: Filter Economics

Waterfall chart (Recharts BarChart).

**Bars:** Each filter's net_filter_value_usd
- Green = filter saved money (blocked losing trades)
- Red = filter cost opportunity (blocked winning trades)

**Filters shown:** hour_filter, direction_filter, price_cap, position_cap

**Time periods:** Toggle between last 24h, last 7d, full cohort

**Data source:** `reports/btc5_filter_economics_latest.json`

### Screen 5: VPS Live Console

Split-pane: top = service status cards, bottom = scrolling log.

**Status cards:**
- jj-live.service: active/inactive/failed
- btc-5min-maker.service: active/inactive/failed
- Last fill: timestamp + age
- Config hash: match/mismatch
- DB size + row counts

**Log pane:** Real-time `journalctl -u btc-5min-maker -f` via SSH

**Controls:**
- Restart service button
- Deploy button (runs deploy.sh via SSH)
- Sync DB button (pulls remote DB to local)

### Screen 6: Guidance Terminal

**Input:** Multi-line text area where John types strategic guidance
**Examples displayed as placeholders:**
- "focus on price range 0.45-0.47 for next 3 cycles"
- "test wider hour windows — try allowing hour 10"
- "increase mutation rate to 50%"
- "run 50,000 Monte Carlo iterations on DOWN with current params"

**Mechanism:** Guidance text saved to `state/guidance/{timestamp}.md`. The autoresearch cycle reads the latest guidance file and incorporates it into hypothesis generation (like Karpathy's `program.md`).

**History panel:** List of past guidance entries with outcomes (was the guided hypothesis better?)

## Backend Services

### VPS Service (`server/services/vps.py`)

```python
import asyncssh

VPS_HOST = '34.244.34.108'
VPS_USER = 'ubuntu'
VPS_KEY = os.environ.get('LIGHTSAIL_KEY', os.path.expanduser('~/.ssh/lightsail.pem'))
REMOTE_BOT_PATH = '/home/ubuntu/polymarket-trading-bot'

async def check_service_status(service: str) -> dict:
    async with asyncssh.connect(VPS_HOST, username=VPS_USER, client_keys=[VPS_KEY]) as conn:
        result = await conn.run(f'systemctl is-active {service}')
        return {'service': service, 'status': result.stdout.strip()}

async def stream_journal(service: str, callback):
    async with asyncssh.connect(VPS_HOST, username=VPS_USER, client_keys=[VPS_KEY]) as conn:
        async with conn.create_process(
            f'journalctl -u {service} -f --output=json'
        ) as proc:
            async for line in proc.stdout:
                await callback(parse_journal_line(line))

async def sync_remote_db(local_path: str):
    async with asyncssh.connect(VPS_HOST, username=VPS_USER, client_keys=[VPS_KEY]) as conn:
        await asyncssh.scp(
            (conn, f'{REMOTE_BOT_PATH}/data/btc_5min_maker.db'),
            local_path
        )

async def run_deploy(profile: str = 'shadow_fast_flow') -> dict:
    # Execute deploy.sh locally (Mac has SSH access)
    proc = await asyncio.create_subprocess_exec(
        './scripts/deploy.sh', '--clean-env', '--profile', profile, '--restart', '--btc5',
        cwd='/Users/johnbradley/Desktop/Elastifund',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return {'exit_code': proc.returncode, 'stdout': stdout.decode(), 'stderr': stderr.decode()}
```

### DB Service (`server/services/db.py`)

```python
import sqlite3
import orjson

DB_PATHS = [
    'data/btc_5min_maker.db',
    'bot/data/btc_5min_maker.db',
]

def get_db_path() -> str:
    for p in DB_PATHS:
        full = os.path.join('/Users/johnbradley/Desktop/Elastifund', p)
        if os.path.exists(full):
            return full
    raise FileNotFoundError('No BTC5 database found')

def get_cohort_fills(cohort_start_ts: int) -> list[dict]:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT * FROM window_trades
        WHERE direction = 'DOWN'
          AND order_status LIKE 'live_%'
          AND order_status NOT LIKE '%shadow%'
          AND order_status NOT LIKE '%skip%'
          AND resolved_side IS NOT NULL
          AND decision_ts >= ?
        ORDER BY decision_ts
    ''', (cohort_start_ts,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_fills(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT * FROM window_trades
        ORDER BY decision_ts DESC LIMIT ?
    ''', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

### Scheduler (`server/scheduler.py`)

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import subprocess, json, os

REPO = '/Users/johnbradley/Desktop/Elastifund'

scheduler = AsyncIOScheduler()

async def run_script(script_path: str, emit_event=None):
    proc = await asyncio.create_subprocess_exec(
        'python3', os.path.join(REPO, script_path),
        cwd=REPO,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    result = {'script': script_path, 'exit_code': proc.returncode, 'stdout': stdout.decode()[-2000:]}
    if emit_event:
        await emit_event(result)
    return result

def setup_scheduler(event_emitter):
    scheduler.add_job(
        lambda: run_script('scripts/run_btc5_autoresearch_cycle.py', event_emitter),
        IntervalTrigger(hours=6), id='autoresearch', replace_existing=True
    )
    scheduler.add_job(
        lambda: run_script('scripts/render_btc5_health_snapshot.py', event_emitter),
        IntervalTrigger(minutes=5), id='health', replace_existing=True
    )
    scheduler.add_job(
        lambda: run_script('scripts/render_btc5_validation_cohort.py', event_emitter),
        IntervalTrigger(minutes=15), id='cohort', replace_existing=True
    )
    scheduler.add_job(
        lambda: run_script('scripts/btc5_monte_carlo.py', event_emitter),
        CronTrigger(hour=3), id='daily_monte_carlo', replace_existing=True
    )
    scheduler.add_job(
        lambda: run_script('scripts/render_btc5_filter_economics.py', event_emitter),
        IntervalTrigger(hours=1), id='filter_econ', replace_existing=True
    )
    scheduler.start()
```

## Compute Utilization

```python
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

MAX_WORKERS = max(1, multiprocessing.cpu_count() - 2)  # Leave 2 cores for UI + OS
research_pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)

# Use for parallel hypothesis backtesting
async def parallel_backtest(hypotheses: list[dict]) -> list[dict]:
    loop = asyncio.get_event_loop()
    futures = [loop.run_in_executor(research_pool, backtest_one, h) for h in hypotheses]
    return await asyncio.gather(*futures)
```

## Data Flow: VPS → Dashboard

```
VPS (Dublin, 34.244.34.108)
  btc-5min-maker.service writes to DB
       │
       │  asyncssh.scp every 30 min (scheduler job)
       ▼
Mac Local Mirror: data/btc_5min_maker_mirror.db
       │
       │  SQLite query (server/services/db.py)
       ▼
FastAPI endpoints + WebSocket events
       │
       │  WebSocket push
       ▼
React Dashboard (localhost:5173)
```

For sub-minute latency on live fills, also stream the VPS systemd journal:
```
VPS journalctl -u btc-5min-maker -f --output=json
  → asyncssh stream → parse → WebSocket → dashboard log pane
```

## Platform Data Integration

| Platform | Data | Method | Refresh |
|:---|:---|:---|:---|
| Polymarket | Fills, P&L, positions | VPS DB mirror | 30min sync |
| Polymarket | Live prices | CLOB WebSocket (from VPS relay) | Real-time |
| Kalshi | Balance, positions | REST API (direct from Mac) | 5min poll |
| Alpaca | Balance, positions | REST API (direct from Mac) | 5min poll |
| VPS | Service status | SSH systemctl | 1min poll |
| VPS | Live logs | SSH journal stream | Real-time |

## Build Order

### Phase 1: Skeleton (Day 1)
1. `npm create vite@latest console -- --template react-ts`
2. Install all frontend deps
3. Set up Tailwind + dark theme
4. Build FastAPI backend with `/api/health` endpoint
5. WebSocket connection (adapt ElastiTune `lib/socket.ts`)
6. Zustand store with SystemSnapshot type
7. TopBar, LeftRail, BottomBar shell components
8. 6 empty screen components with router

### Phase 2: P&L + Cohort (Day 2)
9. DB reader service (read local SQLite)
10. `/api/cohort` endpoint (wraps render_btc5_validation_cohort.py output)
11. PnLFrontier chart (Recharts)
12. CohortProgress bar component
13. BottomBar wired to live cohort data
14. `/api/health` wired to render_btc5_health_snapshot.py output

### Phase 3: Hypothesis Tank (Day 3)
15. HypothesisTank Canvas2D component (adapt FishTankCanvas)
16. Hypothesis data model from autoresearch_results.json
17. `/api/autoresearch/trigger` endpoint
18. ExperimentFeed component
19. Click-to-inspect detail panel in right rail

### Phase 4: VPS Integration (Day 4)
20. asyncssh VPS service
21. Journal log streaming WebSocket
22. DeployButton wired to deploy.sh
23. Service status cards
24. DB sync job + button

### Phase 5: Monte Carlo + Filters (Day 5)
25. Monte Carlo trigger endpoint
26. MonteCarloSurface heatmap (Canvas2D or D3)
27. FilterEconomics waterfall chart
28. Filter data endpoint

### Phase 6: Guidance + Scheduler (Day 6)
29. APScheduler with all 8 jobs
30. GuidanceTerminal component
31. Guidance → state/guidance/ → autoresearch injection
32. KillSwitch, PromoteButton wired
33. Full integration test

## Key Design Principles

1. **The dashboard is a window, not the engine.** The scheduler runs all loops whether the browser is open or not. The dashboard visualizes what's already happening.
2. **Canvas over DOM.** For the FishTank and Monte Carlo views, use Canvas2D like ElastiTune does. No SVG, no DOM nodes per data point. This scales to hundreds of hypotheses.
3. **WebSocket for live, REST for commands.** All streaming data goes over WebSocket. All user actions go over REST (easier to handle auth, retries, error responses).
4. **Zustand, not Redux.** ElastiTune proves this works. One store, flat structure, minimal boilerplate.
5. **orjson on the backend.** Every WebSocket message is serialized with orjson for speed.
6. **Leave 2 CPU cores free.** The dashboard and OS need headroom. Research gets everything else.
7. **VPS is the executor, Mac is the researcher.** Never run backtests on the VPS. It's too small. The Mac has the compute.

## Environment Variables

```bash
# console/server/.env
ELASTIFUND_REPO=/Users/johnbradley/Desktop/Elastifund
VPS_HOST=34.244.34.108
VPS_USER=ubuntu
VPS_KEY=~/.ssh/lightsail.pem
VPS_BOT_PATH=/home/ubuntu/polymarket-trading-bot
KALSHI_API_KEY=  # from main .env
ALPACA_API_KEY=  # from main .env
ALPACA_SECRET=   # from main .env
```

## What NOT to Build

- No auth system (local only, single user)
- No database for the dashboard itself (read from existing SQLite DBs)
- No mobile responsive layout (desktop only, optimized for 27" display)
- No light theme (dark only)
- No unit tests for the dashboard (integration test by running it)
- No Docker (runs natively on Mac)
