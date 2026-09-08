# Changelog

## Purpose

This document records notable Project Passport updates.

## Unreleased

- Added runtime bootstrap foundation for memory/PostgreSQL repository scope and
  Scheduler construction without changing business services.
- Verified runtime bootstrap with focused tests, full Pytest, full MyPy, and
  focused Ruff/Ruff format checks; repository-wide Ruff debt remains unrelated.
- Added Scheduler multi-node lease foundation: domain contract, repository
  interface, memory/PostgreSQL lease repositories, provider wiring, migration
  `0014_scheduler_leases`, focused tests, PostgreSQL verifier, demo, and
  Scheduler documentation updates.
- Verified Scheduler lease foundation against isolated PostgreSQL 17: verifier
  `11/11`, Alembic current/check/downgrade/upgrade/offline SQL, focused tests
  `8 passed`, full Pytest `359 passed, 58 skipped`, full MyPy `344` source
  files, and focused Ruff/Ruff format checks.
- Added Scheduler bootstrap settings and factory helpers for memory/PostgreSQL
  lease configuration.
- Verified FunPay live listing ingestion through the existing HTTP stack:
  marketplace-local redirect handling now prevents empty `302` captures, the
  saved real listing response analyzes correctly, and readiness reports one
  snapshot-ready `ParsedOffer`.
- Verified Playerok live item-list ingestion through the public GraphQL
  `items` operation: the fetcher now downloads raw JSON, the pipeline produces
  20 real `ParsedOffer` objects, and extractor filtering excludes nested
  category/game objects. The Playerok adapter now applies a documented
  source-backed `RUB` fallback because the GraphQL item schema rejects a direct
  `currency` field while the official frontend bundle formats item price events
  as RUB; readiness now reports 20 snapshot-ready Playerok offers.
- Added strict marketplace saved-payload contract verification. The guard reuses
  the readiness checks and currently confirms GGSEL `60/60/60`, Playerok
  `20/20/20`, and FunPay `1/1/1` raw/parsed/snapshot-ready counts.
- Added final core readiness review: MediaEngine is ready as a reusable
  multi-node backend core, with remaining gaps focused on production runtime
  bootstrap, live polling monitoring, credential retrieval, production AI
  wiring, guarded live Telegram verification, CI-portable marketplace fixtures,
  and full Ruff cleanup.
- Started EPIC 18 marketplace data reliability work: added offline readiness
  verification, marketplace capture checklist, GGSEL absolute URL normalization,
  GGSEL extractor/normalizer contract coverage, Playerok response analysis
  tooling, Playerok extractor contract coverage, and FunPay
  fetch/extract/normalize/analyzer boundaries.
- Implemented EPIC 17 Task 4 Scheduler integration selection: enabled
  tenant-owned marketplace integrations are selected through an
  orchestration-only service, inactive tenants are excluded, and Scheduler
  delegates through `EnabledMarketplaceIntegrationsJob`.
- Completed EPIC 17 final verification against isolated PostgreSQL 17.10
  database `epic17_final_verify`: integration persistence/credential boundary
  `18/18`, seller integration API `16/16`, Scheduler integration selection
  `10/10`, focused tests `18 passed`, demo execution, full Pytest
  `336 passed, 58 skipped`, full MyPy `335` source files, Ruff, Ruff format,
  Alembic current/check/downgrade/upgrade, and offline Alembic SQL generation.
- Implemented EPIC 17 Task 3 seller integration API: tenant-scoped routes for
  listing, reading, creating, updating, disabling, and rotating credential
  references for marketplace integrations.
- Verified EPIC 17 Task 3 against isolated PostgreSQL 17.10 database
  `epic17_task3_verify`: seller API verifier `16/16`, focused API/repository
  tests `16 passed`, full Pytest `334 passed, 58 skipped`, full MyPy `331`
  source files, Alembic current/check/downgrade/upgrade/offline SQL, and focused
  Ruff/Ruff format checks.
- Implemented EPIC 17 Task 2 credential metadata and redaction boundary:
  opaque credential-reference metadata, redacted safe DTOs, audit-safe rotation
  intent, memory/PostgreSQL repository updates, SQLAlchemy metadata, and
  migration `0013_marketplace_credentials`.
