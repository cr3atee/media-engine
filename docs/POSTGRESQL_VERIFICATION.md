# PostgreSQL Verification

## Status

PostgreSQL persistence, the EPIC 12 runtime, EPIC 13 transactional market-event
ingestion, durable scoring, generated content, publication-intent state, EPIC 14
delivery orchestration, EPIC 15 administration API, EPIC 16 tenant identity
foundation, EPIC 16 authentication/authorization boundary, and EPIC 16
tenant-scoped seller workflows are live-verified. EPIC 17 marketplace
integration persistence foundation is also live-verified. EPIC 16 and EPIC 17
verification used isolated PostgreSQL 17.10 databases without using a project or
production database. The current verified revision is
`0013_marketplace_credentials`.

## Verified Schema

- Revision `0005_add_persistence_integrity` applies, downgrades to `0004`, and
  re-applies successfully.
- Duplicate offers, duplicate snapshots, and orphan canonical references each
  stop migration `0005` without changing data.
- Offer stable identity is enforced by a partial unique index.
- Exact snapshot identity is enforced by a unique constraint.
- History and canonical lookup indexes exist.
- Canonical product references reject missing IDs and use
  `ON DELETE SET NULL`.
- Revision `0006_use_utc_timestamps` aligns active PostgreSQL columns with the
  UTC-aware application runtime and is reversible.
- Revision `0007_create_market_events` creates only durable market-event storage
  and successfully upgrades, downgrades to `0006`, and re-applies.
- Event deterministic identity is protected by
  `uq_market_events_identity_key`; exact persisted snapshot transitions are
  protected by `uq_market_events_snapshot_transition`.
- Previous and current snapshots use named `ON DELETE RESTRICT` foreign keys;
  the optional canonical-product reference uses `ON DELETE SET NULL`.
- Event lifecycle checks enforce valid state values, non-negative attempts,
  score/state consistency, complete claim leases, paired error fields, and
  positive optimistic versions.
- Pending/retry claims, expired leases, offer timelines, and canonical-product
  timelines have explicit indexes matching repository queries.
- `alembic check` reports no pending schema operations.
- Revision `0008_content_publications` creates immutable generated-content
  attempts and channel-independent publication intents. Offline SQL generation,
  live upgrade, downgrade to `0007`, and re-upgrade pass.
- Content and publication identity, active-attempt uniqueness, lifecycle payload,
  complete claim metadata, optimistic version, event/content lookup, and lease
  recovery rules are database constrained and indexed.
- Generated-content and publication foreign keys use `ON DELETE RESTRICT` so
  event/content audit history is not destroyed by cascade deletion.

## Verified Repositories

- Offer insert, update, optional-value preservation, marketplace isolation,
  nullable identity, canonical assignment, and `Decimal` precision pass.
- Price snapshot conflict suppression, ordering, latest/previous queries,
  out-of-order insertion, equal-timestamp tie-breaking, and marketplace
  isolation pass.
- Two-session offer and snapshot conflicts complete without leaving failed
  transactions.
- Memory and PostgreSQL repositories retain the same public async contract.
- `PostgresMarketEventRepository` preserves typed payload fields, exact snapshot
  identities, `Decimal`, UTC timestamps, enum values, claims, errors, and
  optimistic versions through explicit mapping.
- Repeated compatible event creation returns the existing row; incompatible
  immutable facts raise `RepositoryIdentityConflictError` without overwriting the
  stored event.
- Shared market-event contracts pass against both memory and PostgreSQL
  implementations.
- Focused PostgreSQL tests pass for concurrent creation, identity conflict,
  `FOR UPDATE SKIP LOCKED`, one-event contention, lease recovery, stale versions,
  outer rollback, and exact precision.
- Durable scoring claims only pending/retry-eligible rows. Active leases block
  other workers, while expired claims are exposed only to explicit recovery.
- Guarded scoring completion persists score and success state atomically and
  rejects stale claim tokens and optimistic versions.
- Transient retry state, terminal permanent failure, UTC timestamps, and score
  precision survive fresh sessions.
- Shared generated-content and publication contracts pass against memory and
  PostgreSQL repositories, including immutable attempt ordering, retries, review
  transitions, terminal-state protection, ambiguous publication state, stale
  claim tokens, and optimistic-version conflicts.
- PostgreSQL-specific tests verify two-session generation/publication contention,
  durable fresh-session round trips, unique idempotency, rollback, and atomic
  content/publication completion.

