# Current State

## Purpose

This document records the current implementation state of MediaEngine.

## Status

Foundation is complete.

The current implementation includes the first marketplace processing path,
async memory and PostgreSQL repositories, deterministic matching/comparison,
repository-backed price history, transaction-bounded application execution,
durable post-commit event scoring, and Scheduler orchestration.

EPIC 12 is live-verified and complete against PostgreSQL 17.10.
EPIC 13 is verified and complete: deterministic price-drop events persist
atomically, are scored through durable claims, and produce persistent immutable
content attempts plus idempotent channel-independent publication intents. The
complete lifecycle passed 83 named checks on PostgreSQL 17.10.
EPIC 14 Task 2 is implemented: Telegram publication claims are channel-scoped,
delivery orchestration is durable, dry-run is read-only, Scheduler delegation is
available, and live Telegram sending remains disabled by default.
EPIC 14 PostgreSQL verification passed `39/39`; guarded live Telegram test-chat
verification was not performed.
EPIC 15 Task 1 is implemented and verified: authenticated read-only administration
routes expose durable events, generated content, publications, and related state
through dedicated query contracts without changing lifecycle behavior.
EPIC 15 Task 2 is implemented and verified: guarded content review and
publication commands persist immutable `admin_actions` records atomically with
state changes, and isolated PostgreSQL 17.10 verification passed `26/26` checks
at revision `0009_admin_actions`.
EPIC 15 Task 3 is implemented and verified: dashboard summary, protected
OpenAPI/Swagger/ReDoc, expanded sanitized readiness, final PostgreSQL admin API
verification, and compatibility verifiers passed against isolated PostgreSQL 17.
EPIC 15 is functionally complete for the internal administration API boundary.
EPIC 16 Task 1 tenant identity foundation is implemented and verified against
isolated PostgreSQL 17.10: domain contracts, tenant-aware repository primitives,
deterministic legacy tenant ownership, event identity v2 tenant inputs, and
migration `0010_tenant_identity_foundation` are present. The live tenant
isolation verifier passed `37/37` checks.
EPIC 16 Task 2 authentication and authorization boundary is implemented and
verified against isolated PostgreSQL 17.10: login, refresh, logout, password
reset request/completion, `/api/v1/me`, tenant context lookup, durable sessions,
hashed tokens, centralized permissions, and `AuthorizationService` are present.
The live auth verifier passed `14/14` checks at migration
`0011_auth_boundary`.
EPIC 16 Task 3 seller workflow scoping is implemented and live-verified:
existing event, generated-content, publication, dashboard, content-review, and
publication-operation workflows now have tenant-scoped seller routes and
tenant-aware audit attribution.
EPIC 16 Task 4 final isolation readiness is complete: tenant isolation,
authentication, seller workflow, Alembic lifecycle, full Pytest, MyPy, and
focused Ruff/format verification passed against isolated PostgreSQL 17.10.
EPIC 17 Task 1 marketplace integration foundation is implemented and
live-verified: tenant-owned integration metadata, repository contracts,
memory/PostgreSQL persistence, provider wiring, and migration
`0012_marketplace_integrations` are present. No live credentials are stored yet.
EPIC 17 Task 2 credential metadata and redaction boundary is implemented and
live-verified: opaque credential references, redacted safe DTOs, audit-safe
rotation intent, memory/PostgreSQL credential-reference updates, and migration
`0013_marketplace_credentials` are present. No live marketplace credential is
stored or used yet.
EPIC 17 Task 3 seller integration API is implemented and live-verified:
tenant-scoped routes allow authorized seller users to list, read, create,
update, disable, and rotate credential references for marketplace integrations
without exposing raw credential material.
EPIC 17 Task 4 Scheduler integration selection is implemented and
live-verified: enabled tenant-owned marketplace integrations are selected,
inactive tenants are excluded, and Scheduler delegates to the selection service.
EPIC 17 is functionally complete.
Scheduler multi-node lease primitives are implemented: Scheduler can optionally
acquire infrastructure leases before job execution, memory lease behavior is
covered by focused tests, and PostgreSQL lease persistence is prepared by
migration `0014_scheduler_leases`.
Scheduler factory helpers are implemented for memory and PostgreSQL lease
configuration from `SchedulerSettings`.
The first isolated PostgreSQL 17 Scheduler lease verification passed `11/11`
checks; Alembic current/check, downgrade/upgrade, and offline SQL generation
passed at revision `0014_scheduler_leases`.
EPIC 18 marketplace data reliability has live proof for FunPay listing access:
`FunPayFetcher` follows marketplace redirects through the shared `HttpClient`,
and the saved real listing response produces one snapshot-ready `ParsedOffer`.
Playerok now has live GraphQL item-list proof: the public `items` operation
returns real offers and `PlayerokPipeline` converts them into `ParsedOffer`
objects. Because the GraphQL item-list response omits currency while the
Playerok frontend bundle formats the same item price values as RUB, the
Playerok normalizer applies a documented source-backed `RUB` fallback and the
readiness verifier reports snapshot-ready offers.
The strict saved-payload drift guard now verifies GGSEL, Playerok, and FunPay
with non-zero exit behavior and confirms all three sources are currently
snapshot-ready from saved real payloads.
Runtime bootstrap factories now expose memory/PostgreSQL repository scopes and
Scheduler construction as a single reusable composition boundary for future
process entrypoints.
`RuntimeProcess` now provides a thin lifecycle boundary for registering existing
jobs, executing bounded jobs, starting/stopping Scheduler execution, and reading
status/statistics.
`scripts/run_mediaengine_worker.py` now provides the first worker command for
enabled marketplace integration execution in one-shot or periodic Scheduler mode.
Scheduler jobs retain their last successful result, and `RuntimeMonitor` can
summarize enabled marketplace integration polling batches for safe operational
diagnostics.
The core readiness review is recorded in `docs/CORE_READINESS_REVIEW.md`:
MediaEngine is ready as a reusable backend core, while public production launch
still requires guarded live polling verification, secret retrieval,
production AI wiring, and guarded live Telegram verification.