- Verified EPIC 17 Task 2 against isolated PostgreSQL 17.10 database
  `epic17_task2_verify`: verifier `18/18`, Alembic clean upgrade/current/check/
  downgrade/upgrade/offline SQL, focused marketplace integration repository
  tests `11 passed`, full Pytest `329 passed, 58 skipped`, full MyPy `326`
  source files, and focused Ruff/Ruff format checks.
- Implemented EPIC 17 Task 1 marketplace integration foundation: tenant-owned
  integration domain contract, repository interface, memory/PostgreSQL
  repositories, `RepositoryProvider` wiring, SQLAlchemy metadata, and migration
  `0012_marketplace_integrations`.
- Verified EPIC 17 Task 1 against isolated PostgreSQL 17.10 database
  `epic17_task1_verify`: verifier `12/12`, Alembic clean upgrade/current/check/
  downgrade/upgrade/offline SQL, focused tests, full Pytest
  `325 passed, 58 skipped`, full MyPy `312` source files, and focused
  Ruff/Ruff format checks.
- Added EPIC 17 marketplace integrations and credentials specification,
  defining the tenant-owned integration boundary, credential redaction
  requirements, PostgreSQL schema direction, repository/API/Scheduler
  boundaries, verification requirements, and implementation breakdown.
- Completed EPIC 16 Task 4 final isolation verification against a temporary
  isolated PostgreSQL 17.10 database `epic16_task4_verify`: tenant isolation
  verifier `37/37`, auth verifier `14/14`, and seller workflow verifier `20/20`
  passed.
- Verified EPIC 16 Task 4 quality: focused EPIC16 tests `48 passed, 1 skipped`,
  full Pytest `318 passed, 58 skipped`, full MyPy `305` source files, Alembic
  clean upgrade/current/check/downgrade/upgrade/offline SQL, and focused
  Ruff/Ruff format checks.
- Implemented EPIC 16 Task 3 tenant-scoped seller workflow routes for existing
  event, generated-content, publication, dashboard, content-review, and
  publication-operation workflows.
- Added tenant-aware seller command audit attribution: seller commands carry
  tenant/user actor context, request fingerprints include tenant and actor type,
  and `admin_actions` idempotency lookup is tenant-scoped.
- Fixed PostgreSQL publication mapping to preserve `tenant_id`, aligning it with
  memory publication repository behavior.
- Added `scripts/verify_epic16_seller_workflows_postgres.py`, guarded by
  isolated `EPIC16_DATABASE_URL` and refusing non-`epic16_*` database names.
- Verified EPIC 16 Task 3 offline: focused seller/admin/auth tests, marketplace
  runner tenant propagation coverage, full Pytest `318 passed, 58 skipped`,
  full MyPy `305` source files, Ruff, Ruff format, and Alembic offline SQL.
- Previously recorded the Task 3 live PostgreSQL verification blocker; Task 4
  has now closed that blocker with isolated PostgreSQL verification.
- Implemented EPIC 16 Task 2 authentication and authorization boundary:
  durable password credentials, hashed refresh sessions, hashed password reset
  tokens, short-lived signed access tokens, login/refresh/logout/reset routes,
  `/api/v1/me`, tenant context lookup, centralized `Permission`, and
  `AuthorizationService`.
- Added migration `0011_auth_boundary` after
  `0010_tenant_identity_foundation` for `user_credentials`, `auth_sessions`,
  and `password_reset_tokens`.
- Completed EPIC 16 Task 2 live PostgreSQL verification against isolated
  PostgreSQL 17.10 database `epic16_auth_verify`: auth verifier passed `14/14`,
  Alembic current/check passed at `0011_auth_boundary`, downgrade to
  `0010_tenant_identity_foundation` and upgrade back to head passed, and
  offline upgrade SQL generated.
- Verified EPIC 16 Task 2 quality: focused auth/API tests, full Pytest `313
  passed, 58 skipped`, full MyPy `302` source files, Ruff, and Ruff format for
  touched files.
- Completed EPIC 16 Task 1 live PostgreSQL verification against isolated
  PostgreSQL 17.10 database `epic16_verify`: tenant isolation verifier passed
  `37/37`, Alembic current/check passed at
  `0010_tenant_identity_foundation`, clean downgrade to `0009_admin_actions`
  and upgrade back to head passed, and offline upgrade SQL generated.
