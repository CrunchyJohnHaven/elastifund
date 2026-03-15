from __future__ import annotations

from infra.fast_json import dump_path_atomic, load_path, loads, write_text_atomic


def test_fast_json_loads_bytes_payload() -> None:
    payload = loads(b'{"asset_id":"tok-1","best_bid":0.42}')

    assert payload["asset_id"] == "tok-1"
    assert payload["best_bid"] == 0.42


def test_fast_json_loads_memoryview_payload() -> None:
    payload = loads(memoryview(b'[{"asset_id":"tok-1"},{"asset_id":"tok-2"}]'))

    assert [row["asset_id"] for row in payload] == ["tok-1", "tok-2"]


def test_fast_json_atomic_path_round_trip(tmp_path) -> None:
    target = tmp_path / "payload.json"
    dump_path_atomic(target, {"asset_id": "tok-3", "best_bid": 0.55})

    payload = load_path(target)
    assert payload["asset_id"] == "tok-3"
    assert payload["best_bid"] == 0.55


def test_write_text_atomic_round_trip(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    write_text_atomic(target, "alpha\nbeta\n")

    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"
