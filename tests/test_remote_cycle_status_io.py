from __future__ import annotations

from pathlib import Path

from scripts import remote_cycle_status_io as io_helpers


def test_load_json_returns_default_for_missing_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    fallback = {"ok": False}
    assert io_helpers.load_json(path, default=fallback) == fallback


def test_load_json_returns_default_for_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{bad", encoding="utf-8")
    fallback = {"ok": False}
    assert io_helpers.load_json(path, default=fallback) == fallback


def test_load_jsonl_rows_filters_invalid_and_non_object_lines(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"a":1}',
                "",
                "not-json",
                "[]",
                '{"b":2}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert io_helpers.load_jsonl_rows(path) == [{"a": 1}, {"b": 2}]


def test_fetch_json_url_decodes_payload(monkeypatch) -> None:
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"ok":true,"n":3}'

    monkeypatch.setattr(io_helpers.urllib.request, "urlopen", lambda *args, **kwargs: _Resp())
    payload = io_helpers.fetch_json_url("https://example.test/payload")
    assert payload == {"ok": True, "n": 3}
