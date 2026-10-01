# Task Queue Engine — Master Roadmap & Reference Doc

**Owner:** Anjali
**Goal:** Portfolio project for backend SDE roles (target: 40–50+ LPA, FAANG-tier)
**Timeline:** 4 weeks, full-time effort
**Status:** Living document — update as you build

---

## 1. What This Is

A distributed task queue (Celery/Sidekiq/SQS-class system): clients submit jobs via an API, independent worker processes pick them up and execute them asynchronously, with correctness guarantees that hold even when machines crash, networks partition, or duplicate messages arrive.

**One-sentence pitch:**
> "A distributed task queue with effectively-once execution guarantees, leader-coordinated job assignment with fencing tokens to prevent split-brain, partitioned consumer polling to avoid thundering herd, and full crash-recovery via lock leases — built to explain every tradeoff, not just hit a feature checklist."

**Repo / resume name:** `Ledger` (short form) — because the correctness story is fundamentally a bookkeeping discipline: every state transition recorded via the outbox and `job_events` audit trail, nothing lost, nothing double-applied. Long form for resume bullet: "Distributed Task Queue with Fencing-Token Leader Election and Exactly-Once Semantics."

---

## 2. Tech Stack (interview-ready justification)

| Layer | Choice | Why | Why not the alternative |
|---|---|---|---|
| API | Python + FastAPI | Async-native, Pydantic validates job payloads for free | Flask/Django fight the async worker model |
| Primary datastore | PostgreSQL | ACID needed for the outbox pattern + unique constraint for idempotency | NoSQL stores lose transactional outbox guarantees |
| Queue/broker | Redis Streams (not Lists) | Consumer groups, `XCLAIM` for crash recovery, pending-entries tracking — closer to Kafka's offset model | Lists + `BRPOPLPUSH` need hand-rolled ack/redelivery logic |
| Leader election | Redis lease (`SET NX PX`) | Mutual exclusion for one role doesn't need full consensus | Raft/etcd/ZooKeeper is over-engineering for this problem |
| HA for Redis | Redis Sentinel | Automatic failover without Cluster's operational complexity | Cluster solves sharding, a different problem than "don't lose Redis" |
| Large payloads | S3-compatible storage (MinIO locally) | Claim-check pattern — DB/Redis never holds multi-MB blobs | Inline blobs degrade throughput for everyone once payloads scale |
| Observability | OpenTelemetry + Prometheus + Grafana | Distributed tracing across the job lifecycle, not just logs | — |
| Containerization | Docker Compose | Already set up | — |
| Load testing | Locust or custom async script | Need real benchmark numbers, not estimates | — |

**Explicitly rejected (memorize why — these are common interview traps):**
- Raft/etcd/ZooKeeper — solves consensus for replicated state; you only need mutual exclusion for one role.
- Kafka instead of Redis Streams — operational overhead with no capability this project needs.
- Kubernetes — not needed to demonstrate the distributed-systems concepts this project is about.
- True exactly-once delivery — impossible in distributed systems (two generals problem). Honest framing: **at-least-once delivery + idempotent execution = effectively-once.**

---

## 3. Data Model

### `jobs` table (PostgreSQL)
```
id                UUID PRIMARY KEY
status            ENUM('queued','running','completed','failed','dead_letter','cancelled')
priority          ENUM('high','medium','low')
payload           JSONB
payload_location  TEXT NULL      -- S3 key, if payload offloaded
idempotency_key   TEXT UNIQUE NOT NULL   -- DB-enforced, not check-then-insert
attempts          INT DEFAULT 0
max_attempts      INT DEFAULT 5
locked_by         TEXT NULL      -- worker_id
locked_at         TIMESTAMPTZ NULL
lock_expires_at   TIMESTAMPTZ NULL
cancel_requested  BOOLEAN DEFAULT false
created_at        TIMESTAMPTZ DEFAULT now()
scheduled_for     TIMESTAMPTZ DEFAULT now()
started_at        TIMESTAMPTZ NULL
completed_at      TIMESTAMPTZ NULL
tenant_id         TEXT NULL      -- for per-tenant rate limiting
```

### `job_events` table (audit trail)
```
id, job_id, event_type, worker_id, timestamp, metadata JSONB
```

