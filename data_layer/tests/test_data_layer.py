"""Unit tests for schema creation, migrations, and CRUD operations."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data_layer.schema import Base
from data_layer.database import init_db, db_status, vacuum
from data_layer import crud


@pytest.fixture()
def engine():
    """In-memory SQLite engine for test isolation."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.rollback()
    sess.close()


# ── Schema / migration tests ────────────────────────────────────────

class TestSchema:
    def test_all_tables_created(self, engine):
        expected = {
            "markets", "orderbook_snapshots", "trade_ticks",
            "detector_runs", "edge_cards", "opportunities",
            "experiments", "system_logs",
        }
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
            names = {r[0] for r in rows}
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_init_db_idempotent(self, engine):
        # Should not raise on second call
        Base.metadata.create_all(engine)
        Base.metadata.create_all(engine)

    def test_db_status(self, engine):
        info = db_status(engine)
        assert "tables" in info
        assert len(info["tables"]) == 8
        for count in info["tables"].values():
            assert count == 0

    def test_vacuum(self, engine):
        # Just verify it doesn't error
        vacuum(engine)


# ── Market CRUD ──────────────────────────────────────────────────────

class TestMarketCRUD:
    def test_upsert_insert(self, session):
        m = crud.upsert_market(session, "mkt_1", question="Will X happen?")
        session.commit()
        assert m.market_id == "mkt_1"
        assert m.question == "Will X happen?"

    def test_upsert_update(self, session):
        crud.upsert_market(session, "mkt_1", question="Old")
        session.commit()
        m = crud.upsert_market(session, "mkt_1", question="New")
        session.commit()
        assert m.question == "New"

    def test_get_market(self, session):
        crud.upsert_market(session, "mkt_1")
        session.commit()
        assert crud.get_market(session, "mkt_1") is not None
        assert crud.get_market(session, "mkt_999") is None

    def test_list_markets(self, session):
        for i in range(5):
            crud.upsert_market(session, f"mkt_{i}", status="active")
        crud.upsert_market(session, "mkt_closed", status="closed")
        session.commit()
        assert len(crud.list_markets(session)) == 6
        assert len(crud.list_markets(session, status="active")) == 5


# ── Orderbook CRUD ───────────────────────────────────────────────────

class TestOrderbookCRUD:
    def test_add_and_get(self, session):
        crud.add_orderbook_snapshot(
            session,
            market_id="m1", token_id="t1", best_bid=0.45, best_ask=0.55,
            spread=0.10, midpoint=0.50, bid_depth=3, ask_depth=5,
        )
        session.commit()
        rows = crud.get_orderbook_snapshots(session, "t1")
        assert len(rows) == 1
        assert rows[0].spread == 0.10


# ── Trade tick CRUD ──────────────────────────────────────────────────

class TestTradeCRUD:
    def test_add_single(self, session):
        crud.add_trade_tick(
            session, market_id="m1", token_id="t1", price=0.60, size=10.0,
        )
        session.commit()
        rows = crud.get_trade_ticks(session, "t1")
        assert len(rows) == 1

    def test_add_bulk(self, session):
        ticks = [
            {"market_id": "m1", "token_id": "t1", "price": 0.5 + i * 0.01, "size": 1.0}
            for i in range(10)
        ]
        count = crud.add_trade_ticks_bulk(session, ticks)
        session.commit()
        assert count == 10
        assert len(crud.get_trade_ticks(session, "t1")) == 10


# ── Detector run CRUD ────────────────────────────────────────────────

class TestDetectorRunCRUD:
    def test_create_and_finish(self, session):
        run = crud.create_detector_run(session, config={"threshold": 0.05})
        session.commit()
        assert run.status == "running"

        crud.finish_detector_run(
            session, run.id, status="success",
            markets_scanned=50, edges_found=3,
        )
        session.commit()
        updated = crud.get_detector_run(session, run.id)
        assert updated.status == "success"
        assert updated.markets_scanned == 50
        assert updated.finished_at is not None

    def test_list_runs(self, session):
        for _ in range(3):
            crud.create_detector_run(session)
        session.commit()
        assert len(crud.list_detector_runs(session)) == 3