## Verified Transactions

- One repository scope supplies one `AsyncSession` to all repositories.
- Repositories do not commit independently.
- Event insertion and claim changes roll back with the caller-owned transaction.
- Event claims lock only the selection/update transaction; the repository scope
  is closed before deterministic scoring starts.
- Each scoring completion or failure uses a new short transaction. A completion
  rollback cannot falsely mark the event scored; lease recovery can make the
  retained claim retryable.
- Successful runner scope exit commits once.
- Offer, snapshot, deterministic processing, and commit failures roll back the
  complete run and skip post-commit work.
- Active ingestion ends after durable event commit and does not invoke the legacy
  in-memory scoring/content path.
- Active ingestion inserts offers, exact snapshots, and deterministic market
  events in one shared-session transaction.
- First observations, increases, unchanged prices, reverse chronology, and exact
  duplicate snapshots do not create price-drop events.
- Event insertion failure rolls back the offer, current snapshot, and event; no
  post-commit scoring/content runs.
- Equal external IDs on GGSEL and Playerok produce independent event identities.
- Exact ingestion replay creates no duplicate event row, and stored identity
  matches domain recomputation from exact snapshot facts.
- Content claims commit before AI execution. Provider calls run with no repository
  scope open; completion/failure uses a new short transaction.
- Generated text and publication intent commit atomically. A simulated completion
  transaction failure leaves the attempt claimed for recovery and creates no
  partial publication row.
- Expired generation claims become abandoned. Expired publication claims become
  ambiguous and cannot be automatically reclaimed for delivery.

## Remaining Limits

- Durable ingestion, scoring, and content processing are implemented as separate
  production-shaped services but are not yet composed in one process bootstrap.
- Telegram publication delivery is implemented and verified with mocked transport;
  guarded live test-chat delivery has not been performed.
- Scheduler overlap and multi-process coordination are not implemented.
- Null external IDs remain intentionally append-only.
- Legacy foundation tables remain present and inactive.

Complete evidence is recorded in `EPIC_12_FINAL_VERIFICATION.md`.
EPIC 13 Task 3 evidence is implemented by
`verify_epic13_market_events_postgres.py` and the shared/focused market-event
repository tests. EPIC 13 Task 4 ingestion evidence is implemented by
`verify_epic13_ingestion_postgres.py` and the focused marketplace event
integration tests. EPIC 13 Task 5 evidence is implemented by
`verify_epic13_event_processing_postgres.py`: all 14 live checks pass, covering
durable success, fresh sessions, duplicate suppression, transaction boundaries,
concurrency, retry, active leases, recovery, stale tokens, terminal failure, and
Scheduler delegation.
Task 6 evidence is implemented by
`verify_epic13_content_publication_postgres.py`: all 18 live checks pass, covering
migration, scored-event eligibility, committed claims, transaction-free AI,
durable success/failure/retry, fresh sessions, worker contention, rollback,
idempotency, ambiguous publication protection, and Scheduler delegation.

Final evidence is recorded in `EPIC_13_FINAL_VERIFICATION.md` and implemented by
`verify_epic13_end_to_end_postgres.py`. Clean migration, downgrade/re-upgrade,
schema constraints, fresh-session restart, idempotency, rollback, concurrency,
audit linkage, and complete Scheduler orchestration all pass. External delivery
remains intentionally unimplemented.

## EPIC 14 Task 2 Update

Telegram publication delivery orchestration is implemented on top of the
existing PostgreSQL publication repository without adding a migration. The
existing `publications` schema already stores channel, destination, claim token,
lease, attempt count, retry timestamp, external message ID, published timestamp,
safe processing error, and optimistic version.

The repository contract now supports generic channel-scoped claiming and an
optional attempt budget. PostgreSQL applies the channel predicate before
`FOR UPDATE SKIP LOCKED`, so a Telegram worker does not temporarily claim
non-Telegram publications.

`PublicationDeliveryService` uses short claim/read/completion repository scopes
and calls Telegram adapters outside database transactions. Confirmed success,
retryable failure, permanent failure, and ambiguous outcomes are persisted
through existing guarded publication transitions. Dry-run is read-only.

`scripts/verify_epic14_delivery_service_postgres.py` is the offline PostgreSQL
verification entry point for this task. In environments without an isolated
`EPIC14_DATABASE_URL`, it reports the missing prerequisite instead of fabricating
success. No live Telegram message is sent by this verification path.

## EPIC 14 Task 3 Update

