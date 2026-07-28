# EPIC 12 Task 4 - Transaction Design

Date: 2026-07-28

Status: approved implementation design; no application code or migrations are
included in this document.

## 1. Executive Summary

MediaEngine should use **Alternative D: a composition-root transaction scope**.

One reusable `MarketplaceApplicationRunner` should coordinate a marketplace run:

1. Fetch, extract, normalize, and validate offers without opening a database
   session or transaction.
2. Enter a PostgreSQL repository scope created by the composition root.
3. Create one `AsyncSession`, start one `session.begin()` transaction, and create
   one `RepositoryProvider` whose PostgreSQL repositories all share that session.
4. Persist offers and snapshots, load canonical data and prior snapshots, and run
   deterministic matching, comparison, price-change detection, and event building.
5. Leave the scope. Normal exit commits; an exception rolls back; session exit
   closes the session.
6. Score events and generate content only after commit.

`RepositoryProvider` remains a simple repository container. It must not own a
session, expose commit/rollback, or become an async context manager. Repository
contracts remain independent from SQLAlchemy. Memory providers continue to work
through a no-op repository scope and do not acquire SQLAlchemy lifecycle rules.

The MVP policy is one transaction for one bounded marketplace ingestion unit,
currently one URL/category response. This gives an explicit all-or-nothing rule
for valid offers in that unit. Chunked processing is a later scaling option after
run-size and transaction-duration measurements exist.

This design does not make content delivery reliable. Events are not persisted, so
a crash after commit can lose post-commit content work. Persisted event/publication
intent should be the next reliability task after Task 4, before Telegram delivery.

## 2. Current Runtime Lifecycle

### Engine

- `app/database/session.py` creates one module-level async `engine` with
  `create_async_engine(settings.database.url)`.
- Pool and isolation settings are not customized.
- CLI verification scripts explicitly call `engine.dispose()`.
- FastAPI does not import or dispose the engine through an application lifespan.

### Session factory

- `SessionLocal` is a module-level `async_sessionmaker[AsyncSession]` bound to the
  global engine.
- `expire_on_commit=False` is configured.
- `get_session()` yields a session but does not define commit or rollback policy.
- No current application code uses `session.begin()`.

### Session

- PostgreSQL demos create sessions manually with `async with SessionLocal()`.
- Demos call `session.commit()` explicitly, sometimes more than once in one
  script.
- No reusable rollback boundary exists for a complete marketplace run.
- Closing a session will clean up an uncommitted transaction, but that is not an
  explicit application policy.

### Repository instances

- Every PostgreSQL repository constructor receives an existing `AsyncSession`.
- Repositories do not create or close sessions.
- `PostgresOfferRepository.save()` and
  `PostgresCanonicalProductRepository.save()` call `flush()` after insert/update.
- `PostgresPriceHistoryRepository.add()` calls `flush()` only when it inserts.
- Repositories do not commit, rollback, or refresh records.
- This behavior is compatible with one shared outer transaction.

### RepositoryProvider

- `RepositoryProvider` is a dataclass containing canonical-product, offer, and
  price-history repository contracts.
- `create_postgres_provider(session)` builds all three repositories with the same
  session.
- `create_memory_provider()` creates independent collection-backed repositories.
- The provider has no lifecycle behavior and should retain that responsibility.

### Pipeline

- `MarketplacePipeline` stores a provider in a long-lived instance.
- `MarketplacePipeline.run()` currently performs HTTP fetch, extraction,
  normalization, repository writes and reads, deterministic calculations,
  scoring, and async content generation in one method.
- Wrapping the current `run()` in `session.begin()` would therefore hold a
  transaction during both marketplace HTTP and AI calls.
- `PlayerokPipeline.run()` only fetches, extracts, and normalizes. It does not
  persist offers or run the full downstream flow.
- The exact before/inside/after split required by Task 4 is not currently exposed.

### Scheduler job

- `GGSELJob` and `PlayerokJob` retain concrete pipeline instances.
- A registered job can live for the lifetime of `SchedulerService`.
- `BaseJob.execute()` awaits the pipeline and stores status, but discards the
  returned value.
- A session-bound provider must not be captured in such a long-lived pipeline.
- `SchedulerService` correctly owns scheduling, retries, timeout, and statistics;
  it does not own database lifecycle today.

### FastAPI

- `app/main.py` exposes only `GET /` and configures logging.
- It has no database lifespan, dependency composition, marketplace endpoint, or
  application runner.