# ── Edge card CRUD ───────────────────────────────────────────────────

class TestEdgeCardCRUD:
    def test_add_and_query(self, session):
        run = crud.create_detector_run(session)
        session.commit()

        crud.add_edge_card(
            session,
            market_id="m1", run_id=run.id, side="buy_yes",
            model_prob=0.80, market_price=0.55, edge=0.25,
            confidence="high", reasoning="Strong signal",
        )
        session.commit()
        cards = crud.get_edge_cards_for_run(session, run.id)
        assert len(cards) == 1
        assert cards[0].edge == 0.25

    def test_query_by_market(self, session):
        crud.add_edge_card(
            session,
            market_id="m1", side="buy_no",
            model_prob=0.30, market_price=0.55, edge=0.25,
        )
        session.commit()
        assert len(crud.get_edge_cards_for_market(session, "m1")) == 1
        assert len(crud.get_edge_cards_for_market(session, "m2")) == 0


# ── Opportunity CRUD ─────────────────────────────────────────────────

class TestOpportunityCRUD:
    def test_create_and_resolve(self, session):
        opp = crud.create_opportunity(
            session,
            market_id="m1", side="buy_yes",
            entry_price=0.55, model_prob=0.80, edge=0.25,
            position_size=2.0,
        )
        session.commit()
        assert opp.status == "open"

        crud.resolve_opportunity(session, opp.id, outcome="win", pnl=0.90)
        session.commit()
        updated = session.get(crud.Opportunity, opp.id)
        assert updated.status == "resolved"
        assert updated.pnl == 0.90

    def test_list_by_status(self, session):
        crud.create_opportunity(
            session, market_id="m1", side="buy_yes",
            entry_price=0.5, model_prob=0.7, edge=0.2,
        )
        opp2 = crud.create_opportunity(
            session, market_id="m2", side="buy_no",
            entry_price=0.6, model_prob=0.3, edge=0.3,
        )
        session.commit()
        crud.resolve_opportunity(session, opp2.id, outcome="loss", pnl=-2.0)
        session.commit()

        assert len(crud.list_opportunities(session, status="open")) == 1
        assert len(crud.list_opportunities(session, status="resolved")) == 1
        assert len(crud.list_opportunities(session)) == 2


# ── Experiment CRUD ──────────────────────────────────────────────────

class TestExperimentCRUD:
    def test_create_and_complete(self, session):
        exp = crud.create_experiment(
            session, name="prompt_v2",
            description="Test new prompt", hypothesis="Better calibration",
            parameters={"model": "haiku"},
        )
        session.commit()
        assert exp.status == "draft"

        crud.complete_experiment(
            session, exp.id, result_summary="10% better Brier",
            result_data={"brier": 0.21},
        )
        session.commit()
        updated = crud.get_experiment(session, "prompt_v2")
        assert updated.status == "completed"
        assert updated.result_data["brier"] == 0.21

    def test_unique_name(self, session):
        crud.create_experiment(session, name="exp_1")
        session.commit()
        with pytest.raises(Exception):
            crud.create_experiment(session, name="exp_1")
            session.commit()


# ── System log CRUD ──────────────────────────────────────────────────

class TestSystemLogCRUD:
    def test_log_and_query(self, session):
        crud.log(session, "INFO", "ingest", "Fetched 50 markets")
        crud.log(session, "ERROR", "detector", "Timeout", data={"url": "..."})
        session.commit()

        all_logs = crud.get_logs(session)
        assert len(all_logs) == 2

        errors = crud.get_logs(session, level="ERROR")
        assert len(errors) == 1
        assert errors[0].component == "detector"

        ingest = crud.get_logs(session, component="ingest")
        assert len(ingest) == 1
