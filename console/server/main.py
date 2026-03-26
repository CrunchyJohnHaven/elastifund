from __future__ import annotations
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from server.routes import health, cohort, deploy, guidance, montecarlo, filters, autoresearch
from server.scheduler import setup_scheduler, get_scheduler_status, set_broadcast, scheduler
from server.services.reports import get_health, get_cohort, get_autoresearch_results, get_active_mutation
from server.services.db import get_recent_fills, get_fill_count

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

# Active WebSocket connections
_connections: set[WebSocket] = set()


async def broadcast(event: dict[str, Any]) -> None:
    """Send an event to all active WebSocket connections."""
    if not _connections:
        return
    dead: list[WebSocket] = []
    payload = json.dumps(event)
    for ws in list(_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.discard(ws)


def _build_initial_snapshot() -> dict[str, Any]:
    return {
        'type': 'snapshot',
        'payload': {
            'health': get_health(),
            'cohort': get_cohort(),
            'autoresearch_results': get_autoresearch_results(),
            'active_mutation': get_active_mutation(),
            'recent_fills': get_recent_fills(limit=20),
            'fill_count': get_fill_count(),
            'scheduler': get_scheduler_status(),
            'snapshot_ts': datetime.now(timezone.utc).isoformat(),
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    set_broadcast(broadcast)
    setup_scheduler()
    logger.info("JJ Console backend started")
    yield
    # Shutdown
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("JJ Console backend stopped")


app = FastAPI(
    title='JJ Command Console API',
    description='Backend API for the Elastifund JJ Command Console',
    version='1.0.0',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://localhost:3000',
        'http://127.0.0.1:5173',
        'http://127.0.0.1:3000',
    ],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Include all routers
app.include_router(health.router)
app.include_router(cohort.router)
app.include_router(deploy.router)
app.include_router(guidance.router)
app.include_router(montecarlo.router)
app.include_router(filters.router)
app.include_router(autoresearch.router)


@app.get('/')
async def root():
    return {'status': 'ok', 'service': 'JJ Command Console API', 'version': '1.0.0'}


@app.websocket('/ws/live')
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    _connections.add(websocket)
    logger.info(f"WebSocket connected. Active connections: {len(_connections)}")

    try:
        # Send initial snapshot
        snapshot = _build_initial_snapshot()
        await websocket.send_text(json.dumps(snapshot))

        # Ping task to keep connection alive
        async def ping_loop():
            while True:
                await asyncio.sleep(5)
                try:
                    await websocket.send_text(json.dumps({
                        'type': 'ping',
                        'ts': datetime.now(timezone.utc).isoformat(),
                    }))
                except Exception:
                    break

        ping_task = asyncio.create_task(ping_loop())

        # Listen for client commands
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({
                        'type': 'error',
                        'payload': {'message': 'Invalid JSON'},
                    }))
                    continue

                cmd = msg.get('type', '')
                payload = msg.get('payload', {})

                if cmd == 'kill':
                    strategy = payload.get('strategy', '')
                    logger.warning(f"WS kill command received for strategy: {strategy}")
                    # Delegate to kill endpoint logic
                    from server.routes.deploy import kill_strategy
                    from server.routes.deploy import KillRequest
                    result = None
                    try:
                        import os
                        from server.config import STATE_DIR
                        kill_path = os.path.join(STATE_DIR, f'kill_{strategy}.flag')
                        with open(kill_path, 'w') as f:
                            f.write(f'shadow_only\nkilled_by=websocket\nstrategy={strategy}\n')
                        result = {'success': True, 'strategy': strategy}
                    except Exception as e:
                        result = {'success': False, 'error': str(e)}
                    await websocket.send_text(json.dumps({'type': 'kill.ack', 'payload': result}))

                elif cmd == 'deploy':
                    profile = payload.get('profile', 'shadow_fast_flow')
                    logger.info(f"WS deploy command received: profile={profile}")
                    await websocket.send_text(json.dumps({
                        'type': 'deploy.started',
                        'payload': {'profile': profile},
                    }))
                    from server.services.deployer import run_deploy
                    result = await run_deploy(profile=profile)
                    await websocket.send_text(json.dumps({'type': 'deploy.result', 'payload': result}))

                elif cmd == 'promote':
                    hypothesis_id = payload.get('hypothesis_id', '')
                    logger.info(f"WS promote command received: hypothesis_id={hypothesis_id}")
                    await websocket.send_text(json.dumps({
                        'type': 'promote.ack',
                        'payload': {'hypothesis_id': hypothesis_id, 'status': 'queued'},
                    }))

                elif cmd == 'guidance':
                    text = payload.get('text', '')
                    scope = payload.get('scope', 'general')
                    try:
                        import os
                        from server.config import STATE_DIR
                        guidance_dir = os.path.join(STATE_DIR, 'guidance')
                        os.makedirs(guidance_dir, exist_ok=True)
                        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                        filename = f'{ts}_{scope}.md'
                        path = os.path.join(guidance_dir, filename)
                        with open(path, 'w') as fh:
                            fh.write(f"# Guidance — {ts}\n\n**Scope:** {scope}\n\n{text}\n")
                        await websocket.send_text(json.dumps({
                            'type': 'guidance.ack',
                            'payload': {'success': True, 'filename': filename},
                        }))
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            'type': 'guidance.ack',
                            'payload': {'success': False, 'error': str(e)},
                        }))

                elif cmd == 'refresh':
                    snapshot = _build_initial_snapshot()
                    await websocket.send_text(json.dumps(snapshot))

                else:
                    await websocket.send_text(json.dumps({
                        'type': 'error',
                        'payload': {'message': f"Unknown command: {cmd}"},
                    }))

        finally:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        _connections.discard(websocket)
        logger.info(f"WebSocket removed. Active connections: {len(_connections)}")