- `get_session()` exists but is not wired into the FastAPI application.

### Verification scripts

- PostgreSQL scripts manually create a session, provider/repositories, perform
  operations, and commit.
- `scripts/demo_postgres_end_to_end.py` demonstrates the components but uses two
  manual commits and does not run the real marketplace pipeline inside one
  transaction.
- `scripts/demo_scheduler_end_to_end.py` uses a long-lived memory provider and
  correctly verifies repository-backed history, but not PostgreSQL lifecycle.

## 3. Selected Architecture

### Selected model: Alternative D - composition-root transaction scope

The composition layer provides a transaction-scoped `RepositoryProvider` to an
application operation. Conceptually:

```python
@asynccontextmanager
async def postgres_repository_scope() -> AsyncIterator[RepositoryProvider]:
    async with SessionLocal() as session:
        async with session.begin():
            yield create_postgres_provider(session)
```

The application runner enters that scope only after ingestion succeeds and exits
it before scoring or content generation begins. `session.begin()` supplies the
required behavior: commit on normal exit and rollback on exception. Session exit
closes the session.

The concrete PostgreSQL scope belongs under `app/database/`, because it is
infrastructure composition. The application runner depends only on a callable
that returns an async context yielding `RepositoryProvider`; it does not need to
import `AsyncSession`.

For memory execution, the composition root supplies a no-op async scope yielding
one `create_memory_provider()` instance. The provider itself does not implement
transaction methods. This preserves deterministic memory state across repeated
runs without introducing fake SQLAlchemy behavior.

### Why this fits MediaEngine

- PostgreSQL repositories already accept a shared external session.
- Repositories already use `flush()` instead of `commit()`.
- The provider already builds repositories around a supplied session.
- The missing responsibility is only outer lifecycle and phase separation.
- Scheduler, CLI, future FastAPI endpoints, and tests can call the same runner.
- A new Unit of Work API would not currently coordinate any behavior beyond what
  `session.begin()` and the existing provider already provide.

## 4. Rejected Alternatives

### Alternative A - pipeline-owned session

Rejected.

- It would couple `MarketplacePipeline` to SQLAlchemy and PostgreSQL.
- Memory tests would need backend branches or fake session behavior.
- The current pipeline includes HTTP and AI, making accidental long transactions
  likely.
- Scheduler jobs retain pipelines, so session lifetime could exceed one run.
- Pipeline construction would become infrastructure composition instead of
  application orchestration.

### Alternative B - RepositoryProvider-owned session

Rejected.

- The provider is currently an unambiguous repository container.
- Owning session, commit, rollback, and close would turn it into an implicit Unit
  of Work without naming that contract.
- It would be unclear whether a provider can be reused between runs.
- Memory providers would either expose meaningless transaction methods or diverge
  from the PostgreSQL provider API.
- A provider could still be captured by a long-lived pipeline or job after its
  session closes.

### Alternative C - explicit application Unit of Work

Rejected for the current MVP, but viable later.

- A Unit of Work would correctly own session and repositories.
- Current use cases require only one transaction boundary and one provider; they
  do not need nested transactions, aggregate tracking, or multiple commit modes.
- Adding `commit()`, `rollback()`, repository properties, and context lifecycle to
  a new abstraction would duplicate `session.begin()` and `RepositoryProvider`.
- It becomes justified later if application use cases need several transaction
  types, persisted events/outbox integration, or explicit savepoints.

### Alternative D - composition-root transaction callback

Selected.

- It is the smallest implementation matching current repository constructors.
- Transaction ownership is explicit and outside business components.
- It is straightforward to replace with a Unit of Work later without changing
  repository contracts or domain services.

## 5. Transaction Boundary

### Before transaction

1. Resolve marketplace configuration and source URL.
2. Perform marketplace HTTP request.
3. Extract the raw payload.
4. Normalize raw items into `ParsedOffer` values.
5. Validate normalized offers.
6. Build valid `PriceSnapshot` candidates and record offers that cannot produce a
   snapshot.

No `AsyncSession` should exist during these steps. A malformed offer that cannot
be normalized is skipped and reported before transaction entry. An otherwise
valid offer with incomplete snapshot fields may still be persisted while its
snapshot is counted as skipped, preserving current behavior.

### Inside one transaction

