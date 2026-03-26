from __future__ import annotations
import os
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from server.services.deployer import run_deploy
from server.services.vps import get_vps_status, restart_service, sync_remote_db
from server.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter()


class DeployRequest(BaseModel):
    profile: str = 'shadow_fast_flow'


class KillRequest(BaseModel):
    strategy: str


@router.post('/api/deploy')
async def deploy(request: DeployRequest = DeployRequest()):
    result = await run_deploy(profile=request.profile)
    return result


@router.post('/api/vps/restart/{service}')
async def vps_restart_service(service: str):
    # Safety check: only allow known services
    allowed = {'jj-live', 'btc-5min-maker'}
    if service not in allowed:
        raise HTTPException(status_code=400, detail=f"Service '{service}' not in allowed list: {allowed}")
    result = await restart_service(service)
    return result


@router.post('/api/vps/sync-db')
async def vps_sync_db():
    local_dest = os.path.join(DATA_DIR, 'local_btc_5min_maker.db')
    result = await sync_remote_db(local_dest)
    return result


@router.get('/api/vps/status')
async def vps_status():
    return await get_vps_status()


@router.post('/api/kill')
async def kill_strategy(request: KillRequest):
    """Write shadow_only flag for a strategy as a safety kill."""
    try:
        from server.config import STATE_DIR
        kill_path = os.path.join(STATE_DIR, f'kill_{request.strategy}.flag')
        with open(kill_path, 'w') as f:
            f.write(f'shadow_only\nkilled_by=console\nstrategy={request.strategy}\n')
        logger.warning(f"Kill flag written for strategy: {request.strategy}")
        return {
            'success': True,
            'strategy': request.strategy,
            'flag_path': kill_path,
            'message': f"Kill flag written. Strategy '{request.strategy}' will run in shadow_only mode.",
        }
    except Exception as e:
        logger.error(f"kill_strategy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
