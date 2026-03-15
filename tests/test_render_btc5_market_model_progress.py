from __future__ import annotations

import json
from pathlib import Path

from scripts.render_btc5_market_model_progress import load_records, render_progress


def _ledger_row(
    *,
    experiment_id: int,
    status: str,
    keep: bool,
    loss: float | None,
    champion_id: int | None,
    candidate_model_name: str,
) -> dict[str, object]:
    return {
        "artifact_paths": {
            "chart_svg": "research/btc5_market_model_progress.svg",
            "manifest_path": "benchmarks/btc5_market/v1/manifest.json",
            "packet_json": f"reports/autoresearch/btc5_market/packets/experiment_{experiment_id:04d}.json",
            "packet_md": f"reports/autoresearch/btc5_market/packets/experiment_{experiment_id:04d}.md",
        },
        "benchmark_id": "btc5_market_v1",
        "candidate_hash": f"hash-{experiment_id}",
        "candidate_model_name": candidate_model_name,
        "candidate_path": f"/tmp/{candidate_model_name}.py",
        "champion_id": champion_id,
        "chart_svg": "research/btc5_market_model_progress.svg",
        "decision_reason": "benchmark_failed" if status == "crash" else ("improved_frontier" if keep else "below_frontier"),
        "epoch_id": "2026-03-10T10:55:00Z__2026-03-11T15:20:00Z",
        "error": {"type": "RuntimeError", "message": "intentional test crash"} if status == "crash" else None,
        "experiment_id": experiment_id,
        "generated_at": f"2026-03-11T18:{experiment_id:02d}:00Z",
        "keep": keep,
        "loss": loss,
        "manifest_path": "benchmarks/btc5_market/v1/manifest.json",
        "metrics": {} if loss is None else {"simulator_loss": loss},
        "packet_json": f"reports/autoresearch/btc5_market/packets/experiment_{experiment_id:04d}.json",
        "packet_md": f"reports/autoresearch/btc5_market/packets/experiment_{experiment_id:04d}.md",
        "status": status,
    }


def test_renderer_emits_karpathy_style_loss_chart(tmp_path: Path) -> None:
    ledger = tmp_path / "results.jsonl"
    rows = [
        _ledger_row(experiment_id=1, status="keep", keep=True, loss=0.48, champion_id=1, candidate_model_name="baseline"),
        _ledger_row(experiment_id=2, status="discard", keep=False, loss=0.51, champion_id=1, candidate_model_name="null_result"),
        _ledger_row(experiment_id=3, status="keep", keep=True, loss=0.37, champion_id=3, candidate_model_name="improved"),
        _ledger_row(experiment_id=4, status="crash", keep=False, loss=None, champion_id=3, candidate_model_name="crash_case"),
    ]
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    output = tmp_path / "progress.svg"
    render_progress(
        load_records(ledger),
        svg_out=output,
        title="BTC5 Market-Model Benchmark Progress",
        y_label="BTC5 market-model loss (lower is better)",
    )

    svg_text = output.read_text(encoding="utf-8")
    assert "BTC5 market-model loss (lower is better)" in svg_text
    assert "discarded" in svg_text
    assert "kept" in svg_text
    assert "running best" in svg_text
    assert "crash 4" in svg_text
    assert "Experiments 4 | keeps 2 | discards 1 | crashes 1" in svg_text
    assert "rotate(-32" in svg_text
    assert "#b8b8b8" in svg_text
    assert "#1f7a3a" in svg_text


def test_renderer_renders_crash_only_ledgers_without_dropping_rows(tmp_path: Path) -> None:
    ledger = tmp_path / "results.jsonl"
    rows = [
        _ledger_row(experiment_id=1, status="crash", keep=False, loss=None, champion_id=None, candidate_model_name="broken_a"),
        _ledger_row(experiment_id=2, status="crash", keep=False, loss=None, champion_id=None, candidate_model_name="broken_b"),
    ]
    ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    output = tmp_path / "progress.svg"
    render_progress(
        load_records(ledger),
        svg_out=output,
        title="BTC5 Market-Model Benchmark Progress",
        y_label="BTC5 market-model loss (lower is better)",
    )

    svg_text = output.read_text(encoding="utf-8")
    assert "No BTC5 market-model experiments logged yet" not in svg_text
    assert "No completed loss values yet" in svg_text
    assert "crash 1" in svg_text
    assert "crash 2" in svg_text
    assert "Experiments 2 | keeps 0 | discards 0 | crashes 2" in svg_text
