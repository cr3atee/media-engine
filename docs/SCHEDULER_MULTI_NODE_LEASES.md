# Scheduler Multi-Node Leases

## Purpose

Scheduler leases prevent two MediaEngine scheduler nodes from executing the same
registered job at the same time. The lease layer is infrastructure-only: it does
not contain marketplace, comparison, event, content, Telegram, or repository
business rules.

## Components

- `SchedulerLease` is the immutable domain contract for one active job lease.
- `SchedulerLeaseRepository` defines acquire, release, and read operations.
- `MemorySchedulerLeaseRepository` supports local demos and focused tests.
- `PostgresSchedulerLeaseRepository` performs short atomic lease transactions
  through a caller-provided async session factory.
- `SchedulerService` can optionally acquire a lease before executing a job.

## PostgreSQL Schema

Revision `0014_scheduler_leases` creates the `scheduler_leases` table with:

- `job_name` as the primary key.
- `owner_id` for the scheduler node identity.
- `acquired_at` and `expires_at` as timezone-aware timestamps.
- non-empty checks for `job_name` and `owner_id`.
- an expiry ordering check.
- an index on `expires_at` for stale lease visibility.

## Runtime Behavior

When a lease repository is configured, `SchedulerService.execute_job()`:

1. Attempts to acquire a lease for the job name.
2. Skips execution if another active owner already holds the lease.
3. Executes the existing job unchanged when the lease is acquired.
4. Releases the lease after success, failure, retry exhaustion, or timeout.
5. Records skipped executions in `JobRuntimeStatistics.lease_skips`.

Without a configured lease repository, Scheduler behavior remains unchanged.

## Current Limits

- Production bootstrap must explicitly provide a PostgreSQL lease repository to
  every Scheduler node.
- Lease TTL is fixed per `SchedulerService` instance and should be configured
  longer than the expected job retry/timeout budget.
- The lease guard prevents same-job overlap; it does not provide distributed
  rate limiting, global worker capacity, or marketplace-specific throttling.

## Verification

- Focused tests cover domain validation, memory lease lifecycle, same-job skip
  behavior, and ORM metadata.
- `scripts/demo_scheduler_leases.py` demonstrates two scheduler instances using
  one shared in-memory lease repository.
- `scripts/verify_scheduler_leases_postgres.py` verifies PostgreSQL acquire,
  conflict, release, expired recovery, and concurrent acquisition when
  `SCHEDULER_LEASE_DATABASE_URL` targets an isolated `scheduler_*` database.

## Verification Result

The first isolated PostgreSQL 17 verification passed:

- Scheduler lease verifier: `11/11`.
- Alembic `current`: `0014_scheduler_leases (head)`.
- Alembic `check`: no new upgrade operations detected.
- Alembic downgrade to `0013_marketplace_credentials`: passed.
- Alembic upgrade back to head: passed.
- Offline `upgrade head --sql`: generated successfully and includes
  `scheduler_leases`.
- Focused tests: `4 passed`.
- Full Pytest: `355 passed, 58 skipped, 1 warning`.
- Full MyPy: `342` source files, no issues.
- Focused Ruff and Ruff format check: passed.