## Active Capabilities

- GGSEL catalog HTML can be fetched through the shared HTTP client.
- GGSEL raw product objects can be extracted from embedded payloads.
- FunPay listing HTML can be fetched through the shared HTTP client with
  marketplace-local redirect handling.
- FunPay public offer anchors can be extracted and normalized into
  snapshot-ready `ParsedOffer` objects from a real captured listing response.
- Playerok public GraphQL `items` responses can be fetched and normalized into
  real snapshot-ready `ParsedOffer` objects with id, title, price, RUB currency,
  URL, and seller data.
- `scripts/verify_marketplace_payload_contracts.py` fails fast if any supported
  saved marketplace payload no longer produces ready, snapshot-compatible data.
- Raw marketplace offers are represented by `RawMarketplaceOffer`.
- Raw offers can be normalized into `ParsedOffer`.
- Parsed offers can be persisted through `RepositoryProvider.offers`.
- Canonical products are represented by `CanonicalProduct`.
- Product titles can be normalized, tokenized, filtered by stop words, and expanded through aliases.
- Similarity scores can be calculated deterministically.
- Similarity scores can be classified into `AUTO_MATCH`, `REVIEW`, or `NO_MATCH`.
- `MatchingService` can select the best canonical product candidate for a parsed offer.
- Repository contracts exist for canonical products, offers, and price history.
- Async in-memory and PostgreSQL repository implementations exist.
- `MarketplacePipeline` persists parsed offers and price snapshots through
  `RepositoryProvider`.
- Price-change detection reads the latest persisted snapshot before storing and
  evaluating the current snapshot.
- `MarketplaceApplicationRunner` keeps HTTP/normalization before the database
  transaction and returns after the durable ingestion commit.
- One PostgreSQL repository scope shares one `AsyncSession` across all
  repositories and owns commit/rollback.
- Database constraints protect stable offer identity, exact snapshot identity,
  and canonical-product references.
- Active persistence timestamps are timezone-aware UTC values.
- Scheduler can retry and report a PostgreSQL-backed application run without
  owning business logic or database lifecycle.
- Memory and PostgreSQL providers expose `MarketEventRepository` in the same
  repository container as offers and price history.
