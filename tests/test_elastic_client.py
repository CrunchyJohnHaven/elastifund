from __future__ import annotations

import time
from dataclasses import dataclass

from bot.elastic_client import ElasticClientManager


class FakeCluster:
    def __init__(self, health_response=None, error: Exception | None = None) -> None:
        self._health_response = health_response or {"status": "green", "cluster_name": "test"}
        self._error = error

    def health(self):
        if self._error is not None:
            raise self._error
        return self._health_response


class FakeElasticsearch:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.cluster = FakeCluster()


def _wait_for(predicate, timeout: float = 1.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_disabled_client_is_a_noop():
    client = ElasticClientManager(enabled=False)

    assert client.index_trade({"market_id": "m1", "side": "BUY", "price": 0.42, "size": 10}) is False
    assert client.health_check() == {"enabled": False, "status": "disabled"}


def test_bulk_flushes_documents_and_adds_timestamp():
    flushed_actions: list[dict[str, object]] = []

    def fake_bulk(_client, actions, **kwargs):
        flushed_actions.extend(list(actions))
        return (len(flushed_actions), [])

    @dataclass
    class TradePayload:
        market_id: str
        side: str
        price: float
        size: float

    client = ElasticClientManager(
        enabled=True,
        host="127.0.0.1",
        port=9200,
        user="elastic",
        password="secret",
        flush_interval_seconds=0.05,
        max_batch_size=2,
        client_factory=FakeElasticsearch,
        bulk_helper=fake_bulk,
    )

    try:
        assert client.index_trade(TradePayload("m1", "BUY", 0.55, 12.0)) is True
        assert client.index_signal(
            {
                "signal_source": "ensemble",
                "market_id": "m1",
                "signal_value": 0.63,
                "confidence": 0.71,
            }
        ) is True
        assert _wait_for(lambda: len(flushed_actions) == 2)
    finally:
        client.close()

    assert flushed_actions[0]["_index"] == "elastifund-trades"
    assert flushed_actions[1]["_index"] == "elastifund-signals"
    assert "timestamp" in flushed_actions[0]["_source"]
    assert "timestamp" in flushed_actions[1]["_source"]


def test_health_check_reports_unavailable_cluster():
    class FailingElasticsearch(FakeElasticsearch):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.cluster = FakeCluster(error=RuntimeError("boom"))

    client = ElasticClientManager(
        enabled=True,
        client_factory=FailingElasticsearch,
        bulk_helper=lambda *_args, **_kwargs: (0, []),
    )

    try:
        result = client.health_check()
    finally:
        client.close()

    assert result["enabled"] is True
    assert result["status"] == "unavailable"
    assert result["error"] == "boom"
