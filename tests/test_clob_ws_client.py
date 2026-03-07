import json

import pytest

from bot.clob_ws_client import CLOBWebSocketClient, TokenBook404Error


def _book_message(token_id: str, *, bid: float, ask: float, ts: float = 100.0) -> str:
    return json.dumps(
        {
            "event_type": "book",
            "asset_id": token_id,
            "timestamp": ts,
            "bids": [{"price": f"{bid:.3f}", "size": "100"}],
            "asks": [{"price": f"{ask:.3f}", "size": "120"}],
        }
    )


@pytest.mark.asyncio
async def test_clob_client_dedupes_duplicate_snapshots() -> None:
    clock = [100.0]
    client = CLOBWebSocketClient(clock=lambda: clock[0], stale_book_seconds=30.0)
    client.sync_tokens({"tok-1": "market-1"})
    queue = client.subscribe_books(maxsize=4)

    raw = _book_message("tok-1", bid=0.42, ask=0.44, ts=95.0)
    await client._handle_message(raw)
    await client._handle_message(raw)

    first = queue.get_nowait()
    assert first.token_id == "tok-1"
    assert queue.empty()

    metrics = client.get_metrics()
    assert metrics["message_count"] == 2
    assert metrics["deduped_snapshot_count"] == 1


@pytest.mark.asyncio
async def test_clob_client_marks_books_stale_and_reports_freshness() -> None:
    clock = [100.0]
    client = CLOBWebSocketClient(clock=lambda: clock[0], stale_book_seconds=5.0)
    client.sync_tokens({"tok-1": "market-1"})

    await client._handle_message(_book_message("tok-1", bid=0.40, ask=0.43, ts=99.0))
    assert client.get_book("tok-1") is not None
    assert client.get_market_freshness()["market-1"] == pytest.approx(0.0)

    clock[0] = 107.0
    dropped = client.sweep_stale_books()

    assert dropped == 1
    assert client.get_book("tok-1") is None
    assert client.get_token_state("tok-1").status == "stale"
    metrics = client.get_metrics()
    assert metrics["stale_book_drop_count"] == 1
    assert metrics["per_market_freshness"]["market-1"] == pytest.approx(7.0)


@pytest.mark.asyncio
async def test_clob_client_quarantines_404_tokens_and_retries_slowly() -> None:
    clock = [100.0]
    calls: list[tuple[str, float]] = []

    async def fetch_book(token_id: str):
        calls.append((token_id, clock[0]))
        if len(calls) == 1:
            raise TokenBook404Error(token_id)
        return {
            "asset_id": token_id,
            "timestamp": "100000",
            "bids": [{"price": "0.33", "size": "50"}],
            "asks": [{"price": "0.35", "size": "60"}],
        }

    client = CLOBWebSocketClient(
        rest_book_fetcher=fetch_book,
        clock=lambda: clock[0],
        stale_book_seconds=30.0,
        quarantine_retry_seconds=20.0,
    )
    client.sync_tokens({"tok-404": "market-404"})

    await client.bootstrap_tokens(["tok-404"])
    assert client.get_book("tok-404", require_fresh=False) is None
    assert client.get_token_state("tok-404").status == "quarantined"
    assert client.get_metrics()["token_404_count"] == 1

    clock[0] = 110.0
    await client.retry_quarantined_tokens()
    assert len(calls) == 1

    clock[0] = 121.0
    await client.retry_quarantined_tokens()
    assert len(calls) == 2
    assert client.get_book("tok-404") is not None
    assert client.get_token_state("tok-404").status == "active"
    assert client.get_metrics()["quarantined_tokens"] == {}