- `PriceDropMarketEventBuilder` creates immutable Decimal-safe events from the
  active detector and exact snapshot identities.
- `MarketplaceApplicationRunner` reports durable event candidates, created and
  existing outcomes, event IDs, scored events, and post-commit errors.
- Live PostgreSQL ingestion verification confirms atomic commit/rollback,
  deterministic identity, replay suppression, marketplace isolation, and durable
  event retention across the ingestion/application boundary.
- `EventProcessingService` claims bounded batches, closes the claim transaction
  before scoring, and persists guarded success/failure in follow-up transactions.
- Active leases block competing workers; expired claims are recovered explicitly
  and idempotently according to the durable attempt budget.
- Transient scoring failures retry with bounded exponential backoff; invalid
  inputs and exhausted attempts reach explicit terminal states.
- Scheduler scoring and recovery jobs delegate only to the application service.
- A 14-check live isolated PostgreSQL verification confirms fresh-session
  durability, concurrency, rollback safety, retry/recovery, stale-token rejection,
  terminal failure, and Scheduler delegation.
- Memory and PostgreSQL providers expose generated-content and publication
  repositories through the same transaction scope as other persistence
  boundaries.
- `ContentGenerationProcessingService` claims immutable attempts in short
  transactions, runs AI/content generation without an open database scope, and
  persists guarded success or sanitized retryable failure.
- Successful generated content and its publication intent commit atomically when
  an explicit channel-independent target is configured.
- Expired content claims are abandoned; expired publication claims become
  protected ambiguous outcomes and are not automatically retried.
- Scheduler jobs delegate pending content generation and stale
  content/publication recovery to application services only.
- `PublicationRepository.claim_pending()` supports generic channel filtering and
  an attempt budget for delivery workers.
- `PublicationDeliveryService` claims one Telegram publication at a time, loads
  durable generated content and event data, formats a plain-text message, calls
  the delivery adapter outside repository scopes, and persists success,
  retryable failure, permanent failure, or ambiguous outcome in guarded
  completion scopes.
- Read-only dry-run can render and validate one explicit publication without
  creating a claim, incrementing attempts, changing retry state, or calling
  Telegram.
- `PendingPublicationDeliveryJob` delegates bounded publication delivery to the
  service and contains no repository, formatting, adapter, or retry logic.
- The guarded live Telegram verifier exits safely without network calls unless
  all explicit live-test flags, the exact test-chat confirmation, an allowlisted
  destination, a bot token, and an isolated `EPIC14_DATABASE_URL` are supplied.
- Revision `0008_content_publications` upgrades, downgrades to `0007`, re-applies,
  and matches SQLAlchemy metadata.
- An 18-check live isolated PostgreSQL verification confirms committed claims,
  transaction-free AI, retry, concurrency, rollback, fresh-session durability,
  idempotency, ambiguous-state protection, and Scheduler delegation.
- `app/analytics/price_change.py` is the sole detector; inactive duplicate
  detector/event modules were removed without changing calculation behavior.
- The unreferenced direct `MarketplacePipeline.process_after_commit()` helper was
  removed; production content has one durable claim-based processing path.
- Final verification confirms restart-safe ingestion, scoring, content, and
  publication-intent stages with fresh repositories and services.
- `/api/v1/admin` provides authenticated event, content, and publication list,
  detail, and related-resource reads with typed filters and sorting.
- Stable API errors and request correlation IDs are returned consistently;
  API-key comparison is constant-time and unsafe configurations fail closed.
- Event payloads are explicitly versioned, generated content remains plain text,
  publication destinations are hashed, and claim tokens/secrets are not exposed.
- List APIs use signed, filter-bound timestamp/UUID keyset cursors.
- Liveness is process-only; readiness performs a sanitized database probe and no
  Telegram call.
- EPIC 15 Task 1 passed 27 focused tests and 28 isolated PostgreSQL checks;
  full Pytest passed 291 tests with 54 expected skips.
- EPIC 15 Task 2 passed 26 isolated PostgreSQL admin-mutation checks, focused
  Task 2/repository contract tests, full Pytest, Ruff, Ruff format, MyPy, and
  Alembic upgrade/check/downgrade/offline SQL verification.
