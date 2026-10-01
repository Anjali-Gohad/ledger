"""initial schema: jobs, job_events, outbox

Revision ID: 0001
Revises:
Create Date: 2026-09-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    job_status = postgresql.ENUM(
        "queued", "running", "completed", "failed", "dead_letter", "cancelled",
        name="job_status",
    )
    job_priority = postgresql.ENUM("high", "medium", "low", name="job_priority")
    job_status.create(op.get_bind(), checkfirst=True)
    job_priority.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("priority", job_priority, nullable=False, server_default="medium"),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("payload_location", sa.String(), nullable=True),
        # THE idempotency guarantee: DB-enforced UNIQUE, not app-level
        # check-then-insert. Two concurrent inserts with the same key
        # race at the DB level and Postgres itself rejects the loser
        # with a unique_violation — there's no window where both can
        # pass a check and both insert.
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("locked_by", sa.String(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_jobs_idempotency_key", "jobs", ["idempotency_key"])
    op.create_index("ix_jobs_status_lock_expires", "jobs", ["status", "lock_expires_at"])
    op.create_index("ix_jobs_status_priority_scheduled", "jobs", ["status", "priority", "scheduled_for"])

    op.create_table(
        "job_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                   sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_metadata", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_job_events_job_id_timestamp", "job_events", ["job_id", "timestamp"])

    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                   sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_outbox_published_created", "outbox", ["published", "created_at"])


def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_table("job_events")
    op.drop_index("ix_jobs_status_priority_scheduled", table_name="jobs")
    op.drop_index("ix_jobs_status_lock_expires", table_name="jobs")
    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    op.drop_table("jobs")
    postgresql.ENUM(name="job_priority").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="job_status").drop(op.get_bind(), checkfirst=True)
