# Roadmap

## Purpose

This document tracks only work that is reflected by the current repository state.

## Completed

- Project foundation.
- Configuration foundation.
- Database foundation.
- Alembic foundation.
- Domain events foundation.
- Pipeline foundation.
- GGSEL response analysis.
- GGSEL raw product extraction from saved HTML payloads.
- Typed raw marketplace offer model.
- Parsed offer normalization boundary.
- Canonical product domain model.
- Matching Engine preprocessing.
- Matching Engine similarity scoring.
- Matching Engine confidence classification.
- MatchingService.
- Repository contracts.
- In-memory repositories.
- RepositoryProvider.
- MarketplacePipeline parsed offer persistence through RepositoryProvider.
- PostgreSQL repository implementations.
- Async repository contracts for memory and PostgreSQL backends.
- Repository-backed runtime price history.
- Shared PostgreSQL session and transaction scope per marketplace run.
- `MarketplaceApplicationRunner` transaction and post-commit boundary.
- Race-safe offer upsert and exact snapshot conflict suppression.
- PostgreSQL constraints, indexes, canonical-product FK, and UTC timestamps.
- Live PostgreSQL migration, concurrency, rollback, retry, and Scheduler
  verification for EPIC 12.
- Persistent market-event domain contracts and deterministic identity.
- Memory and PostgreSQL market-event repositories.
- Atomic offer/snapshot/event ingestion through `RepositoryProvider.events`.
- Live PostgreSQL verification of event identity, replay, rollback, marketplace
  isolation, and post-commit compatibility.
- Durable bounded market-event claiming and scoring persistence.
- Guarded scoring completion with claim-token and optimistic-version conflicts.
- Bounded retry/backoff and idempotent stale scoring-claim recovery.
- Scheduler scoring and stale-recovery jobs that delegate only to
  `EventProcessingService`.
- Live PostgreSQL verification of scoring transactions, concurrent workers,
  retry/recovery, terminal failure, and Scheduler delegation.
- Generated-content and publication domain contracts with shared memory and
  PostgreSQL repository behavior.
- Migration `0008_content_publications` with reversible live verification.
- Durable content generation outside repository transactions with immutable
  attempts, bounded retry, and stale-claim recovery.
- Atomic generated-content completion and idempotent channel-independent
  publication-intent creation.
- Scheduler jobs for content processing and stale content/publication recovery.
- Removal of the inactive duplicate price detector and event hierarchy after
  targeted reference verification.
- An 18-check live PostgreSQL content/publication verification.
- Final 83-check production-shaped EPIC 13 PostgreSQL verification covering the
  complete ingestion-to-publication-intent lifecycle.
- Telegram delivery contracts, plain-text formatter, direct Bot API client, and
  offline adapter verification.
- Channel-scoped publication claims for memory and PostgreSQL repositories.
- Durable `PublicationDeliveryService` with short claim/read/completion scopes,
  retry/backoff policy, permanent failure handling, ambiguous-state persistence,
  and read-only dry-run.
- `PendingPublicationDeliveryJob` that delegates bounded delivery processing
  without owning repositories or Telegram HTTP calls.
- Guarded live Telegram verification script with exact test-chat confirmation
  and safe offline default mode.
- Expanded EPIC 14 PostgreSQL verifier checks for retry resumption,
  completion-rollback recovery, one-publication/two-worker claim exclusivity,
  and token redaction.
- EPIC 14 final PostgreSQL verification: `39/39` checks at revision `0008`.
- EPIC 15 Task 1 authenticated read-only administration API for events,
  generated content, and publications.
- SQLAlchemy-independent administration query contracts and PostgreSQL query
  implementations with typed filters and deterministic keyset pagination.
- Stable API errors, request correlation IDs, API-key OpenAPI security, and
  liveness/readiness endpoints.
- EPIC 15 PostgreSQL read verification: `28/28` checks with no Telegram calls.
- EPIC 15 Task 2 guarded administration commands for content approve/reject,
  publication retry/cancel, and ambiguous resolution.
- Immutable `admin_actions` audit persistence with migration
  `0009_admin_actions`, memory/PostgreSQL repositories, idempotency, optimistic
  concurrency, and transaction rollback verification.
- EPIC 15 Task 2 PostgreSQL verification: `26/26` checks on PostgreSQL 17.10 at
  revision `0009_admin_actions`.
- EPIC 15 Task 3 operational completion: bounded admin dashboard summary,
  protected OpenAPI/Swagger/ReDoc, expanded sanitized readiness, and final
  PostgreSQL admin API verification.
