# EPIC 12 Final Verification

Date: 2026-07-29

## 1. Executive Result

**EPIC 12 verified and complete.**

The async repository contract, PostgreSQL repository implementations,
repository-backed price history, shared transaction scope, application runner,
race-safe persistence rules, retry behavior, and Scheduler integration were
verified against PostgreSQL 17.10.

One live defect was found: active ORM models supplied UTC-aware datetimes to
timezone-naive PostgreSQL columns. Revision `0006_use_utc_timestamps` corrects
the active schema without rewriting existing migrations. The complete live
verification passed after that correction.

EPIC 12 completion does not mean production readiness. Event and publication
state are not durable, and delivery idempotency is not implemented.

## 2. Environment

- PostgreSQL: `17.10`, image `postgres:17-alpine`.
- Connection mode: host process to Compose PostgreSQL through
  `localhost:55432`.
- Compose project: `mediaengine-epic12`, isolated from the default project.
- Test databases: `epic12_clean`, three disposable `epic12_preflight_*`
  databases, and `epic12_runtime`.
- Application credentials were supplied through environment variables and are
  not recorded here.
- Verified head revision: `0006_use_utc_timestamps`.
- Persistence-integrity revision under test: `0005_add_persistence_integrity`.

The Windows PostgreSQL service on port `5433` belongs to another application and
was intentionally not used. No production or existing MediaEngine database was
used.

## 3. Migration Results

Clean database verification:

- upgraded from base through `0005_add_persistence_integrity`;
- confirmed revision `0005`;
- inspected the resulting PostgreSQL schema;
- downgraded `0005` to `0004_create_price_snapshots`;
- re-applied `0005` successfully;
- applied `0006_use_utc_timestamps`;
- downgraded one revision from `0006` to `0005` and re-applied head;
- `alembic check` reported `No new upgrade operations detected`;
- offline upgrade and downgrade SQL generation succeeded.

Preflight verification used independent databases at revision `0004`:

- duplicate non-null offer identity stopped `0005` with
  `Duplicate offer identities block Task 5 migration`;
- exact duplicate snapshot identity stopped `0005` with
  `Exact duplicate snapshots block Task 5 migration`;
- orphan canonical reference stopped `0005` with
  `Orphan canonical references block Task 5 migration`.

Each failed migration remained at `0004`. Counts remained two duplicate offer
rows, two duplicate snapshot rows, and one orphan row respectively. No preflight
case removed or changed application data.

## 4. Constraint and Index Verification

Verified directly from PostgreSQL metadata:

- `uq_offers_marketplace_external_id_not_null`: unique partial B-tree index on
  `(marketplace, external_id)` with `external_id IS NOT NULL`;
- `ix_offers_canonical_product_id`: B-tree lookup index;
- `uq_price_snapshots_exact_identity`: unique constraint on marketplace,
  external ID, timestamp, price, and currency;
- `ix_price_snapshots_history_order`: B-tree index on marketplace, external ID,
  timestamp, and record ID;
- `fk_offers_canonical_product_id_canonical_products`: foreign key to
  `canonical_products.id` with `ON DELETE SET NULL`.

Revision `0006` was also verified to create `timestamp with time zone` for
`offers.created_at`, `canonical_products.created_at`, and
`price_snapshots.collected_at`.

## 5. Repository Verification

Offer repository:

- initial insert and domain mapping passed;
- `Numeric(12, 2)` preserved `Decimal('790.12')` exactly;
- the same `(marketplace, external_id)` upserted one logical row;
- mutable non-null values updated;
- incoming optional `None` did not erase existing meaningful values;
- a supplied canonical product ID updated correctly;
- identical external IDs on GGSEL and Playerok remained independent;
- multiple null external IDs persisted with the approved append-only behavior.

Price-history repository:

