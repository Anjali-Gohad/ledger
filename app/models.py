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
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    dead_letter = "dead_letter"
    cancelled = "cancelled"


class JobPriority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.queued
    )
    priority: Mapped[JobPriority] = mapped_column(
        Enum(JobPriority, name="job_priority"), nullable=False, default=JobPriority.medium
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Set once the payload is offloaded to S3/MinIO (Week 4 claim-check
    # pattern). NULL means the payload above is the real, inline payload.
    payload_location: Mapped[str | None] = mapped_column(String, nullable=True)

    # THE core idempotency guarantee. This is a DB-level UNIQUE
    # constraint, not an app-level check-then-insert — see the
    # docstring in api/jobs.py for why that distinction matters.
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Lock ownership for whichever worker currently holds this job.
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Fast "find crashed jobs" scan: workers holding an expired
        # lock while still marked running.
        Index("ix_jobs_status_lock_expires", "status", "lock_expires_at"),
        # Fast "what's due" scan for the dequeue path.
        Index("ix_jobs_status_priority_scheduled", "status", "priority", "scheduled_for"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_job_events_job_id_timestamp", "job_id", "timestamp"),
    )


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # The relay's core query is "give me unpublished rows in order" —
        # this index makes that a cheap index scan instead of a seq scan
        # once the table has history in it.
        Index("ix_outbox_published_created", "published", "created_at"),
    )
