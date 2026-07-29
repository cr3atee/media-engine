# EPIC 13: Persistent Market Events

## Status and Scope

EPIC 12 established an asynchronous PostgreSQL runtime with a single transaction boundary for offer and price-snapshot persistence. The active marketplace flow currently detects price changes and creates `PriceDropEvent` objects in memory. Scoring and content generation run after commit, but events, generated content, and publication state are not persisted.

EPIC 13 closes that durability gap. It introduces a persistent, auditable event lifecycle without moving business logic into repositories, holding database transactions during external calls, or coupling the domain to Telegram.

This document is the implementation specification and task-status record. It does
not itself introduce database migrations.

### Task 1 implementation status

Task 1 is implemented as a database-independent foundation.

Implemented models and value objects:

- Immutable generic `MarketEvent` envelope and `PriceDropPayload`.
- Exact `SnapshotIdentity` containing marketplace, external ID, UTC observation time, `Decimal` price, and normalized currency.
- Versioned `EventIdentity` with `CURRENT_EVENT_IDENTITY_VERSION = 1`.
- Separate event disposition, scoring, content generation, content review, and publication enums.
- Deterministic lifecycle transition validators that reject invalid and terminal-state transitions.
- Immutable generated-content attempt/revision, publication, work-claim, safe error, and typed repository-result contracts.

Implemented repository boundaries:

- Async `MarketEventRepository`.
- Async `GeneratedContentRepository`.
- Async `PublicationRepository`.
- Lifecycle-specific methods and typed outcomes without SQLAlchemy, transaction ownership, retry loops, or provider logic.

Identity implementation details:

- Event identity is SHA-256 over the version, stable event type value, normalized marketplace, external ID, previous snapshot identity, and current snapshot identity.
- Identity fields are UTF-8 encoded, pipe separated, and escape backslashes and pipe characters before joining.
- UTC timestamps use ISO 8601 with six fractional digits and a `Z` suffix.
- Decimal values use fixed-point notation with insignificant trailing fractional zeros removed, so `Decimal("10.0")` and `Decimal("10.00")` are the same logical value.
- Unsupported identity versions fail explicitly instead of falling back to the current algorithm.

Lifecycle implementation details:

- Failed scoring may return to pending for a persisted retry.
- Failed content attempts are immutable terminal attempts; a retry creates a new attempt number.
- Failed publications may return to pending for a known-failure retry.
- Ambiguous publications may move only through explicit reconciliation to pending, published, or cancelled; they are not automatic retry candidates.
- Published and cancelled publications are terminal.
- Rejected content cannot become approved; a new revision is required.

Current runtime compatibility:

- The existing Pydantic `PriceDropEvent` remains unchanged and continues to be used by `EventBuilder`, `EventScorer`, prompts, content generation, and marketplace runtime DTOs.
- `app/domain/events.py` re-exports the persistent event contracts but does not convert or replace runtime events.
- No event persistence or application-runner integration is included.
- `app/analytics/price_change.py` remains the active detector.
- `app/analytics/price_change_detector.py` remains a legacy duplicate pending the dedicated cleanup task; its calculation semantics were not changed.

Remaining EPIC 13 work:

- PostgreSQL repository implementations.
- SQLAlchemy models and Alembic migrations.
- Atomic event insertion in the marketplace transaction.
- Durable scoring, content-generation, claim-recovery, and publication application services.
- Scheduler job integration and live PostgreSQL verification.

### Task 2 implementation status

Task 2 is implemented as standalone, database-independent memory persistence.

Implemented repositories:

- `MemoryMarketEventRepository` with deterministic identity lookup, guarded
  scoring transitions, disposition transitions, retry eligibility, and claim
  release.
- `MemoryGeneratedContentRepository` with immutable attempts, deterministic
  revision history, guarded generation/review transitions, and parent links.
- `MemoryPublicationRepository` with channel-neutral idempotency, scheduling,
  known-failure retry, confirmed delivery, ambiguous delivery, and cancellation.

Fixed contract semantics:

- Repeated event, content-attempt, and publication identities return the original
  immutable record with `IdempotentCreateStatus.EXISTING`.
- An event/content identity that is reused with incompatible immutable facts raises
  `RepositoryIdentityConflictError`; repositories never merge those facts.
- A publication retry with the same idempotency key preserves the original ID,
  creation time, and schedule.
- Exact duplicate publication success is idempotently `APPLIED` without changing
  the first external message ID or publication time. A different external message
  ID is an explicit `INVALID_STATE` outcome.
- Guarded updates distinguish `NOT_FOUND`, `VERSION_CONFLICT`, `CLAIM_LOST`,
  `INVALID_STATE`, and `APPLIED`, and every applied mutation increments the
  optimistic version once.

Claim and lease behavior:

- Repository time comes from explicit UTC-aware method arguments; claim tokens are
  generated through an injectable factory for deterministic tests.
- Active claims cannot be stolen. An expired scoring claim can be reclaimed with a
  new token and version.
- An expired content-generation claim becomes `abandoned`; the failed work is not
  rewritten or silently retried.
- An expired publication claim becomes `ambiguous`, blocking automatic resend when
  provider acceptance cannot be proven.

Stable ordering:

- Events use readiness/next-retry time, creation time, then UUID.
- Generated content uses attempt number, creation time, then UUID.
- Publications use next-retry/scheduled readiness, creation time, then UUID.
- All list methods return detached immutable sequences; repository instances keep
  isolated, non-global state.

Shared contract tests live under `tests/repositories/contracts/`. Concrete memory
tests inherit the three behavior suites and supply only repository factories. The
same suites are intended for Task 3 PostgreSQL implementations without depending
on memory internals.

Task 2 does not change `RepositoryProvider`, SQLAlchemy models, migrations,
transactions, scheduler jobs, marketplace runtime paths, AI generation, or
publication delivery.

Exact recommended Task 3:

Implement only the `market_events` SQLAlchemy model, Alembic migration, domain/ORM
mapping, and `PostgresMarketEventRepository`. Run the shared market-event repository
contract against PostgreSQL, verify identity conflicts and concurrent
`FOR UPDATE SKIP LOCKED` claims, and keep transaction commit ownership outside the
repository. Do not add generated-content/publication tables or runtime integration
in Task 3.

### Current implementation facts

- `app/domain/events.py` is the active event model used by `EventBuilder`, `EventScorer`, prompts, and content generation.
- `app/core/events.py` contains an older standard-library event hierarchy that is not used by the active pipeline.
- `app/analytics/price_change.py` is the detector used by the active marketplace pipeline.
- `app/analytics/price_change_detector.py` is a legacy duplicate used only by the older `PricePipeline` demo path.
- Offers, canonical products, and price snapshots have repository contracts and PostgreSQL implementations.
- `MarketplaceApplicationRunner` commits ingestion before scoring and content generation.
- Generated text and post-commit failures currently exist only in process memory.
- Scheduler jobs orchestrate services and maintain execution statistics in memory.
- Standalone memory repositories exist for persistent events, generated content,
  and publications; no active runtime path or provider uses them yet.

### Architectural invariants