1. Create all PostgreSQL repositories with the same session.
2. Upsert every valid normalized offer.
3. Load canonical products needed by matching/comparison.
4. Run deterministic matching and comparator calculations over loaded DTOs.
5. Persist only canonical associations already explicitly present and valid.
   Current matching output must not automatically change an association because
   administrator confirmation/rejection rules are not implemented in this flow.
6. For each snapshot candidate, load the latest snapshot for the same
   `(marketplace, external_id)`.
7. Insert the current snapshot using exact-duplicate-safe repository behavior.
8. Run synchronous chronological price-change detection on concrete snapshots.
9. Build deterministic domain events in memory.
10. Return a transaction result containing DTOs and counts.
11. Exit `session.begin()`, committing all writes atomically.

Matching, comparator, snapshot construction, price-change calculation, and event
building perform no external I/O. They may execute while the transaction is open
because they use a consistent repository view. If profiling shows that matching
or comparison materially lengthens transactions, their loaded-data calculations
can move before commit while retaining the same session reads and writes.

### After commit

1. Score committed events.
2. Generate AI content.
3. Build `MarketplaceRunResult`.
4. Report structured status to Scheduler, CLI, or future API caller.
5. Future delivery channels consume generated content.

Content generation must never run before successful commit. A post-commit content
failure does not roll back offers or snapshots.

### Current deviations requiring implementation

- `MarketplacePipeline.run()` does not expose separate phases.
- It stores a provider instead of receiving a transaction-scoped provider for the
  persistence phase.
- Scoring and content generation occur in the same method as repository work.
- Playerok output is not automatically passed through the repository-backed
  processing phase.
- Matching decisions are calculated but canonical associations are not persisted.
- Events are not persisted, so post-commit work cannot be recovered after a
  process crash.

### Per-run versus per-offer policy

Recommended MVP policy: one transaction per bounded marketplace ingestion unit.

- One transaction per offer gives weak consistency, excessive commit overhead,
  and allows price history to advance while related offer writes fail.
- Separate write and later read transactions can compare against a state changed
  by another run.
- Chunked transactions improve scale but create intentional partial progress and
  require resumable run metadata that does not exist.
- One transaction gives a clear rollback rule and makes scheduler retry simple.

A run must be defined as one bounded URL/page/category payload, not an unlimited
marketplace crawl. Record offers-per-run and transaction duration. Introduce
page/chunk transactions when measured volume or lock time exceeds an operational
limit; that change must include explicit partial-progress and resume semantics.

## 6. Failure and Rollback Matrix

| Failure | Transaction state | Rollback | Retry policy | Duplicate risk |
| --- | --- | --- | --- | --- |
| Marketplace HTTP fails | Not opened | No | Scheduler may retry full run | None in DB |
| Extraction fails before persistence | Not opened | No | Retry after source/parser diagnosis | None in DB |
| One offer fails pre-transaction validation | Not opened | No | Skip offer, record error, continue valid offers | None |
| First offer saves; second repository write fails | Active | Roll back entire run | Retry full bounded run | Low only with required offer uniqueness/upsert |
| Snapshot read succeeds; snapshot write fails | Active | Roll back offers and snapshots from run | Retry full bounded run | Low only with exact-snapshot constraint |
| Matching fails on malformed canonical data | Active | Roll back entire run | Do not retry until data is corrected, unless transient | None after rollback |
| Price-change detector raises | Active | Roll back entire run | Retry only after code/data cause is resolved | None after rollback |
| Event builder raises | Active | Roll back entire run | Retry only after code/data cause is resolved | None after rollback |
| Commit fails | Commit attempted | Roll back/close failed transaction | Retry with a new session | Possible without DB uniqueness; constrained with required indexes |
| AI/content generation fails | Already committed | No | Do not retry ingestion solely for content; record post-commit error | Duplicate content if whole run is retried |
| Scheduler retries after rollback | New transaction | Prior run already rolled back | Safe full-run retry | Controlled by upsert/unique constraints |
| Scheduler retries after commit before content finishes | Already committed | No | Do not automatically retry whole run for content | High content duplication/loss risk until event intent is persisted |
| Process crashes after commit | Already committed | No | Re-ingestion is persistence-safe; content recovery is unavailable | Content may be lost or duplicated |
| Two runs overlap in one process | Two active transactions possible | Each transaction independent | Prefer future per-job overlap guard | Offer/snapshot constraints protect rows; events/content can duplicate |
| Two processes handle the same run | Two active transactions | Each transaction independent | Future distributed run lock or claim | Isolation alone is insufficient; unique constraints are mandatory |