- `/api/v1/admin/dashboard/summary` returns bounded operational counters through
  a dedicated dashboard query repository.
- `/openapi.json`, `/docs`, and `/redoc` are protected by admin authentication
  when enabled.
- Readiness checks PostgreSQL connectivity and Alembic head without exposing
  secrets or contacting Telegram.
- EPIC 15 final verification passed: Task3 `23/23`, Task1 `29/29`, Task2
  `26/26`, EPIC14 compatibility `39/39`, full Pytest `304 passed, 58 skipped`,
  full MyPy `274` source files, Ruff, Ruff format, and Alembic lifecycle.
- EPIC 16 Task 1 adds `User`, `Tenant`, and `Membership` domain contracts,
  tenant-aware offer, canonical-product, and price-history repository
  primitives, deterministic legacy tenant backfill, tenant-scoped uniqueness and
  lookup indexes, and tenant-aware event identity v2 support.
- EPIC 16 Task 1 verification passed: live PostgreSQL tenant isolation
  `37/37`, focused tests `70 passed`, full Pytest `307 passed, 58 skipped`,
  full MyPy `288` source files, Ruff and Ruff format for touched files,
  Alembic current/check, clean downgrade to `0009_admin_actions`, upgrade back
  to head, and offline SQL generation through `0010_tenant_identity_foundation`.
- EPIC 16 Task 2 adds seller authentication and authorization primitives:
  durable password credentials, durable refresh sessions, hashed reset tokens,
  short-lived signed access tokens, `AuthenticatedPrincipal`, `TenantContext`,
  `Permission`, and centralized `AuthorizationService`.
- Seller auth routes are available for login, refresh, logout, password reset
  request/completion, `/api/v1/me`, and
  `/api/v1/tenants/{tenant_id}/context`.
- EPIC 16 Task 2 verification passed: live PostgreSQL auth boundary `14/14`,
  focused auth/API tests, full Pytest `313 passed, 58 skipped`, full MyPy `302`
  source files, Ruff, Ruff format, Alembic current/check at
  `0011_auth_boundary`, downgrade to `0010_tenant_identity_foundation`, upgrade
  back to head, and offline SQL generation through head.
- Tenant-scoped seller workflow routes exist under `/api/v1/tenants/{tenant_id}`
  for events, generated content, publications, dashboard summary,
  content-review commands, and publication-operation commands.
- Seller workflow routes require bearer authentication, resolve tenant
  membership through `AuthorizationService`, and enforce centralized
  permissions before executing read or command services.
- Seller commands carry tenant/user actor context into `AdminMutationService`;
  `admin_actions` idempotency and request fingerprints are tenant-scoped.
- `MarketplaceApplicationRunner` propagates configured tenant ownership from
  ingestion into `ParsedOffer`, `PriceSnapshot`, and durable market-event
  identity.
- EPIC 16 Task 3 offline verification passed: focused seller/admin/auth tests
  `44 passed, 1 skipped`, focused runner/seller tests `16 passed`, full Pytest
  `318 passed, 58 skipped`, full MyPy `305` source files, Ruff, Ruff format,
  and Alembic offline `upgrade head --sql`.
- EPIC 16 Task 4 final isolation verification passed against isolated
  PostgreSQL 17.10 database `epic16_task4_verify`: tenant isolation `37/37`,
  auth boundary `14/14`, seller workflows `20/20`, focused EPIC16 tests
  `48 passed, 1 skipped`, full Pytest `318 passed, 58 skipped`, full MyPy `305`
  source files, Alembic lifecycle, and focused Ruff/format checks.
- Tenant-owned marketplace integrations can be represented, persisted, listed
  per tenant, selected for enabled active runs, and verified across memory and
  PostgreSQL repositories.
- EPIC 17 Task 1 verification passed: live PostgreSQL integration verifier
  `12/12`, focused marketplace integration tests `7 passed`, focused repository
  tests `27 passed`, full Pytest `325 passed, 58 skipped`, full MyPy `312`
  source files, Alembic lifecycle through `0012_marketplace_integrations`, and
  focused Ruff/format checks.
