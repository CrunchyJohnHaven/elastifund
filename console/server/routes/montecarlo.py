from __future__ import annotations
import logging
from fastapi import APIRouter
from server.services.scripts import run_script
from server.services.reports import get_latest_monte_carlo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post('/api/montecarlo/run')
async def run_montecarlo():
    result = await run_script('scripts/btc5_monte_carlo.py')
    return result


@router.get('/api/montecarlo/latest')
async def latest_montecarlo():
    return get_latest_monte_carlo()