- Fixed EPIC 16 PostgreSQL verification defects exposed by live execution:
  legacy seed timestamps now match pre-tenant timestamp columns, migration
  binds the deterministic legacy tenant as a UUID, and tenant identity migration
  uses `pg_temp` for temporary SQL helper functions.
- Implemented EPIC 16 Task 1 tenant identity foundation locally: tenant/user/
  membership domain contracts, tenant-aware repository primitives, deterministic
  legacy tenant ownership, tenant-scoped persistence constraints, and event
  identity v2 tenant inputs.
- Added migration `0010_tenant_identity_foundation` after `0009_admin_actions`
  to create identity tables, backfill legacy tenant ownership, convert durable
  tenant-owned rows to `NOT NULL`, and replace global business uniqueness with
  tenant-scoped constraints and indexes.
- Added `scripts/verify_epic16_tenant_isolation_postgres.py`; live PostgreSQL
  verification requires an isolated `EPIC16_DATABASE_URL` targeting an
  `epic16_*` database and refuses to fabricate success when that prerequisite is
  missing.
- Verified EPIC 16 Task 1 quality: focused tests, full Pytest `307 passed, 58
  skipped`, full MyPy `288` source files, Ruff, Ruff format, Alembic
  current/check, clean downgrade/upgrade, and offline SQL generation through
  head.
- Completed EPIC 15 Task 3 operational administration API completion with a
  bounded dashboard summary, dedicated dashboard query repository, protected
  OpenAPI/Swagger/ReDoc routes, and expanded sanitized readiness.
- Added final EPIC 15 PostgreSQL admin API verification:
  `scripts/verify_epic15_admin_api_postgres.py` passed `23/23`.
- Updated Task 1 read API verifier for the final admin API surface and protected
  docs; it passed `29/29`.
- Confirmed Task 2 verifier `26/26` and EPIC 14 compatibility verifier `39/39`
  against isolated PostgreSQL 17 databases at current migration head.
- Verified EPIC 15 final quality: full Pytest `304 passed, 58 skipped`, MyPy
  `274` source files, Ruff, Ruff format, Alembic current/check,
  downgrade/upgrade, offline SQL, and `admin_actions` catalog checks.
- Implemented EPIC 15 Task 2 guarded administration commands for content
  approval/rejection, publication retry/cancel, and ambiguous publication
  resolution, with immutable `admin_actions` audit persistence and replay-safe
  idempotency.
- Added focused Task 2 service, API, repository, and PostgreSQL-guarded verifier
  coverage.
- Completed isolated EPIC 15 Task 2 PostgreSQL verification on PostgreSQL 17.10:
  `26/26` verifier checks passed, including approve/reject, retry/cancel,
  ambiguous delivered/not-delivered/cancelled resolution, audit/idempotency,
  optimistic concurrency, rollback, fresh-session persistence, concurrent
  commands, and no Telegram network calls.
- Verified EPIC 15 Task 2 Alembic lifecycle through `0009_admin_actions`,
  downgrade to `0008`, upgrade back to head, offline SQL, and PostgreSQL catalog
  checks for `admin_actions` constraints, indexes, and idempotency uniqueness.
- Implemented EPIC 15 Task 1 read-only administration API for durable events,
  generated content, publications, related-resource reads, and health probes.
- Added fail-closed `X-Admin-API-Key` authentication, OpenAPI security metadata,
  bounded request correlation, stable sanitized errors, typed UTC filters, and
  signed deterministic keyset cursors.
- Added SQLAlchemy-independent query contracts with memory and PostgreSQL
  implementations returning immutable safe projections rather than ORM rows.
- Verified EPIC 15 Task 1 with 27 focused tests, 28 isolated PostgreSQL checks,
  full Pytest, strict MyPy, Ruff, Ruff format, and Alembic current/check/offline
  SQL.
- Added EPIC 14 Task 3 guarded live Telegram verification script with safe
  offline default mode, exact test-chat confirmation, allowlist checks, and no
  default network call.
- Expanded EPIC 14 PostgreSQL verifier with due-retry resumption,
  completion-rollback recovery, stale-claim recovery, one-publication/two-worker
  claim exclusivity, and token-redaction checks.
- Recorded that final EPIC 14 PostgreSQL/live verification is not complete in
  the current environment because no isolated PostgreSQL runtime or live
  Telegram credentials/test chat were available.