The PostgreSQL verifier now includes additional final-verification checks for:

- due retry resumption;
- completion rollback after a successful adapter response;
- stale-claim recovery to `ambiguous` after that rollback;
- one-publication/two-worker claim exclusivity;
- token redaction of provider messages and client representations.

Task 3 PostgreSQL execution passed `39/39` checks against an isolated
`epic14_verify` database. The checks cover due retry resumption, completion
rollback, stale recovery, channel isolation, two-worker exclusivity, dry-run,
fresh-session persistence, transaction-free Telegram calls, Scheduler
delegation, and token redaction.

## EPIC 14 Task 3 Retry (2026-07-31)

Docker Desktop was started successfully and a temporary `postgres:17-alpine`
container exposed only `127.0.0.1:55432` for the isolated `epic14_verify`
database. `scripts/verify_epic14_delivery_service_postgres.py` passed `39/39`.
`alembic current` reported `0008_content_publications (head)`, `alembic check`
reported no new upgrade operations, and offline upgrade SQL generated all eight
migrations in `342` lines.

**EPIC 14 functionally complete; guarded live Telegram test-chat verification
not performed.**

## EPIC 15 Task 1 Read API

`scripts/verify_epic15_read_api_postgres.py` was executed against a temporary
isolated PostgreSQL 16 container and database named `epic15_verify`. It rebuilt
the isolated public schema, applied all migrations through
`0008_content_publications`, seeded durable records through existing repository
contracts, and exercised the real FastAPI ASGI application.

All `28/28` named checks passed: liveness, readiness, missing/invalid/valid API
key authentication, event/content/publication lists and details, typed
price-drop payloads, filters, deterministic pagination, safe destinations,
claim-token absence, sanitized errors, invalid cursors, UTC range validation,
request correlation, absence of mutation routes, absence of Telegram calls, and
fresh-session restart reads.

`alembic current` reported `0008_content_publications (head)`, `alembic check`
reported no new upgrade operations, and offline upgrade SQL generated
successfully through current head. Task 1 required no migration.

## EPIC 15 Task 2 Administration Mutations

`scripts/verify_epic15_admin_mutations_postgres.py` was executed against a
temporary isolated PostgreSQL 17.10 container and database named
`epic15_verification`. The verifier rebuilt the isolated public schema, applied
migrations through `0009_admin_actions`, exercised the real FastAPI ASGI
application, and performed no Telegram network calls.

All `26/26` named checks passed. The checks cover authentication failure,
secret redaction, content approval/rejection, publication retry/cancel,
ambiguous resolution as delivered/not delivered/cancelled, immutable audit
records, idempotent replay, fingerprint conflicts, optimistic version conflicts,
rollback atomicity, fresh-session persistence, concurrent duplicate
idempotency, and conflicting concurrent commands.

Alembic verification also passed:

- clean upgrade to `0009_admin_actions`;
- `alembic current` reported `0009_admin_actions (head)`;
- `alembic check` reported no new upgrade operations;
- downgrade to `0008_content_publications`;
- upgrade back to head;
- offline `upgrade head --sql` with `admin_actions` DDL;
- PostgreSQL catalog verification of `admin_actions` constraints, indexes, and
  idempotency uniqueness.

Focused Task 2 and repository contract tests passed `20/20`. Full Pytest passed
`307` tests with `54` expected skips. Ruff, Ruff format, and MyPy with
`--explicit-package-bases` passed.

## EPIC 15 Task 3 Operational Completion

Task 3 completed the operational administration API boundary:

- dashboard summary via a dedicated query repository;
- protected `/openapi.json`, `/docs`, and `/redoc`;
- public liveness and sanitized readiness with database and Alembic head checks;
- final PostgreSQL admin API verification.

The final verification used a temporary isolated PostgreSQL 17 container.
`scripts/verify_epic15_admin_api_postgres.py` passed `23/23` checks against
database `epic15_task3_verification` at revision `0009_admin_actions`.

Compatibility verifiers also passed:

- Task 1 read API verifier: `29/29`;
- Task 2 admin mutation verifier: `26/26`;
- EPIC 14 delivery verifier at current head: `39/39`.

Alembic current/check, downgrade to `0008_content_publications`, upgrade back to
head, offline upgrade SQL generation, and PostgreSQL catalog checks for
`admin_actions` constraints/indexes all passed.

Full Pytest passed `304` tests with `58` expected skips. MyPy checked `274`
source files with no issues. Ruff and Ruff format checks passed for touched
files.