- Marketplace integration credential references can be persisted as opaque
  metadata and updated through optimistic-version guarded repository methods.
- Credential update responses use redacted safe DTOs; audit metadata records a
  constant redaction marker instead of the raw reference.
- EPIC 17 Task 2 verification passed: live PostgreSQL integration verifier
  `18/18`, focused marketplace integration repository tests `11 passed`, full
  Pytest `329 passed, 58 skipped`, full MyPy `326` source files, Alembic
  lifecycle through `0013_marketplace_credentials`, and focused Ruff/format
  checks.
- Tenant-scoped seller marketplace integration routes exist under
  `/api/v1/tenants/{tenant_id}/marketplace-integrations`.
- Seller integration reads use `INTEGRATIONS_READ`; create/update/disable and
  credential rotation use `INTEGRATION_MANAGE`.
- Seller integration API responses expose only redacted credential metadata and
  stable sanitized errors.
- EPIC 17 Task 3 verification passed: live PostgreSQL seller integration API
  verifier `16/16`, focused API/repository tests `16 passed`, full Pytest
  `334 passed, 58 skipped`, full MyPy `331` source files, Alembic lifecycle
  through `0013_marketplace_credentials`, and focused Ruff/format checks.
- EPIC 17 Task 4 adds `MarketplaceIntegrationExecutionService` and
  `EnabledMarketplaceIntegrationsJob` for orchestration-only execution of
  enabled tenant-owned integrations.
- EPIC 17 Task 4 offline verification passed: focused execution tests
  `2 passed`; live PostgreSQL Scheduler integration selection verifier passed
  `10/10`.
- EPIC 17 final verification passed: integration persistence/credential boundary
  `18/18`, seller integration API `16/16`, Scheduler integration selection
  `10/10`, focused tests `18 passed`, full Pytest `336 passed, 58 skipped`,
  full MyPy `335` source files, Ruff, Ruff format, demo execution, Alembic
  current/check, downgrade/upgrade, and offline Alembic SQL generation.
- Scheduler can optionally use `SchedulerLeaseRepository` to prevent same-job
  overlap across multiple scheduler nodes without changing job implementations.
- Memory scheduler leases are implemented and PostgreSQL scheduler lease
  persistence is prepared by `0014_scheduler_leases`.
- Scheduler factory helpers refuse unsafe lease-enabled construction without an
  explicit lease repository and can create PostgreSQL-backed Scheduler instances
  from an async session factory.
- Scheduler lease verification passed: PostgreSQL `11/11`, focused tests
  `8 passed`, full Pytest `359 passed, 58 skipped`, full MyPy `344` source
  files, and focused Ruff/format checks.
- Runtime component factories can now create memory or PostgreSQL runtime
  wiring with one repository scope factory and one Scheduler instance.
- `RuntimeProcess` can register existing `BaseJob` objects with interval,
  enabled, retry, delay, and timeout settings while keeping business work inside
  the jobs and services.
- The worker command can create default PostgreSQL runtime components, create
  supported marketplace runner factories, register enabled integration
  execution, execute once, or run periodically.
- Runtime polling diagnostics can report selected, executed, skipped
  integrations, per-marketplace run counts, snapshot counts, price changes,
  event counts, and sanitized error counts from the existing execution result.
- Market Terminal integration planning is documented: MediaEngine remains the
  backend core, while Market Terminal is the public visual product shell.
- EPIC 19 has started with public consumer DTOs for product cards, product
  details, offer summaries, comparison results, price-history points, latest
  price changes, categories, and bounded query parameters.
- EPIC 19 Task 2 adds SQLAlchemy-independent public query contracts and
  immutable read projections for product discovery, offers, comparisons, price
  history, price changes, and categories. No public consumer read routes or
  frontend integration are implemented yet.
- EPIC 19 Task 3 adds `PublicProductReadService`, a thin application service
  over the public product query contract for product card/detail projections.
- EPIC 19 Task 4 adds `PublicComparisonReadService`, a thin application service
  over the public comparison query contract for comparison projections without
  duplicating comparator behavior.
- EPIC 19 Task 5 adds `PublicPriceHistoryReadService`, a thin application
  service over the public price-history query contract for bounded chart points.
