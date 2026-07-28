# EPIC 12 - Async Repository Contracts and PostgreSQL Runtime Integration

Date: 2026-07-28

Status: specification plus Task 1 implementation log. The original
specification did not implement application code or migrations; the Task 1
status below records the first completed implementation step.

## Task 1 Implementation Status

Status date: 2026-07-28.

Completed:

- repository contracts for offers, canonical products, and price history were
  converted to async method signatures;
- memory repositories now implement the same async public contract as
  PostgreSQL repositories;
- PostgreSQL repository methods structurally match the async contracts and no
  longer require repository-specific `type: ignore[override]` comments;
- `MemoryPriceHistoryRepository` is functional and supports deterministic
  history ordering, latest snapshot lookup, previous snapshot lookup, and exact
  duplicate snapshot suppression;
- focused memory repository tests were added.

Deviation from the original task list:

- `OfferRepository.list_by_marketplace()` was added because Task 1 explicitly
  requires marketplace filtering verification. This is a repository-level
  lookup method and does not change marketplace or business pipeline
  architecture.

Remaining callers that still require async conversion:

- `app/services/marketplace_pipeline.py`;
- `app/services/playerok_pipeline.py` comparison helpers that delegate into
  repository-backed marketplace pipeline methods;
- scheduler and marketplace demo scripts that still compose the old synchronous
  repository call pattern;
- comparator/demo scripts that call `provider.offers` or
  `provider.canonical_products` synchronously.

Recommended next task:

- adapt `RepositoryProvider` composition demos and repository-backed pipeline
  methods so application services consistently `await` repository calls without
  introducing transaction boundaries yet.

## Task 2 Implementation Status

Status date: 2026-07-28.

Completed application caller changes:

- `MarketplacePipeline.run()` now awaits `RepositoryProvider.offers.save()`
  before repository-backed comparison runs;
- `MarketplacePipeline.compare_offers()` is async because it loads canonical
  products through `RepositoryProvider.canonical_products.list_all()`;
- `MarketplacePipeline.compare_repository_offers()` is async because it loads
  offers through `RepositoryProvider.offers.list_all()`;
- the pure comparison construction inside `MarketplacePipeline` remains
  synchronous after offers and canonical products are loaded;
- `PlayerokPipeline.run_comparison()`, `compare_offers()`, and
  `compare_repository_offers()` now await the repository-backed comparison
  pipeline;
- PostgreSQL end-to-end verification now uses repository contracts directly
  without casting provider repositories to concrete PostgreSQL classes.

Updated repository call sites:

- repository-backed comparator demos now await `save()` and `list_all()`;
- marketplace pipeline persistence and comparator demos now await repository
  reads after pipeline execution;
- scheduler end-to-end verification now awaits canonical-product seeding,
  offer persistence, repository activity reads, and repository-backed
  comparison;
- Playerok comparison demos now await the shared comparison pipeline helpers.

Remaining synchronous callers:

- direct `PriceHistoryService` callers remain synchronous because
  `PriceHistoryService` is not a repository contract and the runtime migration
  to `RepositoryProvider.price_history` is intentionally deferred;
- older story/demo scripts that do not use `RepositoryProvider` may still use
  `PriceHistoryService` directly;
- obsolete scheduler demo variants may still require separate cleanup, but the
  current scheduler end-to-end verification path is async-compatible.

Remaining `PriceHistoryService` usage:

- `MarketplacePipeline` still receives and uses `PriceHistoryService`;
- GGSEL vertical-slice demos and scheduler verification still seed and read
  price history through `PriceHistoryService`;
- `RepositoryProvider.price_history` is not yet the active runtime price-history
  path.

Scheduler impact:

- Scheduler architecture was not redesigned;
- `BaseJob` and `SchedulerService` continue to await job execution as before;
- `GGSELJob` works with the async repository-backed marketplace pipeline;
- scheduler verification now awaits repository-backed helper calls outside the
  scheduler layer.

Deviations:

- no transaction boundary, session ownership change, Unit of Work, migration, or
  PostgreSQL default switch was introduced;
- `PriceHistoryService` was documented as remaining runtime debt rather than
  migrated in this task;
- focused async tests use `asyncio.run()` only inside test helpers because the
  project currently has no pytest async plugin configured.

Recommended Task 3:

- migrate the active marketplace runtime price-history path from
  `PriceHistoryService` to `RepositoryProvider.price_history` while keeping
  snapshot construction, price-change detection, event scoring, and comparator
  logic synchronous after repository data is loaded.

## 1. Executive Summary

MediaEngine has enough infrastructure to demonstrate its core backend value:
marketplace offers can be normalized, matched to canonical products, compared,
stored in memory, converted into price snapshots, transformed into price-drop
events, scored, and passed into content generation.