- Repository contracts remain database independent and asynchronous.
- Repositories perform persistence operations but do not own retry or business policy.
- `Decimal` is used for every persisted monetary value and calculation boundary.
- Every timestamp is timezone-aware UTC and stored as `TIMESTAMPTZ`.
- Marketplace ingestion must not call AI or delivery providers inside its database transaction.
- Telegram is a publication adapter, not a domain dependency.
- Scheduler jobs orchestrate application services only.
- No external broker is required for this EPIC.
- No event is persisted as one untyped JSON payload.

## 1. Event Domain Model

### Selected model

Use a typed, immutable domain envelope with a typed payload. The envelope carries stable event identity and shared lifecycle-independent facts. Each event type supplies its own payload type. EPIC 13 initially supports only a price-drop payload, while preserving an extension point for later event types.

The target domain shape is conceptually:

```python
@dataclass(frozen=True, slots=True)
class MarketEvent[TEventPayload]:
    id: UUID
    identity_key: str
    identity_version: int
    event_type: MarketEventType
    marketplace: str
    external_id: str
    canonical_product_id: UUID | None
    occurred_at: datetime
    detected_at: datetime
    payload: TEventPayload


@dataclass(frozen=True, slots=True)
class PriceDropPayload:
    title: str | None
    url: str | None
    old_price: Decimal
    new_price: Decimal
    currency: str
    percentage: Decimal
    previous_snapshot: SnapshotIdentity
    current_snapshot: SnapshotIdentity
```

This is a design target, not code to be added as part of this documentation task.

### Event envelope responsibilities

- Identify the event independently from process memory.
- Describe the event type and marketplace source.
- Reference the affected marketplace offer through `marketplace` and `external_id`.
- Optionally reference a `CanonicalProduct` without requiring matching to have completed.
- Record when the market condition occurred and when MediaEngine detected it.
- Carry exactly one typed payload compatible with `event_type`.

### Price-drop payload responsibilities

- Preserve old and new prices as `Decimal`.
- Preserve the currency used by both snapshots.
- Preserve the deterministic percentage calculated by the active detector.
- Preserve exact previous and current snapshot identities.
- Carry display context such as title and URL without making those fields part of event identity.

### Relationship with the current `PriceDropEvent`

The current Pydantic `PriceDropEvent` uses `float` prices, has no ID, and does not retain source snapshot identity. It is suitable as a transient content/scoring input but not as the persistent domain source of truth.

EPIC 13 should introduce the durable model first, then adapt the existing scoring and prompt boundaries without changing their scoring or content behavior. Compatibility conversion must be explicit and temporary. New persistence code must never round-trip money through `float`.

### Event type representation

Use a string-backed `MarketEventType` enum in the domain. Persist the string value in a `VARCHAR` column with a database check constraint for currently supported values. Do not use a PostgreSQL enum because adding event types should not require enum type replacement.

Initial persisted event type:

- `price_drop`

The inactive hierarchy in `app/core/events.py` must not become a second persistent event model.

## 2. Event Identity

### Identity requirements

Event identity must remain stable across process restarts, scheduler retries, concurrent workers, content regeneration, title edits, and canonical-product reassignment.

The technical row identifier and logical event identity are separate:

- `id`: UUID generated once for references and APIs.
- `identity_key`: deterministic SHA-256 digest used for idempotent insertion.
- `identity_version`: integer identifying the canonicalization algorithm.

### Price-drop identity algorithm

For `identity_version = 1`, build a UTF-8 canonical string from:

```text
v1|price_drop|marketplace|external_id|previous_snapshot_identity|current_snapshot_identity
```

Each snapshot identity is built from:

```text
marketplace|external_id|collected_at_utc|price_decimal|currency
```

Canonicalization rules:

- Marketplace and currency use their normalized persisted values.
- `external_id` is preserved exactly as the marketplace identifier after existing normalization.
- UTC timestamps use ISO 8601 with six fractional digits and a `Z` suffix.
- Decimal values use fixed-point notation, never scientific notation and never `float` conversion.
- Insignificant trailing fractional zeros are removed before hashing.
- Backslashes and pipe characters are escaped before pipe-separated fields are joined.
- The UTF-8 canonical string is hashed with SHA-256 and stored as 64 lowercase hexadecimal characters.

### Fields excluded from identity

- Title, because marketplace copy can change without creating a different transition.
- URL, because routing and tracking parameters can change.
- Percentage, because it is derived from prices.
- Score, because it is downstream analysis.
- Canonical product ID, because matching may happen later or be corrected administratively.
- Generated content and publication destination, because they are downstream artifacts.

### Database idempotency

The database enforces two complementary uniqueness rules:

- A global unique constraint on `identity_key`.
- A partial unique index on `(event_type, previous_snapshot_id, current_snapshot_id)` when both snapshot references are present.

The application repository uses `INSERT ... ON CONFLICT DO NOTHING` or an equivalent single-statement insert strategy, then reads the existing row by identity. It must not implement check-then-insert in separate statements.

### Legacy and incomplete snapshot references

New runtime events must resolve both persisted snapshot IDs inside the ingestion transaction. A legacy import may lack those IDs. For such data:

- Derive a `legacy_v1` identity key from immutable snapshot facts.
- Require both snapshot foreign keys to be null together.
- Set event disposition to `review_pending`.
- Block automatic publication until source references are resolved or an administrator explicitly approves the event.
- Never invent snapshot IDs, title values, or prices.

## 3. Event Persistence

### Persistence boundary

The event row is inserted in the same database transaction that persists the current snapshot and reads the previous snapshot. This guarantees that a committed price transition has a committed event candidate, and a rolled-back ingestion leaves neither a new snapshot nor an event.

### Persistence representation

Use typed relational columns for queryable and identity-relevant fields:

- Event type and source identifiers.
- Snapshot foreign keys.
- Canonical product foreign key.
- Old price, new price, currency, and percentage.
- Title and URL display context.
- Lifecycle, retry, claim, and audit timestamps.

An optional `audit_metadata JSONB` column may retain non-authoritative source diagnostics. It must not contain the entire event, monetary fields, lifecycle state, secrets, prompts, provider credentials, or data needed to reconstruct identity.

### Idempotent add result

The event repository should return an explicit typed result containing:

- The persisted event.
- Whether the row was newly created.
- Which identity version was used.

This lets orchestration report inserted versus already-known events without performing another race-prone lookup.

### Deletion policy

Market events are audit records and should not be hard-deleted by runtime services. Administrative rejection changes disposition. Retention or archival is outside EPIC 13.

## 4. Event Lifecycle

Do not represent the entire lifecycle with one overloaded status. Event disposition, scoring, content generation, and publication are independent state machines.

### Event disposition

| Status | Meaning | Allowed next states |
|---|---|---|
| `active` | Detected event is eligible for normal processing | `review_pending`, `approved`, `ignored`, `rejected` |
| `review_pending` | Automated processing requires administrator review | `approved`, `ignored`, `rejected` |
| `approved` | Administrator explicitly permits downstream processing | `ignored`, `rejected` |
| `ignored` | Event is intentionally excluded without declaring it invalid | None without explicit administrative reopen |
| `rejected` | Event is invalid or unsuitable and must not be processed | None without explicit administrative reopen |

### Scoring status

| Status | Meaning |
|---|---|
| `pending` | Event is persisted and waiting for scoring |
| `in_progress` | A worker owns a valid scoring lease |
| `succeeded` | Score is persisted |
| `failed` | Last scoring attempt failed and retry policy applies |
| `skipped` | Scoring is intentionally not applicable |

