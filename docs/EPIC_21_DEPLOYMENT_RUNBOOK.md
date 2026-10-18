# EPIC 21 Production Deployment Runbook

## Scope

This runbook covers the production-shaped API and worker deployment boundary.
It does not provision PostgreSQL, create marketplace credentials, approve
catalog links, enable live Telegram delivery, or add business processing.

The deployment uses:

- `docker-compose.production.yml` for API, worker replicas, migration command,
  and Prometheus textfile collection;
- `docker/production.env.example` as the reviewed initial operations policy;
- PostgreSQL Scheduler leases already implemented by the application;
- `/health/ready` for API readiness;
- metrics-file freshness for worker liveness;
- `SIGTERM` and an explicit stop grace period for bounded shutdown.

## Initial Operations Policy

The values below are deployment policy, not domain defaults. They are explicit
in `docker/production.env.example` and can be changed only through an operator
review of source volume, audit requirements, and upstream latency.

| Setting | Initial value | Meaning |
| --- | ---: | --- |
| Worker replicas | 2 | Exercises cross-replica lease exclusion. |
| Marketplace polling interval | 300 seconds | One enabled-integration pass every five minutes. |
| Marketplace retry budget | 1 retry, 5-second delay | Keeps transient retry Scheduler-owned. |
| Marketplace timeout | 60 seconds per attempt | Bounds an upstream polling attempt. |
| Scheduler base lease TTL | 150 seconds | Exceeds the normal bounded job timeout budget. |
| Metrics refresh | 15 seconds | Produces a fresh liveness and collector sample. |
| Worker health maximum age | 60 seconds | Allows four refresh intervals before unhealthy. |
| Worker stop grace | 180 seconds | Exceeds retention retry/timeout budget of 125 seconds. |
| Retention interval | 86,400 seconds | One pass per day. |
| Retention age | 7,776,000 seconds | Retain 90 days of polling history. |
| Newest runs preserved | 10 per integration | Never remove the ten newest evidence rows. |
| Retention batch | 500 per tenant/pass | Keeps each tenant deletion transaction bounded. |
| Retention retries | 1 after 5 seconds | One retry remains Scheduler-owned. |
| Retention timeout | 60 seconds per attempt | Prevents unbounded cleanup execution. |

`SchedulerService` increases a lease above the base TTL when a configured
timeout/retry budget is larger. The retention job runs the existing
tenant-scoped service once for every tenant that currently owns polling
history. Each tenant remains a separate bounded transaction.

## Required Preparation

1. Copy `docker/production.env.example` to an operator-controlled environment
   file outside source control.
2. Replace `DATABASE_URL` with the production PostgreSQL URL supplied by the
   secret-management system.
3. Populate every empty API/auth value with an independent high-entropy secret.
   The committed example leaves these fields empty so Compose fails closed
   until they are supplied. Do not commit the resulting file.
4. Pin `MEDIAENGINE_IMAGE` and `NODE_EXPORTER_IMAGE` to organization-approved
   immutable digests for the target environment.
5. Keep the API and metrics bind addresses on loopback unless a reviewed load
   balancer or monitoring network owns exposure.
6. Confirm migrations and backups before deployment.

Validate interpolation without printing secrets:

```powershell
docker compose `
  --env-file C:\secure\mediaengine-production.env `
  -f docker-compose.production.yml `
  config --quiet
```

## Migration And Startup

Apply migrations as a separate one-shot operation:

```powershell
docker compose `
  --env-file C:\secure\mediaengine-production.env `
  -f docker-compose.production.yml `
  --profile operations run --rm migrate
```

Start the runtime services:

```powershell
docker compose `
  --env-file C:\secure\mediaengine-production.env `
  -f docker-compose.production.yml `
  up -d api worker metrics-collector
```

The worker replica count is declared in the Compose deployment model. An
orchestrator may override it, but every replica must share the same PostgreSQL
database and must keep Scheduler leases enabled. `SCHEDULER_OWNER_ID` is left
empty deliberately so each process receives a collision-resistant owner ID.

## Health And Metrics

- API liveness: `GET /health/live`.
- API readiness: `GET /health/ready`; it checks database access, migration
  head, and repository composition without returning credentials.
- Worker liveness: `scripts/check_worker_health.py` verifies that the
  replica-specific Prometheus file exists, contains Scheduler state, and is
  newer than the configured maximum age.
- Each worker writes `/metrics/mediaengine-worker-${HOSTNAME}.prom`, preventing
  replica overwrite in the shared textfile volume.
- The collector exposes only the textfile collector on loopback by default.
  Production Prometheus must scrape that endpoint through the reviewed
  monitoring network.
- Node exporter emits textfile modification times. Alert when a replica file is
  stale and remove stale files left by permanently deleted replicas as part of
  deployment reconciliation.

Metrics and structured alerts continue to exclude tenant names, source URLs,
credential references, raw exceptions, provider responses, and tokens.
Process-local alert acknowledgement resets on restart; the external collector
must own durable cross-replica notification state.

## Graceful Shutdown

The worker translates `SIGTERM` into its async shutdown event. It cancels the
Scheduler periodic loop, allows active repository scopes and leases to unwind,
cancels metrics and alert refresh tasks, writes final metrics, and then closes
the shared HTTP client. The configured 180-second grace period is longer than
the initial retention timeout/retry budget. Raising job timeout or retry values
requires reviewing the grace period at the same time.

The API uses Uvicorn's native termination handling and a separate 30-second
grace period.

## Failure And Rollback

- If API readiness fails, do not route traffic to the replica.
- If worker metrics become stale, replace that replica; Scheduler leases keep
  another replica from overlapping the same named job.
- A failed retention tenant transaction rolls back without affecting another
  tenant's history.
- Disabling `POLLING_RETENTION_ENABLED` removes scheduled deletion without
  changing stored history.
- Roll back the application image only after confirming that its schema is
  compatible with the already-applied Alembic revision.

## Verification

Task 5 verification includes:

- valid production Compose interpolation;
- lockfile-based, non-root Docker image build and import smoke test;
- real container `SIGTERM` with Scheduler stop, exit code `0`, and no OOM;
- `25/25` offline deployment checks, including missing-secret rejection;
- explicit retention-policy validation;
- multi-tenant memory retention through Scheduler;
- fresh/stale worker health behavior;
- focused Ruff/format and `25` Pytest checks;
- full Pytest (`523 passed, 58 skipped`) and MyPy (`448` source files).

The final production-shaped gate passed against isolated PostgreSQL `17.10`:
`scripts/verify_epic21_operations_postgres.py` completed `38/38` checks across
two worker schedulers, lease exclusion/release, durable polling outcomes,
tenant isolation, rollback, replica metrics, alert lifecycle, scheduled
retention, fresh-process restart, and graceful shutdown. It made no live
marketplace, Telegram, or AI calls. Alembic current/check, downgrade/re-upgrade,
and offline SQL generation also passed at `0017_marketplace_polling_runs`.

This verification closes EPIC 21 software readiness. It does not replace
target-environment PostgreSQL backup validation, secret delivery, collector and
alert-manager rollout, or approved credentials for authenticated sources.