EPIC 10 introduced PostgreSQL repositories. EPIC 11 introduced Scheduler jobs.
The current runtime is still not safely PostgreSQL-backed because repository
contracts are synchronous while PostgreSQL implementations are asynchronous.
This creates a concrete failure mode: a business service can receive a
PostgreSQL repository through `RepositoryProvider`, call `save()` or `list_all()`
synchronously, and receive a coroutine that is never awaited.

The runtime problem is not that PostgreSQL is missing. It is that PostgreSQL is
not yet a safe drop-in backend for the application pipelines.

EPIC 12 will change:

- repository contracts become async where methods perform repository access;
- memory and PostgreSQL repositories implement the same async interfaces;
- business orchestration awaits repository operations consistently;
- runtime price history moves behind `RepositoryProvider.price_history`;
- a clear transaction boundary is introduced for PostgreSQL-backed pipeline runs;
- Scheduler jobs invoke a production-shaped async application flow.

EPIC 12 will intentionally not change:

- matching algorithms;
- comparator algorithms;
- marketplace extraction logic;
- Telegram publishing;
- frontend/API work;
- FunPay implementation;
- event bus or queue infrastructure;
- domain rules around `Decimal`, attribute-based catalogue, and administrator
  confirmation principles.

## 2. Verified Current Call Graph

### Current marketplace pipeline path

Current main module:

- `app/services/marketplace_pipeline.py`

Current flow:

1. `MarketplacePipeline.run(url)` awaits `GGSelFetcher.fetch_html(url)`.
2. It calls `GGSelExtractor.extract(html)` synchronously.
3. It calls `OfferNormalizer.normalize(raw_offer)` synchronously.
4. It calls `RepositoryProvider.offers.save(offer)` synchronously.
5. It calls `MarketplacePipeline.compare_repository_offers()`.
6. `compare_repository_offers()` calls `RepositoryProvider.offers.list_all()`
   synchronously.
7. `compare_offers()` calls
   `RepositoryProvider.canonical_products.list_all()` synchronously.
8. Matching and comparator components execute synchronously.
9. `SnapshotBuilder.build(offer)` runs synchronously.
10. `PriceHistoryService.get_last()` and `PriceHistoryService.add()` are called
    synchronously.
11. `PriceChangeDetector.detect()` runs synchronously.
12. `EventBuilder.build()` runs synchronously.
13. `EventScorer.score()` runs synchronously.
14. `ContentGenerator.generate(event)` is awaited because AI providers are async.

Problem:

- Steps 4, 6, and 7 work with memory repositories but are unsafe with
  PostgreSQL repositories.
- Steps 10 bypass `RepositoryProvider.price_history` entirely.

### Current Playerok pipeline path

Current module:

- `app/services/playerok_pipeline.py`

Current flow:

1. `PlayerokPipeline.run(url)` awaits `PlayerokFetcher.fetch(url)`.
2. It calls `PlayerokExtractor.extract(raw_response)` synchronously.
3. It calls `PlayerokNormalizer.normalize(extracted_offers)` synchronously.
4. It returns `list[ParsedOffer]`.
5. It does not persist offers.
6. `run_comparison()` and `compare_offers()` delegate comparison into an
   existing `MarketplacePipeline`.

Problem:

- Playerok output is not automatically repository-backed.
- Scheduler can execute `PlayerokJob`, but the returned offers are discarded by
  `BaseJob.execute()`.

### Current repository layer

Contracts:

- `CanonicalProductRepository.save(product) -> None`
- `CanonicalProductRepository.get_by_id(id) -> CanonicalProduct | None`
- `CanonicalProductRepository.list_all() -> Sequence[CanonicalProduct]`
- `OfferRepository.save(offer) -> None`
- `OfferRepository.list_all() -> Sequence[ParsedOffer]`
- `PriceHistoryRepository.add(snapshot) -> None`
- `PriceHistoryRepository.get_last(...) -> PriceSnapshot | None`
- `PriceHistoryRepository.get_previous(...) -> PriceSnapshot | None`
- `PriceHistoryRepository.get_history(...) -> list[PriceSnapshot]`

Memory implementations:

- `MemoryCanonicalProductRepository`: synchronous.
- `MemoryOfferRepository`: synchronous append-only storage.
- `MemoryPriceHistoryRepository`: synchronous in-memory list storage.

PostgreSQL implementations:

- `PostgresCanonicalProductRepository`: async methods with
  `type: ignore[override]`.
- `PostgresOfferRepository`: async methods with `type: ignore[override]`.
- `PostgresPriceHistoryRepository`: async methods with `type: ignore[override]`.

### Current database composition

Modules:

- `app/database/session.py`
- `app/repositories/provider.py`

Current flow:

1. `SessionLocal` creates an `AsyncSession`.
2. `create_repository_provider("postgres", session)` creates PostgreSQL
   repositories sharing that session.
3. Demo scripts manually cast repositories to PostgreSQL classes and await
   methods.
4. Demo scripts manually call `session.commit()`.

Problem:

- This works in PostgreSQL demos, but it is not the runtime pipeline contract.
- Business services still assume synchronous repositories.

### Current scheduler flow

Modules:

- `app/scheduler/jobs.py`
- `app/scheduler/service.py`

Current flow:

1. `SchedulerService.register_job(job)` stores `BaseJob` instances.
2. `SchedulerService.execute_job(name)` awaits `BaseJob.execute()`.
3. `BaseJob.execute()` calls `job.run()` and awaits it when awaitable.
4. `GGSELJob.run()` returns `MarketplacePipeline.run(self.url)`.
5. `PlayerokJob.run()` returns `PlayerokPipeline.run(self.url)`.
6. Scheduler records status, retry statistics, timeout, and duration.

Problem:

- Scheduler executes async jobs correctly.
- Scheduler does not preserve pipeline return values.
- Scheduler should not become the owner of persistence or marketplace logic.

## 3. Architectural Decision

Selected architecture:

- Use one async repository contract hierarchy for memory and PostgreSQL.
- Keep repository interfaces independent from SQLAlchemy.
- Keep memory repositories deterministic but async-compatible.
- Use one `RepositoryProvider` per pipeline run.
- Use one shared `AsyncSession` for all PostgreSQL repositories in one pipeline
  run.
- Use one database transaction around repository writes and reads that must be
  consistent for that run.
- Keep external HTTP calls outside the transaction.
- Keep AI/content generation outside the transaction.
- Keep matching, comparison, normalization, scoring, snapshot building, and
  price-change calculation synchronous because they are pure CPU/domain work.
- Scheduler jobs invoke the async application flow and rely on persisted state,
  not returned in-memory values, for downstream integration.

### Rejected alternative: keep sync interfaces and wrap PostgreSQL

Rejected because SQLAlchemy async cannot be safely hidden behind synchronous
interfaces without blocking, running nested event loops, or using unsafe adapter
patterns.

### Rejected alternative: separate sync and async repository hierarchies

Rejected for MVP because it doubles interfaces, splits business services by
backend type, and keeps repository-specific branching in runtime code.

### Rejected alternative: one transaction per repository operation

Rejected for pipeline runtime because it allows partial success. Offers could be
saved while snapshots or canonical associations fail, leaving inconsistent data
after retries.

### Rejected alternative: one transaction around HTTP, DB, and AI

Rejected because it would keep database transactions open during slow external
network calls and AI calls.

## 4. Repository Contract Changes

All repository methods should become async. Return values stay semantically the
same unless explicitly noted.

### CanonicalProductRepository

| Method | Current signature | Proposed signature | Implementations | Callers |
| --- | --- | --- | --- | --- |
| `save` | `def save(product: CanonicalProduct) -> None` | `async def save(product: CanonicalProduct) -> None` | memory, postgres | demos, future matching/admin flows |
| `get_by_id` | `def get_by_id(id: UUID) -> CanonicalProduct | None` | `async def get_by_id(id: UUID) -> CanonicalProduct | None` | memory, postgres | demos, future admin/API flows |
| `list_all` | `def list_all() -> Sequence[CanonicalProduct]` | `async def list_all() -> Sequence[CanonicalProduct]` | memory, postgres | `MarketplacePipeline.compare_offers`, comparator demos |

Affected modules:

- `app/repositories/canonical_products.py`
- `app/repositories/memory/memory_canonical_products.py`
- `app/repositories/postgres/postgres_canonical_products.py`
- `app/services/marketplace_pipeline.py`
- comparator and repository demo scripts.

### OfferRepository

| Method | Current signature | Proposed signature | Implementations | Callers |
| --- | --- | --- | --- | --- |
| `save` | `def save(offer: ParsedOffer) -> None` | `async def save(offer: ParsedOffer) -> None` | memory, postgres | `MarketplacePipeline.run`, demos |
| `list_all` | `def list_all() -> Sequence[ParsedOffer]` | `async def list_all() -> Sequence[ParsedOffer]` | memory, postgres | `MarketplacePipeline.compare_repository_offers`, demos |

Recommended additional method:

| Method | Current signature | Proposed signature | Purpose |
| --- | --- | --- | --- |
| `get_by_identity` | absent | `async def get_by_identity(marketplace: str, external_id: str) -> ParsedOffer | None` | support idempotent upsert and repeated scheduled runs |

Optional later method, only if needed by implementation:

| Method | Current signature | Proposed signature | Purpose |
| --- | --- | --- | --- |
| `upsert` | absent | `async def upsert(offer: ParsedOffer) -> ParsedOffer` | replace append-only behavior with identity-based save semantics |

For EPIC 12 MVP, either `save()` must become idempotent by contract or a new
`upsert()` method must be introduced. The safer explicit option is `upsert()`,
but it changes the interface more. The smallest safe option is to keep `save()`
and define that `save()` means "insert or update by `(marketplace, external_id)`
when `external_id` is present".

Affected modules:

- `app/repositories/offers.py`
- `app/repositories/memory/memory_offers.py`
- `app/repositories/postgres/postgres_offers.py`
- `app/services/marketplace_pipeline.py`
- comparator demos and PostgreSQL demos.

### PriceHistoryRepository

Current methods already exist in the interface, but they are synchronous.

| Method | Current signature | Proposed signature | Implementations | Callers |
| --- | --- | --- | --- | --- |
| `add` | `def add(snapshot: PriceSnapshot) -> None` | `async def add(snapshot: PriceSnapshot) -> None` | memory, postgres | pipeline runtime, demos |
| `get_last` | `def get_last(marketplace: str, external_id: str) -> PriceSnapshot | None` | `async def get_last(marketplace: str, external_id: str) -> PriceSnapshot | None` | memory, postgres | pipeline runtime |
| `get_previous` | `def get_previous(marketplace: str, external_id: str) -> PriceSnapshot | None` | `async def get_previous(marketplace: str, external_id: str) -> PriceSnapshot | None` | memory, postgres | demos, verification |
| `get_history` | `def get_history(marketplace: str, external_id: str) -> list[PriceSnapshot]` | `async def get_history(marketplace: str, external_id: str) -> list[PriceSnapshot]` | memory, postgres | demos, verification |

Recommended additional method:

| Method | Current signature | Proposed signature | Purpose |
| --- | --- | --- | --- |
| `add_if_changed` | absent | `async def add_if_changed(snapshot: PriceSnapshot) -> PriceSnapshot | None` | avoid duplicate adjacent snapshots on repeated scheduler retries |

If `add_if_changed` feels too business-specific for the repository, keep it in
an application service and use existing `get_last()` plus `add()` inside one
transaction. For EPIC 12 MVP, the preferred smaller change is application-level
idempotency with `get_last()` before `add()`.

Affected modules:

- `app/repositories/price_history.py`
- `app/repositories/memory/memory_price_history.py`
- `app/repositories/postgres/postgres_price_history.py`
- `app/services/marketplace_pipeline.py`
- `app/services/price_history.py`
- price-history and scheduler demo scripts.

## 5. Runtime Composition

### Memory runtime provider

`create_memory_provider()` should continue to exist.

Required change:

- it returns repositories implementing async methods;
- storage remains Python collections;
- methods return immediately without `asyncio.sleep()`;
- insertion order remains deterministic.

Memory repositories remain suitable for tests and local demos.

### PostgreSQL runtime provider

`create_postgres_provider(session: AsyncSession)` should continue to exist.

Required behavior:

- all repositories share the same `AsyncSession`;
- provider does not own the session lifecycle when a session is injected;
- a separate application-level runtime factory owns session and transaction for
  a complete pipeline run.

Recommended new composition boundary:

- create a small application service or unit-of-work factory, for example
  `RepositoryProviderFactory` or `AsyncUnitOfWork`, in a later implementation
  task.

It should:

- create one `AsyncSession`;
- open one transaction for DB work;
- build `RepositoryProvider`;
- pass provider into pipelines/services;
- commit on success;
- roll back on failure;
- close the session.

FastAPI startup does not currently compose this flow, so EPIC 12 should avoid
changing FastAPI behavior until the backend runtime service is stable.

## 6. Transaction Design

Recommended MVP transaction model:

- one database session and one transaction per complete marketplace processing
  run;
- external HTTP request happens before the transaction starts;
- extraction and normalization happen before the transaction starts unless they
  need stored canonical data;
- repository writes, canonical-product reads, offer reads, snapshot writes, and
  price-history reads happen inside the transaction;
- event creation and scoring may happen inside the transaction only if they do
  not call external systems and if their output is not persisted;
- AI/content generation happens after commit.

### Boundary by stage

| Stage | Inside DB transaction? | Reason |
| --- | --- | --- |
| Marketplace HTTP request | No | avoid long transaction during external I/O |
| Raw extraction | No | pure CPU parsing |
| Normalization | No | pure CPU mapping |
| Save/update offers | Yes | must be atomic with downstream repository state |
| Load canonical products | Yes | consistent comparison input |
| Matching | Usually yes as CPU inside service call | uses loaded data; no DB I/O itself |
| Comparator | Usually yes as CPU inside service call | uses loaded data; no DB I/O itself |
| Build snapshots | No DB I/O itself | can run before writing snapshots |
| Load previous snapshot | Yes | must be consistent with snapshot write |
| Save current snapshot | Yes | price-history mutation |
| Price change detection | No DB I/O itself | pure calculation after loaded snapshots |
| Event creation/scoring | No DB I/O itself | currently not persisted |
| Commit | Yes | after repository writes are complete |
| Content generation | No | external/async provider should not run in DB transaction |

Rollback rule:

- if saving offers or snapshots fails, roll back the transaction;
- do not generate content after rollback;
- Scheduler retry can safely rerun because persistence is idempotent.

## 7. Price-History Migration Plan

