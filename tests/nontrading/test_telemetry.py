from __future__ import annotations

from pathlib import Path

from nontrading.telemetry import TelemetryBridge


def make_bridge(tmp_path: Path) -> TelemetryBridge:
    return TelemetryBridge(output_path=tmp_path / "events.jsonl")


def make_event() -> dict[str, object]:
    return {
        "event_type": "interaction",
        "timestamp": "2026-03-09T00:00:00+00:00",
        "id": "interaction-1",
        "engine": "outreach",
        "status": "queued_review",
    }


def test_format_event_builds_ecs_document(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    document = bridge.format_event(make_event())

    assert document["event"]["action"] == "interaction"
    assert document["service"]["type"] == "nontrading"
    assert TelemetryBridge.is_ecs_compatible(document)


def test_emit_writes_jsonl_document(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    document = bridge.emit(make_event())

    assert bridge.output_path.exists()
    assert TelemetryBridge.is_ecs_compatible(document)


def test_emit_appends_multiple_documents(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    bridge.emit(make_event())
    bridge.emit({**make_event(), "id": "interaction-2"})

    assert len(bridge.read_all()) == 2


def test_read_all_returns_empty_list_when_file_is_missing(tmp_path: Path) -> None:
    bridge = make_bridge(tmp_path)

    assert bridge.read_all() == []


def test_invalid_document_is_not_ecs_compatible() -> None:
    assert not TelemetryBridge.is_ecs_compatible({"event": {}})