Rollback-required failures are repository, matching, detector, event-building, and
commit failures inside the transaction. A single invalid offer is recoverable only
when detected before transaction entry. Content failures are post-commit failures
and must not trigger rollback. Retry safety depends on database-enforced offer and
snapshot identity, not only application lookups.

## 7. Repository Changes

### `app/repositories/postgres/postgres_offers.py`

- Keep constructor injection of `AsyncSession`.
- Replace lookup-then-insert with PostgreSQL upsert after the offer identity
  migration exists.
- Use `(marketplace, external_id)` when `external_id` is non-null.
- Preserve record `id` and `created_at` on update.
- Continue `flush()` so constraint failures surface before transaction exit.
- Do not commit or rollback.

### `app/repositories/postgres/postgres_canonical_products.py`

- Keep current session injection and `flush()` behavior.
- Do not commit or rollback.
- No transaction-specific API changes are required.

### `app/repositories/postgres/postgres_price_history.py`

- Keep constructor injection of the shared session.
- Replace lookup-then-insert duplicate suppression with database uniqueness plus
  `ON CONFLICT DO NOTHING` after the snapshot migration exists.
- Continue ordering by `collected_at`, then `id`.
- Continue `flush()` after a real insert.
- Do not commit or rollback.

### Repository contracts

- No SQLAlchemy types or transaction methods are added.
- No commit/rollback methods are added.
- Existing async interfaces remain unchanged unless a return value is later
  required to report whether an insert was suppressed; that is not required for
  the first transaction-boundary commit.

### Flush and refresh policy

- `flush()` is required before later operations depend on generated IDs or before
  the application needs constraint failures to occur inside the transaction body.
- Current canonical IDs and offer IDs are application-generated, so `refresh()` is
  unnecessary for normal mapping.
- `commit()` belongs only to the outer transaction scope.

## 8. RepositoryProvider Changes

Final Task 4 responsibility:

- remain a simple, session-agnostic container of repository contracts;
- receive preconstructed session-bound PostgreSQL repositories through
  `create_postgres_provider(session)`;
- continue supporting `create_memory_provider()`;
- expose no transaction or session methods;
- not become an async context manager;
- not own commit, rollback, or close.

The provider should be created inside the PostgreSQL transaction scope and must
not escape into a long-lived scheduler job or singleton. Domain and repository
interfaces remain unaware of `AsyncSession`.

## 9. Application Runner Design

### Proposed component

Name: `MarketplaceApplicationRunner`

Location: `app/services/marketplace_application_runner.py`

Purpose: provide the single reusable application entry point for one marketplace
execution while separating external I/O, transactional repository work, and
post-commit content work.

### Proposed collaborators

- marketplace identifier;
- an ingestion callable/service that returns normalized `ParsedOffer` objects;
- the repository-scope factory supplied by composition;
- transaction-phase marketplace processing extracted from the current
  `MarketplacePipeline`;
- `EventScorer`;
- `ContentGenerator`;
- optional stage reporter.

The runner must not receive `AsyncSession` directly. PostgreSQL-specific session
construction remains in `app/database/`.

### Proposed method

```python
async def run(self, url: str) -> MarketplaceRunResult:
    ...
```

The runner is configured for one marketplace and one ingestion implementation.
GGSEL and Playerok composition create separate runner instances using existing
fetch/extract/normalize behavior, but both use the same transaction processing
and result contract.

### Proposed result DTO

```python
@dataclass(slots=True, frozen=True)
class MarketplaceRunResult:
    marketplace: Marketplace
    offers_received: int
    offers_persisted: int
    comparison_results: int
    snapshots_created: int
    snapshots_persisted: int
    skipped_offers: int
    price_changes_detected: int
    events_created: int
    content_items_generated: int
    persistence_committed: bool
    errors: tuple[str, ...]
```

The DTO contains no SQLAlchemy objects, sessions, mapped records, or repository
instances. Transaction failures raise and are handled by Scheduler/CLI/API
boundaries. Recoverable validation and post-commit content errors are summarized.

### Required pipeline phase extraction

The current `MarketplacePipeline.run()` must be split without duplicating logic:

1. ingestion returns normalized offers;
2. a transaction-phase method accepts normalized offers and a scoped provider,
   then returns comparison data and in-memory events;
3. post-commit code scores events and generates content.

The final public runner replaces production-shaped calls to the monolithic
pipeline. Temporary delegation from existing demos is acceptable during focused
commits, but no second implementation of matching, comparison, snapshots, or
events may be created.

