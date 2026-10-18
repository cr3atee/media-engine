# EPIC 21 - Production Operations Readiness

## Status

Tasks 1 through 4 are implemented and verified. Deployment configuration and
the final production-shaped operations gate remain separate tasks.

## Goal

Make the verified worker observable and operable in production without moving
marketplace, matching, persistence, event, or content business logic into the
operations layer.

## Task 1 - Worker Metrics Export

Delivered:

- Dependency-free Prometheus text exposition generated from existing
  `RuntimeProcess` Scheduler state and the latest
  `MarketplaceIntegrationExecutionBatch`.
- Process-local Scheduler counters for executions, successes, failures,
  retries, and multi-node lease skips.
- Latest-batch integration outcome gauges plus per-marketplace offer, snapshot,
  price-change, event, and non-fatal processing-error gauges.
- Low-cardinality labels limited to stable job, state, marketplace, and outcome
  values. Tenant IDs, integration IDs, source URLs, credential references,
  query strings, and error summaries are omitted.
- Atomic Prometheus textfile replacement suitable for a node-exporter textfile
  collector or another deployment agent.
- Opt-in worker flags:
  - `--metrics-file PATH`
  - `--metrics-refresh-seconds SECONDS`
- One-shot workers write after execution. Periodic workers refresh independently
  from marketplace polling cadence and write once more during graceful shutdown.
- No new dependency, database table, migration, or business-service change.

Example:

```powershell
.venv\Scripts\python.exe scripts\run_mediaengine_worker.py `
  --interval-seconds 300 `
  --metrics-file C:\metrics\mediaengine.prom
```

## Metric Semantics

- Scheduler metrics ending in `_total` are cumulative only for the current
  worker process and reset on restart.
- Marketplace metrics describe the latest completed integration batch and are
  gauges, not lifetime counters.
- Per-marketplace offer and snapshot gauges provide source-volume signals for
  later drift rules; Task 1 does not invent a baseline or alert threshold.
- Metrics export is disabled unless an output path is explicitly configured.
- The exporter does not expose an HTTP listener and therefore does not add a
  new unauthenticated network surface.

## Task 2 - Operational Alert Conditions and Routing

Delivered:

- A pure `OperationalAlertEngine` evaluates existing marketplace execution
  batches and dashboard read models without performing I/O.
- Deterministic conditions cover failed and skipped marketplace polling,
  successful polling with item-processing errors, explicit source-volume
  drift, event-scoring failures, content-generation failures, permanent
  publication failures, and ambiguous publications.
- Source-volume drift requires a caller-owned positive baseline scoped to one
  tenant integration. The engine does not infer thresholds from sparse or
  process-local history.
- Alerts carry stable SHA-256 fingerprints derived from safe condition and
  scope identifiers. Changing an observed count does not create a new alert
  identity.
- `AlertSink`, `AlertRoute`, and `OperationalAlertRouter` provide a
  delivery-neutral boundary with severity/code filters, deterministic order,
  per-routing-pass deduplication, and isolation of individual sink failures.
- Routing failures retain only the sink route name, alert fingerprint, and
  exception class. Source URLs, query strings, credentials, raw upstream
  errors, and raw sink errors are not copied into alert results.
- No Telegram, HTTP, database, Scheduler, retry, or production sink wiring was
  added.

Alert semantics:

- Evaluation is a snapshot over supplied observations; it does not persist
  active/resolved state or notification history.
- Dashboard counters are evaluated only when positive. The general
  `generated_content_failed` counter continues to report all failed attempts.
  The separate `generated_content_attempts_exhausted` counter requires both a
  failed attempt and the persisted `generation_attempts_exhausted` error code,
  so only this exact signal raises the critical terminal-exhaustion alert.
- Tenant and integration UUIDs are retained as internal routing scope but are
  not placed in user-controlled summaries or metric labels.
- Cross-replica durable acknowledgement and deduplication remain the external
  alert collector's responsibility. Task 4 adds the process-local lifecycle
  needed to avoid repeated worker notifications and emits stable fingerprints
  for collector-side correlation.

## Task 3 - Polling-History Retention

Delivered:

- The existing `MarketplacePollingRunRepository` now exposes one typed,
  tenant-scoped, bounded pruning operation implemented consistently by memory
  and PostgreSQL repositories.
- `MarketplacePollingRetentionPolicy` requires an explicit positive retention
  period, preserves at least the newest run for every integration, and caps one
  deletion pass at `1,000` records.
