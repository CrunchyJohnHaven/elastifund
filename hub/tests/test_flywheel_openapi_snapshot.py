from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI

from hub.app import flywheel_api


def _openapi_subset() -> dict[str, object]:
    app = FastAPI()
    app.include_router(flywheel_api.router)
    openapi = app.openapi()
    return {
        "paths": {
            path: openapi["paths"][path]
            for path in sorted(openapi["paths"])
            if path.startswith("/api/v1/flywheel/")
        },
        "schemas": {
            key: value
            for key, value in openapi.get("components", {}).get("schemas", {}).items()
            if key
            in {
                "HTTPValidationError",
                "ValidationError",
                "FlywheelTaskRecord",
                "FlywheelTaskListResponse",
                "FlywheelFindingRecord",
                "FlywheelFindingListResponse",
            }
        },
    }


def test_flywheel_openapi_snapshot_matches_fixture() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "flywheel_openapi_snapshot.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert _openapi_subset() == expected