### Content generation status

| Status | Meaning |
|---|---|
| `pending` | A generation attempt is ready |
| `in_progress` | A worker owns a valid generation lease |
| `generated` | Valid content is persisted |
| `failed` | The attempt failed |
| `abandoned` | The attempt was superseded or its lease expired irrecoverably |

### Content review status

| Status | Meaning |
|---|---|
| `not_required` | Content can proceed without manual approval |
| `pending` | Content waits for administrator review |
| `approved` | Content is approved for publication |
| `rejected` | Content must not be published |

### Publication status

| Status | Meaning |
|---|---|
| `pending` | Delivery is scheduled or ready |
| `in_progress` | A worker owns a valid delivery lease |
| `published` | Provider acceptance and external message ID are persisted |
| `failed` | Delivery failed with a known outcome and may be retried |
| `ambiguous` | Provider outcome is unknown; automatic resend is blocked |
| `cancelled` | Publication was intentionally cancelled |

### Product-language lifecycle mapping

- Detected means a `market_events` row exists with scoring status `pending`.
- Scored means scoring status is `succeeded` and `score` is present.
- Generation pending, in progress, generated, or failed belongs to a generated-content attempt.
- Publication pending, published, or failed belongs to a publication row.
- Ignored and rejected belong to event disposition.

## 5. Generated Content Model

Generated content is an immutable revision history, not a mutable text column on the event.

### Revision rules

- Each AI generation request creates a new attempt row.
- A completed attempt's text, provider label, model label, prompt version, and checksum are immutable.
- Retrying a failed attempt creates a new `attempt_number`; it does not erase the failed row.
- A human edit creates a new row with `origin = human_edit` and `parent_content_id` pointing to the source revision.
- Provider and model fields are descriptive labels only. API keys and credentials are never persisted.
- Full prompts are not persisted by default. `prompt_version` identifies the template, while optional safe diagnostics belong in audit metadata only after explicit review.

### Idempotency

The generation idempotency key is a SHA-256 digest of:

```text
event_id|content_type|language|prompt_version|attempt_number
```

Only one active generation attempt is allowed for the same event, content type, language, and prompt version. A terminal failed attempt permits a later attempt number.

### Validation

- `generated` requires non-empty `content_text`, `content_checksum`, and `completed_at`.
- `failed` requires a safe error code and summary.
- Error summaries must not include secrets, authorization headers, or raw provider responses containing sensitive data.

## 6. Publication Model

Publication is channel independent. Telegram-specific DTOs, chat IDs, formatting modes, and API objects must remain in a future Telegram adapter.

### Publication identity

The publication idempotency key is a SHA-256 digest of:

```text
event_id|content_id|channel|destination_key
```

`destination_key` is an opaque application-level destination reference or configuration ID. It is not a provider credential.

### Delivery records

- One publication row represents delivery of one immutable content revision to one channel destination.
- `external_message_id` is stored only after provider acceptance is known.
- A content edit produces a different content ID and therefore a different publication identity.
- A known rejection or transport failure uses `failed` and can follow retry policy.
- An uncertain provider outcome uses `ambiguous` and must not be retried automatically.
- Provider-specific response details may be stored only as scrubbed audit metadata.

### Channel independence

The domain and repository contracts use `channel: str`. Future adapters can implement `telegram`, another messenger, email, or an internal preview without altering event or content tables.

## 7. Transaction Boundary

### Marketplace ingestion transaction

The existing EPIC 12 transaction boundary is retained and extended minimally:

1. Fetch and normalize marketplace data outside the database transaction.
2. Open one application transaction.
3. Save offers idempotently.
4. Resolve the previous persisted snapshot.
5. Save the current snapshot idempotently.
6. Detect a price change using the active detector.
7. Build a typed event candidate.
8. Resolve source snapshot record IDs through persistence mapping.
9. Insert the event idempotently.
10. Commit offers, snapshots, and events together.

No scoring, AI call, publication call, or scheduler retry delay occurs inside this transaction.

### Post-commit event processing

Scoring moves to a separate `EventProcessingService`:

1. Claim pending events in a short transaction.
2. Commit the claim.
3. Calculate the deterministic score outside a database transaction.
4. Persist success or failure in a short transaction guarded by claim token and version.
5. Create the first content-generation attempt when policy permits.

### Content generation

1. Claim pending content attempts in a short transaction.
2. Commit the claim.
3. Call `ContentGenerator` and `AIProvider` outside a database transaction.
4. Validate the generated text.
5. Persist the terminal attempt state in a short transaction.
6. If publication policy is configured, create the publication row in the same short transaction as generated content completion.

### Publication delivery

1. Claim pending publication rows in a short transaction.
2. Commit the claim.
3. Call the channel adapter outside a database transaction.
4. Persist `published`, `failed`, or `ambiguous` in a short guarded transaction.

## 8. Outbox and Queue Decision

### Decision

Do not add Kafka, Redis, Celery, RabbitMQ, or a separate transactional outbox in EPIC 13.

The persistent lifecycle tables are sufficient durable work queues for the current deployment model:

- `market_events` queues scoring work through `scoring_status`.
- `generated_contents` queues content generation through `generation_status`.
- `publications` queues delivery through `publication_status`.

Each queue supports indexed polling, atomic claiming, leases, idempotent completion, and auditable failures.

### Why a separate outbox is deferred

- Current consumers run inside MediaEngine rather than on an external message bus.
- PostgreSQL already participates in the source transaction.
- A second outbox row would duplicate lifecycle state without providing another delivery boundary.
- The present workload does not justify operating a broker.

### Reconsideration trigger

Add a transactional outbox only when MediaEngine must publish event notifications to independently deployed consumers, sustain polling contention that PostgreSQL queues cannot meet, or provide cross-service delivery guarantees.

## 9. Concurrency and Claiming

### Claim algorithm

Workers claim work with `SELECT ... FOR UPDATE SKIP LOCKED` in a short transaction. The selected rows are atomically updated with:

- Processing status set to `in_progress`.
- New UUID `claim_token`.
- `worker_id` for diagnostics.
- `claimed_at` in UTC.
- `lease_expires_at` in UTC.
- Incremented `version`.
- Incremented attempt count where the lifecycle owns attempts.

The transaction commits before CPU work or network I/O begins.

### Completion guard

Completion and failure updates match all of:

- Row ID.
- Expected `in_progress` status.
- `claim_token`.
- Expected optimistic `version`.

An update affecting zero rows means the lease was lost or the work was already finalized. The worker must not overwrite the newer state.

### Lease recovery

A stale-claim recovery service finds `in_progress` rows with `lease_expires_at <= now`:

- Scoring rows return to `pending` or become terminal `failed` according to retry policy.
- Content attempts become `abandoned`; a new attempt may be scheduled.
- Publications with a known unsent outcome may return to `pending`.
- Publications whose provider outcome may be unknown become `ambiguous`.

### Concurrency guarantees

- Unique event identity prevents duplicate transition events.
- `SKIP LOCKED` prevents two live workers from owning the same row.
- Claim tokens prevent stale workers from completing reclaimed work.
- Optimistic versions prevent silent lost updates.
- No long-running row lock is held during AI or publication calls.