Current runtime issue:

- `MarketplacePipeline` uses `PriceHistoryService`, not
  `RepositoryProvider.price_history`.
- `PriceHistoryService` duplicates memory repository behavior.

Recommended EPIC 12 plan:

1. Convert `PriceHistoryRepository` methods to async.
2. Convert `MemoryPriceHistoryRepository` and `PostgresPriceHistoryRepository`
   to the same async contract.
3. Change runtime pipelines to use `RepositoryProvider.price_history`.
4. Retain `PriceHistoryService` temporarily only as a compatibility wrapper or
   mark it demo-only.
5. Remove direct `PriceHistoryService` injection from production-shaped pipeline
   composition.

Snapshot ordering semantics:

- order by `collected_at`, then by database `id` for PostgreSQL tie-breaking;
- memory repository should mimic the same behavior by insertion order when
  timestamps tie.

Duplicate snapshot behavior:

- repeated scheduler retry with the same offer price should not create invalid
  duplicate analytical events;
- for MVP, allow append-only snapshots only when either price changed or
  collection time is intentionally different;
- exact duplicate `(marketplace, external_id, price, currency, collected_at)`
  should be ignored or constrained.

Idempotency requirement:

- detecting a price change should compare the last persisted snapshot before
  adding the current snapshot;
- if the current snapshot is equivalent to the last snapshot, do not emit a new
  price-change event.

## 8. Scheduler Adaptation

Scheduler should remain orchestration-only.

Required scheduler behavior after EPIC 12:

- `BaseJob.execute()` continues to await async `run()` methods.
- Jobs call application pipeline services.
- Jobs do not perform repository writes directly.
- Jobs do not open marketplace-specific transactions themselves unless they
  delegate to a generic application runtime service.
- Jobs record status and statistics only.

Job return values:

- downstream production flow should rely on persisted repository state, not
  returned in-memory lists;
- preserving the last return value in `BaseJob` is optional and useful for
  diagnostics, but should not be required for correctness.

Transaction lifecycle:

- a job should call a pipeline/runtime service that owns one session and
  transaction for DB work;
- failed transaction rolls back inside that service;
- scheduler records failure and may retry.

Overlap policy:

- MVP should prevent overlapping executions of the same job;
- if a job is still running when the next interval arrives, skip the next run or
  mark it as skipped;
- do not run two writes for the same marketplace/category concurrently until
  idempotency is proven.

Retries:

- retries must be safe because offer save/update and snapshot handling are
  idempotent;
- content generation should not run before DB commit;
- if content generation later becomes persisted, it needs its own idempotency
  key.

## 9. Idempotency Model

### Duplicate marketplace offers

Use `(marketplace, external_id)` as the natural identity when `external_id` is
available.

Database safeguard:

- unique index or constraint on `offers(marketplace, external_id)` for non-null
  `external_id`.

Application behavior:

- `OfferRepository.save()` should update existing offer data rather than append
  duplicates.

### Updates to existing offers

Fields that can update:

- title;
- URL;
- price;
- currency;
- seller ID;
- seller name;
- canonical product ID.

Preserve:

- stable database ID;
- creation timestamp if present.

### Duplicate price snapshots

Use a two-level rule:

- do not create a new analytical event when price and currency did not change
  from the previous snapshot;
- optionally constrain exact duplicate snapshots by `(marketplace, external_id,
  collected_at)`.

For MVP, application-level deduplication before `add()` is enough. Database
constraints can be added when the exact snapshot identity policy is finalized.

### Repeated retry processing

Safe retry flow:

1. Fetch external data outside transaction.
2. Start transaction.
3. Upsert offers.
4. Load previous snapshot.
5. Add current snapshot only when meaningful.
6. Detect event.
7. Commit.
8. Generate content after commit.

If the transaction fails, no content is generated.

### Duplicated market events

Current events are not persisted. EPIC 12 should not introduce an event bus, but
the design should reserve an idempotency key for future event persistence:

- event type;
- marketplace;
- external ID;
- previous price;
- current price;
- current snapshot timestamp or snapshot ID.

### Repeated content generation

Content generation should be post-commit. If the same event is processed twice,
future content persistence should use event idempotency keys.

## 10. Implementation Tasks

### Task 1 - Convert repository contracts to async

Objective:

- make repository interfaces match PostgreSQL reality and remove the need for
  override ignores.

Likely modules/files:

- `app/repositories/canonical_products.py`
- `app/repositories/offers.py`
- `app/repositories/price_history.py`
- `app/repositories/memory/*.py`
- `app/repositories/postgres/*.py`

Implementation boundaries:

- no business logic changes;
- no schema changes yet;
- no pipeline conversion yet.

Acceptance criteria:

- all repository contracts define async methods;
- memory and PostgreSQL implementations match signatures;
- `type: ignore[override]` is removed from PostgreSQL repositories.

Tests:

- repository contract import tests;
- memory repository async behavior tests;
- MyPy on repository modules.

