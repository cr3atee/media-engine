# Tech Lead Notes

## Purpose

This document captures architecture notes that are important for future reviews.

## Current Notes

- Matching Engine is deterministic and marketplace independent.
- Matching currently uses token preprocessing, Jaccard similarity, and fixed confidence thresholds.
- `MatchingService` depends on existing matching components rather than duplicating preprocessing or similarity logic.
- Repository contracts are database-independent.
- In-memory repositories are development implementations only.
- `RepositoryProvider` is the current boundary for exposing repository implementations.
- `MarketplacePipeline` persists parsed offers and price snapshots through
  `RepositoryProvider`, not through concrete repositories or a parallel service.
- Price-history ordering is chronological by collection timestamp with a
  deterministic backend tie-break for equal timestamps.
- Exact snapshot duplicates are suppressed by memory semantics and a PostgreSQL
  unique constraint with race-safe `ON CONFLICT DO NOTHING`.
- `MarketplaceApplicationRunner` owns the production-shaped run boundary; one
  PostgreSQL scope shares one session and transaction across repositories.
- Live PostgreSQL verification covers migration preflight, two-session conflicts,
  FK behavior, commit/rollback, retries, Scheduler delegation, and UTC timestamps.
- Durable market events now share the offer/snapshot ingestion transaction and use
  exact persistence-neutral snapshot identities.
- The Pydantic `PriceDropEvent` is a temporary scoring/content adapter only; the
  durable `MarketEvent` owns identity and audit facts.
- Exact snapshot replay is suppressed before event construction. Repository-level
  compatible replay remains `EXISTING`; immutable conflicts fail explicitly.
- Durable scoring uses three boundaries: short claim transaction, deterministic
  scoring with no open repository scope, and short guarded completion/failure
  transaction.
- Expired `in_progress` claims are never silently stolen by normal claim polling;
  only the explicit recovery operation invalidates and reschedules them.
- Application retry policy owns backoff and failure classification. Repositories
  expose only lifecycle-specific async transitions and typed outcomes.
- Scheduler event jobs only delegate bounded service calls; persisted work-item
  retries are separate from Scheduler invocation retries/statistics.
- Durable content processing uses three boundaries: attempt preparation/claim,
  provider execution with no open repository scope, and guarded completion or
  failure persistence.
- Generated text and publication intent are atomic when a target is supplied;
  missing target configuration leaves generated content valid without inventing
  delivery metadata.
- Failed generation retries create new immutable attempts. Expired content claims
  become abandoned; expired publication claims become ambiguous and cannot be
  automatically resent.
- Publication delivery uses three boundaries: short channel-scoped claim
  transaction, Telegram adapter call with no open repository scope, and short
  guarded completion transaction.
- Retry/backoff policy lives in `PublicationDeliveryService`, not in Telegram
  adapter, Scheduler, or repositories.
- Telegram `429` stops the current delivery batch after persisting a durable
  retry timestamp. Ambiguous delivery outcomes are terminal for automatic
  processing and require future manual resolution.
- Dry-run is a separate read-only operation and must not be routed through the
  normal claim path.
- `RepositoryProvider` exposes generated-content and publication repositories for
  both memory and PostgreSQL scopes; PostgreSQL repositories share the
  caller-owned session and never commit.
- Scheduler content/recovery jobs delegate only to application services and own
  neither retry policy nor delivery behavior.
- The duplicate price detector and inactive `app/core/events.py` hierarchy were
  removed after targeted reference verification. `PriceDropEvent` remains only a
  transient adapter for existing scoring/prompt interfaces.
- Final EPIC 13 production-shaped verification passed 83 live PostgreSQL checks
  across ingestion, scoring, content, publication intent, restart, concurrency,
  rollback, Scheduler delegation, and audit linkage.
- EPIC 14 PostgreSQL verification passed against an isolated database. Guarded
  live Telegram test-chat delivery remains unperformed and must not be implied
  until one approved test-chat message is actually sent and persisted.
- The guarded live Telegram script must not be treated as proof of live delivery
  unless one approved test-chat message is actually sent and its external message
  ID is persisted.
- EPIC 15 Task 2 administration commands are verified against PostgreSQL 17.10.
  Routes remain thin, commands write immutable `admin_actions` atomically with
  state changes, and no Telegram call is made from the administration workflow.
- EPIC 15 Task 3 completes the internal admin API boundary. Dashboard aggregates
  use a dedicated query repository; routes still contain no SQL or lifecycle
  transitions.
- OpenAPI, Swagger UI, and ReDoc are protected by the same admin API key when
  enabled. They should stay disabled or protected in production.
- Readiness can report database and Alembic head status, repository composition,
  Scheduler configuration, and Telegram configuration without exposing secrets
  or contacting Telegram.
- EPIC 16 Task 1 resolves the durable tenant-ownership foundation; EPIC 16 Task
  2 resolves the seller authentication and centralized authorization boundary.
- Seller access tokens are short-lived signed bearer tokens, but tenant roles
  and permissions are resolved from durable memberships on each tenant-context
  lookup. Do not treat token payloads as authoritative role state.
