"""Asynchronous SQLAlchemy engine and session construction."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

AsyncSessionFactory = async_sessionmaker[AsyncSession]


def create_database_engine(database_url: str) -> AsyncEngine:
    """Create the application database engine without opening a connection."""
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
    """Create sessions whose objects remain readable after commits."""
    return async_sessionmaker(engine, expire_on_commit=False)
