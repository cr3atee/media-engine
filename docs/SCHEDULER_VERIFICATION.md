# Scheduler Verification

## Status

Scheduler orchestration is verified for PostgreSQL-backed marketplace ingestion
and durable market-event scoring/recovery.

## Verified Flow

1. `SchedulerService` executes `GGSELJob`.
2. The job delegates to the application runner.
3. The runner opens the PostgreSQL repository scope.
4. Offer, snapshot, comparison, price-change, and durable event persistence run
   in one transaction.
5. Ingestion returns after durable event commit.
6. A controlled failed call is retried by Scheduler.
7. A permanently failing job is reported as failed without stopping Scheduler.
8. A repeated successful run reuses persisted history and remains idempotent for
   the exact snapshot.
9. Scheduler shuts down cleanly.
10. `MarketEventScoringJob` delegates one bounded claim/score batch to
    `EventProcessingService`.
11. `StaleScoringClaimRecoveryJob` delegates one bounded recovery batch to the
    same application service.
12. Durable scoring success and stale-lease recovery are confirmed against fresh
    PostgreSQL sessions.

## Verified Responsibilities

- Jobs own no sessions or repositories.
- Scheduler contains no marketplace business logic.
- Transaction ownership remains in the runner repository scope.
- Jobs receive the expanded immutable `MarketplaceRunResult` without owning event
  repositories or changing their orchestration contract.
- Scheduler records successful, failed, and retry statistics correctly for the
  verified non-overlapping execution path.
- Event jobs create no repository, session, scorer, or retry policy and perform no
  lifecycle updates themselves.
- Per-event retry state is persisted by the application service and remains
  independent from Scheduler invocation retries/statistics.

## Remaining Limits

- There is no explicit same-job overlap guard.
- Multiple Scheduler processes are not coordinated.
- Market-event scoring progress is durable; generated content and publication
  attempts are not yet durable.
- No content-generation or publication-delivery jobs exist yet.
- Production intervals, monitoring, and alerting are not verified.

Marketplace live evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
Durable event job evidence is recorded by the Task 5 service/Scheduler tests and
`verify_epic13_event_processing_postgres.py` (14 checks passed).
