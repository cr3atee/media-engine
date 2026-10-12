# EPIC 21 - Production Operations Readiness

## Status

Task 1 is implemented and verified. Alert evaluation/routing, polling-history
retention, and deployment wiring remain separate tasks.

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

## Verification

- Offline runtime verifier: `12/12` checks passed.
- Focused runtime/monitoring tests: `10` passed.
- Full Pytest: `494 passed, 58 skipped` with one known unrelated Starlette
  TestClient deprecation warning.
- Full MyPy: no issues in `433` source files.
- Focused Ruff and Ruff format checks: passed.

## Remaining Tasks

1. Define deterministic alert conditions and a delivery-neutral alert routing
   contract for failed/skipped polling, source-volume drift, exhausted content
   attempts, and ambiguous publications.
2. Add explicit polling-history retention and pruning policy with memory and
   PostgreSQL parity, rollback safety, and tenant isolation.
3. Document and verify deployment configuration for worker replicas, Scheduler
   leases, metrics collection, health checks, and graceful shutdown.
4. Run an isolated PostgreSQL production-shaped operations verification before
   declaring EPIC 21 complete.