- Implemented EPIC 14 Task 2 durable Telegram publication delivery
  orchestration without live sending.
- Added generic channel-scoped publication claims and attempt-budget filtering
  for memory and PostgreSQL publication repositories.
- Added `PublicationDeliveryService` with short claim/read/completion scopes,
  retry/backoff policy, success, permanent failure, retryable failure, ambiguous
  outcome handling, and read-only dry-run.
- Added `PendingPublicationDeliveryJob` as an orchestration-only Scheduler job.
- Added focused delivery-service tests, PostgreSQL-guarded verification, and
  documentation updates for live Task 3 requirements.
- Completed final EPIC 13 production-shaped verification against isolated
  PostgreSQL 17.10: 83 end-to-end checks passed from ingestion through durable
  publication intent.
- Verified restart recovery, idempotency, rollback, multi-worker contention,
  short transaction boundaries, audit linkage, and orchestration-only Scheduler
  execution.
- Updated legacy EPIC 13 live scripts for migration head `0008` and restrictive
  downstream foreign keys; removed two obsolete MyPy ignore comments.
- Added revision `0008_content_publications` for immutable generated-content
  attempts and channel-independent publication intents.
- Added memory/PostgreSQL generated-content and publication repositories to
  `RepositoryProvider` with shared behavioral contracts.
- Added durable content processing with committed claims, transaction-free AI,
  atomic content/publication completion, bounded retry, safe persisted errors,
  and stale-claim recovery.
- Added Scheduler jobs for pending content generation and stale
  content/publication claim recovery without external delivery logic.
- Added PostgreSQL contention, rollback, fresh-session, retry, and recovery tests
  plus an 18-check live verification.
- Removed the inactive duplicate price detector and `app/core/events.py` hierarchy
  after redirecting the remaining legacy demo import to the active detector.
- Removed the unreferenced direct marketplace post-commit scoring/content helper,
  leaving one durable claim-based content-generation path.
- Added durable bounded market-event claiming and scoring through
  `EventProcessingService`.
- Added the explicit durable-event scoring adapter, immutable processing result
  DTOs, safe error categories, bounded exponential retry policy, and idempotent
  stale-claim recovery.
- Added Scheduler jobs for pending scoring and stale scoring-claim recovery while
  preserving orchestration-only boundaries.
- Stopped active ingestion from invoking the legacy immediate scoring/content
  path before durable claims.
- Added memory, PostgreSQL, concurrency, rollback, retry/recovery, and Scheduler
  coverage plus a 14-check live PostgreSQL verification.
- Integrated deterministic market-event persistence into the existing ingestion
  transaction.
- Added event repositories to memory/PostgreSQL providers and preserved one shared
  PostgreSQL session per run.
- Added a Decimal-safe event builder, exact snapshot identity mapping, idempotent
  insertion, rollback coverage, and a temporary post-commit legacy event adapter.
- Added focused memory/PostgreSQL integration tests and live EPIC 13 Task 4
  verification.
- Completed EPIC 12 live verification against PostgreSQL 17.10.
- Verified migration preflight, constraints, indexes, concurrency, FK behavior,
  transaction rollback, retry, Scheduler execution, and practical overlap.
- Added reversible UTC-aware timestamp migration `0006_use_utc_timestamps` after
  live `asyncpg` verification exposed a timezone schema mismatch.
- Recorded the final EPIC 12 acceptance checklist and production limitations.
- Migrated active runtime price history to `RepositoryProvider.price_history`.
- Removed the duplicate standalone `PriceHistoryService`.
- Documented deterministic snapshot ordering and duplicate behavior.
- Updated scheduler and PostgreSQL verification paths for repository-backed history.
- Synchronized Project Passport with the current implementation state.
- Documented completed Matching Engine components.
- Documented `MatchingService`.
- Documented repository contracts.
- Documented in-memory repositories.
- Documented `RepositoryProvider`.
- Documented `MarketplacePipeline` parsed offer persistence through `RepositoryProvider`.
- Documented current known gaps around GGSEL price normalization, price history persistence, Telegram delivery, and production AI wiring.

## Previous Notes

- Initial Project Passport structure was created.
- First local Architecture Review was recorded for the price-change processing flow.
