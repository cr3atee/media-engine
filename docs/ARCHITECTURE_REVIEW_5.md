# Architecture Review #5

Date: 2026-07-28

Scope: review after EPIC 10 PostgreSQL Persistence and EPIC 11 Scheduler.

This review is documentation-only. Application code was not changed.

## 1. Overall Architecture

The project still follows the intended layered direction in the core areas:

- marketplace adapters produce marketplace data;
- parser and normalizer components convert source data into `ParsedOffer`;
- repository contracts isolate storage access;
- matching and comparator services remain marketplace-independent;
- analytics, events, scoring, and content generation are separated from parsing;
- scheduler jobs call existing pipelines instead of containing business logic.

The architecture is stronger than in earlier reviews because PostgreSQL repository implementations and Scheduler orchestration now exist. However, the system is not yet fully unified at runtime because PostgreSQL repositories are async while the repository contracts and several business services still call repositories synchronously.

Main architectural issues:

- `MarketplacePipeline` is named generically but remains GGSEL-specific through constructor dependencies on `GGSelFetcher`, `GGSelExtractor`, and `OfferNormalizer`.
- `PlayerokPipeline` can produce parsed offers, but it does not persist offers by itself, while `MarketplacePipeline` does.
- `ParsedOffer` lives in `app/parsers` while it is used as a cross-layer application DTO by repositories, matching, comparator, snapshots, and demos.
- Two price change detector modules exist: `app/analytics/price_change.py` and `app/analytics/price_change_detector.py`.

Overall status: solid foundation, but the orchestration boundaries need cleanup before adding more automation.

## 2. Repository Layer

What is working:

- Repository interfaces exist for canonical products, offers, and price history.
- Memory repositories implement the contracts synchronously and are usable by demos and current business services.
- PostgreSQL repositories exist for offers, canonical products, and price snapshots.
- `RepositoryProvider` centralizes backend selection between memory and PostgreSQL.

Main issue:

- The repository interfaces define synchronous methods, but PostgreSQL repositories implement async methods with `type: ignore[override]`.

Why this matters:

- Business services can receive PostgreSQL repositories through `RepositoryProvider`, but calls such as `provider.offers.save(offer)` return coroutines and are not awaited by existing synchronous pipeline code.
- Type safety is weakened exactly at the persistence boundary.
- The default memory provider keeps demos working, but PostgreSQL is not a drop-in replacement for current business services yet.

Recommendation:

- Before production persistence, introduce a single consistent repository contract style.
- Prefer async repository contracts if PostgreSQL remains the production backend.
- Keep memory repositories available, but make them implement the same async contract instead of maintaining sync and async semantics in one interface.

## 3. PostgreSQL Readiness

What is ready:

- Async SQLAlchemy engine and session factory exist.
- Alembic async configuration exists and imports model metadata dynamically.
- Migrations exist for:
- marketplace/product/price foundation tables;
- offers;
- canonical products;
- price snapshots.
- PostgreSQL repositories map database records back into domain/data-transfer objects.

Current risks:

- PostgreSQL repositories are not safely interchangeable with memory repositories because of async method mismatch.
- `PriceHistoryService` still stores runtime price history in memory and is separate from `RepositoryProvider.price_history`.
- There is no explicit transaction boundary for a full pipeline run.
- `offers.canonical_product_id` is not constrained by a foreign key to `canonical_products.id`.
- Key lookup tables do not yet define practical indexes for production access patterns.
- Older tables from `0001_init_marketplace_support` (`marketplaces`, `products`, `prices`) coexist with newer `offers`, `canonical_products`, and `price_snapshots`, creating possible schema ambiguity.

Recommended database improvements:

- Add indexes for `offers(marketplace, external_id)`.
- Add indexes for `price_snapshots(marketplace, external_id, collected_at)` or equivalent ordering field.
- Decide whether legacy `products` and `prices` tables are still part of the active model.
- Add foreign key semantics for canonical product references if the field is meant to be durable relational data.
- Add transaction ownership around complete pipeline execution.

Readiness: PostgreSQL foundation is present, but production readiness is partial.

## 4. Scheduler Architecture

What is working:

- `SchedulerService` registers jobs.
- `BaseJob` tracks state, duration, failures, and timing.
- `GGSELJob` and `PlayerokJob` wrap existing pipelines.
- Periodic execution exists.
- Retry, timeout, and statistics are implemented at the scheduler layer.
- Scheduler failure handling is separated from marketplace business logic.

Current risks:

- `BaseJob.execute()` records status but discards the pipeline return value.
- Playerok offers produced by `PlayerokPipeline` are therefore not naturally available to repository-backed downstream flow through the scheduled job result.
- Scheduler currently has no concurrency policy for overlapping executions of the same job.
- There is no distributed lock or process-level coordination for multiple scheduler instances.
- Scheduler configuration is not yet centralized through production settings.
- Scheduler demos use deterministic local inputs for verification, not live marketplace execution.

