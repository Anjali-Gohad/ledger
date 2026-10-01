"""
DB engine + session factory.

Why explicit pool_size/max_overflow instead of defaults: the default
QueuePool sizing (5 + 10 overflow) is a generic guess. For a queue
system, we know the access pattern ahead of time — many short-lived
transactions from the API process and from N worker processes, all
sharing one Postgres instance. Sizing this deliberately (and keeping
it in config.py, not hardcoded here) means we can tune it per
environment without touching code, and it forces us to think about
"what happens when the pool is exhausted" up front rather than
discovering it under load.

pool_pre_ping=True: makes the pool test a connection with a cheap
`SELECT 1` before handing it out. Without this, a connection killed
by a firewall/proxy/Postgres idle-timeout looks fine to SQLAlchemy
until you try to use it and get a broken-pipe error mid-request.
This trades a tiny bit of latency (per checkout) for not surfacing
stale-connection errors to callers.
"""
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,  # we often read attributes after commit (e.g. job.id in the response)
    autoflush=False,
)


async def get_db():
    """FastAPI dependency: one session per request, always closed."""
    async with AsyncSessionLocal() as session:
        yield session
