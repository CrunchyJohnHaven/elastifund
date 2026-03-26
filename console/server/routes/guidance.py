from __future__ import annotations
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from server.config import STATE_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

GUIDANCE_DIR = os.path.join(STATE_DIR, 'guidance')


class GuidanceRequest(BaseModel):
    text: str
    scope: str = 'general'


@router.post('/api/guidance')
async def save_guidance(request: GuidanceRequest):
    try:
        os.makedirs(GUIDANCE_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        filename = f'{ts}_{request.scope}.md'
        path = os.path.join(GUIDANCE_DIR, filename)
        content = f"# Guidance — {ts}\n\n**Scope:** {request.scope}\n\n{request.text}\n"
        with open(path, 'w') as f:
            f.write(content)
        logger.info(f"Guidance saved: {path}")
        return {'success': True, 'filename': filename, 'path': path}
    except Exception as e:
        logger.error(f"save_guidance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/api/guidance/history')
async def guidance_history():
    try:
        os.makedirs(GUIDANCE_DIR, exist_ok=True)
        files = sorted(
            [f for f in os.listdir(GUIDANCE_DIR) if f.endswith('.md')],
            reverse=True,
        )
        result = []
        for filename in files:
            path = os.path.join(GUIDANCE_DIR, filename)
            stat = os.stat(path)
            result.append({
                'filename': filename,
                'path': path,
                'size_bytes': stat.st_size,
                'modified_ts': stat.st_mtime,
            })
        return result
    except Exception as e:
        logger.error(f"guidance_history error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
