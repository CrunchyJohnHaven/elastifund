"""Shared test fixtures."""
import asyncio
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Set test env vars BEFORE any imports
os.environ["POLYMARKET_PRIVATE_KEY"] = "test_key"
os.environ["POLYMARKET_FUNDER_ADDRESS"] = "test_funder"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test.db"
os.environ["LIVE_TRADING"] = "false"
os.environ["DASHBOARD_TOKEN"] = "test_token"
# Allow paper order placement in tests (NO_TRADE_MODE guardrail is tested
# separately in test_no_trade_mode.py which manages this env var itself).
os.environ["NO_TRADE_MODE"] = "false"

from src.store.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