- EPIC 15 final verification: Task3 `23/23`, Task1 `29/29`, Task2 `26/26`,
  EPIC14 compatibility `39/39`, full Pytest `304 passed, 58 skipped`, MyPy
  `274` source files, Ruff, Ruff format, and Alembic lifecycle.
- EPIC 16 Task 1 tenant identity foundation: durable `User`, `Tenant`,
  `Membership`, deterministic legacy tenant backfill, tenant-aware repository
  primitives, tenant-scoped constraints/indexes, and event identity v2 inputs.
- EPIC 16 Task 1 PostgreSQL verification: tenant isolation `37/37`, full Pytest
  `307 passed, 58 skipped`, MyPy `288` source files, Ruff, Ruff format, and
  Alembic lifecycle through `0010_tenant_identity_foundation`.
- EPIC 16 Task 2 authentication and authorization boundary: durable password
  credentials, refresh sessions, password reset tokens, signed access tokens,
  login/refresh/logout/reset routes, `/api/v1/me`, tenant context lookup,
  `AuthenticatedPrincipal`, `TenantContext`, `Permission`, and
  `AuthorizationService`.
- EPIC 16 Task 2 PostgreSQL verification: auth boundary `14/14`, full Pytest
  `313 passed, 58 skipped`, MyPy `302` source files, Ruff, Ruff format, and
  Alembic lifecycle through `0011_auth_boundary`.
- EPIC 16 Task 3 tenant-scoped seller workflow routes for existing event,
  generated-content, publication, dashboard, content-review, and
  publication-operation workflows.
- EPIC 16 Task 3 tenant-aware seller command audit attribution and tenant-scoped
  admin-action idempotency.
- EPIC 16 Task 3 offline verification: focused seller/admin/auth tests,
  marketplace runner tenant propagation coverage, full Pytest `318 passed, 58
  skipped`, MyPy `305` source files, Ruff, Ruff format, and Alembic offline SQL
  generation.
- EPIC 16 Task 4 final isolation verification: tenant isolation `37/37`, auth
  boundary `14/14`, seller workflows `20/20`, full Pytest `318 passed, 58
  skipped`, MyPy `305` source files, Alembic lifecycle, and focused Ruff/format
  checks against isolated PostgreSQL 17.10.
- EPIC 17 marketplace integrations and credentials specification.
- EPIC 17 Task 1 marketplace integration foundation: domain contract,
  repository contract, memory/PostgreSQL repositories, provider wiring,
  migration `0012_marketplace_integrations`, live PostgreSQL verifier `12/12`,
  full Pytest `325 passed, 58 skipped`, MyPy `312` source files, Alembic
  lifecycle, and focused Ruff/format checks.
- EPIC 17 Task 2 credential metadata and redaction boundary: opaque credential
  reference metadata, redacted safe DTOs, audit-safe rotation intent,
  memory/PostgreSQL repository updates, migration
  `0013_marketplace_credentials`, live PostgreSQL verifier `18/18`, full Pytest
  `329 passed, 58 skipped`, MyPy `326` source files, Alembic lifecycle, and
  focused Ruff/format checks.
- EPIC 17 Task 3 seller integration API: tenant-scoped routes for listing,
  reading, creating, updating, disabling, and rotating credential references for
  marketplace integrations, live PostgreSQL verifier `16/16`, full Pytest
  `334 passed, 58 skipped`, MyPy `331` source files, Alembic lifecycle, and
  focused Ruff/format checks.
- EPIC 17 Task 4 Scheduler integration selection implementation:
  orchestration-only enabled integration selection, inactive tenant exclusion,
  injected marketplace runner factories, and `EnabledMarketplaceIntegrationsJob`.
- EPIC 17 final verification: integration persistence/credential boundary
  `18/18`, seller integration API `16/16`, Scheduler integration selection
  `10/10`, focused tests `18 passed`, full Pytest `336 passed, 58 skipped`,
  MyPy `335` source files, Ruff, Ruff format, demo, Alembic lifecycle, and
  offline Alembic SQL generation against isolated PostgreSQL 17.10.
- EPIC 18 marketplace data readiness foundation: offline readiness verifier,
  marketplace capture checklist, GGSEL absolute URL normalization, GGSEL
  extractor/normalizer contract coverage, Playerok response analyzer and
  extractor contract coverage, and FunPay fetch/extract/normalize/analyzer
  boundaries.
- Playerok live GraphQL source verification: public `items` operation fetches
  real item-list JSON, `PlayerokPipeline` produces 20 real snapshot-ready
  `ParsedOffer` objects through the documented `RUB` fallback, and extractor
  filtering avoids nested category/game false positives.
- Marketplace saved-payload drift guard: strict verifier fails if GGSEL,
  Playerok, or FunPay no longer produce ready, snapshot-compatible data from the
  captured real responses.
