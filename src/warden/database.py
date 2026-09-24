"""Asynchronous SQLAlchemy engine and session construction."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

AsyncSessionFactory = async_sessionmaker[AsyncSession]


def create_database_engine(
    database_url: str,
    database_role: str | None = None,
) -> AsyncEngine:
    """Create an engine that can assume the restricted application role."""
    connect_args: dict[str, object] = {}
    if database_role is not None:
        connect_args["server_settings"] = {"role": database_role}
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
    """Create sessions whose objects remain readable after commits."""
    return async_sessionmaker(engine, expire_on_commit=False)