## EPIC 16 Task 1 Tenant Identity Foundation

`scripts/verify_epic16_tenant_isolation_postgres.py` was executed against a
temporary isolated PostgreSQL 17.10 database named `epic16_verify`. The verifier
recreated the isolated public schema, applied migrations through
`0009_admin_actions`, seeded legacy tenant-blind rows, upgraded to
`0010_tenant_identity_foundation`, and exercised tenant-aware repository
primitives.

All `37/37` named checks passed. The checks cover identity tables, tenant-aware
constraints and indexes, deterministic legacy tenant creation, legacy backfill,
`NOT NULL` tenant ownership, same marketplace external IDs across tenants,
tenant-isolated offer reads, tenant-isolated price history, event identity v2
tenant separation, equivalent tenant events persisted independently, and
fresh-session persistence.

Alembic verification passed:

- clean upgrade to `0010_tenant_identity_foundation`;
- `alembic current` reported `0010_tenant_identity_foundation (head)`;
- `alembic check` reported no new upgrade operations;
- clean downgrade to `0009_admin_actions`;
- upgrade back to head;
- offline `upgrade head --sql` generation.

Focused tenant/repository tests passed. Full Pytest passed `307` tests with `58`
expected skips. MyPy checked `288` source files with no issues. Ruff and Ruff
format checks passed for EPIC 16 touched files.

Downgrading a populated multi-tenant database that already contains duplicate
tenant-scoped business identities back to the pre-tenant global uniqueness model
is not lossless and should be treated as a development rollback only. Clean
downgrade/upgrade lifecycle is verified.

## EPIC 16 Task 2 Authentication Boundary

`scripts/verify_epic16_auth_postgres.py` was executed against a temporary
isolated PostgreSQL 17.10 database named `epic16_auth_verify`. The verifier
recreated the isolated public schema, applied migrations through
`0011_auth_boundary`, seeded one user, tenant, membership, and password
credential, then exercised the real FastAPI authentication routes and durable
PostgreSQL repositories.

All `14/14` named checks passed. The checks cover invalid login and secret
redaction, successful login, `/api/v1/me`, tenant context and permission
resolution, refresh-token rotation, old refresh rejection, logout-driven access
session revocation, password-reset request enumeration safety, reset-token
hashing, password reset session revocation, credential rotation, role changes,
membership removal, and fresh-session persistence.

Alembic verification passed:

- `alembic current` reported `0011_auth_boundary (head)`;
- `alembic check` reported no new upgrade operations;
- downgrade to `0010_tenant_identity_foundation`;
- upgrade back to head;
- offline `upgrade head --sql` generation through `0011_auth_boundary`.

Focused auth/API tests passed. Full Pytest passed `313` tests with `58`
expected skips. MyPy checked `302` source files with no issues. Ruff and Ruff
format checks passed for touched files.

## EPIC 16 Task 3 Seller Workflows

EPIC 16 Task 3 implemented tenant-scoped seller workflow routes for event,
generated-content, publication, dashboard, content-review, and
publication-operation access. Read-side query contracts now support optional
tenant filtering, seller command contexts carry tenant and user actor
attribution, `admin_actions` idempotency lookup is tenant-scoped, and
PostgreSQL publication mapping preserves `tenant_id`.

`MarketplaceApplicationRunner` already carries a configured tenant context from
ingestion into parsed offers, snapshots, and durable event identities; focused
coverage now verifies this propagation through the memory-backed application
runner.

Offline verification passed:

- focused seller/admin/auth tests: `44 passed, 1 skipped`;
- focused runner/seller tests: `16 passed`;
- full Pytest: `318 passed, 58 skipped`;
- full MyPy: `305 source files`;
- Ruff and Ruff format for touched files;
- Alembic offline `upgrade head --sql` generation.

Live PostgreSQL verification later passed during EPIC 16 Task 4.

## EPIC 16 Task 4 Final Isolation Readiness

Task 4 verification used a temporary `postgres:17-alpine` container with
PostgreSQL 17.10 and isolated database `epic16_task4_verify` on
`127.0.0.1:55433`. No project or production database was used.

The following PostgreSQL verifiers passed:

- tenant isolation: `37/37`;
- authentication boundary: `14/14`;
- tenant-scoped seller workflows: `20/20`.