## 10. Retry Policy

Retry policy belongs to application services. Repositories only persist attempts, claims, status, errors, and `next_retry_at`. Scheduler only invokes retry-capable services.

### Error classification

| Error class | Examples | Action |
|---|---|---|
| Transient | Connection reset, temporary database outage, provider 5xx | Retry with bounded exponential backoff |
| Rate limited | Provider 429 with retry information | Honor `Retry-After`, otherwise use bounded backoff |
| Permanent input | Invalid event payload, unsupported currency, invalid generated content | Mark failed and require correction or review |
| Authentication/configuration | Missing or invalid provider credentials | Mark failed, stop automatic retry until configuration changes |
| Ambiguous delivery | Timeout after request may have reached channel | Mark ambiguous, do not automatically resend |

### Initial defaults

| Work type | Maximum attempts | Initial delay | Maximum delay |
|---|---:|---:|---:|
| Event scoring | 3 | 5 seconds | 5 minutes |
| Content generation | 5 | 30 seconds | 30 minutes |
| Publication | 5 | 30 seconds | 30 minutes |

Defaults must be configurable. Add jitter when concurrent workers are introduced. Attempts are persisted so a process restart does not reset the retry budget.

### Manual retry

Administrators may reset eligible failed work by creating a new content attempt or setting a known-failure publication back to pending. Manual retry must add an audit timestamp and actor reference when an administrator identity system exists.

## 11. Scheduler Responsibilities

Scheduler remains orchestration only. It does not detect price changes, calculate scores, build prompts, generate content, choose destinations, or mutate repository state directly.

### Required jobs

| Job | Application service invoked | EPIC 13 role |
|---|---|---|
| Marketplace ingestion jobs | Existing marketplace application runners | Persist offers, snapshots, and event candidates |
| Pending event processing job | `EventProcessingService` | Claim and score persisted events |
| Content generation job | `ContentGenerationService` | Claim attempts and generate content |
| Publication delivery job | `PublicationService` | Deliver approved content when an adapter exists |
| Stale claim recovery job | `ClaimRecoveryService` | Recover expired work leases safely |

The first EPIC 13 implementation does not need a Telegram adapter. Publication delivery remains inactive until a channel adapter is configured.

### Job behavior

- Jobs call one public application-service method.
- Jobs retain the existing scheduler retry boundary for job invocation failures.
- Work-item retries remain persisted and are not inferred from scheduler process statistics.
- A duplicate scheduler process remains safe because repositories claim rows atomically.

## 12. Administrator Workflow

EPIC 13 defines application operations but does not implement a frontend or public API.

Supported future operations:

- List events by disposition, scoring status, marketplace, event type, and time range.
- Approve, reject, or ignore an event.
- Inspect source snapshot references and price facts.
- List generated content revisions for an event.
- Approve or reject generated content.
- Create a human-edited revision without overwriting the source revision.
- Schedule or cancel a publication.
- Retry a known failed generation or publication.
- Resolve an ambiguous publication after external verification.

The administrator confirms or rejects system decisions. The workflow must not require manually constructing the catalogue or recreating event facts.

## 13. Telegram Boundary

Telegram is a delivery adapter behind a channel-neutral publication application port.

### Allowed future adapter responsibility

- Convert approved content and destination configuration into a Telegram request.
- Call the Telegram API.
- Return a typed delivery outcome containing success, known failure, or ambiguous status.
- Return an external message identifier when available.

### Forbidden coupling

- No Telegram imports in domain event, generated-content, publication, repository, scoring, or content-generation models.
- No chat ID as a core event field.
- No Telegram formatting mode in event identity.
- No Telegram API call inside a database transaction.
- No Telegram-specific retry policy in generic repositories.

## 14. Repositories

Repository contracts must be asynchronous, lifecycle specific, database independent, and free of commit ownership.

### Market event repository

Recommended operations:

```python
async def add_idempotently(candidate: MarketEventCandidate) -> EventAddResult: ...
async def get_by_id(event_id: UUID) -> MarketEvent | None: ...
async def get_by_identity(identity_key: str) -> MarketEvent | None: ...
async def list_pending(now: datetime, limit: int) -> Sequence[MarketEvent]: ...
async def claim_pending(
    now: datetime,
    worker_id: str,
    lease_until: datetime,
    limit: int,
) -> Sequence[ClaimedMarketEvent]: ...
async def mark_scored(
    event_id: UUID,
    claim_token: UUID,
    expected_version: int,
    score: int,
    completed_at: datetime,
) -> bool: ...
async def mark_scoring_failed(
    event_id: UUID,
    claim_token: UUID,
    expected_version: int,
    error: ProcessingError,
    next_retry_at: datetime | None,
) -> bool: ...
async def set_disposition(
    event_id: UUID,
    disposition: EventDisposition,
    changed_at: datetime,
) -> bool: ...
```

### Generated content repository

Recommended operations:

```python
async def create_attempt(command: CreateContentAttempt) -> GeneratedContentAttempt: ...
async def get_by_id(content_id: UUID) -> GeneratedContentAttempt | None: ...
async def list_for_event(event_id: UUID) -> Sequence[GeneratedContentAttempt]: ...
async def claim_pending(...) -> Sequence[ClaimedContentAttempt]: ...
async def complete_attempt(...) -> bool: ...
async def fail_attempt(...) -> bool: ...
async def set_review_status(...) -> bool: ...
```

### Publication repository

Recommended operations:

```python
async def create_idempotently(command: CreatePublication) -> PublicationCreateResult: ...
async def get_by_id(publication_id: UUID) -> Publication | None: ...
async def list_for_event(event_id: UUID) -> Sequence[Publication]: ...
async def claim_pending(...) -> Sequence[ClaimedPublication]: ...
async def mark_published(...) -> bool: ...
async def mark_failed(...) -> bool: ...
async def mark_ambiguous(...) -> bool: ...
```

### Provider integration

`RepositoryProvider` eventually gains `events`, `generated_contents`, and `publications` fields for both memory and PostgreSQL configurations. Add them together only after their contracts and implementations exist. Existing repository fields and business-service call sites remain compatible.

### Prohibited repository behavior

- No scoring or discount calculation.
- No prompt construction or AI call.
- No channel delivery.
- No sleep, retry loop, or backoff policy.
- No implicit commit.
- No generic untyped CRUD interface.

## 15. Database Schema

Use `VARCHAR` plus check constraints for lifecycle values. This keeps state evolution migration friendly. Use explicit constraint and index names.

### Table `market_events`