### `outbox` table (transactional outbox pattern)
```
id, job_id, event_type, payload JSONB, published BOOLEAN DEFAULT false, created_at
```

### Redis structures
```
leader:lease              -- SET NX PX, holds current leader instance_id + epoch
leader:epoch               -- monotonic counter, incremented on each new leader election
worker:registry (HASH)     -- worker_id -> {last_heartbeat, status, assigned_buckets}
stream:jobs:{bucket_n}     -- Redis Streams, one per partition bucket
ratelimit:{tenant_id}      -- token bucket state for per-tenant backpressure
```

---

## 4. Phase-by-Phase Roadmap (4 Weeks)

### Week 1 — Core Queue Foundation
Goal: a working single-node queue with correct crash recovery.
- Day 1–2: Job model + migrations, DB connection pooling, idempotency unique constraint (not check-then-insert)
- Day 3–4: `QueueManager` — `enqueue`, `dequeue`, `ack`, `nack`, using Redis Streams + consumer groups
- Day 5: Lock-renewal thread (TTL refresh every 20s for long-running jobs)
- Day 6–7: `job_events` table + timeline API endpoint; basic FastAPI submit/status endpoints

**Deliverable:** submit a job via API, worker picks it up, completes it, status is queryable, a crashed worker's job is reclaimed automatically.

### Week 2 — Correctness Under Failure
Goal: close the correctness gaps that make "exactly-once" claims honest.
- Day 1–2: Outbox pattern (job completion + business effect in one DB transaction; separate relay publishes)
- Day 2: Fix dual-write at enqueue — Postgres write only, relay/`LISTEN-NOTIFY` pushes to Redis Streams
- Day 3: Priority + fairness — weighted round-robin across high/medium/low streams (e.g. 5:3:1)
- Day 4: Poison-pill handling — exponential backoff with jitter, `dead_letter` at `max_attempts`
- Day 5: Graceful shutdown — catch `SIGTERM`, drain, finish in-flight job with timeout
- Day 6–7: Tests proving all of the above, including:
  - idempotency-key edge case: same key + different payload → defined 409 error, not silent accept
  - concurrent requests with same key → UNIQUE constraint handles the race
  - Redis/Postgres reconciliation: on startup, a reconciler scans for `queued` jobs in Postgres with no corresponding Redis entry and re-pushes them (explicit policy, not assumed)

**Deliverable:** duplicate submissions don't double-execute, a crash mid-enqueue doesn't lose the job, low-priority jobs don't starve, a bad job doesn't hammer a worker in a tight retry loop.

### Week 3 — Distributed Coordination at Scale
Goal: multi-node correctness.
- Day 1–2: Leader election via Redis lease, renewed every 3s
- Day 2–3: Fencing tokens — monotonic `leader_epoch`, every leader-originated write carries its epoch, stale-epoch writes rejected. Explicit test case: a reassigned "zombie" worker tries to report success after its lock expired — fencing token rejects the stale write.
- Day 4: Partitioned polling — consistent-hash job/tenant IDs into N buckets, workers own a subset
- Day 5: Jittered polling on top of partitioning
- Day 6: Backpressure — circuit breaker around downstream calls; token-bucket rate limiter per worker/tenant
- Day 7: Redis Sentinel setup; test failover manually

**Deliverable:** run 3+ workers and 2+ schedulers; kill the leader mid-run, confirm clean failover with no duplicate assignment (provable via fencing tokens in `job_events`); kill Redis primary, confirm Sentinel failover.

### Week 4 — Polish, Proof, Interview-Readiness
- Day 1: Claim-check pattern (S3/MinIO) for large payloads
- Day 2: Distributed tracing — OpenTelemetry spans submit → enqueue → dequeue → execute → complete
- Day 3: Load testing — real p50/p99 latency and throughput numbers
- Day 4: Chaos testing (manual, documented) — kill worker mid-job, kill leader, kill Redis primary; also test:
  - graceful shutdown as an actual kill test, not just a unit test
  - resource exhaustion (queue backlog behavior under sustained overload)
  - basic API-level security checklist (input validation, auth on submit endpoint)