The scheduler design is clean as orchestration. The next scheduler work should focus on operational policy, not business logic.

## 5. Marketplace Integrations

### GGSEL

Status: strongest marketplace path.

What exists:

- fetcher;
- extractor;
- typed raw marketplace model;
- normalizer;
- marketplace pipeline;
- snapshot/event/content vertical slice;
- scheduler job.

Risks:

- Legacy `GGSelParser` still overlaps with the newer fetcher/extractor/normalizer path.
- The generic `MarketplacePipeline` is effectively GGSEL-specific.
- Live response stability and payload changes remain operational risks.

### Playerok

Status: structurally integrated, less proven with live marketplace data.

What exists:

- fetcher;
- extractor;
- normalizer;
- pipeline;
- scheduler job;
- comparator compatibility through parsed offers.

Risks:

- Playerok does not currently persist parsed offers inside its own pipeline.
- The scheduled Playerok job cannot expose produced offers because `BaseJob` discards return values.
- Live extraction stability still needs stronger verification.

### FunPay

Status: adapter directories exist, but no active implementation.

## 6. Matching

The matching layer remains clean:

- normalization;
- tokenization;
- stop-word filtering;
- alias expansion;
- Jaccard similarity;
- confidence classification;
- matching service.

Strengths:

- deterministic;
- marketplace-independent;
- no AI or embedding dependency;
- reusable by comparator grouping.

Limitations:

- Jaccard similarity is intentionally simple and may miss close product variants.
- Alias data is hardcoded in code, not administrator-managed.
- There is no persisted rejection history for administrator decisions yet.

Current readiness: good for MVP demos, not final for large catalogs.

## 7. Comparator

The comparator stack is one of the most coherent parts of the project.

What works:

- offers can be grouped by canonical product;
- the cheapest valid offer can be selected;
- currency mismatch is detected without unsafe conversion;
- differences are calculated with `Decimal`;
- immutable comparison results are produced.

Risks:

- Comparator quality depends on canonical products being seeded and offers being repository-backed.
- It currently compares current offers, not historical trends.
- It does not create events directly from comparison results.

Current readiness: high for deterministic comparison, partial for production integration.

## 8. Event Pipeline

What works:

- `PriceSnapshot` is database-independent.
- `PriceChangeDetector` can detect price movement.
- `EventBuilder` creates `PriceDropEvent` only for decreases.
- `EventScorer` assigns deterministic importance score.
- `ContentGenerator` can generate content from events.

Risks:

- `EventBuilder` maps `product_identifier` into event `title`, which loses human-readable product title context.
- `PriceChangeDetector` exists in two modules with different output completeness.
- Event generation is driven by price snapshots, not comparator results.
- There is no event bus or event persistence by design, but this limits auditability once scheduling is active.

Current readiness: good vertical slice, not yet production event infrastructure.

## 9. Content Generation

What works:

- `AIProvider` abstraction exists.
- `FakeAIProvider` enables deterministic local demos.
- `PriceDropPromptBuilder` uses a reusable template.
- `ContentGenerator` separates prompt building from provider execution.

Risks:

- Production AI integration is not part of the committed baseline.
- Generated content currently depends on event payload quality; event payloads do not yet carry full offer context.
- There is no moderation, deduplication, or publication approval workflow.

Current readiness: demo-ready, not production-ready.

## 10. Documentation Consistency

Outdated documentation found:

- `docs/PROJECT_PASSPORT/02_ARCHITECTURE.md` still describes only memory repositories and does not reflect PostgreSQL repositories or Scheduler.
- `docs/PROJECT_PASSPORT/11_ROADMAP.md` says PostgreSQL repository implementations are not present.
- `docs/PROJECT_PASSPORT/13_CURRENT_STATE.md` says `PriceHistoryRepository` is empty and no PostgreSQL repositories exist.
- `docs/PROJECT_REVIEW_3.md` says Scheduler is 0% and PostgreSQL is future work.
- `docs/INTEGRATION_REVIEW.md` contains older statements that PostgreSQL repositories and Scheduler do not exist, although later sections start mentioning PostgreSQL foundation.
- `docs/SCHEDULER_FOUNDATION.md` says Scheduler integration with PostgreSQL-backed providers is intentionally later, while PostgreSQL provider selection now exists but is not safely integrated into business services.

Documentation that appears current:

- `docs/POSTGRESQL_VERIFICATION.md` correctly records partial PostgreSQL readiness and async integration limitations.
- `docs/SCHEDULER_VERIFICATION.md` correctly records scheduler verification and job result limitations.
- `docs/SCHEDULER_JOBS.md` reflects retry, timeout, periodic execution, and job status behavior.