- EPIC 19 Task 6 adds read-only `/api/v1/public` routes for products, product
  details, offers, comparisons, price history, price changes, and categories.
  Routes use explicit public DTOs, require no seller/admin authentication, and
  fail safely until a public read provider is wired.
- EPIC 19 Task 7 adds a repository-backed public read adapter over the existing
  `RepositoryProvider`, projecting product cards, offers, comparison results,
  price-history points, latest eligible price changes, and categories without
  mutating lifecycle state.

## Known Gaps

- GGSEL saved-response extraction now produces 60 snapshot-ready `ParsedOffer`
  objects with absolute catalog URLs.
- Playerok has live GraphQL item-list proof and produces real snapshot-ready
  parsed offers. The GraphQL response itself contains no `currency` field, so
  the `RUB` fallback must remain documented and covered by drift monitoring.
- Saved-payload drift monitoring exists; live scheduled marketplace polling
  still needs production runtime configuration and operational monitoring.
- Core readiness is no longer blocked by domain architecture; remaining work is
  production runtime and operational integration.
- FunPay saved-response extraction now produces one snapshot-ready `ParsedOffer`
  from a real public listing response.
- Snapshot creation is skipped when parsed offers from any marketplace do not
  contain normalized price and currency.
- Ingestion, scoring, and durable content processing are separate services and
  still require production process/bootstrap configuration.
- Production deployment can now start from `scripts/run_mediaengine_worker.py`;
  guarded live operational verification still needs to be executed before
  unattended polling.
- Public Market Terminal integration still needs saved-payload UI readiness
  verification through the public DTO/route layer and PostgreSQL-specific public
  query adapter work if direct SQL read optimization is approved later.
- Live Telegram delivery is not yet verified; credentials, exact test-chat
  confirmation, live flags, and PostgreSQL verification database were not
  supplied.
- No production AI provider is wired into the marketplace pipeline.
- Live marketplace credential storage and execution-time credential retrieval are
  not implemented yet.
- Password hashing currently uses a standard-library PBKDF2 boundary so Task 2
  could remain dependency-neutral; production hardening should revisit Argon2id
  if adding a dependency is approved.

## Architecture Review

Current architecture separates:

- marketplace retrieval and extraction;
- normalization into internal offer format;
- repository contracts and memory implementations;
- deterministic matching;
- pipeline orchestration.

EPIC 13 final verification adds one production-shaped 83-check PostgreSQL path
across ingestion, scoring, content, publication intent, restart, overlap,
rollback, Scheduler delegation, and audit evidence. EPIC 14 connects the Telegram
adapter to durable publication state and passed isolated PostgreSQL verification;
the optional guarded live test-chat message remains unperformed. EPIC 15 Task 1
adds a separate read model and API boundary without coupling HTTP transport to ORM
or lifecycle repositories. EPIC 15 Task 2 adds guarded application commands with
atomic immutable audit rows. EPIC 15 Task 3 completes the operational admin
boundary with dashboard/readiness/OpenAPI hardening. EPIC 16 Task 1 adds durable
tenant ownership, Task 2 adds seller authentication/authorization, Task 3 scopes
existing workflows through `TenantContext`, and Task 4 verifies the complete
tenant isolation loop against PostgreSQL. EPIC 17 Task 1 adds the tenant-owned
marketplace integration persistence foundation. EPIC 17 Task 2 adds the
credential metadata and redaction boundary without live credential use. EPIC 17
Task 3 adds tenant-scoped seller integration routes with permission checks and
redacted credential responses. EPIC 17 Task 4 adds Scheduler-facing integration
selection without moving marketplace business logic into Scheduler. EPIC 17 is
functionally complete; live marketplace credential storage and execution-time
credential retrieval require a new explicitly approved EPIC. EPIC 18 continues
marketplace data reliability closure: GGSEL, Playerok, and FunPay are verified
from real saved/live payloads as snapshot-ready, and a strict saved-payload
drift guard is present. Runtime bootstrap/process helpers and the worker command
now centralize repository scope, Scheduler construction, job registration, and
safe shutdown. Production scheduling should still wait for guarded live polling
verification.