Migration impact:

- none.

Risks:

- demos and services calling repositories synchronously will break until later
  tasks adapt them.

Dependencies:

- none.

Non-goals:

- no transaction manager;
- no schema changes.

### Task 2 - Adapt repository provider and composition typing

Objective:

- keep `RepositoryProvider` backend-neutral while supporting async repositories.

Likely modules/files:

- `app/repositories/provider.py`
- `scripts/demo_repository_provider.py`
- `scripts/demo_repository_provider_postgres.py`

Implementation boundaries:

- provider remains a simple container;
- no globals or singleton.

Acceptance criteria:

- memory provider and PostgreSQL provider expose the same async contract;
- no casts to concrete PostgreSQL repositories are needed in provider demos.

Tests:

- provider creation tests;
- memory and PostgreSQL provider contract tests.

Migration impact:

- none.

Risks:

- PostgreSQL demos need running DB.

Dependencies:

- Task 1.

Non-goals:

- no FastAPI integration.

### Task 3 - Convert repository-backed pipeline methods to async

Objective:

- make `MarketplacePipeline` await repository calls.

Likely modules/files:

- `app/services/marketplace_pipeline.py`
- `app/services/playerok_pipeline.py`
- comparator-related demo scripts.

Implementation boundaries:

- keep extraction, normalization, matching, comparator, scoring synchronous;
- change only orchestration methods that touch repositories.

Acceptance criteria:

- `MarketplacePipeline.run()` awaits offer save/list and canonical product list;
- `compare_offers()` remains sync if it receives already-loaded candidates;
- `compare_repository_offers()` becomes async because it performs I/O.

Tests:

- pipeline with memory provider;
- pipeline with mocked async repositories;
- MyPy for services.

Migration impact:

- none.

Risks:

- many demos call comparator helper methods synchronously.

Dependencies:

- Tasks 1 and 2.

Non-goals:

- no algorithm changes.

### Task 4 - Move price history runtime to RepositoryProvider

Objective:

- remove production runtime dependence on `PriceHistoryService`.

Likely modules/files:

- `app/services/marketplace_pipeline.py`
- `app/repositories/price_history.py`
- `app/repositories/memory/memory_price_history.py`
- `app/repositories/postgres/postgres_price_history.py`
- `app/services/price_history.py`

Implementation boundaries:

- use `provider.price_history`;
- keep `PriceHistoryService` only as a demo wrapper or mark it obsolete.

Acceptance criteria:

- marketplace pipeline no longer requires `PriceHistoryService`;
- current and previous snapshots are loaded through repository provider;
- memory and PostgreSQL flows behave consistently.

Tests:

- price-history ordering tests;
- pipeline snapshot persistence tests;
- no direct production imports of `PriceHistoryService`.

Migration impact:

- possible index migration later, but not in this task.

Risks:

- snapshot duplicate behavior must be explicit.

Dependencies:

- Tasks 1-3.

Non-goals:

- no event persistence.

### Task 5 - Introduce runtime transaction boundary

Objective:

- define one session/transaction per complete PostgreSQL pipeline run.

Likely modules/files:

- new application runtime/unit-of-work module, likely under `app/services/` or
  `app/database/`;
- `app/database/session.py`;
- selected demo verification script.

Implementation boundaries:

- no marketplace logic in transaction manager;
- no scheduler logic in transaction manager.

Acceptance criteria:

- HTTP fetch happens before transaction;
- repository writes happen inside transaction;
- rollback prevents partial DB state;
- content generation happens after commit.

Tests:

- rollback test with failing repository operation;
- transaction success test;
- content generation not called after rollback.

Migration impact:

- none.

Risks:

- if the transaction includes too much work, DB locks may be held too long.

Dependencies:

- Tasks 1-4.

Non-goals:

- no Celery/Kafka/event bus.

### Task 6 - Add idempotent offer persistence

Objective:

- repeated scheduled runs do not duplicate offers.

Likely modules/files:

- `app/repositories/offers.py`
- `app/repositories/memory/memory_offers.py`
- `app/repositories/postgres/postgres_offers.py`
- Alembic migration later.

Implementation boundaries:

- define `save()` as upsert by `(marketplace, external_id)` or add explicit
  `upsert()`;
- do not change `ParsedOffer` fields.

Acceptance criteria:

- saving the same marketplace/external ID twice updates one stored offer;
- memory and PostgreSQL behavior match.

Tests:

- memory idempotency test;
- PostgreSQL unique/upsert test;
- scheduled retry simulation.

Migration impact:

- unique index/constraint on `offers(marketplace, external_id)`.

Risks:

- `external_id=None` requires fallback behavior.

Dependencies:

- Tasks 1-5.

Non-goals:

- no historical offer versioning.

### Task 7 - Add price snapshot idempotency and ordering

Objective:

- repeated runs do not create invalid duplicate price events.

Likely modules/files:

- `app/repositories/price_history.py`
- `app/repositories/memory/memory_price_history.py`
- `app/repositories/postgres/postgres_price_history.py`
- `app/models/price_snapshot_record.py`
- Alembic migration later.

Implementation boundaries:

- keep price-change calculation unchanged except for caller ordering;
- do not introduce event persistence.

Acceptance criteria:

- previous snapshot is reliably the snapshot before current;
- unchanged price does not create a price-change event;
- ordering is deterministic.

Tests:

- get last/previous/history ordering;
- unchanged price scenario;
- repeated retry scenario.

Migration impact:

- index on `(marketplace, external_id, collected_at)`.

Risks:

- equal timestamps require deterministic tie-breaker.

Dependencies:

- Tasks 1-5.

Non-goals:

- no time-series aggregation.

### Task 8 - Adapt Scheduler verification to PostgreSQL runtime

Objective:

- prove Scheduler can invoke the async repository-backed application flow.

Likely modules/files:

- `app/scheduler/jobs.py`
- `app/scheduler/service.py`
- `scripts/demo_scheduler_end_to_end.py`
- new PostgreSQL scheduler verification demo if needed.

Implementation boundaries:

- Scheduler remains business-logic free;
- jobs call pipeline/runtime service only.

Acceptance criteria:

- scheduled GGSEL-shaped flow completes with PostgreSQL provider;
- job failure rolls back DB transaction;
- retry does not create invalid duplicates;
- Scheduler statistics still work.

Tests:

- scheduler async pipeline test;
- failing job rollback test;
- overlap policy test.

Migration impact:

- none directly.

Risks:

- live marketplace network failure may make tests flaky; use fixtures for tests.

Dependencies:

- Tasks 1-7.

Non-goals:

- no Telegram.

### Task 9 - Update demos and remove obsolete compatibility paths

Objective:

- keep only current demos runnable after async conversion.

Likely modules/files:

- `scripts/demo_*`

Implementation boundaries:

- update demos to `await` repository operations;
- mark old one-story demos obsolete or adapt them;
- do not preserve outdated sync repository usage only for demos.

Acceptance criteria:

- current verification demos run;
- obsolete demos are documented or removed in a later cleanup task.

Tests:

- run selected demos;
- Ruff on touched scripts.

Migration impact:

- none.

Risks:

- many scripts duplicate composition setup.

Dependencies:

- Tasks 1-8.

Non-goals:

- no feature changes.

### Task 10 - Documentation sync

Objective:

- update Project Passport after EPIC 12 implementation.

Likely modules/files:

- `docs/PROJECT_PASSPORT/02_ARCHITECTURE.md`
- `docs/PROJECT_PASSPORT/03_DOMAIN_MODEL.md`
- `docs/PROJECT_PASSPORT/11_ROADMAP.md`
- `docs/PROJECT_PASSPORT/13_CURRENT_STATE.md`
- `docs/PROJECT_PASSPORT/16_TECH_LEAD_NOTES.md`
- `docs/PROJECT_PASSPORT/CHANGELOG.md`

Implementation boundaries:

- do not rewrite historical review documents;
- mark `ARCHITECTURE_REVIEW_5.md` as historical by referencing newer docs.

Acceptance criteria:

- docs no longer say PostgreSQL repositories and Scheduler are absent;
- EPIC 12 completion state is recorded.

Tests:

- documentation review only.

Migration impact:

- none.

Risks:

- Project Passport has older encoding issues in some files.

Dependencies:

- Tasks 1-9.

Non-goals:

- no application code.

## 11. Test Plan

### Repository contract tests

- verify every repository implementation satisfies async contract;
- verify no `type: ignore[override]` remains;
- verify memory and PostgreSQL implementations expose matching method names and
  return types.

### Memory repository tests

- save/list canonical products;
- save/list offers;
- idempotent offer save/update;
- add/get_last/get_previous/get_history snapshots;
- deterministic insertion/order behavior.

### PostgreSQL integration tests

- create provider from `AsyncSession`;
- save/list canonical products;
- save/list offers;
- save/list price snapshots;
- verify commit persistence;
- verify rollback removes uncommitted writes.

### Transaction rollback tests

- fail after offer save but before snapshot save;
- assert no partial writes remain after rollback;
- assert content generation was not called.

### Idempotency tests

- rerun same offer ingestion;
- retry after simulated failure;
- duplicate snapshot input;
- unchanged price input;
- repeated event-generation path.

### Price-history ordering tests

- same marketplace/external ID with increasing timestamps;
- equal timestamps with deterministic tie-breaker;
- get previous after inserting current;
- no previous snapshot case.

### Pipeline integration tests

- memory-backed pipeline completes;
- PostgreSQL-backed pipeline completes;
- repository operations are awaited;
- comparison uses repository-loaded offers and canonical products;
- price history uses provider repository.

### Scheduler integration tests