Recommendation:

- Update Project Passport after the repository contract decision is made.
- Keep review documents as historical snapshots, but clearly mark them as superseded by later reviews.

## 11. Remaining Technical Debt

Real technical debt:

- Sync repository contracts are incompatible with async PostgreSQL implementations.
- `type: ignore[override]` is used to bypass repository interface mismatches.
- Runtime price history still uses `PriceHistoryService` instead of `RepositoryProvider.price_history`.
- `MarketplacePipeline` is generic in name but GGSEL-specific in dependencies.
- Playerok scheduled execution does not naturally feed repository-backed comparison.
- Legacy and modular GGSEL parser paths coexist.
- Two price change detector modules coexist with different output fields.
- Several demo scripts are incremental story artifacts and duplicate setup code.
- Project Passport docs lag behind current implementation.
- PostgreSQL schema lacks important indexes and relational constraints for production usage.
- Transaction boundaries are not explicit around full pipeline execution.
- Scheduler has no concurrency or distributed execution guard yet.

## 12. Production Readiness

Estimated readiness:

- Overall architecture: 78%
- Repository layer: 55%
- PostgreSQL readiness: 45%
- Scheduler architecture: 65%
- Marketplace integrations: 55%
- Matching: 80%
- Comparator: 85%
- Event pipeline: 65%
- Content generation: 55%
- Documentation consistency: 50%
- Overall production readiness: 48%

Interpretation:

- The project can demonstrate core product value.
- The deterministic matching and comparator layers are strong.
- The main blockers are persistence semantics, live marketplace stability, and scheduler-to-pipeline result handling.
- Production readiness should not be claimed until PostgreSQL can replace memory repositories without changing business service behavior.

## 13. Updated MVP Readiness

MVP readiness estimate: 60%.

Completed enough for MVP demonstration:

- GGSEL vertical slice;
- Playerok structural pipeline;
- repository abstraction;
- memory and PostgreSQL repository implementations;
- matching;
- comparator;
- price snapshot and price change flow;
- event scoring;
- fake content generation;
- scheduler foundation and jobs.

Still required for a credible MVP:

- make repository contracts and PostgreSQL implementations semantically consistent;
- route price history through repository provider or make the in-memory service explicitly demo-only;
- prove live Playerok extraction with stable data;
- decide how scheduled Playerok output reaches persistence and comparator stages;
- update Project Passport;
- remove or clearly mark obsolete demos;
- add Telegram or another publication delivery boundary if MVP includes publishing.

## 14. Recommended Next EPICs

### 1. Repository Contract Alignment

Highest priority.

Resolve the sync/async mismatch between repository interfaces and PostgreSQL implementations. This unlocks safe PostgreSQL usage without changing business logic later.

### 2. Repository-Backed Pipeline Integration

Move runtime flows to `RepositoryProvider` consistently, especially price history. Add transaction ownership for complete pipeline runs.

### 3. Marketplace Runtime Hardening

Stabilize live GGSEL and Playerok extraction, error reporting, diagnostics, rate-limit behavior, and payload drift handling.

### 4. Scheduler Production Policy

Define intervals, concurrency behavior, overlap protection, retry settings, result handling, and operational logging for scheduled jobs.

### 5. Telegram Publisher Boundary

Introduce delivery infrastructure only after persistence and scheduler semantics are stable. Telegram should consume generated content, not own marketplace or analytics logic.

## Highlighted Risks

Outdated documentation:

- Project Passport and earlier reviews no longer represent EPIC 10 and EPIC 11 accurately.

Duplicated code:

- duplicate price change detector modules;
- legacy GGSEL parser path plus modular GGSEL fetch/extract/normalize path;
- many incremental demo scripts with repeated setup.

Obsolete demo scripts:

- early one-story demos remain useful for development history but should not be treated as current product verification.
- GGSEL demos have both `ggsel` and `ggsell` naming variants.

Architectural inconsistencies:

- sync repository interfaces with async PostgreSQL implementations;
- generic `MarketplacePipeline` with GGSEL-specific dependencies;
- Playerok pipeline output is not persisted by the scheduled job path.

Integration risks:

- PostgreSQL provider can be created but is not safely drop-in for synchronous business services.
- Scheduler can run jobs but does not expose job results to downstream orchestration.
- Price history persistence exists in PostgreSQL but is not the runtime path used by `MarketplacePipeline`.

## Final Verdict

MediaEngine is in a healthy foundation-plus-integration stage, not yet a production-ready backend.

The architecture remains directionally correct. The next work should not add new product features yet. It should close the repository contract mismatch and persistence integration gap first. Once PostgreSQL can replace memory repositories cleanly, Scheduler and Telegram can build on stable durable state instead of demo-oriented in-memory flows.
