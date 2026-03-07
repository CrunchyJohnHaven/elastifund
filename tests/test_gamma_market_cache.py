import pytest

from bot.gamma_market_cache import GammaMarketCache


def _market(
    market_id: str,
    outcome: str,
    *,
    tokens: str,
    question: str,
    neg_risk: bool = True,
    enable_order_book: bool = True,
) -> dict:
    return {
        "id": market_id,
        "question": question,
        "slug": market_id,
        "conditionId": f"cond-{market_id}",
        "clobTokenIds": tokens,
        "outcomes": '["Yes","No"]',
        "groupItemTitle": outcome,
        "negRisk": neg_risk,
        "enableOrderBook": enable_order_book,
        "endDate": "2026-11-03T23:59:00Z",
        "resolutionSource": "Associated Press",
    }


@pytest.mark.asyncio
async def test_gamma_cache_uses_group_item_titles_for_neg_risk_ontology() -> None:
    event = {
        "id": "evt-1",
        "slug": "who-wins",
        "title": "Who wins?",
        "category": "politics",
        "negRisk": True,
        "enableNegRisk": True,
        "markets": [
            _market("m1", "Alice", tokens='["ya","na"]', question="Will Alice win?"),
            _market("m2", "Bob", tokens='["yb","nb"]', question="Will Bob win?"),
            _market("m3", "Carol", tokens='["yc","nc"]', question="Will Carol win?"),
        ],
    }

    async def fetch(offset: int, limit: int) -> list[dict]:
        return [event] if offset == 0 else []

    cache = GammaMarketCache(
        max_pages=2,
        page_size=100,
        page_fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    queue = cache.subscribe()

    snapshot = await cache.refresh_once(force=True)
    queued = await queue.get()

    assert queued == snapshot
    assert snapshot.metrics.multi_outcome_event_count == 1
    assert snapshot.events["evt-1"].is_multi_outcome is True
    assert snapshot.events["evt-1"].executable is True

    record = snapshot.markets["m1"]
    assert record.outcome_name == "Alice"
    assert record.outcome_names == ("Alice", "Bob", "Carol")
    assert record.normalized_market.is_multi_outcome is True
    assert record.normalized_market.outcomes == ("Alice", "Bob", "Carol")
    assert snapshot.token_to_market_id["ya"] == "m1"
    assert snapshot.token_to_market_id["na"] == "m1"


@pytest.mark.asyncio
async def test_gamma_cache_blocks_incomplete_multi_outcome_event() -> None:
    event = {
        "id": "evt-2",
        "slug": "sentence-range",
        "title": "Harvey sentence range",
        "category": "politics",
        "negRisk": True,
        "enableNegRisk": True,
        "markets": [
            _market("m1", "No prison", tokens='["y1","n1"]', question="No prison time?"),
            _market("m2", "Under 5", tokens='["y2"]', question="Under 5 years?"),
            _market("m3", "5-10", tokens='["y3","n3"]', question="5-10 years?"),
        ],
    }

    async def fetch(offset: int, limit: int) -> list[dict]:
        return [event] if offset == 0 else []

    cache = GammaMarketCache(
        max_pages=2,
        page_size=100,
        page_fetcher=fetch,
        clock=lambda: 1_700_000_100.0,
    )
    snapshot = await cache.refresh_once(force=True)

    assert snapshot.metrics.incomplete_market_count == 1
    assert snapshot.events["evt-2"].is_multi_outcome is True
    assert snapshot.events["evt-2"].executable is False
    assert "incomplete_token_coverage" in snapshot.events["evt-2"].blocked_reasons
    assert "incomplete_market" in snapshot.events["evt-2"].blocked_reasons
    assert "missing_no_token" in snapshot.markets["m2"].incomplete_reasons


@pytest.mark.asyncio
async def test_gamma_cache_does_not_misclassify_threshold_ladders() -> None:
    event = {
        "id": "evt-3",
        "slug": "btc-ladder",
        "title": "BTC ladder",
        "category": "crypto",
        "negRisk": False,
        "enableNegRisk": False,
        "markets": [
            _market("m1", "March 31, 2026", tokens='["y1","n1"]', question="Will BTC be above $90,000 by March 31, 2026?", neg_risk=False),
            _market("m2", "June 30, 2026", tokens='["y2","n2"]', question="Will BTC be above $95,000 by June 30, 2026?", neg_risk=False),
            _market("m3", "December 31, 2026", tokens='["y3","n3"]', question="Will BTC be above $100,000 by December 31, 2026?", neg_risk=False),
        ],
    }

    async def fetch(offset: int, limit: int) -> list[dict]:
        return [event] if offset == 0 else []

    cache = GammaMarketCache(
        max_pages=2,
        page_size=100,
        page_fetcher=fetch,
        clock=lambda: 1_700_000_200.0,
    )
    snapshot = await cache.refresh_once(force=True)

    assert snapshot.metrics.multi_outcome_event_count == 0
    assert snapshot.events["evt-3"].is_multi_outcome is False
    assert snapshot.events["evt-3"].executable is False