- first exact insert returned `True`;
- repeated exact insert returned `False`;
- the transaction remained usable after conflict suppression;
- same timestamp with different price persisted both rows;
- same price with a later timestamp persisted both rows;
- out-of-order inserts returned in chronological order;
- equal timestamps used persistent record ID as the deterministic tie-breaker;
- latest, previous, and marketplace-isolation semantics matched the contract.

Canonical references:

- valid and null references persisted;
- invalid canonical IDs were rejected;
- deleting a canonical product retained the offer and set its reference to null.

## 6. Concurrency Verification

Two independent `AsyncSession` instances upserting the same non-null offer
identity both completed. PostgreSQL retained one row. The second writer waited
for the first transaction and then applied the repository's non-null update
rules, so the controlled final value was deterministic.

Two independent sessions inserting the same exact snapshot both completed. One
`add()` returned `True`, one returned `False`, one row remained, and the losing
transaction stayed usable. Two non-identical snapshots inserted concurrently
both persisted.

A practical same-process overlap of two complete application runs retained one
logical offer and one new exact snapshot. PostgreSQL offer-upsert serialization
resulted in one observed event and one content item across the two runs.

These constraints protect persisted offer and snapshot rows. They are not a
general event or publication idempotency mechanism.

## 7. Transaction Verification

- Offer, canonical-product, and price-history repositories received the exact
  same `AsyncSession` in one scope.
- Repository writes were invisible to another session before scope exit.
- Successful scope exit committed the writes.
- Exceptional scope exit rolled them back.
- One controlled runner execution produced exactly one observed commit.
- Content generation observed committed rows, proving it ran after commit.
- `MarketplaceRunResult` exposed no SQLAlchemy session or ORM object.
- Controlled offer-write, snapshot-write, and deterministic event failures
  rolled back all writes from the run and skipped post-commit content.
- A database-level deferred uniqueness violation forced failure at commit; the
  runner propagated the failure, rolled back application writes, skipped
  content, and left the session without an active transaction.
- A forced content-provider failure happened after commit; offer and snapshot
  rows remained durable and the result recorded the error.

## 8. Retry Verification

- Retrying the same input after a rolled-back run succeeded with a fresh scope.
- Retrying after success upserted the offer, suppressed the exact snapshot, and
  created no false event.
- Retrying after post-commit content failure remained persistence-idempotent.
  It did not regenerate content because the persisted snapshot no longer
  produced a new event.

The last behavior prevents a duplicate sequential publication but also means a
failed publication is not recovered. Durable publication state is required for
reliable retry.

## 9. Scheduler Verification

`SchedulerService` executed a real `GGSELJob` through a PostgreSQL-backed
`MarketplaceApplicationRunner`:

- the first controlled application call failed;
- Scheduler retried it once;
- the retry entered the runner-owned PostgreSQL scope and succeeded;
- a permanently failing Playerok job exhausted its retry and was reported as
  failed;
- Scheduler continued and executed GGSEL again;
- persisted history made the repeated exact observation idempotent;
- successful, failed, and retry statistics matched the observed executions;
- graceful shutdown completed.

Jobs did not create sessions or repositories. Scheduler remained an
orchestration layer.

## 10. Quality Results

- Focused Ruff for all EPIC 12 verification and defect-fix files: passed.
- Strict MyPy: passed, `105` source files.
- Pytest: passed, `47` tests.
- Live PostgreSQL verification script: passed, `89` checks.
- Alembic live upgrade/downgrade/check: passed.
- Alembic offline upgrade/downgrade SQL generation: passed.
- Memory repository demo: passed.
- Memory RepositoryProvider demo: passed.
- Memory Scheduler end-to-end demo: passed.
- Existing PostgreSQL end-to-end smoke demo: passed after revision `0006`.

Full `ruff check .` still reports `69` pre-existing, non-EPIC-12 violations.
They were not changed under the verification defect-fix policy:

- import/order issues in migration `0001`, `app/ai/prompts/price_drop.py`,
  `app/database/session.py`, `app/main.py`, and legacy demos;
