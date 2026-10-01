# Ledger — Distributed Task Queue with Fencing-Token Leader Election and Exactly-Once Semantics

A Celery/Sidekiq/SQS-class distributed task queue: clients submit jobs via an
API, independent worker processes execute them asynchronously, with
correctness guarantees that hold under crashes, network partitions, and
duplicate delivery.

> True exactly-once delivery is impossible in a distributed system. This
> project's honest claim is **at-least-once delivery + idempotent execution
> = effectively-once** — and every design decision below exists to make
> that claim hold up under adversarial conditions.

Status: **Week 1, Day 1-2 — data model, migrations, connection pooling.**
See `task-queue-engine-roadmap.md` for the full 4-week plan.

## Stack
FastAPI · PostgreSQL (SQLAlchemy async + Alembic) · Redis Streams · Docker Compose

## Run it

```bash
cp .env.example .env
docker compose up --build
```

Then apply migrations (from your host, with deps installed, or `docker compose exec api alembic upgrade head`):

```bash
pip install -r requirements.txt
alembic upgrade head
```

Check it's alive:
```bash
curl http://localhost:8000/healthz
```

## Local dev without Docker
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# run postgres+redis however you like, point DATABASE_URL/REDIS_URL at them
alembic upgrade head
uvicorn app.main:app --reload
```

## Project layout
```
app/
  config.py     settings, env-driven
  db.py         async engine + pooled session factory
  models.py     jobs / job_events / outbox
  main.py       FastAPI app
migrations/     Alembic, hand-authored initial schema
```
