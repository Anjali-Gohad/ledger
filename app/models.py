"""
Data model for the three tables that carry the correctness guarantees:

- jobs: the source of truth for a job's state.
- job_events: append-only audit trail — every transition gets a row,
  so "what happened to job X" is always answerable without guessing
  from mutated state.
- outbox: transactional-outbox pattern. A job's state-changing write
  and its "notify the queue" intent are committed in the SAME
  transaction, so a crash between "update DB" and "push to Redis"
  can never happen — the outbox row is either committed with the
  state change or not committed at all. A separate relay process
  (Week 2) reads unpublished outbox rows and pushes them to Redis.
"""
"""
ORM models: jobs (core table), job_events (audit trail),
outbox (transactional outbox pattern, wired up in Week 2).
"""
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(
        Enum("queued", "running", "completed", "failed", "dead_letter", "cancelled",
             name="job_status"),
        nullable=False, server_default="queued",
    )
    priority = Column(
        Enum("high", "medium", "low", name="job_priority"),
        nullable=False, server_default="medium",
    )
    payload = Column(JSONB, nullable=False)
    payload_location = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=False, unique=True)
    attempts = Column(Integer, nullable=False, server_default="0")
    max_attempts = Column(Integer, nullable=False, server_default="5")
    locked_by = Column(String, nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    lock_expires_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, server_default="false")
    tenant_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    scheduled_for = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    worker_id = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    event_metadata = Column(JSONB, nullable=False, server_default="{}")


class Outbox(Base):
    __tablename__ = "outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    published = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())