- Scheduler executes async pipeline job;
- failed job does not stop scheduler;
- retry does not create duplicate offers or invalid duplicate events;
- overlapping run is skipped or blocked according to policy.

### MyPy and Ruff expectations

- MyPy should pass for repository interfaces and implementations without
  override ignores;
- Ruff should pass for touched modules;
- no new broad `type: ignore` should be introduced.

## 12. Migration Plan

Do not implement migrations in this specification.

Required Alembic changes for EPIC 12 implementation:

1. Add unique/index support for offer identity:
   - preferred: unique constraint or partial unique index on
     `offers(marketplace, external_id)` where `external_id` is not null;
   - if partial indexes are avoided, define explicit behavior for null
     `external_id`.

2. Add lookup indexes:
   - `offers(marketplace, external_id)`;
   - `offers(canonical_product_id)`;
   - `price_snapshots(marketplace, external_id, collected_at)`;
   - optionally `price_snapshots(marketplace, external_id, id)`.

3. Add canonical product foreign key:
   - `offers.canonical_product_id -> canonical_products.id`, if canonical links
     are meant to be relationally enforced.

4. Review legacy tables:
   - `marketplaces`;
   - `products`;
   - `prices`.

   Decide whether they are active persistence models or legacy foundation
   tables. Do not drop them until a separate migration decision is approved.

5. Timestamp handling:
   - confirm timezone-aware storage policy;
   - normalize all runtime timestamps to UTC;
   - ensure ordering fields are consistent.

6. Decimal precision:
   - review whether `Numeric(12, 2)` is sufficient for all supported
     marketplaces and currencies.

## 13. Documentation Updates

When EPIC 12 is implemented, update:

- `docs/PROJECT_PASSPORT/02_ARCHITECTURE.md`: record async repository contracts,
  PostgreSQL runtime integration, and scheduler role.
- `docs/PROJECT_PASSPORT/03_DOMAIN_MODEL.md`: clarify `ParsedOffer`,
  `PriceSnapshot`, `PriceChange`, and persistence records.
- `docs/PROJECT_PASSPORT/11_ROADMAP.md`: mark EPIC 10/11 accurately and add
  EPIC 12 completion state.
- `docs/PROJECT_PASSPORT/13_CURRENT_STATE.md`: remove stale statements about
  missing PostgreSQL repositories and empty price-history repository.
- `docs/PROJECT_PASSPORT/16_TECH_LEAD_NOTES.md`: add async repository and
  transaction decisions.
- `docs/PROJECT_PASSPORT/CHANGELOG.md`: record EPIC 12.
- `docs/POSTGRESQL_VERIFICATION.md`: update once PostgreSQL is a real runtime
  backend.
- `docs/SCHEDULER_VERIFICATION.md`: update once Scheduler runs the
  PostgreSQL-backed application flow.

Do not rewrite `docs/ARCHITECTURE_REVIEW_5.md`. It must remain a historical
checkpoint. If needed, add a later review that supersedes it.

## 14. EPIC Acceptance Criteria

EPIC 12 is complete when:

- all repository contracts use one async method convention;
- memory repositories implement the same async contract as PostgreSQL
  repositories;
- PostgreSQL repository implementations no longer need
  `type: ignore[override]`;
- business services await repository calls;
- `RepositoryProvider.price_history` is the active runtime price-history path;
- `PriceHistoryService` is removed from production runtime or clearly marked as
  demo/compatibility only;
- one PostgreSQL-backed marketplace pipeline completes without unawaited
  coroutines;
- repeated scheduled runs do not create invalid duplicate offers;
- repeated unchanged price snapshots do not create invalid duplicate events;
- Scheduler can invoke the async application flow and report status;
- database transaction rollback prevents partial repository writes;
- external HTTP calls and AI/content generation are outside DB transactions;
- matching, comparator, normalization, scoring, and deterministic calculations
  remain database-independent and marketplace-independent where they are today;
- no Telegram, frontend, FunPay, event bus, queue, or unrelated feature work is
  introduced.

## 15. Recommended First Implementation Task

Recommended first task:

**Convert repository contracts and memory repositories to async signatures.**

Why this is the smallest safe first step:

- it directly fixes the root interface mismatch;
- it does not require migrations;
- it does not change business algorithms;
- it allows PostgreSQL repositories to remove override ignores;
- it makes all later pipeline and scheduler work explicit because callers must
  `await` repository methods;
- memory repositories can remain deterministic and simple.

Scope of the first task:

- update `app/repositories/canonical_products.py`;
- update `app/repositories/offers.py`;
- update `app/repositories/price_history.py`;
- update `app/repositories/memory/*.py`;
- remove matching override ignores from PostgreSQL repositories if signatures now
  align;
- update only the minimal repository demo/import checks needed to prove the
  contract.

Non-goals of the first task:

- no migrations;
- no transaction manager;
- no scheduler changes;
- no marketplace pipeline rewrite;
- no Telegram or AI changes.
