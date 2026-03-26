from __future__ import annotations
from fastapi import APIRouter
from server.services.reports import get_health, get_cohort
from server.scheduler import get_scheduler_status

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
