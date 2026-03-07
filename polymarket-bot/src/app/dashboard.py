"""FastAPI dashboard for trading bot monitoring and control.

Includes:
- Static HTML dashboard at GET / with Chart.js equity curve
- REST API endpoints for status, metrics, risk, orders, kill switch
- GET /api/equity-curve for daily portfolio snapshots
- Basic auth (DASHBOARD_USER/DASHBOARD_PASS) + token auth
"""
import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from src.app.dependencies import get_db_session, verify_token, get_config
from src.store.repository import Repository

logger = structlog.get_logger(__name__)

app = FastAPI(title="Polymarket Bot Dashboard", version="0.2.0")
_start_time = datetime.utcnow()


# ---------------------------------------------------------------------------
# Basic Auth dependency
# ---------------------------------------------------------------------------

async def verify_basic_auth(request: Request) -> bool:
    """Check basic auth if DASHBOARD_USER/DASHBOARD_PASS are set."""
    settings = get_config()
    if not settings.dashboard_user or not settings.dashboard_pass:
        return True  # No basic auth configured — fall through

    import base64
    auth_header = request.headers.get("authorization", "")

    # Accept Bearer token auth as alternative
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        if token == settings.dashboard_token:
            return True
        raise HTTPException(status_code=401, detail="Invalid token")

    if not auth_header.lower().startswith("basic "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic realm=\"Polymarket Bot\""},
        )

    try:
        decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode()
        user, passwd = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid auth header")

    if not (
        secrets.compare_digest(user, settings.dashboard_user)
        and secrets.compare_digest(passwd, settings.dashboard_pass)
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic realm=\"Polymarket Bot\""},
        )

    return True


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: int

class StatusResponse(BaseModel):
    running: bool
    positions_count: int
    estimated_pnl_usd: float
    last_heartbeat: Optional[datetime] = None
    kill_switch_enabled: bool
    last_error: Optional[str] = None

class RiskLimitsResponse(BaseModel):
    max_position_usd: float
    max_daily_drawdown_usd: float
    max_orders_per_hour: int

class RiskLimitsUpdate(BaseModel):
    max_position_usd: Optional[float] = None
    max_daily_drawdown_usd: Optional[float] = None
    max_orders_per_hour: Optional[int] = None

class KillSwitchRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Static HTML Dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Predictive Alpha Fund — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace;background:#0d1117;color:#c9d1d9;padding:20px}
h1{color:#58a6ff;margin-bottom:20px;font-size:1.5rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card h3{color:#8b949e;font-size:0.75rem;text-transform:uppercase;margin-bottom:8px}
.card .value{font-size:1.5rem;font-weight:700;color:#f0f6fc}
.card .value.green{color:#3fb950}
.card .value.red{color:#f85149}
.card .value.yellow{color:#d29922}
.chart-container{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:24px}
table{width:100%;border-collapse:collapse;font-size:0.85rem}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #21262d}
th{color:#8b949e;font-weight:600;text-transform:uppercase;font-size:0.7rem}
td{color:#c9d1d9}
.status-badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.7rem;font-weight:600}
.status-ok{background:#238636;color:#fff}
.status-killed{background:#da3633;color:#fff}
.status-pending{background:#d29922;color:#000}
#last-updated{color:#484f58;font-size:0.75rem;margin-top:16px}
</style>
</head>
<body>
<h1>Predictive Alpha Fund &mdash; Live Dashboard</h1>

<div class="grid" id="cards">
  <div class="card"><h3>Portfolio Value</h3><div class="value" id="portfolio-value">—</div></div>
  <div class="card"><h3>Realized P&amp;L</h3><div class="value" id="realized-pnl">—</div></div>
  <div class="card"><h3>Unrealized P&amp;L</h3><div class="value" id="unrealized-pnl">—</div></div>
  <div class="card"><h3>Win Rate (last 50)</h3><div class="value" id="win-rate">—</div></div>
  <div class="card"><h3>Open Positions</h3><div class="value" id="open-positions">—</div></div>
  <div class="card"><h3>System Status</h3><div class="value" id="system-status">—</div></div>
</div>

<div class="chart-container">
  <canvas id="equityChart" height="80"></canvas>
</div>

<div class="card" style="overflow-x:auto">
  <h3 style="margin-bottom:12px">Recent Trades</h3>
  <table>
    <thead><tr><th>Time</th><th>Market</th><th>Side</th><th>Entry</th><th>Size</th><th>Status</th></tr></thead>
    <tbody id="trades-body"><tr><td colspan="6" style="text-align:center">Loading...</td></tr></tbody>
  </table>
</div>

<div id="last-updated"></div>

<script>
let chart = null;

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(resp.status);
  return resp.json();
}

function fmtUSD(v) { return (v >= 0 ? '+' : '') + '$' + v.toFixed(2); }

async function refresh() {
  try {
    const [statusData, equityData, ordersData] = await Promise.all([
      fetchJSON('/api/dashboard-data'),
      fetchJSON('/api/equity-curve'),
      fetchJSON('/api/recent-trades'),
    ]);

    // Cards
    const pv = document.getElementById('portfolio-value');
    pv.textContent = '$' + statusData.total_value.toFixed(2);

    const rp = document.getElementById('realized-pnl');
    rp.textContent = fmtUSD(statusData.realized_pnl);
    rp.className = 'value ' + (statusData.realized_pnl >= 0 ? 'green' : 'red');

    const up = document.getElementById('unrealized-pnl');
    up.textContent = fmtUSD(statusData.unrealized_pnl);
    up.className = 'value ' + (statusData.unrealized_pnl >= 0 ? 'green' : 'red');

    const wr = document.getElementById('win-rate');
    if (statusData.win_rate !== null) {
      wr.textContent = statusData.win_rate.toFixed(1) + '%';
    } else {
      wr.textContent = 'N/A';
    }

    document.getElementById('open-positions').textContent = statusData.open_positions;

    const ss = document.getElementById('system-status');
    if (statusData.kill_switch) {
      ss.innerHTML = '<span class="status-badge status-killed">KILLED</span>';
    } else {
      ss.innerHTML = '<span class="status-badge status-ok">RUNNING</span>';
    }

    // Equity chart
    if (equityData.dates && equityData.dates.length > 0) {
      const ctx = document.getElementById('equityChart').getContext('2d');
      if (chart) chart.destroy();
      chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: equityData.dates,
          datasets: [{
            label: 'Portfolio Value ($)',
            data: equityData.values,
            borderColor: '#58a6ff',
            backgroundColor: 'rgba(88,166,255,0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { labels: { color: '#8b949e' } } },
          scales: {
            x: { ticks: { color: '#484f58' }, grid: { color: '#21262d' } },
            y: { ticks: { color: '#484f58', callback: v => '$' + v }, grid: { color: '#21262d' } },
          }
        }
      });
    }

    // Trades table
    const tbody = document.getElementById('trades-body');
    if (ordersData.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center">No trades yet</td></tr>';
    } else {
      tbody.innerHTML = ordersData.map(o => `<tr>
        <td>${o.created_at.replace('T',' ').slice(0,16)}</td>
        <td title="${o.market_id}">${o.market_id.slice(0,12)}...</td>
        <td>${o.side}</td>
        <td>$${o.price.toFixed(4)}</td>
        <td>$${o.size.toFixed(2)}</td>
        <td><span class="status-badge ${o.status==='FILLED'?'status-ok':o.status==='CANCELLED'?'status-killed':'status-pending'}">${o.status}</span></td>
      </tr>`).join('');
    }

    document.getElementById('last-updated').textContent = 'Last updated: ' + new Date().toLocaleString();
  } catch(e) {
    console.error('Dashboard refresh error:', e);
  }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(_=Depends(verify_basic_auth)):
    """Serve the static HTML dashboard."""
    return DASHBOARD_HTML


@app.get("/api/dashboard-data")
async def dashboard_data(session: AsyncSession = Depends(get_db_session), _=Depends(verify_basic_auth)):
    """Aggregated dashboard data for the web UI."""
    bot_state = await Repository.get_or_create_bot_state(session)
    positions = await Repository.get_all_positions(session)
    realized = sum(p.realized_pnl for p in positions)
    unrealized = sum(p.unrealized_pnl for p in positions)
    total_exposure = sum(p.size * p.avg_entry_price for p in positions)

    settings = get_config()
    cash = max(0, settings.max_position_usd - total_exposure)
    total_value = cash + total_exposure + unrealized

    return {
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "open_positions": len(positions),
        "kill_switch": bot_state.kill_switch,
        "last_heartbeat": bot_state.last_heartbeat.isoformat() if bot_state.last_heartbeat else None,
        "last_error": bot_state.last_error,
        "win_rate": None,  # Populated once we have enough resolved trades
    }


@app.get("/api/equity-curve")
async def equity_curve(session: AsyncSession = Depends(get_db_session), _=Depends(verify_basic_auth)):
    """Return daily portfolio snapshots for Chart.js equity curve."""
    snapshots = await Repository.get_equity_curve(session)
    return {
        "dates": [s.date for s in snapshots],
        "values": [round(s.total_value_usd, 2) for s in snapshots],
        "realized_pnl": [round(s.realized_pnl, 2) for s in snapshots],
    }


@app.get("/api/recent-trades")
async def recent_trades(
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_db_session),
    _=Depends(verify_basic_auth),
):
    """Get last N trades for the dashboard table."""
    orders = await Repository.get_recent_orders(session, limit=limit)
    return [
        {
            "id": o.id,
            "market_id": o.market_id,
            "token_id": o.token_id,
            "side": o.side,
            "price": o.price,
            "size": o.size,
            "filled_size": o.filled_size,
            "status": o.status,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]


# ---------------------------------------------------------------------------
# Existing API endpoints (kept unchanged)
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if the API is running."""
    uptime = int((datetime.utcnow() - _start_time).total_seconds())
    return HealthResponse(status="ok", version="0.2.0", uptime_seconds=uptime)


@app.get("/status", response_model=StatusResponse)
async def get_status(session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
    """Get current bot status."""
    try:
        bot_state = await Repository.get_or_create_bot_state(session)
        positions = await Repository.get_all_positions(session)
        pnl = sum(p.unrealized_pnl + p.realized_pnl for p in positions)
        return StatusResponse(
            running=bot_state.is_running,
            positions_count=len(positions),
            estimated_pnl_usd=pnl,
            last_heartbeat=bot_state.last_heartbeat,
            kill_switch_enabled=bot_state.kill_switch,
            last_error=bot_state.last_error,
        )
    except Exception as e:
        logger.error("status_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics(session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
    """Get bot metrics and statistics."""
    bot_state = await Repository.get_or_create_bot_state(session)
    positions = await Repository.get_all_positions(session)
    orders = await Repository.get_open_orders(session)
    uptime = int((datetime.utcnow() - _start_time).total_seconds())
    return {
        "order_count": len(orders),
        "position_count": len(positions),
        "uptime_seconds": uptime,
        "last_heartbeat": bot_state.last_heartbeat.isoformat() if bot_state.last_heartbeat else None,
        "kill_switch": bot_state.kill_switch,
        "last_error": bot_state.last_error,
    }


@app.get("/risk", response_model=RiskLimitsResponse)
async def get_risk_limits(_=Depends(verify_token)):
    """Get current risk limits."""
    settings = get_config()
    return RiskLimitsResponse(
        max_position_usd=settings.max_position_usd,
        max_daily_drawdown_usd=settings.max_daily_drawdown_usd,
        max_orders_per_hour=settings.max_orders_per_hour,
    )


@app.put("/risk", response_model=RiskLimitsResponse)
async def update_risk_limits(update: RiskLimitsUpdate, _=Depends(verify_token)):
    """Update risk limits (NOTE: changes only affect this process instance)."""
    settings = get_config()
    if update.max_position_usd is not None:
        settings.max_position_usd = update.max_position_usd
    if update.max_daily_drawdown_usd is not None:
        settings.max_daily_drawdown_usd = update.max_daily_drawdown_usd
    if update.max_orders_per_hour is not None:
        settings.max_orders_per_hour = update.max_orders_per_hour
    logger.info("risk_limits_updated", max_pos=settings.max_position_usd, max_dd=settings.max_daily_drawdown_usd)
    return RiskLimitsResponse(
        max_position_usd=settings.max_position_usd,
        max_daily_drawdown_usd=settings.max_daily_drawdown_usd,
        max_orders_per_hour=settings.max_orders_per_hour,
    )


@app.post("/kill")
async def enable_kill_switch(req: KillSwitchRequest, session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
    """Enable kill switch: pause trading AND cancel all open orders."""
    await Repository.set_kill_switch(session, enabled=True)
    await Repository.create_risk_event(session, "kill_switch", req.reason, {"source": "api"})
    await session.commit()
    logger.critical("kill_switch_enabled_via_api", reason=req.reason)

    cancelled_count = 0
    try:
        from src.broker.polymarket_broker import PolymarketBroker, PolymarketBrokerConfig
        from src.core.config import get_settings as _get_settings
        settings = _get_settings()
        if settings.live_trading:
            config = PolymarketBrokerConfig(
                live_trading=True,
                private_key=settings.effective_private_key,
                user_address=settings.effective_funder_address,
                api_key=settings.polymarket_api_key,
                api_secret=settings.polymarket_api_secret,
                api_passphrase=settings.polymarket_api_passphrase,
                chain_id=settings.chain_id,
                signature_type=settings.signature_type,
                clob_url=settings.polymarket_clob_url,
            )
            broker = PolymarketBroker(config)
            cancelled_count = await broker.cancel_all_open_orders()
            logger.info("kill_orders_cancelled", count=cancelled_count)
    except Exception as e:
        logger.error("kill_cancel_orders_failed", error=str(e))

    try:
        from src.telegram import TelegramNotifier
        notifier = TelegramNotifier()
        if notifier.is_configured:
            await notifier.send_kill_switch(reason=req.reason, cancelled_orders=cancelled_count)
            await notifier.close()
    except Exception as e:
        logger.error("kill_telegram_failed", error=str(e))

    return {
        "status": "ok",
        "message": f"Kill switch enabled: {req.reason}",
        "orders_cancelled": cancelled_count,
    }


@app.post("/unkill")
async def disable_kill_switch(session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
    """Disable kill switch to resume trading."""
    success, message = await Repository.clear_kill_switch(session)
    if not success:
        logger.warning("unkill_blocked_cooldown", message=message)
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=message)

    await Repository.create_risk_event(
        session, "kill_switch_disabled", "Disabled via API after cooldown", {"source": "api"},
    )
    await session.commit()
    logger.info("kill_switch_disabled_via_api")
    return {"status": "ok", "message": "Kill switch disabled (cooldown expired)"}


@app.get("/orders")
async def get_recent_orders_api(limit: int = Query(50, le=200), session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
    """Get recent open orders."""
    orders = await Repository.get_open_orders(session)
    return [
        {
            "id": o.id, "market_id": o.market_id, "token_id": o.token_id,
            "side": o.side, "price": o.price, "size": o.size,
            "filled_size": o.filled_size, "status": o.status,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders[:limit]
    ]


@app.get("/execution")
async def get_execution_stats(
    limit: int = Query(100, le=500),
    sandbox_only: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
    _=Depends(verify_token),
):
    """Get execution quality metrics."""
    summary = await Repository.get_execution_summary(session)
    recent = await Repository.get_execution_stats(
        session, limit=limit, maker_sandbox_only=sandbox_only,
    )
    return {
        "summary": summary,
        "recent": [
            {
                "id": s.id, "order_id": s.order_id, "market_id": s.market_id,
                "token_id": s.token_id, "side": s.side, "quoted_mid": s.quoted_mid,
                "order_price": s.order_price, "fill_price": s.fill_price,
                "expected_fee": s.expected_fee, "actual_fee": s.actual_fee,
                "expected_edge": round(s.expected_edge, 6),
                "slippage_vs_mid": round(s.slippage_vs_mid, 6) if s.slippage_vs_mid is not None else None,
                "fill_time_seconds": round(s.fill_time_seconds, 3) if s.fill_time_seconds is not None else None,
                "was_filled": s.was_filled, "was_cancelled": s.was_cancelled,
                "cancel_reason": s.cancel_reason, "execution_mode": s.execution_mode,
                "is_maker_sandbox": s.is_maker_sandbox, "created_at": s.created_at.isoformat(),
            }
            for s in recent
        ],
    }


@app.get("/logs/tail")
async def get_log_tail(n: int = Query(100, le=1000), _=Depends(verify_token)):
    """Get last N lines of the log file."""
    log_file = os.getenv("LOG_FILE", "/tmp/polymarket_bot.log")
    if not os.path.exists(log_file):
        return {"lines": [], "total": 0}
    with open(log_file, "r") as f:
        lines = f.readlines()
    return {"lines": lines[-n:], "total": len(lines)}
