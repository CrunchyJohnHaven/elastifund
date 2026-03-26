from __future__ import annotations
import os
import logging
from datetime import datetime, timezone
from typing import Any
from server.config import VPS_HOST, VPS_USER, VPS_KEY, VPS_BOT_PATH

logger = logging.getLogger(__name__)


async def check_service_status(service: str) -> dict[str, Any]:
    try:
        import asyncssh
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY],
            known_hosts=None,
        ) as conn:
            result = await conn.run(f'systemctl is-active {service}', check=False)
            status = result.stdout.strip()
            uptime_result = await conn.run(
                f'systemctl show {service} --property=ActiveEnterTimestamp',
                check=False,
            )
            return {
                'service': service,
                'status': status,
                'uptime_info': uptime_result.stdout.strip(),
            }
    except Exception as e:
        logger.warning(f"check_service_status({service}) failed: {e}")
        return {'service': service, 'status': 'unknown', 'error': str(e)}


async def get_vps_status() -> dict[str, Any]:
    jj = await check_service_status('jj-live')
    btc = await check_service_status('btc-5min-maker')
    return {
        'jj_live': jj.get('status', 'unknown'),
        'jj_live_detail': jj,
        'btc_5min_maker': btc.get('status', 'unknown'),
        'btc_5min_maker_detail': btc,
        'last_check': datetime.now(timezone.utc).isoformat(),
    }


async def sync_remote_db(local_dest: str) -> dict[str, Any]:
    try:
        import asyncssh
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY],
            known_hosts=None,
        ) as conn:
            await asyncssh.scp(
                (conn, f'{VPS_BOT_PATH}/data/btc_5min_maker.db'),
                local_dest,
            )
            size = os.path.getsize(local_dest)
            return {'success': True, 'size_bytes': size, 'dest': local_dest}
    except Exception as e:
        logger.error(f"sync_remote_db failed: {e}")
        return {'success': False, 'error': str(e)}


async def restart_service(service: str) -> dict[str, Any]:
    try:
        import asyncssh
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY],
            known_hosts=None,
        ) as conn:
            result = await conn.run(f'sudo systemctl restart {service}', check=False)
            return {
                'success': result.exit_status == 0,
                'service': service,
                'output': result.stdout.strip(),
                'stderr': result.stderr.strip(),
            }
    except Exception as e:
        logger.error(f"restart_service({service}) failed: {e}")
        return {'success': False, 'service': service, 'error': str(e)}
