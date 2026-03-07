"""Database configuration and session management."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import get_settings
from src.core.logging import get_logger
from src.store.models import Base

logger = get_logger(__name__)


class DatabaseManager:
    """Manages database connections and sessions."""

    _engine = None
    _async_session_factory = None

    @classmethod
    def initialize(cls) -> None:
        """Initialize database engine and session factory."""
        settings = get_settings()
        database_url = settings.database_url

        logger.info("Initializing database", url=database_url)

        # SQLite doesn't support connection pooling options
        engine_kwargs: dict = dict(echo=False, future=True)
        if "sqlite" not in database_url:
            engine_kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)

        cls._engine = create_async_engine(database_url, **engine_kwargs)

        cls._async_session_factory = sessionmaker(
            cls._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    async def init_db(cls) -> None:
        """Create all database tables."""
        if cls._engine is None:
            cls.initialize()

        logger.info("Creating database tables")
        async with cls._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        """Get an async database session context manager.

        Yields:
            AsyncSession instance
        """
        if cls._async_session_factory is None:
            cls.initialize()

        async with cls._async_session_factory() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                logger.error("Database session error", error=str(e))
                raise
            finally:
                await session.close()

    @classmethod
    async def close(cls) -> None:
        """Close database engine and connections."""
        if cls._engine is not None:
            logger.info("Closing database engine")
            await cls._engine.dispose()
            cls._engine = None
            cls._async_session_factory = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for database sessions.

    Yields:
        AsyncSession instance
    """
    async with DatabaseManager.get_session() as session:
        yield session