- Day 5: README + architecture diagram, real benchmark numbers, chaos-test results
- Day 6: Rehearse the explanation out loud, unscripted, until fluent
- Day 7: Buffer — then redirect time to DSA/mock system-design interviews

**Task cancellation semantics** (build during Week 2 or 3, alongside the state machine):
- `queued` job: trivial — just don't dequeue it
- `running` job: best-effort cooperative cancellation — worker polls `cancel_requested` flag between steps; no promise of instant-kill

**Deliverable: the final project.** Stop adding scope after Week 4. Redirect remaining pre-December time to interview prep.

---

## 5. Master List of Hard Problems Solved

| # | Problem | Solution | Why this over alternatives |
|---|---|---|---|
| 1 | Exactly-once execution | At-least-once + idempotent execution via `idempotency_key` UNIQUE + transactional outbox | True exactly-once is impossible; this is the honest framing |
| 2 | Idempotency TOCTOU race | DB-level UNIQUE constraint + `ON CONFLICT`, not check-then-insert | Atomicity enforced by DB, not app logic |
| 3 | Dual-write at enqueue | Write Postgres only; relay/`LISTEN-NOTIFY` pushes to Redis | Removes the crash window between two writes |
| 4 | Leader coordination | Redis lease, renewed every 3s | Right-sized — no full Raft needed |
| 5 | Split-brain on failover | Fencing tokens (monotonic `leader_epoch`) | Rejects stale leader writes even if it hasn't noticed it lost leadership |
| 6 | Thundering herd on polling | Consistent-hash partitioned buckets | Divides load by N instead of full contention |
| 7 | Synchronized bursts within a bucket | Jittered intervals | Cheap, layers on partitioning |
| 8 | Downstream dependency failure | Circuit breaker | Fail fast instead of piling up timeouts |
| 9 | Thundering herd on recovery | Token-bucket rate limiter per worker/tenant | Prevents simultaneous recovery from overwhelming DB |
| 10 | Worker crash mid-job | Lock TTL + renewal thread | Self-healing, no manual intervention |
| 11 | Priority starvation | Weighted round-robin | Guarantees eventual low-priority execution |
| 12 | Poison-pill jobs | Exponential backoff + jitter, dead-letter at max_attempts | Prevents tight-loop hammering |
| 13 | Redis single point of failure | Redis Sentinel | HA without Cluster's complexity |
| 14 | Large payloads | Claim-check pattern | Keeps DB/Redis rows small and fast |
| 15 | Ungraceful shutdown | SIGTERM handling — drain, finish in-flight, exit | Clean deploys, not just TTL-expiry recovery |
| 16 | Lack of observability | OpenTelemetry tracing, single trace_id per job | Debuggable in production |
| 17 | Zombie worker post-reassignment | Fencing token rejects late success report from a worker whose lock already expired | Closes the gap fencing tokens exist to solve — explicit test case |
| 18 | Redis/Postgres drift after Redis dies | Startup reconciler scans Postgres for `queued` jobs missing from Redis, re-pushes them | Outbox fix reduces the window but doesn't eliminate it — needs an explicit policy |
| 19 | In-flight job cancellation | `cancel_requested` flag, cooperative check between steps | Instant-kill of a running job is a much harder problem than it looks — don't promise it |

---

## 6. Explicitly Out of Scope (say this proactively in interviews — signals judgment)

- Multi-region / geo-replication
- Job DAGs / dependencies (Airflow-style) — mention as a natural extension, don't build it
- Full recurring/cron scheduling (cron parsing, DST handling, missed-schedule backfill) — kept only the already-built single-fire `scheduled_for` delayed execution, since it was effectively free
- Full Raft implementation
- Automated chaos-engineering harness — manual, documented chaos tests are sufficient proof at this scale

---

## 7. Final Deliverable Checklist

- [ ] All 19 problems in Section 5 implemented and tested
- [ ] Real benchmark numbers in README (not estimates)
- [ ] At least 3 documented manual chaos tests with outcomes
- [ ] Architecture diagram
- [ ] 5-minute walkthrough you can give without notes
- [ ] Code typed by hand, understood line by line
- [ ] After Week 4: stop adding scope, shift to DSA + mock system-design interviews

---

*Update this doc as you build — mark phases done, note what actually changed vs. plan, log new edge cases as you discover them.*