| Column | PostgreSQL type | Null | Purpose |
|---|---|---:|---|
| `id` | `UUID` | No | Primary key |
| `identity_key` | `CHAR(64)` | No | Deterministic logical identity |
| `identity_version` | `SMALLINT` | No | Identity algorithm version |
| `identity_source` | `VARCHAR(32)` | No | `snapshot_ids` or `legacy_facts` |
| `event_type` | `VARCHAR(64)` | No | Typed event discriminator |
| `marketplace` | `VARCHAR(64)` | No | Marketplace code |
| `external_id` | `VARCHAR(255)` | No | Marketplace offer identifier |
| `canonical_product_id` | `UUID` | Yes | Optional canonical product reference |
| `previous_snapshot_id` | `BIGINT` | Yes | Previous source snapshot |
| `current_snapshot_id` | `BIGINT` | Yes | Current source snapshot |
| `title` | `VARCHAR(1000)` | Yes | Display title at detection time |
| `url` | `VARCHAR(2048)` | Yes | Display URL at detection time |
| `old_price` | `NUMERIC(12,2)` | No | Previous price |
| `new_price` | `NUMERIC(12,2)` | No | Current price |
| `currency` | `VARCHAR(16)` | No | Shared snapshot currency |
| `percentage` | `NUMERIC(12,6)` | No | Deterministic percentage drop |
| `score` | `SMALLINT` | Yes | Persisted importance score |
| `disposition` | `VARCHAR(32)` | No | Administrative event state |
| `scoring_status` | `VARCHAR(32)` | No | Scoring work state |
| `scoring_attempt_count` | `INTEGER` | No | Durable scoring attempts |
| `next_retry_at` | `TIMESTAMPTZ` | Yes | Earliest next scoring attempt |
| `claim_token` | `UUID` | Yes | Current claim guard |
| `worker_id` | `VARCHAR(255)` | Yes | Claim owner for diagnostics |
| `claimed_at` | `TIMESTAMPTZ` | Yes | Claim creation time |
| `lease_expires_at` | `TIMESTAMPTZ` | Yes | Claim expiry time |
| `last_error_code` | `VARCHAR(128)` | Yes | Safe machine-readable error |
| `last_error_summary` | `VARCHAR(2000)` | Yes | Safe diagnostic summary |
| `occurred_at` | `TIMESTAMPTZ` | No | Current snapshot observation time |
| `detected_at` | `TIMESTAMPTZ` | No | Event detection time |
| `created_at` | `TIMESTAMPTZ` | No | Row creation time |
| `updated_at` | `TIMESTAMPTZ` | No | Last state update time |
| `version` | `INTEGER` | No | Optimistic concurrency version |
| `audit_metadata` | `JSONB` | Yes | Optional non-authoritative diagnostics |

Primary key and foreign keys:

- `pk_market_events` on `id`.
- `fk_market_events_canonical_product` references `canonical_products.id` with `ON DELETE SET NULL`.
- `fk_market_events_previous_snapshot` references `price_snapshots.id` with `ON DELETE RESTRICT`.
- `fk_market_events_current_snapshot` references `price_snapshots.id` with `ON DELETE RESTRICT`.

Unique constraints and indexes:

- `uq_market_events_identity_key` unique on `identity_key`.
- `uq_market_events_snapshot_transition` unique on `(event_type, previous_snapshot_id, current_snapshot_id)` where both snapshot IDs are not null.
- `ix_market_events_scoring_claim` on `(scoring_status, next_retry_at, created_at)` where disposition is eligible and scoring status is `pending` or `failed`.
- `ix_market_events_offer_timeline` on `(marketplace, external_id, occurred_at DESC)`.
- `ix_market_events_canonical_timeline` on `(canonical_product_id, occurred_at DESC)` where canonical product ID is not null.

Check constraints:

- `ck_market_events_snapshot_pair`: snapshot IDs are both null or both non-null.
- `ck_market_events_prices_nonnegative`: old and new prices are greater than or equal to zero.
- `ck_market_events_price_drop_direction`: `event_type <> 'price_drop' OR new_price < old_price`.
- `ck_market_events_score_range`: score is null or between 0 and 100.
- `ck_market_events_disposition`: value is one of the defined dispositions.
- `ck_market_events_scoring_status`: value is one of the defined scoring states.
- `ck_market_events_attempt_count`: scoring attempt count is non-negative.
- `ck_market_events_identity_version`: identity version is positive.

### Table `generated_contents`

| Column | PostgreSQL type | Null | Purpose |
|---|---|---:|---|
| `id` | `UUID` | No | Primary key |
| `event_id` | `UUID` | No | Source event |
| `parent_content_id` | `UUID` | Yes | Previous revision |
| `content_type` | `VARCHAR(64)` | No | Publication content kind |
| `language` | `VARCHAR(16)` | No | Content language |
| `origin` | `VARCHAR(32)` | No | `ai` or `human_edit` |
| `provider` | `VARCHAR(128)` | Yes | Non-secret provider label |
| `model` | `VARCHAR(255)` | Yes | Non-secret model label |
| `prompt_version` | `VARCHAR(64)` | No | Prompt/template version |
| `content_text` | `TEXT` | Yes | Generated or edited content |
| `generation_status` | `VARCHAR(32)` | No | Generation lifecycle |
| `review_status` | `VARCHAR(32)` | No | Administrative review lifecycle |
| `attempt_number` | `INTEGER` | No | Monotonic event content attempt |
| `idempotency_key` | `CHAR(64)` | No | Deterministic attempt key |
| `content_checksum` | `CHAR(64)` | Yes | SHA-256 of final UTF-8 text |
| `next_retry_at` | `TIMESTAMPTZ` | Yes | Earliest retry time |
| `claim_token` | `UUID` | Yes | Current claim guard |
| `worker_id` | `VARCHAR(255)` | Yes | Claim owner |
| `claimed_at` | `TIMESTAMPTZ` | Yes | Claim creation time |
| `lease_expires_at` | `TIMESTAMPTZ` | Yes | Claim expiry time |
| `last_error_code` | `VARCHAR(128)` | Yes | Safe machine-readable error |
| `last_error_summary` | `VARCHAR(2000)` | Yes | Safe diagnostic summary |
| `created_at` | `TIMESTAMPTZ` | No | Row creation time |
| `updated_at` | `TIMESTAMPTZ` | No | Last state update time |
| `completed_at` | `TIMESTAMPTZ` | Yes | Terminal completion time |
| `version` | `INTEGER` | No | Optimistic concurrency version |

Primary key and foreign keys:

- `pk_generated_contents` on `id`.
- `fk_generated_contents_event` references `market_events.id` with `ON DELETE RESTRICT`.
- `fk_generated_contents_parent` references `generated_contents.id` with `ON DELETE RESTRICT`.

Unique constraints and indexes:

- `uq_generated_contents_idempotency_key` unique on `idempotency_key`.
- `uq_generated_contents_event_attempt` unique on `(event_id, content_type, language, prompt_version, attempt_number)`.
- `uq_generated_contents_active_generation` unique on `(event_id, content_type, language, prompt_version)` where generation status is `pending` or `in_progress`.
- `ix_generated_contents_claim` on `(generation_status, next_retry_at, created_at)` where generation status is `pending` or `failed`.
- `ix_generated_contents_event_created` on `(event_id, created_at DESC)`.
- `ix_generated_contents_review` on `(review_status, created_at)` where review status is `pending`.

Check constraints:

- `ck_generated_contents_generation_status`: value is one of the defined generation states.
- `ck_generated_contents_review_status`: value is one of the defined review states.
- `ck_generated_contents_origin`: value is `ai` or `human_edit`.
- `ck_generated_contents_attempt_number`: attempt number is positive.
- `ck_generated_contents_terminal_payload`: generated rows have non-empty content, checksum, and completion time; failed rows have an error code.

### Table `publications`

