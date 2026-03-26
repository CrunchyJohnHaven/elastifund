from __future__ import annotations
import logging
from fastapi import APIRouter
from server.services.reports import get_autoresearch_results
from server.services.scripts import run_script

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/api/autoresearch/results')
async def autoresearch_results():
    return get_autoresearch_results()


@router.post('/api/autoresearch/trigger')
async def trigger_autoresearch():
    result = await run_script('scripts/run_btc5_autoresearch_cycle.py')
    return result
