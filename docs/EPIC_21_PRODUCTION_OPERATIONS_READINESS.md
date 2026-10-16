# EPIC 21 - Production Operations Readiness

## Status

Tasks 1 and 2 are implemented and verified. Polling-history retention,
production sink wiring, alert lifecycle policy, and deployment wiring remain
separate tasks.

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
- Dashboard counters are evaluated only when positive. The current
  `generated_content_failed` counter proves failed generation attempts, not
  that every retry for a content item is exhausted, so the alert is named
  `content_generation_failed` rather than overstating terminal exhaustion.
- Tenant and integration UUIDs are retained as internal routing scope but are
  not placed in user-controlled summaries or metric labels.
- Production deduplication windows, escalation, acknowledgement, resolution,
  and concrete delivery sinks remain deployment concerns.

## Verification

- Offline runtime verifier: `12/12` checks passed.
- Offline operational-alert verifier: `17/17` checks passed.
- Focused runtime/monitoring tests: `10` passed.
- Focused operational-alert tests: `6` passed.
- Full Pytest: `500 passed, 58 skipped` with one known unrelated Starlette
  TestClient deprecation warning.
- Full MyPy: no issues in `436` source files.
- Focused Ruff and Ruff format checks: passed.

## Remaining Tasks

1. Add explicit polling-history retention and pruning policy with memory and
   PostgreSQL parity, rollback safety, and tenant isolation.
2. Wire an approved production alert sink and define alert lifecycle,
   deduplication-window, acknowledgement, and escalation policy. Add a distinct
   terminal content-attempt signal before alerting on retry exhaustion.
3. Document and verify deployment configuration for worker replicas, Scheduler
   leases, metrics collection, health checks, and graceful shutdown.
4. Run an isolated PostgreSQL production-shaped operations verification before
   declaring EPIC 21 complete.