- Core readiness review: MediaEngine is accepted as a reusable backend core,
  with remaining gaps limited to production runtime and operational integration.
- FunPay live listing verification: marketplace redirect handling, real listing
  capture, analyzer proof, pipeline proof, and one snapshot-ready `ParsedOffer`
  from the saved response.
- Scheduler same-job overlap guard foundation: scheduler lease domain contract,
  repository interface, memory/PostgreSQL implementations, provider wiring,
  migration `0014_scheduler_leases`, focused tests, demo, and isolated
  PostgreSQL verification `11/11`.
- Scheduler bootstrap configuration: `SchedulerSettings` lease fields and
  memory/PostgreSQL scheduler factory helpers.
- Runtime bootstrap foundation: memory/PostgreSQL runtime component factories
  expose repository scope and Scheduler construction without changing business
  services.
- Runtime process lifecycle foundation: `RuntimeProcess` registers existing
  Scheduler jobs, executes bounded jobs, starts/stops periodic execution, and
  exposes statuses/statistics without owning business logic.
- Production worker command foundation: `scripts/run_mediaengine_worker.py`
  builds default runtime components, registers enabled marketplace integration
  execution, supports one-shot and periodic modes, and prints Scheduler status
  without owning marketplace business logic.
- Runtime polling diagnostics foundation: Scheduler jobs retain their last
  successful result and `RuntimeMonitor` summarizes enabled marketplace
  integration batches without exposing secrets or performing extra I/O.
- Market Terminal integration planning: MediaEngine is documented as the
  backend core and Market Terminal as the public visual product shell.
- EPIC 19 Task 1 public consumer DTO foundation: product cards, product details,
  offer summaries, comparison results, price-history points, price changes,
  categories, and bounded public query parameter schemas.
- EPIC 19 Task 2 public consumer query contracts: SQLAlchemy-independent
  immutable read projections and ABC interfaces for product discovery, offers,
  comparisons, price history, price changes, and categories.
- EPIC 19 Task 3 public product read service: application-layer delegation for
  product card/detail projections without FastAPI, SQLAlchemy, or UI coupling.
- EPIC 19 Task 4 public comparison read service: application-layer delegation
  for comparison projections without duplicating matching, best-offer selection,
  or price-difference logic.
- EPIC 19 Task 5 public price-history read service: application-layer
  delegation for bounded chart points without mutating lifecycle state.
- EPIC 19 Task 6 public FastAPI route surface: read-only `/api/v1/public`
  routes for products, offers, comparisons, price history, price changes, and
  categories with safe unavailable-provider handling.

## Current Status

MediaEngine has a live-verified PostgreSQL runtime foundation for repository-backed
offers, price history, deterministic market events, bounded transactions,
durable post-commit scoring and content generation with recovery, persisted
publication intent, PostgreSQL-verified Telegram delivery orchestration, guarded
live-test tooling, Scheduler delegation, a PostgreSQL-verified read-only
  administration API, PostgreSQL-verified guarded administration commands with
immutable audit history, and PostgreSQL-verified operational dashboard/readiness
hardening. EPIC 16 is functionally complete for tenant identity, authentication,
authorization, tenant-scoped seller workflows, and final PostgreSQL isolation
readiness. EPIC 17 is functionally complete for tenant-owned marketplace
integration metadata, credential-reference redaction, seller integration API, and
Scheduler-facing integration selection without enabling live credential use.
EPIC 18 is functionally complete for saved/live marketplace data readiness:
GGSEL, Playerok, and FunPay all produce snapshot-ready `ParsedOffer` objects
from real captured marketplace responses, and a strict saved-payload drift guard
is available. Runtime bootstrap, process lifecycle helpers, and the worker
command now centralize memory/PostgreSQL repository scope, Scheduler
construction, enabled integration job registration, one-shot execution,
periodic execution, safe Scheduler shutdown, and safe polling diagnostics. The
Market Terminal integration plan is documented and EPIC 19 has started with the
public consumer DTO, query-contract, product read-service, comparison
read-service, price-history read-service, and FastAPI route foundations. The
remaining work before production polling is guarded live operational
verification and explicit runtime integration configuration; the remaining work
before visual integration is a buyer-facing query implementation layer.

## Not Present Yet

- Live marketplace polling monitoring for scheduled production ingestion.
- Optional guarded live Telegram test-chat message.
- Production AI provider integration in the pipeline.
- Live marketplace credential storage and credential retrieval for execution.
- Public consumer query implementations for Market Terminal UI.
## Recommended Next EPIC

**Consumer Read API continuation.**

Implement read-side services and routes over the new public DTOs so the visual
product can consume MediaEngine without importing backend internals.
