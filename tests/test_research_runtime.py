from __future__ import annotations

from pathlib import Path

from scripts.research_runtime import cap_for_mode, load_json_dict, normalize_mode, write_json


def test_normalize_mode_defaults_to_full() -> None:
    assert normalize_mode(None) == "full"
    assert normalize_mode("FULL") == "full"
    assert normalize_mode("unexpected") == "full"
    assert normalize_mode("analyze") == "analyze"


def test_cap_for_mode_respects_analyze_cap() -> None:
    assert cap_for_mode(5000, mode="analyze", analyze_cap=750, floor=1) == 750
    assert cap_for_mode(200, mode="analyze", analyze_cap=750, floor=1) == 200
    assert cap_for_mode(5000, mode="full", analyze_cap=750, floor=1) == 5000


def test_load_and_write_json_dict_roundtrip(tmp_path: Path) -> None:
    payload = {"status": "ok", "rows": 3}
    path = tmp_path / "payload.json"
    write_json(path, payload)
    assert load_json_dict(path) == payload