- modern typing/enum issues in catalog, comparator, core, domain, matching, and
  parser foundation modules;
- unused comparator import;
- line-length issues in database, GGSEL, and older demo files;
- module-import-after-path-bootstrap findings across older demo scripts.

All files added or changed for this final EPIC 12 task pass Ruff.

## 11. Defects Found and Fixed

### UTC timestamp schema mismatch

Live PostgreSQL rejected repository writes because the application supplies
UTC-aware datetimes while the active columns were `timestamp without time zone`.

Fix:

- active ORM timestamp columns now declare `DateTime(timezone=True)`;
- revision `0006_use_utc_timestamps` converts existing active values by treating
  them as UTC and is fully reversible;
- a metadata regression test verifies all three active columns remain
  timezone-aware.

No business logic or repository interface changed.

## 12. Remaining Limitations

- Scheduler has no explicit same-job overlap guard and no distributed lock.
- Multiple scheduler processes are not coordinated.
- Market events are not persisted and have no durable identity.
- Content-generation and publication status are not persisted.
- A post-commit content failure cannot be reliably resumed.
- Database constraints do not guarantee Telegram/content delivery idempotency.
- Live marketplace response stability remains outside this deterministic
  PostgreSQL verification.
- Production AI is not verified in the application flow.
- Telegram delivery is not implemented.
- Structured operational metrics, tracing, and alerting are not implemented.
- Null offer external IDs intentionally remain append-only and cannot be
  deduplicated by the approved stable identity.
- Legacy foundation tables remain present but unused by active repositories.
- Full-project Ruff debt remains outside EPIC 12.

The exact next reliability requirement is durable event and publication state
with stable event identity, status transitions, and idempotent delivery claims.

## 13. EPIC 12 Acceptance Checklist

- [x] One async convention is used by all repository contracts.
- [x] Memory and PostgreSQL repositories implement the same async contracts.
- [x] PostgreSQL repositories need no override-suppression comments.
- [x] Business services await repository calls.
- [x] `RepositoryProvider.price_history` is the active runtime path.
- [x] The standalone runtime `PriceHistoryService` is removed.
- [x] A PostgreSQL-backed marketplace application run completes.
- [x] Repeated runs do not create duplicate stable offers.
- [x] Repeated exact snapshots do not create false events.
- [x] Scheduler invokes the async application runner and reports status.
- [x] Transaction rollback prevents partial repository writes.
- [x] HTTP/normalization runs before the transaction.
- [x] Scoring/content runs after commit.
- [x] Matching, comparator, normalization, and deterministic calculations remain
  database-independent.
- [x] No Telegram, frontend, FunPay, event bus, queue, or unrelated product work
  was introduced.
- [x] Persistence constraints and two-session conflicts are live-verified.
- [x] Migration preflight rejects unsafe existing data without silent mutation.

## 14. Production Readiness

Verified for development:

- async repository interchangeability;
- memory and PostgreSQL repository semantics;
- migrations, constraints, indexes, and UTC timestamp handling;
- one transaction per bounded application run;
- rollback, retry, and Scheduler orchestration.

Verified for a PostgreSQL-backed MVP foundation:

- deterministic prepared marketplace input through persistence, comparison,
  history, event construction, scoring, and post-commit content;
- repeated sequential and controlled overlapping persistence behavior.

Not production-ready:

- durable events/publications;
- publication retry and idempotency;
- multi-process Scheduler coordination;
- production observability;
- production AI and Telegram delivery;
- externally stable marketplace ingestion.

## 15. Recommended Next EPIC

**Persistent Market Events and Publication State**

This should introduce durable event identity, event persistence,
content-generation status, publication status, retry after post-commit failure,
and protection from duplicate content or Telegram delivery. It should consume
the completed EPIC 12 transaction boundary without moving delivery into the
marketplace database transaction.