The seller workflow verifier covers tenant-scoped read access, cross-tenant
resource hiding, multi-tenant membership reads, tenant-scoped content and
publication lists, dashboard isolation, content approvals, command idempotency,
fingerprint conflicts, cross-tenant command blocking, tenant/user audit
attribution, publication retry, permission denial, preserved internal admin
behavior, fresh-session persistence, and rollback atomicity.

Alembic verification passed:

- clean upgrade through `0011_auth_boundary`;
- `alembic current` reported `0011_auth_boundary (head)`;
- `alembic check` reported no new upgrade operations;
- downgrade from `0011_auth_boundary` to `0010_tenant_identity_foundation`;
- upgrade back to head;
- offline `upgrade head --sql` generation.

Quality verification passed:

- focused EPIC 16 seller/auth/repository/runner tests:
  `48 passed, 1 skipped`;
- full Pytest: `318 passed, 58 skipped`;
- full MyPy: `305 source files`;
- Ruff and Ruff format checks for EPIC 16 touched files.

Full-repository Ruff and full-repository Ruff format still report pre-existing
issues outside EPIC 16 scope. They were not changed during Task 4.

## EPIC 17 Task 1 Marketplace Integration Foundation

Task 1 introduced tenant-owned marketplace integration metadata without storing
live credentials or plaintext secrets. It added the domain contract, repository
contract, memory repository, PostgreSQL repository, `RepositoryProvider` wiring,
SQLAlchemy metadata, and migration `0012_marketplace_integrations`.

`scripts/verify_epic17_marketplace_integrations_postgres.py` was executed
against a temporary `postgres:17-alpine` container with PostgreSQL 17.10 and
isolated database `epic17_task1_verify` on `127.0.0.1:55434`. No project or
production database was used.

All `12/12` verifier checks passed. The checks cover table creation,
constraints/indexes, tenant-scoped identity for external accounts and source
URLs, cross-tenant detail hiding, tenant-isolated lists, enabled-active
selection, updates, duplicate rejection within one tenant, fresh-session
persistence, and rollback atomicity.

Alembic verification passed:

- clean upgrade through `0012_marketplace_integrations`;
- `alembic current` reported `0012_marketplace_integrations (head)`;
- `alembic check` reported no new upgrade operations;
- downgrade from `0012_marketplace_integrations` to `0011_auth_boundary`;
- upgrade back to head;
- offline `upgrade head --sql` generation.

Quality verification passed:

- focused marketplace integration tests: `7 passed`;
- focused repository tests: `27 passed`;
- full Pytest: `325 passed, 58 skipped`;
- full MyPy: `312 source files`;
- Ruff and Ruff format checks for EPIC 17 touched files.

## EPIC 17 Task 2 Credential Metadata Boundary

Task 2 introduced opaque credential-reference metadata and redacted repository
responses for marketplace integrations. Live credentials and plaintext secrets
are still not stored or used.

The domain layer now exposes `MarketplaceCredentialMetadata`,
`CredentialRotationIntent`, `RedactedCredentialMetadata`, and
`SafeMarketplaceIntegration`. Repository credential-reference updates are
optimistic-version guarded and return only redacted safe DTOs.

Migration `0013_marketplace_credentials` adds credential-reference metadata
columns, state consistency checks, non-empty reference checks, rotation timestamp
ordering, credential version checks, and a credential lookup index.

`scripts/verify_epic17_marketplace_integrations_postgres.py` was executed
against a temporary `postgres:17-alpine` container with PostgreSQL 17.10 and
isolated database `epic17_task2_verify` on `127.0.0.1:55435`. No project or
production database was used.

All `18/18` verifier checks passed. The checks cover table existence,
constraints and indexes, credential metadata columns, tenant-scoped identity,
cross-tenant hiding, enabled-active selection, credential-reference persistence,
redacted update responses, stale version rejection, duplicate rejection,
fresh-session persistence, and rollback atomicity for integration and
credential-reference updates.

Alembic verification passed:

- clean upgrade through `0013_marketplace_credentials`;
- `alembic current` reported `0013_marketplace_credentials (head)`;
- `alembic check` reported no new upgrade operations;
- downgrade from `0013_marketplace_credentials` to
  `0012_marketplace_integrations`;
- upgrade back to head;
- offline `upgrade head --sql` generation.

Quality verification passed:

- focused marketplace integration repository tests: `11 passed`;
- full Pytest: `329 passed, 58 skipped`;
- full MyPy: `326 source files`;
- Ruff and Ruff format checks for EPIC 17 Task 2 touched files.
