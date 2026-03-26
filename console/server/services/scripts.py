from __future__ import annotations
import asyncio
import os
import logging
from server.config import REPO_ROOT

logger = logging.getLogger(__name__)


async def run_script(script_path: str, cwd: str = None) -> dict:
    full_path = os.path.join(REPO_ROOT, script_path)
    effective_cwd = cwd or REPO_ROOT
    logger.info(f"Running script: {full_path}")
    try:
        proc = await asyncio.create_subprocess_exec(
            'python3',
            full_path,
            cwd=effective_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            'script': script_path,
            'exit_code': proc.returncode,
            'stdout': stdout.decode()[-3000:],
            'stderr': stderr.decode()[-1000:],
            'success': proc.returncode == 0,
        }
    except Exception as e:
        logger.error(f"run_script({script_path}) failed: {e}")
        return {
            'script': script_path,
            'exit_code': -1,
            'stdout': '',
            'stderr': str(e),
            'success': False,
        }
