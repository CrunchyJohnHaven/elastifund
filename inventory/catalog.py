from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


INVENTORY_ROOT = Path(__file__).resolve().parent
DATA_ROOT = INVENTORY_ROOT / "data"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _catalog_blob() -> dict[str, Any]:
    return _read_json(DATA_ROOT / "systems.json")


@lru_cache(maxsize=1)
def _runs_blob() -> dict[str, Any]:
    return _read_json(DATA_ROOT / "runs.json")


def catalog_metadata() -> dict[str, Any]:
    blob = _catalog_blob()
    return {
        "captured_at": blob["captured_at"],
        "source_artifact": blob["source_artifact"],
    }


def runs_metadata() -> dict[str, Any]:
    blob = _runs_blob()
    return {
        "as_of": blob["as_of"],
        "state": blob["state"],
    }


def list_systems() -> list[dict[str, Any]]:
    systems = copy.deepcopy(_catalog_blob()["systems"])
    return sorted(systems, key=lambda item: (item.get("tier", 99), item["name"].lower()))


def get_system(system_id: str) -> dict[str, Any] | None:
    for system in list_systems():
        if system["id"] == system_id:
            return system
    return None


def list_runs() -> list[dict[str, Any]]:
    return copy.deepcopy(_runs_blob()["runs"])


def get_run(run_id: str) -> dict[str, Any] | None:
    for run in list_runs():
        if run["id"] == run_id:
            return run
    return None
