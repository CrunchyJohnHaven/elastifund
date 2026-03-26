from __future__ import annotations
import logging
from typing import Callable, Optional, Any, Coroutine
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from server.services.scripts import run_script

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# broadcast_fn is set by main.py on startup
_broadcast_fn: Optional[Callable[[dict], Coroutine]] = None


def set_broadcast(fn: Callable[[dict], Coroutine]) -> None:
    global _broadcast_fn
    _broadcast_fn = fn


async def _run_and_broadcast(script: str, event_type: str) -> None:
    result = await run_script(script)
    if not _broadcast_fn:
        return
    try:
        if 'health' in script:
            from server.services.reports import get_health
            await _broadcast_fn({'type': 'health.tick', 'payload': get_health()})
        elif 'cohort' in script:
            from server.services.reports import get_cohort
            await _broadcast_fn({'type': 'cohort.checkpoint', 'payload': get_cohort()})
        elif 'filter' in script:
            from server.services.reports import get_filter_economics
            await _broadcast_fn({'type': 'filter.update', 'payload': get_filter_economics()})
        else:
            await _broadcast_fn({'type': event_type, 'payload': result})
    except Exception as e:
        logger.error(f"_run_and_broadcast broadcast error: {e}")


def setup_scheduler() -> None:
    scheduler.add_job(
        lambda: _run_and_broadcast('scripts/render_btc5_health_snapshot.py', 'health.tick'),
        'interval', minutes=5, id='health', replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_and_broadcast('scripts/render_btc5_validation_cohort.py', 'cohort.checkpoint'),
        'interval', minutes=15, id='cohort', replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run_and_broadcast('scripts/render_btc5_filter_economics.py', 'filter'),
        'interval', hours=1, id='filter_econ', replace_existing=True,
    )
    scheduler.add_job(
        lambda: run_script('scripts/run_btc5_autoresearch_cycle.py'),
        'interval', hours=6, id='autoresearch', replace_existing=True,
    )
    scheduler.add_job(
        lambda: run_script('scripts/btc5_monte_carlo.py'),
        'cron', hour=3, id='daily_monte_carlo', replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler started with 5 jobs")


def get_scheduler_status() -> list[dict]:
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'next_run': str(job.next_run_time) if job.next_run_time else None,
            'trigger': str(job.trigger),
        })
    return jobs
