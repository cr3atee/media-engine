# Scheduler Verification

## Status

Scheduler orchestration is verified through a PostgreSQL-backed
`MarketplaceApplicationRunner`.

## Verified Flow

1. `SchedulerService` executes `GGSELJob`.
2. The job delegates to the application runner.
3. The runner opens the PostgreSQL repository scope.
4. Persistence, comparison, history, change detection, and event construction
   run in one transaction.
5. Scoring and content run after commit.
6. A controlled failed call is retried by Scheduler.
7. A permanently failing job is reported as failed without stopping Scheduler.
8. A repeated successful run reuses persisted history and remains idempotent for
   the exact snapshot.
9. Scheduler shuts down cleanly.

## Verified Responsibilities

- Jobs own no sessions or repositories.
- Scheduler contains no marketplace business logic.
- Transaction ownership remains in the runner repository scope.
- Scheduler records successful, failed, and retry statistics correctly for the
  verified non-overlapping execution path.

## Remaining Limits

- There is no explicit same-job overlap guard.
- Multiple Scheduler processes are not coordinated.
- Events and publication attempts are not durable.
- Failed post-commit content cannot yet be resumed by Scheduler.
- Production intervals, monitoring, and alerting are not verified.

Complete live evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
