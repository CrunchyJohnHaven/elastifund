from __future__ import annotations
import logging
from fastapi import APIRouter
from server.services.reports import get_filter_economics
from server.services.db import get_pnl_timeseries

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/api/filters')
async def filter_economics():
    return get_filter_economics()


@router.get('/api/pnl/history')
async def pnl_history():
    return get_pnl_timeseries()