## 10. Scheduler Composition

Target flow:

```text
SchedulerService
  -> GGSELJob / PlayerokJob
  -> MarketplaceApplicationRunner.run(url)
  -> ingestion without DB transaction
  -> transaction-scoped RepositoryProvider
  -> commit or rollback
  -> post-commit scoring/content
  -> MarketplaceRunResult
```

Jobs receive a configured runner and URL. They do not construct sessions,
repositories, providers, or transaction scopes. They do not contain matching,
snapshot, or content logic.

The job result should be `MarketplaceRunResult`, a pipeline summary. A persisted
run identifier and event IDs are not available because run/event persistence does
not exist. `BaseJob` may retain the last result for diagnostics, but correctness
must continue to depend on committed repository state.

Transaction failures raise so existing Scheduler retry policy applies. A content
failure after commit should be recorded in the result and logged without retrying
the whole ingestion run. The current scheduler cannot represent partial success;
the result DTO is the narrow place to expose it without moving business logic into
the scheduler.

## 11. FastAPI/CLI Reuse

### Scheduler

The composition root builds one runner per marketplace and jobs call it.

### FastAPI

A future endpoint can receive a configured runner through FastAPI dependency
composition and await `runner.run(url)`. The endpoint must not open transactions
or construct repositories. No endpoint is part of Task 4.

FastAPI lifespan should eventually own engine disposal, while a request/run scope
owns sessions. The global engine and `SessionLocal` may remain infrastructure
singletons.

### CLI

Verification scripts call the same runner with PostgreSQL or memory repository
scope composition. Scripts no longer reproduce manual repository and commit
sequences.

### Tests

Tests supply a memory scope or a recording transaction scope and deterministic
ingestion/content collaborators. They do not require SQLAlchemy for application
runner unit tests.

## 12. Idempotency and Schema Requirements

### Offers

Natural identity is `(marketplace, external_id)` when `external_id` is not null.

Current state:

- memory save updates by this identity;
- PostgreSQL save performs lookup then insert/update;
- schema has no unique constraint;
- two sessions can race and create duplicate rows.

Required behavior:

- add a partial unique index for non-null `external_id`;
- use PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`;
- keep nullable external IDs as append-only records until a separate identity
  rule is approved.

### Price snapshots

Task 3 semantics require exact duplicate suppression while allowing:

- the same price at a new timestamp;
- a different price at the same timestamp;
- out-of-order snapshots;
- deterministic timestamp/id ordering.

The matching unique identity is:

`(marketplace, external_id, collected_at, price, currency)`.

Use both a database unique constraint/index and `ON CONFLICT DO NOTHING`. The
database is authoritative under concurrency; repository conflict handling makes
the expected duplicate case non-fatal. A preliminary application lookup may be
removed because it cannot prevent races and adds a round trip.

Add a separate history lookup index ordered by marketplace, external ID,
collection timestamp, and record ID.

### Canonical-product associations

`offers.canonical_product_id` currently has neither a foreign key nor an index.
Add a nullable foreign key to `canonical_products.id` with `ON DELETE SET NULL`
and an index on the column.

Task 4 must not automatically persist `MatchingService` output. The accepted
administrator confirmation/rejection rules require a separate association
decision workflow. Task 4 persists only associations already present on a valid
offer.

## 13. Concurrency Limitations

### Solved by Task 4 transaction scope

- all writes in one run use one session and one atomic transaction;
- repository failures cannot leave partial state from that run;
- reads and writes share one transaction view;
- content is not generated for rolled-back data.

### Solved by uniqueness and PostgreSQL upsert

- concurrent non-null offer identities converge on one row;
- exact duplicate snapshots converge on one row;
- expected conflicts do not fail an otherwise valid transaction.

Transaction isolation alone does not solve lookup-then-insert races. No explicit
isolation level is currently configured, and even stronger isolation would not
replace identity constraints.

### Not solved by Task 4

- two runs with different collection timestamps can both persist snapshots;
- duplicate deterministic events and content can be produced by overlapping runs;
- Scheduler has no per-job overlap lock;
- multiple processes have no distributed run claim;
- there is no content/event idempotency key or persisted delivery state.

Minimum deployment policy until a run-lock task is implemented:

- run one scheduler process;
- do not overlap the same marketplace/category job;
- configure intervals longer than observed worst-case execution;
- rely on database constraints for row integrity, not for content deduplication.

A future scheduler/run-lock EPIC should add in-process per-job exclusion first,
then a PostgreSQL advisory lock or persisted run claim if multiple processes are
required. Redis or distributed infrastructure is not needed for Task 4.

## 14. Implementation Task Breakdown

### Commit 1 - Separate application phases

Goal:

- expose ingestion, transaction processing, and post-commit content phases
  without changing matching, comparator, price, event, or content algorithms.

Files/modules:

- `app/services/marketplace_pipeline.py`;
- `app/services/playerok_pipeline.py` only where needed to expose normalized
  offers;
- new transaction-result DTO module under `app/services/`;
- focused pipeline tests.

Acceptance criteria:

- HTTP/extraction/normalization can complete before any provider scope opens;
- transaction processing accepts a scoped `RepositoryProvider`;
- events are returned as in-memory DTOs;
- content generation can run separately after processing;
- existing memory behavior remains equivalent.

Tests:

- phase order;
- unchanged comparison/event output;
- invalid offer handling;
- no duplicated orchestration logic.

Risks:

- broad constructor churn across demos;
- accidentally changing current skip/report behavior.

Dependencies:

- EPIC 12 Tasks 1-3.

Non-goals:

- no SQLAlchemy session scope, migration, scheduler change, or new business rule.

### Commit 2 - Add PostgreSQL repository transaction scope and runner

Goal:

- implement Alternative D and `MarketplaceApplicationRunner`.

Files/modules:

- new `app/database/repository_scope.py`;
- new `app/services/marketplace_application_runner.py`;
- `app/database/session.py` only for reusable factory typing/lifecycle helpers;
- application runner tests.

Acceptance criteria:

- one session is shared by all repositories in a run;
- normal scope exit commits;
- exceptions roll back and close the session;
- HTTP and AI are outside scope;
- memory scope remains SQLAlchemy-free.

Tests:

- shared-session construction;
- commit and rollback;
- scope enter/exit ordering;
- memory provider compatibility.

Risks:

- transaction scope entering too early;
- leaking a provider after session close.

Dependencies:

- Commit 1.

Non-goals:

- no schema changes, scheduler lock, event persistence, or API endpoint.

### Commit 3 - Enforce database idempotency

Goal:

- make concurrent offer upserts and exact snapshot suppression database-safe.

Files/modules:

- `app/models/offer.py`;
- `app/models/price_snapshot_record.py`;
- `app/repositories/postgres/postgres_offers.py`;
- `app/repositories/postgres/postgres_price_history.py`;
- new Alembic migrations;
- PostgreSQL integration tests.

Acceptance criteria:

- duplicate non-null offer identity updates one row;
- exact duplicate snapshot creates one row;
- same price/new timestamp and same timestamp/different price remain valid;
- required lookup indexes exist;
- repositories still do not commit.

Tests:

- two-session concurrent offer upsert where practical;
- two-session exact snapshot insert;
- history ordering after conflicts.

Risks:

- existing duplicate rows can block migration;
- PostgreSQL partial-index conflict syntax must match the model/index definition.

Dependencies:

- data preflight against existing tables; Commit 2 for end-to-end verification.

Non-goals:

- no event/content idempotency or legacy-table removal.

### Commit 4 - Compose Scheduler with application runners

Goal:

- make jobs invoke transaction-scoped runners without owning persistence logic.

Files/modules:

- `app/scheduler/jobs.py`;
- application composition module/factory;
- scheduler integration tests;
- current scheduler verification script.

Acceptance criteria:

- jobs receive runner instances and URL only;
- no job imports SQLAlchemy repositories or sessions;
- transaction failures reach Scheduler retry handling;
- post-commit content errors do not retry ingestion;
- a structured run result is available for diagnostics.

Tests:

- successful scheduled commit;
- rollback then retry;
- content failure after commit;
- job remains orchestration-only.

Risks:

- current `BaseJob` discards results;
- retry classification must distinguish transaction and post-commit failures.

Dependencies:

- Commits 1-3.

Non-goals:

- no overlap lock, distributed scheduler, or Telegram.

### Commit 5 - Reuse runner in CLI and prepare FastAPI composition

Goal:

- remove manual commit sequences from the canonical PostgreSQL verification path
  and prove one reusable entry point.

Files/modules:

- `scripts/demo_postgres_end_to_end.py`;
- selected repository/scheduler verification scripts;
- optional composition factory used by future FastAPI lifespan;
- no API route changes.

Acceptance criteria:

- CLI verification uses `MarketplaceApplicationRunner`;
- FastAPI can later receive the same runner without changing its API;
- engine disposal ownership is documented for CLI and FastAPI.

Tests:

- CLI-shaped runner invocation;
- engine/session cleanup after success and failure.

Risks:

- retaining obsolete manual demos as apparent production examples.

Dependencies:

- Commits 1-4.

Non-goals:

- no endpoint, seller API, frontend, or live Playerok stabilization.

### Commit 6 - Verification and documentation sync

Goal:

- verify Task 4 acceptance criteria and update current architecture records.

Files/modules:

- transaction integration tests;
- `docs/EPIC_12_ASYNC_RUNTIME_INTEGRATION.md`;
- Project Passport current-state documents;
- PostgreSQL and Scheduler verification documents.

Acceptance criteria:

- focused and full tests pass;
- Ruff and MyPy pass for touched modules;
- PostgreSQL verification records actual commit/rollback results;
- outdated transaction statements are removed from current docs.

Tests:

- complete matrix from Section 15 where supported by the local environment.

Risks:

- live PostgreSQL may not be available in every development environment.

Dependencies:

- Commits 1-5.

Non-goals:

- no unrelated documentation rewrite, including `ARCHITECTURE_REVIEW_5.md`.

## 15. Test Plan

### Successful commit

- Ingest two valid offers outside the scope.
- Verify all provider repositories reference the same session.
- Verify offers and snapshots are visible after scope exit.
- Verify one commit occurs.

### Rollback on repository failure

- Save the first offer, fail the second repository write, and assert neither
  offer nor snapshot persists.
- Verify content generation is not called.

### No transaction during HTTP

- Use a recording scope and fetcher.
- Assert fetch/extract/normalize finish before scope entry.

### No transaction during AI generation

- Assert scope exit and commit complete before `ContentGenerator.generate()`.

### Shared session across repositories

- Build a PostgreSQL provider inside one scope.
- Assert canonical, offer, and price repositories receive the same session.
- Avoid exposing that assertion through repository contracts.

### Memory provider compatibility

- Execute the same runner with a no-op memory scope.
- Run twice and verify repository state persists between runs.
- Verify no SQLAlchemy object is required.

### Scheduler invocation

- Register jobs configured with runners.
- Verify jobs do not create sessions or repositories.
- Verify transaction failure updates Scheduler failure/retry statistics.

### Retry after rollback

- Fail the first attempt after one write.
- Retry with a new session.
- Assert one final offer identity and valid price history.

### Commit failure

- Simulate commit failure at scope exit.
- Assert no content call and no reusable failed session.
- Verify Scheduler receives a retryable exception.

### Post-commit content failure

- Commit persistence successfully.
- Fail content generation.
- Assert persistence remains and the result records a post-commit error.
- Assert the ingestion transaction is not retried automatically.

### Concurrent duplicate simulation

- Use two PostgreSQL sessions to upsert the same offer identity.
- Use two sessions to add one exact snapshot.
- Assert one row after both transactions.
- Verify same timestamp/different price remains two rows.

### Additional regression coverage

- first snapshot produces no price event;
- decrease produces one event;
- increase produces no price-drop event;
- unchanged price produces no event;
- out-of-order snapshot persists without reverse event;
- malformed canonical data rolls back;
- event-builder exception rolls back;
- result DTO contains no mapped SQLAlchemy objects.

## 16. Migration Plan

No migration is created by this design task.

### Migration 0005 - offer identity and canonical association integrity

Preflight:

- detect duplicate non-null `(marketplace, external_id)` rows;
- select a deterministic survivor and merge/update data before adding uniqueness;
- detect orphan `canonical_product_id` values and set them to null or resolve them
  through an approved data-cleanup decision.

DDL:

- create partial unique index
  `uq_offers_marketplace_external_id_not_null` on
  `offers(marketplace, external_id)` where `external_id IS NOT NULL`;
- create index `ix_offers_canonical_product_id` on
  `offers(canonical_product_id)`;
- add nullable foreign key
  `offers.canonical_product_id -> canonical_products.id` with
  `ON DELETE SET NULL`.

### Migration 0006 - price snapshot identity and lookup

Preflight:

- remove exact duplicate rows using the smallest `id` as survivor;
- preserve rows with a new timestamp or a different price/currency.

DDL:

- create unique constraint/index
  `uq_price_snapshots_exact_identity` on
  `(marketplace, external_id, collected_at, price, currency)`;
- create lookup index `ix_price_snapshots_history_order` on
  `(marketplace, external_id, collected_at DESC, id DESC)`.

### Deferred migration decisions

- Do not remove legacy `marketplaces`, `products`, or `prices` tables until their
  ownership is separately decided.
- Confirm UTC-aware PostgreSQL column types before altering existing timestamps;
  runtime values are UTC, while current SQLAlchemy columns use default
  timezone-naive `DateTime` mapping.
- Review `Numeric(12, 2)` limits separately; Task 4 preserves `Decimal` and does
  not change monetary precision.
- Do not create event/outbox tables in Task 4. That is the next reliability
  design after transaction ownership is implemented.

## 17. Documentation Updates

When Task 4 is implemented, update:

- `docs/EPIC_12_ASYNC_RUNTIME_INTEGRATION.md` with implementation commits,
  transaction behavior, and deviations;
- `docs/POSTGRESQL_VERIFICATION.md` with real commit and rollback verification;
- `docs/SCHEDULER_VERIFICATION.md` with runner-based PostgreSQL execution;
- `docs/SCHEDULER_FOUNDATION.md` because its PostgreSQL integration limitation
  will be outdated;
- `docs/SCHEDULER_JOBS.md` with runner invocation and result semantics;
- `docs/PROJECT_PASSPORT/02_ARCHITECTURE.md` with the application runner and
  transaction scope;
- `docs/PROJECT_PASSPORT/03_DOMAIN_MODEL.md` with `MarketplaceRunResult` if added;
- `docs/PROJECT_PASSPORT/11_ROADMAP.md` with Task 4 status;
- `docs/PROJECT_PASSPORT/13_CURRENT_STATE.md` after shared-session verification;
- `docs/PROJECT_PASSPORT/16_TECH_LEAD_NOTES.md` with the selected ownership model;
- `docs/PROJECT_PASSPORT/CHANGELOG.md`.

Keep `docs/ARCHITECTURE_REVIEW_5.md` unchanged as a historical checkpoint.

## 18. Task 4 Acceptance Criteria

- [ ] One marketplace application run has one explicitly owned PostgreSQL
  `AsyncSession`.
- [ ] All PostgreSQL repositories in the run share that session.
- [ ] `RepositoryProvider` remains a simple container.
- [ ] Repository contracts expose no SQLAlchemy types or transaction methods.
- [ ] Marketplace HTTP, extraction, normalization, and validation finish before
  transaction entry.
- [ ] Offer persistence, canonical reads, snapshot reads, and snapshot writes run
  inside one transaction.
- [ ] Deterministic price changes and events are produced from transaction-loaded
  DTOs.
- [ ] Successful scope exit commits exactly once.
- [ ] Any transaction-phase failure rolls back all writes from the run.
- [ ] Scoring and content generation start only after commit.
- [ ] Content failure does not roll back committed marketplace data.
- [ ] Scheduler jobs invoke the application runner without session/repository
  construction.
- [ ] Memory runner behavior remains available without SQLAlchemy lifecycle
  semantics.
- [ ] Offer upsert and exact snapshot deduplication are protected by PostgreSQL
  constraints before concurrent production scheduling is enabled.
- [ ] First snapshot, decrease, increase, unchanged, equal-timestamp, and
  out-of-order semantics remain unchanged.
- [ ] Focused rollback, phase-order, scheduler, and idempotency tests pass.
- [ ] Ruff and MyPy pass for all touched modules without new broad ignores.
- [ ] No Telegram, frontend, FunPay, matching/comparator redesign, event bus,
  Redis, Celery, Kafka, or distributed lock is introduced.

## 19. Recommended First Implementation Commit

Recommended commit:

`refactor(pipeline): separate transactional processing phases`

This is the smallest safe first step because the current monolithic
`MarketplacePipeline.run()` cannot be wrapped in a database transaction without
also enclosing marketplace HTTP and AI generation. The commit should:

- expose normalized-offer ingestion separately;
- extract one provider-driven persistence/analysis phase returning in-memory
  events and counts;
- expose post-commit scoring/content separately;
- preserve existing algorithms and memory-backed behavior;
- add phase-order regression tests;
- introduce no session scope, transaction manager, migration, scheduler change,
  or new business rule.

Only after this phase boundary is proven should the next commit add the
PostgreSQL repository scope and `MarketplaceApplicationRunner`.
