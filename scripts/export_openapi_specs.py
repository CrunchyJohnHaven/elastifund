#!/usr/bin/env python3
"""Export the current FastAPI OpenAPI specs into docs/api/.

This script intentionally exports specs from the code that exists today:

- hub/app/main.py
- polymarket-bot/src/app/dashboard.py

Run from the repo root after installing the relevant FastAPI dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_API_DIR = ROOT / "docs" / "api"
POLYMARKET_BOT_ROOT = ROOT / "polymarket-bot"


def _purge_modules(prefix: str) -> None:
    """Drop cached modules when two packages share the same top-level name."""
    for name in list(sys.modules):
        if name == prefix or name.startswith(f"{prefix}."):
            sys.modules.pop(name, None)


def _write_spec(path: Path, spec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")


def export_hub_spec() -> Path:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from hub.app.main import app

    spec = app.openapi()
    spec["info"]["description"] = (
        "OpenAPI export for the Elastifund hub gateway scaffold. "
        "This covers the current topology, health, benchmark, and Elasticsearch API-key bootstrap "
        "endpoints present in the repo."
    )
    spec["servers"] = [
        {
            "url": "http://localhost:8000",
            "description": "Default Docker Compose hub gateway port",
        },
        {
            "url": "https://hub.example.internal",
            "description": "Placeholder private-network hub host",
        },
    ]

    output = DOCS_API_DIR / "elastifund-hub.openapi.json"
    _write_spec(output, spec)
    return output


def export_dashboard_spec() -> Path:
    if str(POLYMARKET_BOT_ROOT) not in sys.path:
        sys.path.insert(0, str(POLYMARKET_BOT_ROOT))

    _purge_modules("src")

    from src.app.dashboard import app

    spec = app.openapi()
    spec["info"]["description"] = (
        "OpenAPI export for the Polymarket dashboard and control API used by the current "
        "Elastifund trading stack. Authentication behavior is documented in docs/api/README.md "
        "because the runtime uses custom FastAPI dependencies rather than OpenAPI security helpers."
    )
    spec["servers"] = [
        {
            "url": "http://localhost:8000",
            "description": "Default standalone dashboard port",
        },
        {
            "url": "http://localhost:8001",
            "description": "Suggested dashboard port when the hub gateway is also running locally",
        },
        {
            "url": "https://dashboard.example.internal",
            "description": "Placeholder private-network dashboard host",
        },
    ]

    output = DOCS_API_DIR / "polymarket-dashboard.openapi.json"
    _write_spec(output, spec)
    return output


def main() -> int:
    DOCS_API_DIR.mkdir(parents=True, exist_ok=True)

    hub_path = export_hub_spec()
    dashboard_path = export_dashboard_spec()

    print(hub_path.relative_to(ROOT))
    print(dashboard_path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
