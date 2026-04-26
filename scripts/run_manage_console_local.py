#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import uvicorn


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local manage console as a single FastAPI app with UI and operator API on one port."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8130, help="Bind port. Default: 8130")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn autoreload.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    from hub.app.manage_console_local import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
