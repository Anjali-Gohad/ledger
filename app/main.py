"""
API entrypoint. Deliberately thin right now — Day 1-2 scope is the
data model + migrations + connection pooling. The submit/status
endpoints and the enqueue/dequeue logic (QueueManager) are Day 3-4.
"""
"""
FastAPI app. For now: just a health check that proves the connection
pool actually works, not just that the process is running.
"""

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

app = FastAPI(title="Ledger", version="0.1.0")


@app.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)):
    """
    Proves the connection pool is actually live, not just that the
    process is up. A process can be "running" while its DB pool is
    fully exhausted or pointed at a dead host — this catches that.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}





