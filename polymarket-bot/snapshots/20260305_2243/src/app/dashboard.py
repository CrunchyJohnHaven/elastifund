"""FastAPI dashboard for trading bot monitoring and control."""
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from src.app.dependencies import get_db_session, verify_token, get_config
from src.store.repository import Repository

logger = structlog.get_logger(__name__)

app = FastAPI(title="Polymarket Bot Dashboard", version="0.1.0")
_start_time = datetime.utcnow()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    uptime_seconds: int


class StatusResponse(BaseModel):
    """Bot status response."""
    running: bool
    positions_count: int
    estimated_pnl_usd: float
    last_heartbeat: Optional[datetime] = None
    kill_switch_enabled: bool
    last_error: Optional[str] = None


class RiskLimitsResponse(BaseModel):
    """Risk limits configuration."""
    max_position_usd: float
    max_daily_drawdown_usd: float
    max_orders_per_hour: int


class RiskLimitsUpdate(BaseModel):
    """Risk limits update request."""
    max_position_usd: Optional[float] = None
    max_daily_drawdown_usd: Optional[float] = None
    max_orders_per_hour: Optional[int] = None


class KillSwitchRequest(BaseModel):
    """Kill switch request."""
    reason: str


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if the API is running."""
    uptime = int((datetime.utcnow() - _start_time).total_seconds())
    return HealthResponse(status="ok", version="0.1.0", uptime_seconds=uptime)


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
    """Enable kill switch to pause trading."""
    await Repository.set_kill_switch(session, enabled=True)
    await Repository.create_risk_event(session, "kill_switch", req.reason, {"source": "api"})
    await session.commit()
    logger.critical("kill_switch_enabled_via_api", reason=req.reason)
    return {"status": "ok", "message": f"Kill switch enabled: {req.reason}"}


@app.post("/unkill")
async def disable_kill_switch(session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
    """Disable kill switch to resume trading."""
    await Repository.set_kill_switch(session, enabled=False)
    await Repository.create_risk_event(session, "kill_switch_disabled", "Disabled via API", {"source": "api"})
    await session.commit()
    logger.info("kill_switch_disabled_via_api")
    return {"status": "ok", "message": "Kill switch disabled"}


@app.get("/orders")
async def get_recent_orders(limit: int = Query(50, le=200), session: AsyncSession = Depends(get_db_session), _=Depends(verify_token)):
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


@app.get("/logs/tail")
async def get_log_tail(n: int = Query(100, le=1000), _=Depends(verify_token)):
    """Get last N lines of the log file."""
    log_file = os.getenv("LOG_FILE", "/tmp/polymarket_bot.log")
    if not os.path.exists(log_file):
        return {"lines": [], "total": 0}
    with open(log_file, "r") as f:
        lines = f.readlines()
    return {"lines": lines[-n:], "total": len(lines)}