| Column | PostgreSQL type | Null | Purpose |
|---|---|---:|---|
| `id` | `UUID` | No | Primary key |
| `event_id` | `UUID` | No | Source event |
| `content_id` | `UUID` | No | Immutable content revision |
| `channel` | `VARCHAR(64)` | No | Channel adapter key |
| `destination_key` | `VARCHAR(255)` | No | Opaque destination reference |
| `publication_status` | `VARCHAR(32)` | No | Delivery lifecycle |
| `attempt_count` | `INTEGER` | No | Durable delivery attempts |
| `idempotency_key` | `CHAR(64)` | No | Logical delivery identity |
| `external_message_id` | `VARCHAR(255)` | Yes | Provider message identifier |
| `scheduled_at` | `TIMESTAMPTZ` | Yes | Requested delivery time |
| `next_retry_at` | `TIMESTAMPTZ` | Yes | Earliest retry time |
| `published_at` | `TIMESTAMPTZ` | Yes | Confirmed delivery time |
| `claim_token` | `UUID` | Yes | Current claim guard |
| `worker_id` | `VARCHAR(255)` | Yes | Claim owner |
| `claimed_at` | `TIMESTAMPTZ` | Yes | Claim creation time |
| `lease_expires_at` | `TIMESTAMPTZ` | Yes | Claim expiry time |
| `last_error_code` | `VARCHAR(128)` | Yes | Safe machine-readable error |
| `last_error_summary` | `VARCHAR(2000)` | Yes | Safe diagnostic summary |
| `created_at` | `TIMESTAMPTZ` | No | Row creation time |
| `updated_at` | `TIMESTAMPTZ` | No | Last state update time |
| `version` | `INTEGER` | No | Optimistic concurrency version |

Primary key and foreign keys:

- `pk_publications` on `id`.
- `fk_publications_event` references `market_events.id` with `ON DELETE RESTRICT`.
- `fk_publications_content` references `generated_contents.id` with `ON DELETE RESTRICT`.

Unique constraints and indexes:

- `uq_publications_idempotency_key` unique on `idempotency_key`.
- `uq_publications_content_channel_destination` unique on `(content_id, channel, destination_key)`.
- `ix_publications_claim` on `(publication_status, scheduled_at, next_retry_at, created_at)` where status is `pending` or `failed`.
- `ix_publications_event_created` on `(event_id, created_at DESC)`.
- `ix_publications_status_schedule` on `(publication_status, scheduled_at)`.

Check constraints:

- `ck_publications_status`: value is one of the defined publication states.
- `ck_publications_attempt_count`: attempt count is non-negative.
- `ck_publications_published_payload`: published rows have `published_at` and `external_message_id`.

### Migration policy

EPIC 13 implementation must add migrations in dependency order:

1. `market_events`.
2. `generated_contents`.
3. `publications`.

The migrations must not modify historical EPIC 12 migrations. PostgreSQL live verification must cover constraints, idempotent inserts, claim concurrency, and downgrade only when the project migration policy requires downgrade support.

## 16. Duplicate Detector Cleanup

There are two price-change detector modules with overlapping algorithms:

- Active: `app/analytics/price_change.py`.
- Legacy: `app/analytics/price_change_detector.py`.

The active detector preserves marketplace, product identifier, and timestamp and is already used by marketplace runtime processing. It is the canonical implementation for EPIC 13.

Cleanup plan:

- Redirect `PricePipeline` and its demo to the active detector without changing calculation behavior.
- Verify identical unchanged, increase, decrease, and zero-previous-price behavior.
- Remove the legacy module only after no imports remain.
- Do not redesign the percentage algorithm during cleanup.
- Keep detector cleanup in a separate commit from event persistence to make behavioral review explicit.

The inactive event hierarchy in `app/core/events.py` should receive the same treatment: confirm no runtime imports, migrate any remaining type references to the selected domain model, then remove it in a dedicated cleanup task.

## 17. Application Services

### Event candidate builder

Builds a typed event candidate from `PriceChange`, current offer context, and exact source snapshots. It owns no persistence and performs no scoring.

### Event processing service

Claims persisted events, runs the existing deterministic `EventScorer`, persists the score, and creates a content-generation attempt when policy permits.

### Content generation service

Claims a generated-content attempt, converts the durable event into the current prompt input, calls the existing `ContentGenerator`, validates output, and persists success or failure.

### Publication service

Claims publication rows, invokes a channel-neutral delivery port, and records published, failed, or ambiguous outcomes. No concrete Telegram implementation is part of this EPIC.

### Claim recovery service

Recovers expired leases according to work type and ambiguity rules. It does not retry work directly.

### Administrative lifecycle service

Applies explicit disposition and review transitions, validates allowed transitions, and records actor metadata when identity infrastructure becomes available.

## 18. Result and API Boundaries

No HTTP or frontend API is implemented in EPIC 13. Application-service result DTOs must nevertheless be stable, typed, and free of SQLAlchemy models.

### Marketplace ingestion result

Extend runtime results with durable event facts rather than transient event objects:

- `event_ids` or typed event references.
- `events_created`.
- `events_existing`.
- `event_persistence_errors`.

Do not return generated text from ingestion. Content belongs to the post-commit flow.

### Processing batch result

Use a typed summary containing:

- Claimed count.
- Succeeded count.
- Failed count.
- Deferred count.
- Lost-claim count.
- Processed entity IDs.
- Safe error summaries.

### Future API rules

- Expose UUIDs and typed lifecycle strings, not ORM instances.
- Serialize Decimal as strings at external boundaries unless a consumer contract explicitly guarantees decimal-safe handling.
- Serialize timestamps as UTC ISO 8601.
- Do not expose claim tokens, worker IDs, provider credentials, or raw internal errors.

## 19. Failure Matrix

| Failure | Durable state | Automatic action | Duplicate protection | Operator action |
|---|---|---|---|---|
| Crash before ingestion commit | No new snapshot or event; transaction rolls back | Marketplace job may retry | Snapshot and event unique constraints | None normally |
| Crash after event commit | Event remains `pending` | Event processing job claims it | Event identity key | None normally |
| Duplicate scheduler execution | Same candidate may be submitted concurrently | Both workers continue safely | Snapshot uniqueness, event identity, `SKIP LOCKED` | None |
| Scoring exception | Event becomes `failed` with next retry | Retry within persisted budget | Claim token and version | Review after terminal failure |
| Scoring worker loses lease | Stale worker cannot complete | Recovery requeues eligible work | Claim token and version | None normally |
| AI timeout with known failure | Content attempt becomes `failed` | New attempt after backoff | Attempt identity and active-attempt unique index | Review after terminal failure |
| AI returns invalid or empty content | Content attempt becomes permanent `failed` | No blind automatic retry unless policy classifies recoverable | Immutable failed attempt | Correct configuration or retry manually |
| Crash after content save | Generated revision remains durable; publication row is pending if policy created it atomically | Publication job continues | Content checksum and publication identity | None normally |
| Publication connection failure before request acceptance | Publication becomes `failed` | Retry within budget | Publication identity and claim guard | Review after terminal failure |
| Publication timeout after request may have been accepted | Publication becomes `ambiguous` | No automatic resend | Ambiguous state blocks retry | Reconcile externally or resolve manually |
| Crash after channel accepted message but before local success update | Expired `in_progress` publication is treated as potentially ambiguous | Recovery marks ambiguous unless adapter can reconcile by external ID | No blind resend | Reconcile provider state; then mark published or retry |
| Missing provider credentials | Work becomes configuration failure | No automatic retry until configuration changes | Persistent failed state | Fix secret configuration and reset work |
| Database unavailable during completion | Claimed row remains in progress until lease expiry | Recovery evaluates the lease | Claim token and idempotent external identity where available | Investigate repeated outages |
| Administrator rejects event | Event disposition becomes `rejected` | Downstream work is not created; pending unpublished work is cancelled by service policy | Disposition checks | Reopen only through explicit audited action |
| Administrator rejects content | Content review becomes `rejected` | No publication created for that revision | Immutable revision and review state | Create or approve another revision |

