from __future__ import annotations

import logging

import pytest

from bot.anomaly_consumer import ElasticAnomalyConsumer
from bot.elastic_ml_setup import ElasticClientError
from bot.jj_live import JJLive


class FakeElasticClient:
    def __init__(self, responses: list[dict] | None = None, *, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def post(self, path: str, payload: dict):
        self.calls.append((path, payload))
        if self.error is not None:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return {"hits": {"hits": []}}


def _search_response(*records: dict) -> dict:
    return {"hits": {"hits": [{"_source": record} for record in records]}}


def test_vpin_anomaly_reduces_position_size() -> None:
    client = FakeElasticClient(
        [
            _search_response(
                {
                    "job_id": "elastifund-vpin-anomaly",
                    "timestamp": 1_710_000_000_000,
                    "record_score": 83.0,
                    "partition_field_name": "market_id",
                    "partition_field_value": "market-123",
                    "function": "high_mean",
                    "field_name": "vpin",
                    "actual": [0.92],
                    "typical": [0.38],
                    "is_interim": False,
                    "result_type": "record",
                }
            )
        ]
    )
    consumer = ElasticAnomalyConsumer(
        client=client,
        enabled=True,
        caution_hold_seconds=3600,
    )

    records = consumer.poll_once()

    assert len(records) == 1
    feedback = consumer.get_market_feedback("market-123")
    assert feedback["paused"] is False
    assert feedback["score"] == 83.0
    assert feedback["size_multiplier"] == pytest.approx(0.17)


def test_spread_anomaly_pauses_market() -> None:
    client = FakeElasticClient(
        [
            _search_response(
                {
                    "job_id": "elastifund-spread-anomaly",
                    "timestamp": 1_710_000_000_000,
                    "record_score": 91.0,
                    "partition_field_name": "market_id",
                    "partition_field_value": "market-456",
                    "function": "high_mean",
                    "field_name": "spread_bps",
                    "actual": [94.0],
                    "typical": [18.0],
                    "is_interim": False,
                    "result_type": "record",
                }
            )
        ]
    )
    consumer = ElasticAnomalyConsumer(
        client=client,
        enabled=True,
        market_pause_seconds=120,
    )

    consumer.poll_once()

    assert consumer.is_market_paused("market-456") is True
    assert "spread anomaly" in consumer.pause_reason("market-456")


def test_ml_api_failure_is_non_fatal(caplog) -> None:
    client = FakeElasticClient(
        error=ElasticClientError("Elasticsearch request failed: status=503 method=POST path=/.ml-anomalies-*/_search")
    )
    consumer = ElasticAnomalyConsumer(client=client, enabled=True)

    with caplog.at_level(logging.WARNING, logger="JJ.elastic_ml"):
        records = consumer.poll_once()

    assert records == []
    assert "Elastic ML poll failed (non-fatal)" in caplog.text


def test_jj_live_hook_applies_elastic_ml_size_modifier() -> None:
    class DummyConsumer:
        def get_market_feedback(self, market_id: str) -> dict:
            return {
                "market_id": market_id,
                "size_multiplier": 0.2,
                "score": 80.0,
                "jobs": ["elastifund-vpin-anomaly"],
                "paused": False,
                "pause_reason": "",
            }

    live = JJLive.__new__(JJLive)
    live.anomaly_consumer = DummyConsumer()

    signal: dict = {}
    adjusted = live._apply_elastic_ml_size_modifier(
        signal,
        market_id="market-789",
        size_usd=10.0,
    )

    assert adjusted == pytest.approx(2.0)
    assert signal["elastic_ml_score"] == 80.0
    assert signal["elastic_ml_jobs"] == ["elastifund-vpin-anomaly"]