- `MarketplacePollingRetentionService` computes one UTC cutoff and performs one
  bounded repository call inside the existing transaction scope. It does not
  own Scheduler or deployment configuration.
- Runs are eligible only when `finished_at` is strictly before the cutoff and
  they are outside the configured newest-N protection for their integration.
  Eligible records are deleted oldest-first with UUID tie-breaking.
- PostgreSQL deletion returns only IDs actually removed by `DELETE ...
  RETURNING`; concurrent callers therefore cannot both report ownership of one
  deletion.
- Memory and PostgreSQL rollback preserve the complete pre-pruning state when
  the caller-owned transaction fails.
- No schema change was required. The existing tenant/integration/newest-first
  index supports retention ranking, and `alembic check` reports no drift.

Retention semantics:

- No production retention duration is hardcoded. Deployment must select
  `retain_for`, `keep_latest_per_integration`, and `batch_size` from operational
  volume and audit requirements.
- A full cleanup may require multiple bounded passes. `batch_limit_reached`
  reports that the current pass hit its limit; it does not claim that more rows
  definitely remain.
- Pruning deletes immutable history records but never mutates retained evidence
  or marketplace-integration latest-outcome metadata.

## Task 4 - Alert Lifecycle and Production Log Sink

Delivered:

- `OperationalAlertLifecycle` tracks deterministic `opened`, `reminder`,
  `escalated`, and `resolved` transitions by stable alert fingerprint.
- Duplicate notifications are suppressed for an explicit reminder interval.
  Acknowledged alerts remain active but do not emit reminders; an increase from
  warning to critical clears acknowledgement and emits immediately.
- `StructuredLoggingAlertSink` emits only allowlisted codes, fingerprints,
  numeric values, stable scope IDs, and lifecycle timestamps through the
  project's structured logging boundary. Alert summaries, source URLs, query
  strings, exception text, provider responses, and credentials are omitted.
- `RuntimeAlertMonitor` combines the latest marketplace execution batch with
  tenant-scoped dashboard reads, reconciles lifecycle state after the read
  transaction has closed, and isolates sink failures by exception class only.
- A failed dashboard read leaves lifecycle state unchanged instead of emitting
  false resolutions from a partial observation.
- PostgreSQL runtime composition now exposes the existing read-repository
  scope. The worker wiring is opt-in through `ALERTING_ENABLED=true` and uses:
  - `ALERTING_EVALUATION_INTERVAL_SECONDS`;
  - `ALERTING_DASHBOARD_WINDOW_SECONDS`;
  - `ALERTING_REMINDER_INTERVAL_SECONDS`.
- Alert delivery performs no Telegram, HTTP, AI, or other external network
  call. Production stdout/stderr collection is the concrete sink boundary.

Lifecycle limits:

- Lifecycle and acknowledgement state are process-local and reset on worker
  restart. Stable fingerprints permit the deployment's external alert manager
  to provide durable cross-replica deduplication, acknowledgement, escalation,
  and history.
- Runtime source-volume alerts still require explicit per-integration baselines;
  no production thresholds are inferred or hardcoded by the worker.
- Alerting remains disabled by default until deployment collector and policy
  values are explicitly configured.

## Verification

- Offline runtime verifier: `12/12` checks passed.
- Offline operational-alert verifier: `25/25` checks passed.
- Focused runtime/monitoring tests: `10` passed.
- Focused operational-alert, lifecycle, and runtime-monitor tests: `12` passed.
- Focused polling-retention and existing polling-history tests: `9` passed.
- Isolated PostgreSQL 17 retention verifier: `16/16` checks passed, including
  memory parity, tenant isolation, rollback, concurrency, and fresh-session
  persistence.
- Alembic current/check, downgrade to `0016`, re-upgrade to head, and offline
  SQL generation passed at `0017_marketplace_polling_runs`.
- Full Pytest: `511 passed, 58 skipped` with one known unrelated Starlette
  TestClient deprecation warning.
- Full MyPy: no issues in `444` source files.
- Focused Ruff and Ruff format checks: passed.

## Remaining Tasks

1. Document and verify deployment configuration for worker replicas, Scheduler
   leases, metrics collection, health checks, graceful shutdown, and scheduled
   bounded retention using explicitly approved policy values.
2. Run an isolated PostgreSQL production-shaped operations verification before
   declaring EPIC 21 complete.