- Logout and password reset revoke durable auth sessions, so existing access
  tokens become unusable when the backing session is no longer active.
- Refresh tokens and password reset tokens are stored only as hashes. API
  responses must never expose refresh-token hashes, reset tokens, password
  hashes, or signing secrets.
- Password hashing currently uses a dependency-neutral PBKDF2 boundary. Revisit
  Argon2id before production only if adding a dedicated password-hashing
  dependency is approved.
- The next major architecture risk is tenant-scoping existing workflows through
  `TenantContext`; do not expose seller-facing content/publication operations
  until reads, commands, audit, and repository access are tenant-scoped end to
  end.
- EPIC 16 Task 3 adds seller-facing tenant-scoped workflow routes without
  changing the internal `/api/v1/admin` boundary. Seller routes must continue to
  resolve `TenantContext` from bearer auth and path tenant ID before invoking
  read or command services.
- Seller command audit records must keep tenant-scoped idempotency and actor
  attribution. Internal API-key admin commands remain non-tenant-selected at the
  route layer, but the command service records the actual resource tenant.
- `MarketplaceApplicationRunner` is the tenant propagation point for ingestion:
  parsers remain tenant-unaware, while the runner stamps normalized offers with
  the configured tenant before snapshots and durable event identity are built.
- EPIC 16 Task 4 closes the tenant isolation verification loop: live PostgreSQL
  verifiers passed for tenant isolation, auth boundary, and seller workflows.
  Public seller launch should now wait on tenant-owned marketplace credentials,
  operational limits, and product-facing UI scope rather than core tenant
  isolation.
- EPIC 17 should start with integration identity and persistence only. Do not
  store live marketplace credentials until the credential-reference, redaction,
  audit, and key-management boundaries are explicitly verified.
- EPIC 17 Task 1 completed the integration identity and persistence foundation.
  `marketplace_integrations` stores tenant-owned metadata only; no live secrets
  or credential references are persisted yet.
- EPIC 17 Task 2 completed the credential metadata and redaction boundary.
  Credential references are opaque internal metadata; repository rotation
  responses, audit metadata, logs, and future seller API responses must expose
  only redacted safe DTOs.
- EPIC 17 Task 3 completed the seller integration API boundary. Seller routes
  use `TenantContext`, `INTEGRATIONS_READ`, and `INTEGRATION_MANAGE`; mutation
  endpoints stay action-style `POST` routes to preserve the existing OpenAPI
  hardening policy.
- Seller integration APIs return redacted credential metadata only. Raw
  credential references remain internal repository metadata and are not returned
  by HTTP responses.
- EPIC 17 Task 4 adds a Scheduler-facing selection service for enabled
  tenant-owned integrations. It must stay an orchestration boundary: parsers,
  marketplace fetchers, matching, comparison, credential retrieval, and Telegram
  delivery remain outside Scheduler.
- EPIC 17 final verification passed against isolated PostgreSQL 17.10:
  integration persistence/credential boundary `18/18`, seller integration API
  `16/16`, Scheduler integration selection `10/10`, full Pytest, MyPy, Ruff,
  Ruff format, and Alembic lifecycle.
- Live marketplace credential material remains out of scope. Do not add
  plaintext credential columns or execution-time credential retrieval without an
  explicit secret-storage design.
- GGSEL saved-response extraction now reaches snapshot-ready `ParsedOffer`
  objects. FunPay has also passed captured real-listing proof with one
  snapshot-ready `ParsedOffer`. Playerok has live GraphQL `items` proof and
  snapshot-ready parsed-offer conversion through a documented source-backed
  `RUB` fallback.
- Playerok GraphQL item-list requests must include an `APPROVED` status filter;
  an unfiltered request produced a backend validation/runtime error during
  source investigation.
- Keep the Playerok `RUB` fallback inside the Playerok adapter boundary only.
  Shared `ParsedOffer`, `SnapshotBuilder`, repositories, analytics, and events
  must not assume a currency for other marketplaces.
- Marketplace saved-payload readiness is now guarded by
  `scripts/verify_marketplace_payload_contracts.py`. This is a core regression
  guard for captured real payloads, not a substitute for production live polling
  monitoring.
- The core readiness review concludes that the next valuable work is production
  runtime bootstrap, not another domain redesign. Preserve the existing
  repository, Scheduler, event, content, and tenant boundaries unless a concrete
  production integration issue requires a targeted change.
- FunPay fetcher follows marketplace-local redirects because the shared
  `HttpClient` intentionally remains generic and redirect-neutral.
- Scheduler same-job overlap is now guarded by optional scheduler leases.
  Production multi-node deployments must create Scheduler through the PostgreSQL
  scheduler factory and provide a stable `SCHEDULER_OWNER_ID` per node.

## Review Notes

- Keep repository interfaces free from SQLAlchemy and PostgreSQL details.
- Keep matching free from AI, embeddings, and marketplace-specific assumptions unless explicitly requested.
- Keep parser extraction separate from domain matching and persistence decisions.
