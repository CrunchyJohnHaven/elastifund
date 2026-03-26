from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from server.config import REPO_ROOT

logger = logging.getLogger(__name__)


async def run_deploy(profile: str = 'shadow_fast_flow') -> dict:
    logger.info(f"Starting deploy with profile={profile}")
    try:
        proc = await asyncio.create_subprocess_exec(
            './scripts/deploy.sh',
            '--clean-env',
            '--profile', profile,
            '--restart',
            '--btc5',
            cwd=REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            'exit_code': proc.returncode,
            'profile': profile,
            'stdout': stdout.decode()[-5000:],
            'stderr': stderr.decode()[-2000:],
            'success': proc.returncode == 0,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"run_deploy failed: {e}")
        return {
            'exit_code': -1,
            'profile': profile,
            'stdout': '',
            'stderr': str(e),
            'success': False,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
