# Scheduler Verification

## Status

Scheduler orchestration is verified for PostgreSQL-backed marketplace ingestion,
durable market-event scoring/recovery, content generation, and content/publication
stale-claim recovery. EPIC 14 additionally verifies PostgreSQL-backed pending
Telegram publication delivery through the orchestration-only Scheduler job.

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
13. `PendingContentGenerationJob` delegates a bounded durable generation batch.
14. `StaleContentClaimRecoveryJob` delegates expired content-claim recovery.
15. `StalePublicationClaimRecoveryJob` delegates protected ambiguous-state
    recovery without delivery or resend.
16. Generated content and publication intent remain visible through fresh
    PostgreSQL sessions after Scheduler execution.

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
- Content jobs create no repositories, sessions, AI provider, publication target,
  or retry policy. They pass configured limits, worker identity, and time to the
  application service only.
- Publication recovery jobs never call a delivery adapter and never return an
  ambiguous publication to pending.

## Remaining Limits

- There is no explicit same-job overlap guard.
- Multiple Scheduler processes are not coordinated.
- Telegram publication delivery and its Scheduler job are implemented and
  verified with mocked transport; guarded live test-chat delivery is not
  verified.
- Production intervals, monitoring, and alerting are not verified.

Marketplace live evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
Durable event job evidence is recorded by the Task 5 service/Scheduler tests and
`verify_epic13_event_processing_postgres.py` (14 checks passed).
Durable content/publication job evidence is recorded by the Task 6 focused tests
and `verify_epic13_content_publication_postgres.py` (18 checks passed).

Final EPIC 13 verification also runs ingestion, scoring, content generation, and
all three stale-claim recovery jobs in one Scheduler instance against PostgreSQL.
The sequence completes with durable event, content, and publication state. Source
inspection confirms that these jobs remain orchestration-only. Five existing
Scheduler demos exit normally; restricted live marketplace access is surfaced as
failed job status without stopping Scheduler.

## EPIC 14 Task 2 Update

`PendingPublicationDeliveryJob` has been added as an orchestration-only Scheduler
job. It receives a configured `PublicationDeliveryService`, worker ID, batch
size, and clock, then delegates one bounded `process_batch()` call. The job does
not open sessions, access repositories, format Telegram messages, call the Bot
API directly, calculate retry delays, or mutate publication lifecycle state.

Stale publication recovery remains handled by the existing
`StalePublicationClaimRecoveryJob`. Delivery retries are represented through the
durable publication state and are selected by the same channel-scoped claim path.
Live Telegram delivery remains disabled by default and is reserved for the
guarded Task 3 test-chat verification.

## EPIC 14 Task 3 Update

The final PostgreSQL-backed `PendingPublicationDeliveryJob` verification passed
against an isolated PostgreSQL 17 database. It confirms that Scheduler delegates
only to `PublicationDeliveryService` and does not own repositories, Telegram
HTTP calls, formatting, or retry policy.

The guarded live Telegram verifier does not route live sends through Scheduler;
it verifies exactly one durable publication through `PublicationDeliveryService`
when all live-test guards are explicitly satisfied.

## EPIC 14 Task 3 Retry (2026-07-31)

The isolated PostgreSQL retry passed the Scheduler delivery check as part of the
`39/39` EPIC 14 verifier result. The job successfully delegated one bounded
delivery batch, persisted the result through fresh sessions, and reported no
failure. No Scheduler code changes were required.

**EPIC 14 functionally complete; guarded live Telegram test-chat verification
not performed.**

## EPIC 15 Final Verification Note

EPIC 15 Task 3 did not change Scheduler behavior. The final verification
re-ran `scripts/verify_epic14_delivery_service_postgres.py` against an isolated
PostgreSQL 17 database at current migration head `0009_admin_actions`; the
delivery Scheduler check remained green as part of the `39/39` verifier result.