## 20. Implementation Plan

### Task 1: Persistent event domain contracts

- Goal: Add typed Decimal-safe event envelope, price-drop payload, identity types, lifecycle enums, and result DTOs.
- Likely files: `app/domain/events.py`, new focused domain modules if needed, and domain unit tests.
- Acceptance: Event identity is deterministic; UTC and Decimal invariants are validated; no SQLAlchemy, AI, scheduler, or Telegram imports exist in the domain.
- Tests: Identity stability, field exclusion, timezone validation, Decimal serialization, typed payload/event-type compatibility.
- Migration impact: None.
- Risks: Accidental public-interface break for current `PriceDropEvent`; mitigate with an explicit temporary adapter.
- Dependencies: Existing `PriceSnapshot`, `PriceChange`, and marketplace identity conventions.
- Non-goals: Persistence, scoring, content generation, publication delivery.

### Task 2: Memory implementations and repository contract tests

- Status: Completed.

- Goal: Implement deterministic memory repositories for the existing asynchronous event, generated-content, and publication contracts.
- Likely files: `app/repositories/memory/memory_events.py`, `app/repositories/memory/memory_generated_contents.py`, `app/repositories/memory/memory_publications.py`, memory package exports, and shared repository contract tests.
- Acceptance: Idempotent add, pending listing, claim, guarded completion, failure, and disposition transitions work without database dependencies.
- Tests: Reusable behavioral contract classes run against each memory repository,
  covering duplicate identity, claim exclusivity, stale claim recovery, lost claim
  token, optimistic conflicts, invalid transitions, immutable revisions, and stable
  ordering.
- Migration impact: None.
- Risks: Memory concurrency semantics can diverge from PostgreSQL; the same behavioral contract suite must be reused for PostgreSQL implementations later.
- Dependencies: Task 1.
- Non-goals: `RepositoryProvider` changes, PostgreSQL, scheduler jobs, runtime integration, scoring policy, AI calls, and publication delivery.

### Task 3: PostgreSQL event model and migration

- Goal: Add `market_events` SQLAlchemy model, migration, mapping, and PostgreSQL repository.
- Likely files: `app/models/market_event.py`, `app/repositories/postgres/postgres_events.py`, model imports, repository provider, `alembic/versions/*`, and repository tests.
- Acceptance: Schema matches Section 15; concurrent duplicate inserts return one logical event; claims use `FOR UPDATE SKIP LOCKED`; repositories never commit.
- Tests: PostgreSQL contract tests, unique constraints, check constraints, FK behavior, exact snapshot resolution, concurrent claims, timezone and Decimal round trips.
- Migration impact: Creates `market_events` and its constraints/indexes.
- Risks: Resolving persisted snapshot IDs without leaking ORM identifiers into the domain boundary.
- Dependencies: Tasks 1 and 2; EPIC 12 transaction manager and PostgreSQL test environment.
- Non-goals: Generated content and publication tables.

### Task 4: Ingestion transaction integration

- Goal: Persist event candidates atomically with offers and snapshots while keeping current detection behavior.
- Likely files: `app/services/marketplace_pipeline.py`, transaction DTOs, transaction manager/provider wiring, and integration tests.
- Acceptance: A detected transition commits one event; duplicate ingestion creates no duplicate; rollback leaves no new snapshot or event; no scoring or AI occurs in the transaction.
- Tests: Commit, rollback, duplicate run, out-of-order snapshot, unchanged price, price increase, price drop, concurrent ingestion.
- Migration impact: None beyond Task 3.
- Risks: Current snapshot domain objects do not expose database IDs; repository mapping must resolve exact persisted rows inside the transaction.
- Dependencies: Task 3.
- Non-goals: Post-commit scoring and content.

### Task 5: Event processing and durable scoring

- Goal: Claim persisted events, reuse `EventScorer`, persist score and failure state, and create content work eligibility.
- Likely files: new `app/services/event_processing.py`, event repository contracts/implementations, scheduler job wiring, and tests.
- Acceptance: Scoring survives restart, retries are bounded, duplicate workers do not score the same claim concurrently, and score remains within 0 to 100.
- Tests: Success, transient failure, permanent failure, lease expiry, lost token, disabled/rejected event, duplicate scheduler invocation.
- Migration impact: None beyond Task 3.
- Risks: Current scorer accepts transient Pydantic `PriceDropEvent` with floats; conversion must preserve persisted Decimal facts and existing thresholds.
- Dependencies: Task 4.
- Non-goals: AI and publication.

### Task 6: Duplicate detector and legacy event cleanup

- Goal: Establish `app/analytics/price_change.py` and the new persistent domain model as the only active paths.
- Likely files: `app/services/price_pipeline.py`, affected demos/imports, deletion of unused modules after verification, and tests.
- Acceptance: No runtime import references the legacy detector or inactive event hierarchy; all previous detector behavior remains unchanged.
- Tests: Parity tests for decrease, increase, unchanged price, zero baseline, metadata preservation.
- Migration impact: None.
- Risks: Demo-only imports can conceal remaining usage; perform targeted import search before deletion.
- Dependencies: Task 5 is preferred so the target event path already exists.
- Non-goals: Algorithm changes or new event types.

### Task 7: Generated content contracts and persistence

- Goal: Add immutable content attempts, repository contracts, memory/PostgreSQL implementations, and migration.
- Likely files: domain content models, `app/repositories/generated_contents.py`, memory/PostgreSQL implementations, `app/models/generated_content.py`, provider wiring, `alembic/versions/*`, and tests.
- Acceptance: Attempts are immutable after terminal state; only one active attempt exists per generation key; human revisions preserve parent linkage; no secrets are stored.
- Tests: Attempt numbering, active uniqueness, claim concurrency, generated validation, failed validation, human revision, Decimal/UTC unaffected.
- Migration impact: Creates `generated_contents` and its constraints/indexes.
- Risks: Prompt or provider diagnostics may accidentally persist sensitive data; keep the stored contract intentionally narrow.
- Dependencies: Tasks 3 and 5.
- Non-goals: Telegram and public admin UI.

### Task 8: Content generation service and scheduler job

- Goal: Move content generation from immediate post-commit memory processing to claimed durable attempts.
- Likely files: new application service, scheduler job module, runtime composition, existing content generator adapters, and tests.
- Acceptance: AI runs outside database transactions; crashes leave recoverable work; invalid output is durable; existing `FakeAIProvider` behavior remains usable.
- Tests: Successful generation, timeout, invalid response, provider exception, stale lease, process restart simulation, duplicate worker.
- Migration impact: None beyond Task 7.
- Risks: Preserving current prompt/scoring behavior while changing orchestration timing.
- Dependencies: Task 7.
- Non-goals: External provider redesign and publication delivery.

