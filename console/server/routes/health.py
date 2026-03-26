from __future__ import annotations
import os
import platform
from datetime import datetime, timezone
from fastapi import APIRouter
from server.services.reports import get_health, get_cohort
from server.scheduler import get_scheduler_status
from server.config import REPO_ROOT, DATA_DIR

router = APIRouter()


@router.get('/api/health')
async def health_snapshot():
    return get_health()


@router.get('/api/health/full')
async def health_full():
    return {
        'health': get_health(),
        'cohort': get_cohort(),
        'scheduler': get_scheduler_status(),
    }


@router.get('/api/scheduler')
async def scheduler_status():
    return get_scheduler_status()


@router.get('/api/system/info')
async def system_info():
    return {
        'hostname': platform.node(),
        'platform': platform.system(),
        'repo_root': REPO_ROOT,
        'db_exists': os.path.exists(os.path.join(DATA_DIR, 'btc_5min_maker.db')),
        'python_version': platform.python_version(),
        'local_time': datetime.now(timezone.utc).isoformat(),
        'mode': 'local',
    }
