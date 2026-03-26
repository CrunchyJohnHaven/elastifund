from __future__ import annotations
from fastapi import APIRouter, Query
from server.services.reports import get_cohort, get_cohort_contract
from server.services.db import get_cohort_fills

router = APIRouter()


@router.get('/api/cohort')
async def cohort_report():
    return get_cohort()


@router.get('/api/cohort/fills')
async def cohort_fills(cohort_start_ts: int = Query(default=0)):
    return get_cohort_fills(cohort_start_ts)


@router.get('/api/cohort/contract')
async def cohort_contract():
    return get_cohort_contract()