### Task 9: Publication contracts and persistence

- Goal: Add channel-neutral publication domain model, repositories, SQLAlchemy model, and migration.
- Likely files: domain publication models, repository contracts and implementations, `app/models/publication.py`, provider wiring, `alembic/versions/*`, and tests.
- Acceptance: Publication creation is idempotent; claims are exclusive; published, failed, ambiguous, and cancelled transitions are guarded; no Telegram imports exist.
- Tests: Duplicate creation, scheduling, claims, known failure, ambiguous result, published validation, stale lease recovery.
- Migration impact: Creates `publications` and its constraints/indexes.
- Risks: Treating an ambiguous timeout as a normal failure would create duplicate public posts.
- Dependencies: Task 7.
- Non-goals: Concrete Telegram API calls.

### Task 10: Lifecycle orchestration and recovery

- Goal: Add publication and stale-claim application services, persisted retry policies, and scheduler jobs.
- Likely files: application services, scheduler jobs, runtime composition, configuration, and tests.
- Acceptance: Scheduler remains orchestration only; expired leases recover safely; terminal budgets stop retrying; ambiguous publication never auto-resends.
- Tests: Restart recovery, max attempts, backoff scheduling, rate-limit delay, ambiguous delivery, scheduler overlap.
- Migration impact: None beyond Tasks 7 and 9.
- Risks: Scheduler-level retries and item-level retries could multiply attempts; item policy must be authoritative.
- Dependencies: Tasks 8 and 9.
- Non-goals: Distributed broker and Telegram adapter.

### Task 11: Administrative application operations

- Goal: Add typed services for event disposition, content review, human revision, publication scheduling, cancellation, retry, and ambiguity resolution.
- Likely files: application services, repository contracts where transitions are missing, and tests.
- Acceptance: Only valid transitions succeed; rejected work does not publish; prior revisions and failures remain auditable.
- Tests: Transition matrix, concurrent administrator updates, retry audit, revision lineage, rejected event/content behavior.
- Migration impact: No new tables expected; actor columns may require a later migration when administrator identity exists.
- Risks: No identity system currently exists, so actor attribution must not be fabricated.
- Dependencies: Tasks 7, 9, and 10.
- Non-goals: Frontend, FastAPI endpoints, authentication, and authorization.

### Task 12: End-to-end PostgreSQL verification

- Goal: Verify ingestion through persisted event, scoring, content generation, publication preparation, retry, and restart recovery.
- Likely files: verification scripts, integration tests, and a new verification document.
- Acceptance: Live PostgreSQL proves exactly-once logical event creation, at-least-once processing with idempotent completion, no open transaction during AI, restart recovery, and audit history.
- Tests: Full happy path, every failure in Section 19, two-worker claims, duplicate scheduler, transaction rollback, AI failure, publication ambiguity.
- Migration impact: Applies all EPIC 13 migrations to a clean and upgraded EPIC 12 database.
- Risks: A demo-only happy path can hide concurrency defects; live integration tests are mandatory.
- Dependencies: Tasks 1 through 11 as applicable.
- Non-goals: Production Telegram delivery and public release.

## 21. Test Plan

### Domain tests

- Deterministic event identity across repeated construction.
- Identity changes when either source snapshot changes.
- Identity does not change when title, URL, score, or canonical mapping changes.
- Decimal values never pass through float conversion.
- Naive datetimes are rejected or explicitly normalized at one documented boundary.
- Event type and payload type cannot disagree.

### Repository contract tests

- Run the same behavioral suite against memory and PostgreSQL repositories.
- Verify idempotent create returns the same logical entity.
- Verify claims are exclusive.
- Verify stale claim tokens cannot complete work.
- Verify invalid lifecycle transitions fail without partial mutation.
- Verify repositories do not commit their transaction.

### PostgreSQL integration tests

- Concurrent event insertion under the same identity.
- Concurrent `SKIP LOCKED` claims across two sessions.
- Unique and check constraints named in Section 15.
- Foreign-key delete behavior.
- `TIMESTAMPTZ` UTC round trip.
- `NUMERIC` Decimal round trip.
- Transaction rollback across offer, snapshot, and event writes.
- Upgrade from the final EPIC 12 migration.

### Application-service tests

- Scoring success, failure, retry budget, and stale claim recovery.
- Content generation success, timeout, invalid output, and process restart.
- Publication known failure versus ambiguous outcome.
- Administrator approval, rejection, ignore, and retry transitions.
- Scheduler overlap without duplicate logical processing.

### End-to-end verification

- Real marketplace ingestion creates a durable event candidate when a real price drop is observed.
- A controlled second snapshot can be used where live marketplace prices do not change during verification.
- Persisted event survives process restart and is scored afterward.
- Generated content survives process restart.
- Publication preparation is channel neutral.
- No test claims successful Telegram delivery until a real adapter and destination are configured.

## 22. EPIC Acceptance Criteria

EPIC 13 is complete when all of the following are true:

- Price-drop events have a typed, Decimal-safe, UUID-addressable domain model.
- Event identity is deterministic, versioned, documented, and database enforced.
- A price-drop event is persisted atomically with its source snapshot transaction.
- Repeated ingestion and concurrent workers cannot create duplicate logical events.
- Event scoring state and score survive process restarts.
- Generated content attempts and human revisions are durable and auditable.
- Publication records are durable, channel independent, and idempotent.
- Known failures and ambiguous delivery outcomes have different states.
- AI and delivery calls never execute while a database transaction is open.
- Work claiming uses short `FOR UPDATE SKIP LOCKED` transactions, leases, claim tokens, and version guards.
- Retry budgets and next-run timestamps are durable and owned by application services.
- Scheduler jobs contain orchestration only.
- Memory and PostgreSQL repository implementations satisfy shared contract tests.
- Legacy duplicate detector and inactive event paths no longer participate in runtime processing.
- All new tables use UTC `TIMESTAMPTZ`, Decimal-compatible `NUMERIC`, named constraints, and query-supporting indexes.
- No secrets, authorization headers, or provider credentials are persisted.
- PostgreSQL end-to-end verification covers restart, duplicate, concurrency, rollback, and failure scenarios.

## 23. Recommended First Implementation Task

Start with **Task 1: Persistent event domain contracts**.

It is the smallest safe step because it has no migration, provider, scheduler, AI, or marketplace side effects. It establishes the event vocabulary, Decimal and UTC invariants, snapshot identity, lifecycle enums, and idempotency algorithm required by every later repository and migration.

The first implementation commit should contain only:

- Typed event envelope and price-drop payload.
- Snapshot identity value object.
- Event identity builder with `identity_version = 1`.
- Lifecycle enums and typed add/claim result DTOs needed by the next repository task.
- Focused unit tests for identity, Decimal, UTC, and payload invariants.
- A compatibility adapter for the existing transient `PriceDropEvent` only if current imports require it.

It must not contain SQLAlchemy models, Alembic migrations, repository implementations, scheduler jobs, AI calls, publication code, or cleanup of legacy modules.
