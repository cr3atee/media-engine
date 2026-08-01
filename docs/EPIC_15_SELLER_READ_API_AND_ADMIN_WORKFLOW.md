# EPIC 15 - Seller Read API and Administration Workflow

Status: Task 1 implemented and verified; Task 2 administration mutations and immutable audit persistence are implemented and verified against isolated PostgreSQL 17.10

Baseline commit: c48b06c11f10cd41981d6809c36ea30c94ee66ef

The original sections retain the approved EPIC design. The implementation record
at the end of this document describes the completed read-only Task 1 boundary.
No frontend, administration mutation, audit migration, or Telegram operation was
introduced by Task 1.

## Current Evidence

EPIC 14 is functionally complete at the durable delivery boundary:

- Telegram delivery contracts and a Telegram adapter exist.
- Plain-text formatting is deterministic and bounded.
- PublicationDeliveryService owns claims, delivery outcome classification, and
  guarded persistence.
- Publication claims are channel-scoped.
- Success, retryable failure, permanent failure, and ambiguous delivery states are
  represented durably.
- Telegram 429 responses and retry-after handling are covered.
- Dry-run is read-only.
- Scheduler delivery orchestration exists.
- PostgreSQL verification passed 39/39 checks.
- Telegram adapter verification passed 16/16 checks.
- Full Pytest passed 265 tests with 53 skipped.
- MyPy, Ruff, Ruff format, and Alembic verification passed for the recorded run.
- Guarded live Telegram test-chat delivery was not performed.
- EPIC 15 Task 2 guarded content review and publication administration commands
  are implemented with immutable `admin_actions` persistence, guarded
  transitions, idempotent replay, sanitized admin errors, and isolated
  PostgreSQL verification.
- Task 2 PostgreSQL verification passed `26/26` checks on PostgreSQL 17.10 at
  revision `0009_admin_actions`.

The database already stores durable marketplace offers, price snapshots, market
events, scoring state, generated-content attempts, content review state,
publication intents, and publication delivery state.

The current FastAPI application now exposes both the read boundary and guarded
administration mutation routes. The administration API remains an internal
boundary rather than a seller-facing feature because seller identity and tenant
scoping still do not exist.

Some Project Passport pages still contain historical EPIC 14 wording that predates
the final verification commit. For implementation decisions, the current code and
docs/EPIC_14_FINAL_VERIFICATION.md are authoritative. The documentation drift is
recorded here so it is not mistaken for an API capability.

## 1. Product Boundary

EPIC 15 exposes a stable HTTP boundary for:

- a future seller dashboard;
- an internal administration workflow;
- operational inspection of event, content, and publication state;
- manual lifecycle actions that require an authorized human.

It is not:

- a public marketplace API;
- a Telegram bot command interface;
- a frontend application;
- a replacement for repositories;
- a direct ORM exposure layer;
- a general analytics warehouse;
- a multi-tenant billing system;
- a second event-processing or delivery engine.

### Seller and administration boundary

The project does not currently have seller identity, tenant ownership, or
permission records. Exposing a route called seller-facing before those concepts
exist would falsely imply isolation between sellers. The safe MVP decision is:

| Boundary | MVP status | Intended data |
| --- | --- | --- |
| Authenticated administration API | Implement first | Internal operators can inspect all project records and perform guarded workflow actions. |
| Seller-facing read API | Reserve, do not expose yet | Only records belonging to an authenticated seller after ownership and tenant rules exist. |
| Read-only operator role | Future scope | Read access without state-changing commands. |
| Reviewer role | Future scope | Content review actions only, subject to policy. |
| Publication administrator role | Future scope | Retry, cancellation, and ambiguous resolution. |

For the current MVP, one authenticated administration API with future role
separation is safer than prematurely implementing seller/admin RBAC. The route
namespace should still make the boundary explicit: initial routes live under
/api/v1/admin. A later seller API can be added under /api/v1/seller only after
authorization is based on a real seller identity and every query is tenant
scoped.

## 2. API Architecture

The target dependency direction is:

    HTTP route
        -> request DTO validation
        -> application query or command service
        -> repository contract
        -> domain lifecycle operation
        -> response DTO

Routes must not:

- open raw SQLAlchemy queries;
- manipulate ORM records;
- calculate lifecycle transitions;
- call Telegram;
- run AI generation;
- contain retry policy;
- bypass claim or optimistic-version protections;
- translate arbitrary exceptions into public response text.

### Proposed package layout

This is a proposed layout, not a set of files to create in this task:

    app/api/
        dependencies.py
        errors.py
        middleware.py
        routes/
            admin_events.py
            admin_content.py
            admin_publications.py
            admin_dashboard.py
            health.py
        schemas/
            common.py
            events.py
            content.py
            publications.py
            dashboard.py
            commands.py
    app/services/
        admin_queries.py
        content_review.py
        publication_administration.py
        dashboard.py
    app/repositories/
        queries/
            events.py
            generated_contents.py
            publications.py
            dashboard.py

The exact module names can follow existing naming conventions, but the boundary
should remain the same. Pydantic v2 DTOs belong at the HTTP boundary. Domain
dataclasses and repository contracts remain independent of FastAPI and
SQLAlchemy. A request should acquire a repository scope through the existing
composition and session infrastructure; a command should finish its database
mutation and audit write before returning. No external Telegram or AI call may
run inside that transaction.

## 3. API Versioning and Route Structure

Use one coherent REST-oriented namespace:

    /api/v1/admin

Resource reads use GET. Lifecycle changes use explicit action endpoints because
the action names make state transitions and authorization reviewable. These
actions remain application commands, not RPC implementations hidden in routes.

### Proposed routes

| Method | Route | Boundary | Purpose |
| --- | --- | --- | --- |
| GET | /api/v1/admin/events | Admin read | List durable market events. |
| GET | /api/v1/admin/events/{event_id} | Admin read | Return one typed event and related summaries. |
| GET | /api/v1/admin/events/{event_id}/content | Admin read | List content attempts for an event. |
| GET | /api/v1/admin/events/{event_id}/publications | Admin read | List publication intents for an event. |
| GET | /api/v1/admin/content | Admin read | List generated-content attempts. |
| GET | /api/v1/admin/content/{content_id} | Admin read | Inspect one content attempt or revision. |
| GET | /api/v1/admin/content/{content_id}/publications | Admin read | List publications for content. |
| POST | /api/v1/admin/content/{content_id}/approve | Admin command | Approve eligible generated content. |
| POST | /api/v1/admin/content/{content_id}/reject | Admin command | Reject content with a bounded reason. |
| GET | /api/v1/admin/publications | Admin read | List publication intents and delivery state. |
| GET | /api/v1/admin/publications/{publication_id} | Admin read | Inspect one publication. |
| POST | /api/v1/admin/publications/{publication_id}/retry | Admin command | Requeue only a safely retryable publication. |
| POST | /api/v1/admin/publications/{publication_id}/cancel | Admin command | Cancel an eligible publication. |
| POST | /api/v1/admin/publications/{publication_id}/resolve-ambiguous | Admin command | Explicitly resolve uncertain external delivery. |
| GET | /api/v1/admin/dashboard/summary | Admin read | Return bounded operational counters. |

The existing root endpoint remains separate. Liveness and readiness are
operational endpoints rather than domain resources:

    /health/live
    /health/ready

No seller route should be enabled as an alias for an admin route. A future
seller route must have a separately reviewed response model and tenant filter.

## 4. Authentication and Authorization

### MVP authentication decision

Use one environment-provided administration API key for the first API slice:

- store it as SecretStr in settings;
- read it from an explicitly named environment variable;
- require it in a dedicated header such as X-Admin-API-Key;
- compare supplied and configured values with hmac.compare_digest;
- never log either value;
- fail closed if authentication is enabled but the key is absent;
- refuse an unsafe no-auth configuration outside an explicitly identified
  development or test environment.

This is appropriate for an internal MVP behind TLS and a trusted reverse proxy.
It is not a final multi-user identity system. JWT, OAuth, registration, password
reset, and full RBAC are out of scope because current code has no user store or
identity provider requirement.

The dependency should return a small internal principal, for example an
administrator identity and a future role set. It must not pass secrets into
application services. The initial principal can be a configured administrator;
future role separation should be added behind the same authorization boundary.

### Future conceptual roles

- Read-only operator: list and inspect resources and dashboard metrics.
- Reviewer: approve or reject generated content.
- Publication administrator: retry, cancel, and resolve ambiguous delivery.

The API key should not be presented as proof of a seller's ownership. Until
seller identity exists, all seller-facing access remains disabled.

## 5. Security Requirements

Responses and logs must never expose:

- Telegram bot tokens;
- database URL credentials;
- claim tokens;
- worker IDs unless a separately approved operational view requires them;
- raw exception text or stack traces;
- full provider responses;
- ORM objects or internal SQLAlchemy state;
- application secrets;
- tokenized Telegram URLs.

The existing Telegram security utilities already establish useful behavior:
known and token-shaped credentials are redacted, provider messages are bounded,
and destination references can be hashed. The API should reuse those principles
without importing Telegram concerns into domain DTOs.

Expose optimistic version as a safe integer concurrency field. Do not expose
claim tokens. Error responses must use stable public codes and sanitized
messages. Limit request bodies and reason/search fields at the DTO boundary.
Reject oversized content instead of silently truncating an administrative
command.

## 6. Market Event Read API

### List

GET /api/v1/admin/events accepts typed filters:

- marketplace;
- event type;
- disposition;
- scoring status;
- content-generation status;
- content review status;
- publication status;
- minimum score;
- canonical product ID, product identifier, or marketplace external ID;
- created-at range;
- detected-at range;
- has generated content;
- has a publication;
- has a failure;
- ambiguous publication only.

The last several filters require an existence check or a read-side join with
content/publication state. They should not be simulated by loading every event
into Python. The default order is detected_at descending, then event ID
descending. If detected_at is absent for a particular query projection, created_at
descending and event ID descending is the fallback.

### Detail

GET /api/v1/admin/events/{event_id} returns an immutable response DTO containing:

- event ID, identity key, and version;
- event type and marketplace;
- external offer identifier and canonical product identifier when present;
- typed event payload;
- previous and current snapshot identities;
- old and new Decimal prices represented as JSON strings;
- currency, absolute difference, percentage, and source URL;
- occurred, detected, and created timestamps as UTC ISO-8601 values;
- disposition and scoring states;
- score, scoring attempt, and safe retry metadata;
- summaries of related generated content and publications.

Claims, claim tokens, raw last-error values, and worker internals are not part
of the default response.

The current MarketEventRepository supports lifecycle-oriented pending lists,
claims, scoring completion, disposition changes, and related eligibility. It
does not provide the arbitrary filters, detail projection, or cross-resource
summary needed by this endpoint. That is a query-side gap, not a reason to
change event identity or add SQL to the route.

## 7. Event Payload Representation

Payloads use a stable discriminator and explicit schema version:

~~~json
{
  "type": "price_drop",
  "version": 1,
  "title": "Minecraft Premium",
  "old_price": "990",
  "new_price": "790",
  "currency": "RUB",
  "percentage": "20.2020202020",
  "previous_snapshot": {
    "marketplace": "playerok",
    "external_id": "offer-1",
    "price": "990",
    "currency": "RUB",
    "collected_at": "2026-08-01T10:00:00Z"
  },
  "current_snapshot": {
    "marketplace": "playerok",
    "external_id": "offer-1",
    "price": "790",
    "currency": "RUB",
    "collected_at": "2026-08-01T11:00:00Z"
  }
}
~~~

The exact payload values are illustrative only; the response must be produced
from the durable domain object. Decimal values are strings to avoid JSON
floating-point loss. Future event types add a new typed discriminator/version
and a new response schema. Python class names and arbitrary JSON columns are
never serialized as the public contract.

## 8. Generated Content Read API

The following reads are sufficient for the first dashboard:

- GET /api/v1/admin/content;
- GET /api/v1/admin/content/{content_id};
- GET /api/v1/admin/events/{event_id}/content.

List filters should include event ID, generation status, review status, content
type, language, attempt number, created/completed ranges, and whether a usable
latest revision exists. Detail responses may include:

- content ID and event ID;
- content type and language;
- attempt number and parent/revision relationship;
- generation and review statuses;
- rendered text as plain JSON data;
- checksum;
- provider/model and prompt version when approved for operational exposure;
- created, completed, and reviewed timestamps;
- bounded sanitized error category/summary;
- publication summaries.

Do not expose credentials, raw provider responses, prompts that contain secrets,
claim tokens, or unbounded exception text. The current
GeneratedContentRepository can create, claim, complete, fail, list by event,
return latest revision, and set review status. It has no actor/reason history and
no general filtered read contract; those are part of the planned query and audit
work.

## 9. Content Review Commands

### Approve

POST /api/v1/admin/content/{content_id}/approve accepts expected_version and
request correlation context. The command service must:

1. load the durable attempt;
2. require a generated, usable attempt with review pending;
3. apply the domain review transition;
4. persist with expected version;
5. write an audit action in the same transaction;
6. return the safe content DTO and resulting version.

Repeated approval of an already approved attempt is a compatible idempotent
request. Approval of rejected content is a 409 conflict. A stale version is a
409 conflict even when the requested state might otherwise be valid.

Approval should only change review state. EPIC 13's content processing path
already creates a publication intent when a configured publication target is
created, and delivery eligibility waits for review approval. Recreating an
intent inside the approve route would duplicate orchestration. If an eligible
content attempt has no publication intent, a separately explicit scheduling or
publication-intent command can be designed later; approval must not silently
invent one in this EPIC.

### Reject

POST /api/v1/admin/content/{content_id}/reject requires a bounded, non-empty
reason. The command service applies the review transition, persists the expected
version, and writes actor, reason, and correlation data to the immutable audit
record. Repeated rejection with the same terminal state is compatible; a
conflicting approval is a 409. Generated history is never deleted. Published
content is not retroactively represented as unsent.

The current repository method set_review_status is enough for the state update
but does not persist an actor or reason. The audit design below closes that
administration gap without adding mutable review metadata to the content
record.

## 10. Publication Read API

The following reads are proposed:

- GET /api/v1/admin/publications;
- GET /api/v1/admin/publications/{publication_id};
- GET /api/v1/admin/events/{event_id}/publications;
- GET /api/v1/admin/content/{content_id}/publications.

Supported filters:

- event ID and content ID;
- channel;
- status;
- retryable, permanent, or ambiguous classification;
- scheduled-at and next-retry ranges;
- attempt count;
- safe destination reference;
- published-at range.

Safe response fields:

- publication ID, event ID, and content ID;
- channel;
- masked destination or stable destination hash;
- status;
- attempt count;
- scheduled, next-retry, and published timestamps;
- external message ID when durable success recorded;
- sanitized error category and message;
- ambiguous reason in bounded form;
- created/updated timestamps;
- optimistic version.

Claim tokens are never returned. Worker ID and lease expiration should remain
internal by default. If an operational admin detail view later needs lease
visibility, expose only a bounded lease timestamp and never the worker or token;
this is not required for the first read slice.

The current PublicationRepository supports event reads, pending/expired claims,
guarded completion, and cancellation, but not arbitrary list filters or detail
projections. A dedicated query contract is safer than adding dashboard joins to
the delivery repository.

## 11. Publication Retry Command

POST /api/v1/admin/publications/{publication_id}/retry does not call Telegram.
It only moves a safely retryable publication back to a scheduler-eligible state.

Allowed by default:

- a known retryable failed publication;
- a resolved ambiguous publication explicitly marked not delivered;
- a failed publication below the configured attempt budget.

Not allowed:

- published;
- actively claimed;
- cancelled;
- unresolved ambiguous;
- exhausted failure without a separately authorized override;
- invalid content or invalid destination.

The command must:

- validate the lifecycle state;
- require expected_version;
- require a bounded reason;
- preserve attempt count and prior error/audit history;
- reset only the minimum scheduling/claim fields;
- persist and audit atomically;
- return the new pending state for later Scheduler processing.

The existing lifecycle allows failed-to-pending, but the repository contract
does not expose a dedicated manual retry operation or policy-specific result.
Task 2 should add a guarded application command and minimal repository operation
rather than mutate status in a route. A permanent-failure override, if ever
needed, must be an explicit privileged operation, not an accidental side effect
of retry.

## 12. Publication Cancellation

POST /api/v1/admin/publications/{publication_id}/cancel requires a bounded
reason and expected_version. It is eligible for pending, scheduled, and known
retryable failed records. A pending record may be cancelled before the scheduler
claims it.

Cancellation is rejected for:

- published;
- active in-progress delivery whose outcome is still uncertain;
- unresolved ambiguous;
- already cancelled, unless the request is a compatible idempotent repeat.

Ambiguous records use the dedicated resolution endpoint, not cancellation
through a generic route. Cancellation never calls Telegram and preserves all
existing durable state and audit history.

The exact state guard must be implemented by the command service and domain
transition, not inferred from HTTP route code. Existing PublicationStatus
transitions already distinguish pending, in_progress, published, failed,
ambiguous, and cancelled; the current admin operation layer is missing.

## 13. Ambiguous Delivery Resolution

POST /api/v1/admin/publications/{publication_id}/resolve-ambiguous is the only
manual path for an unresolved ambiguous publication. It accepts one explicit
decision:

### Mark delivered

- only an ambiguous publication;
- administrator confirmation and bounded reason required;
- external Telegram message ID required for the normal path;
- transition to published;
- no retry and no Telegram request.

Requiring an external message ID preserves the domain invariant that published
means a confirmed external message. If a future operational policy allows
confirmation without an ID, that must first change the domain contract and
audit policy; it must not be smuggled through this API.

### Mark not delivered

- administrator confirmation and reason required;
- transition to pending or the explicitly retryable state;
- preserve attempt and ambiguity history;
- allow a later Scheduler run;
- do not send immediately.

### Cancel

- reason required;
- transition to cancelled;
- no retry and no external call.

All decisions require expected_version and produce a guarded atomic transition
plus audit record. A stale administrator request is rejected. A repeated
compatible decision returns the current terminal state; a conflicting decision
returns 409. The service never infers delivery from timing and never queries
Telegram history automatically in EPIC 15.

The current publication repository has mark_ambiguous and guarded completion
methods and the lifecycle permits ambiguous-to-published, pending, or cancelled.
It does not provide a dedicated administrative resolution contract, so Task 2
must add one consistently to memory and PostgreSQL implementations.

## 14. Audit Trail

Current durable event, content, and publication rows preserve lifecycle state,
versions, claim metadata, and bounded operational errors. Application logs
provide execution evidence. Neither is sufficient as an immutable record of who
manually approved, rejected, retried, cancelled, or resolved an external
delivery outcome. Manual ambiguous resolution in particular requires durable
audit evidence.

### Selected approach

Add one immutable admin_actions table in Task 2. This is smaller and safer than
adding actor/reason columns separately to three mutable domain tables.

Proposed columns:

| Column | Type/constraint | Meaning |
| --- | --- | --- |
| id | UUID primary key | Audit record identity. |
| actor_id | VARCHAR(128), non-empty | Authenticated principal, never a secret. |
| action | VARCHAR(64), allowlisted | approve, reject, retry, cancel, resolve_delivered, resolve_not_delivered, or equivalent. |
| resource_type | VARCHAR(32), allowlisted | content or publication initially. |
| resource_id | UUID, non-null | Affected durable record. |
| previous_state | VARCHAR(64), non-empty | State observed in the guarded transaction. |
| new_state | VARCHAR(64), non-empty | State after the transition. |
| reason | VARCHAR(2000), non-empty for destructive/ambiguous actions | Human explanation, bounded and sanitized. |
| request_id | VARCHAR(128), non-empty | HTTP correlation identifier. |
| expected_version | INTEGER, nullable | Version supplied by the command. |
| resulting_version | INTEGER, positive | Version committed by the command. |
| created_at | TIMESTAMPTZ, UTC, non-null | Immutable action time. |
| metadata | JSONB, optional allowlisted object | Small safe facts only; no secrets, tokens, raw bodies, or provider responses. |

Use a CHECK or database enum for resource_type and action, length checks for
text, positive version checks, and an append-only repository contract with no
update/delete operation. Index resource_type/resource_id/created_at descending,
actor_id/created_at descending, and request_id. A generic resource_type/resource_id
pair avoids nullable foreign keys across three tables; application validation and
the resource-specific command transaction maintain referential meaning. If the
team later requires database-enforced foreign keys, separate audit tables can be
considered, but that is not justified for the first slice.

The audit insert and state mutation must share one database transaction. If the
audit insert fails, the state change rolls back. Read requests do not create
audit rows.

## 15. Dashboard Summary API

GET /api/v1/admin/dashboard/summary returns operational counters, not a BI
warehouse. Default window: the last 24 hours in UTC. Allow an explicit UTC
from/to range with a bounded maximum, such as 31 days, and reject inverted or
naive timestamps.

Recommended counters:

- new events in the window;
- events awaiting scoring;
- scoring failures;
- content generation pending and failed;
- content awaiting review;
- approved content awaiting publication;
- publications pending;
- retryable publications;
- permanently failed publications;
- ambiguous publications;
- published publications;
- delivery success count/rate where denominator is defined;
- latest successful publication timestamp.

The current Scheduler keeps execution statistics in process memory. Therefore
latest successful pipeline run is not a durable metric today. Omit it or return
null with an explicit availability indicator rather than inventing a value.

Use DashboardQueryRepository for bounded aggregate queries, preferably one
transaction-consistent query set. Do not load all events or publications into
Python. Expected freshness is seconds to a small number of minutes, depending
on normal database load; this is an operational dashboard, not a real-time
stream.

The response should be a versioned Pydantic DTO with the UTC window, generated
at timestamp, counts, and an optional freshness note. No provider credentials,
claim data, or raw errors belong in it.

## 16. Pagination

Use deterministic keyset/cursor pagination for growing event, content, and
publication lists. Offset pagination is already useful for one internal
eligibility method, but it becomes unstable and increasingly expensive when
records are inserted while an operator pages through a list.

Recommended defaults:

- default page size: 50;
- maximum page size: 100;
- reject zero, negative, or excessive sizes;
- use a stable descending order by primary timestamp plus UUID.

Stable keys:

- events: detected_at DESC, id DESC;
- content: created_at DESC, id DESC;
- publications: created_at DESC, id DESC.

The cursor is an opaque URL-safe encoding of a versioned object containing the
last sort timestamp, last UUID, direction, and a hash of normalized filters.
Validate the schema, timestamp timezone, UUID, sort version, and filter binding.
Do not expose SQL offsets, ORM objects, or arbitrary serialized query state.
Invalid, expired, or filter-mismatched cursors return a stable 400 error.

The response contains items and an optional next_cursor. A later implementation
may sign cursors with an internal key if tamper detection is required; even
without signing, strict decoding and filter binding are mandatory.

## 17. Filtering and Sorting

Use Pydantic v2 query DTOs with explicit enums for marketplace, event type,
disposition, scoring state, content review state, publication state, channel,
and error class. Date ranges must be timezone-aware UTC values. Reject a
from value later than to, excessive ranges, and overlong text.

Define exact and partial search separately:

- IDs, marketplace, channel, status, and dates are exact filters;
- title/content search is bounded case-insensitive partial search;
- URL search is exact or prefix-only, not arbitrary user-supplied SQL.

Allow-list sort fields and directions. A request must never supply a raw SQL
column name or an expression. Use deterministic secondary UUID ordering for
every sort. Avoid a general-purpose query language; the state model is small
enough for explicit parameters.

## 18. Search

MVP search should cover:

- marketplace external ID;
- canonical product ID;
- event/product title;
- generated content text;
- source URL.

PostgreSQL ILIKE with bounded input is sufficient for an initial internal
operator API, especially for exact IDs and modest title searches. Add only
indexes justified by observed queries. Prefix/exact lookup should use normal
indexes where possible. If arbitrary substring title/content search becomes a
measured bottleneck, evaluate pg_trgm in a separate migration; do not introduce
Elasticsearch or another service in EPIC 15.

Search must never return records outside the authorized scope. A future seller
search query must add the seller/tenant predicate before any text predicate.

## 19. Repository and Query Contracts

### Existing state

The current contracts are deliberately database-independent and lifecycle
oriented:

- MarketEventRepository handles identity insertion, scoring claims, scoring
  completion/failure, disposition, and content eligibility.
- GeneratedContentRepository handles attempts, claims, completion/failure,
  latest revision, event listing, and review status.
- PublicationRepository handles idempotent intent creation, delivery claims,
  guarded outcomes, event listing, and cancellation.

These contracts do not expose a general filtered list/detail projection for the
administration UI.

### Options

Option A would add every filter, join, sort, and dashboard method to the domain
repositories. That would make delivery and lifecycle contracts know about
operator projections and cross-resource joins.

Option B introduces read-side query repositories that return immutable read DTOs:

- MarketEventQueryRepository;
- GeneratedContentQueryRepository;
- PublicationQueryRepository;
- DashboardQueryRepository.

### Decision

Choose Option B. Query contracts remain SQLAlchemy-independent and accept typed
filter/cursor objects. PostgreSQL implementations may use joins, EXISTS
subqueries, and aggregate queries internally. They return API-neutral read
models, not ORM rows. Memory implementations are required only for query and
service tests where they provide meaningful coverage; they are not required to
reproduce every PostgreSQL search optimization.

Lifecycle repositories remain the source for guarded writes and worker claims.
Command services use those contracts, while query services use the read-side
contracts. This preserves the existing repository/provider boundary and avoids
duplicating domain transition logic.

## 20. Command Services

Create focused application services rather than putting workflows in routes:

### ContentReviewService

- load content;
- validate generated/reviewable state;
- apply approve or reject transition;
- persist with expected version;
- append admin action;
- return immutable content result DTO.

### PublicationAdministrationService

- load publication;
- validate retry, cancel, or ambiguous resolution policy;
- apply one guarded lifecycle operation;
- preserve attempt/error history;
- append admin action;
- return immutable publication result DTO.

Command services do not:

- raise FastAPI HTTP exceptions;
- import route modules;
- send Telegram requests;
- run AI;
- manage Scheduler;
- mutate ORM objects directly;
- open an unrelated transaction for each sub-step.

They translate repository/domain outcomes into application result types. The
HTTP layer maps those results to status codes and public error envelopes.

## 21. HTTP Error Model

Use one stable envelope:

~~~json
{
  "error": {
    "code": "publication_not_retryable",
    "message": "Publication cannot be retried in its current state.",
    "details": {},
    "request_id": "req-01J...",
  }
}
~~~

The trailing comma is illustrative only; the actual JSON must be valid.

Recommended mappings:

| Condition | Status | Public code example |
| --- | --- | --- |
| Malformed/invalid DTO or cursor | 422 or 400 consistently | invalid_request |
| Missing authentication | 401 | authentication_required |
| Invalid credential or role | 403 | forbidden |
| Resource absent | 404 | resource_not_found |
| Invalid lifecycle or version conflict | 409 | lifecycle_conflict or stale_version |
| Bounded request/rate limit | 429 | rate_limited |
| Unexpected failure | 500 | internal_error |

Validation details can identify fields, but must not include secrets or raw
exceptions. Internal logs retain structured context and a traceback where
appropriate; the client receives only a safe message and request ID.

## 22. Optimistic Concurrency

Use a request-body expected_version field for all mutation commands in the MVP.
Do not support both body and If-Match initially; two mechanisms create ambiguity
for clients and tests. A later HTTP caching design can introduce ETags.

Required commands:

- approve;
- reject;
- retry;
- cancel;
- resolve ambiguous.

Each command loads and mutates only when the stored version equals
expected_version. On mismatch, return 409 with the current safe state, current
version, and request ID when it is safe to do so. Never return claim tokens or
raw lease internals. A compatible already-applied command may return the current
terminal state according to the idempotency rules below, but a stale conflicting
decision remains a conflict.

## 23. Idempotency

Command behavior must be state-aware:

- repeated approval returns the approved state;
- approval after rejection returns 409;
- repeated rejection returns the rejected state;
- retry does not repeatedly reset the same pending state;
- repeated cancellation returns the cancelled state;
- ambiguous resolution cannot apply a conflicting second decision.

An optional Idempotency-Key header is reasonable for clients that may retry a
network request, especially ambiguous resolution, but a global idempotency
subsystem is not required in the first slice. Expected versions plus immutable
audit rows protect the lifecycle. If the header is accepted, validate its
length/characters and bind it to actor, action, resource, and request result;
never use it as the event identity.

## 24. API Request Correlation

Add middleware or a dependency that:

- accepts X-Request-ID only when it matches a bounded safe format and maximum
  length of 128;
- otherwise generates a UUID-based request ID;
- binds it to structlog contextvars for the request lifetime;
- includes it in every API error;
- passes it to command services and the audit record;
- does not use it as a domain identity, idempotency key, or event identity.

Do not log the API key, Bot API token, database URL, claim token, or raw
provider response in the correlated log context. Existing structlog setup is a
reasonable base, but request context binding and secret filtering need an API
boundary design.

## 25. Destination Safety

A Telegram destination is operational configuration, not a seller-facing
business field. Default API response behavior:

- expose channel;
- expose a stable destination hash or masked label;
- expose full numeric chat ID only to a separately authorized internal
  administrator if a real operational need is demonstrated;
- never expose a Bot API token or tokenized URL;
- never expose destination values to a future seller role by default.

Filtering can accept a safe destination reference generated from the actual
destination. The query layer must not log raw destination IDs unnecessarily.

## 26. Generated Content Safety

AI-generated text is untrusted data. Return it as a JSON string/plain data and
let a future frontend render it safely. Do not mark it as trusted HTML, execute
markup, or destructively sanitize the durable content during a read.

Preserve Unicode and line breaks. Enforce a response and field-size bound in
DTOs. The existing Telegram formatter has a channel-specific message limit; the
read API may expose validation metadata but should not rewrite content. Provider
and model labels can be returned when approved for operations; credentials,
prompts with secrets, raw responses, and stack traces cannot.

## 27. OpenAPI

The API should expose:

- tagged groups for Events, Content, Publications, Dashboard, and Health;
- Pydantic v2 request and response models;
- enum descriptions and lifecycle conflict responses;
- an API-key security scheme for X-Admin-API-Key;
- examples with fake UUIDs and non-secret values;
- explicit 401, 403, 404, 409, 422, 429, and 500 responses where applicable;
- no ORM or internal repository schemas.

OpenAPI and Swagger UI may remain enabled in development. In production they
must either be protected by the same authentication boundary or disabled by
configuration. Examples must never contain real Bot API tokens, database
credentials, chat IDs, claim tokens, or provider output that includes secrets.

## 28. Health and Readiness

EPIC 15 should define, but can implement in its final task, separate endpoints:

- GET /health/live: process liveness only, no database or Telegram network call;
- GET /health/ready: database connectivity and migration readiness, plus safe
  application configuration checks.

Readiness may report whether Scheduler components are initialized, but it must
not report secrets. Telegram readiness should describe configuration state
without contacting Telegram; live delivery remains a separate guarded
verification path. A failed database readiness check returns a safe degraded
response and does not expose the connection string or driver exception.

## 29. Test Plan

### Authentication

- missing key;
- invalid key;
- valid key;
- constant-time comparison behavior at the boundary;
- token redaction;
- explicit test-only auth bypass;
- unsafe missing-key startup behavior outside development.

### Event reads

- empty result;
- every supported filter;
- stable sorting;
- next cursor and invalid cursor;
- typed price-drop payload;
- related content/publication summaries;
- UTC date ranges and invalid ranges.

### Content reads

- attempts ordered by creation/attempt;
- latest attempt;
- failed generation;
- pending, approved, and rejected review states;
- bounded sanitized error;
- event relationship.

### Content review

- approve;
- reject with required reason;
- repeated compatible command;
- conflicting state;
- stale version;
- unauthorized role;
- atomic audit record;
- no duplicate publication intent.

### Publication reads

- event/content relationships;
- channel and status filters;
- retryable and permanent failures;
- ambiguous state;
- safe destination;
- published external message ID;
- cursor pagination.

### Retry and cancellation

- valid retry;
- invalid state;
- active claim;
- exhausted attempts;
- stale version;
- compatible repeat;
- required reason;
- no direct Telegram call.

### Ambiguous resolution

- mark delivered;
- mark not delivered;
- cancel;
- conflicting second resolution;
- required reason;
- external message ID requirement;
- stale version;
- audit record.

### Dashboard

- zero state;
- mixed lifecycle state;
- time-window filtering;
- deterministic counts;
- no full-table Python aggregation.

### Layering

- routes do not import ORM mappings;
- routes do not import Telegram adapter;
- services do not import FastAPI;
- query contracts do not import SQLAlchemy;
- command services do not call external network clients;
- memory and PostgreSQL command outcomes match.

## 30. PostgreSQL Verification

Create scripts/verify_epic15_admin_api_postgres.py in the implementation task,
using an isolated PostgreSQL database and real ASGI requests through the current
project test approach (for example httpx AsyncClient with the FastAPI
application). Never use a production database.

Minimum checks:

1. Missing/invalid authentication is rejected.
2. Event list returns typed records.
3. Event detail returns a typed payload.
4. Event filters and deterministic sorting work.
5. Cursor pagination works and invalid cursors are rejected.
6. Content list and detail work.
7. Content approval works.
8. Content rejection and reason persistence work.
9. Stale review version returns a conflict.
10. Publication list and detail work.
11. Safe publication destination is returned.
12. Manual retry moves only an eligible failure.
13. Cancellation persists a terminal state.
14. Ambiguous mark-delivered works with an external ID.
15. Ambiguous mark-not-delivered requeues without sending.
16. Ambiguous cancellation works.
17. Audit records are immutable and complete.
18. Dashboard counters match seeded data.
19. Request correlation appears in errors and audit records.
20. Restart preserves state and admin commands never call Telegram.

The verifier should use a recording/failing adapter or a mocked transport to
prove no network call occurs. It should check transaction rollback by forcing
an audit write failure and confirming the state mutation did not commit.

## 31. Migration Assessment

Read-only list/detail APIs need no migration if existing columns and indexes are
adequate. EPIC 15 does need one focused migration for durable administration
audit and, only if query measurements justify it, additional indexes.

Proposed migration contents:

- create admin_actions with the columns and constraints in section 14;
- add allowlisted checks for resource_type and action;
- add non-empty/length checks and positive version checks;
- add indexes on resource_type/resource_id/created_at DESC,
  actor_id/created_at DESC, and request_id;
- do not change event identity;
- do not add claim tokens or secrets;
- do not add mutable rejection/resolution fields merely for display;
- do not add a materialized dashboard view.

Rejection and resolution reasons live in the immutable audit record initially.
If product requirements later demand a fast current-reason filter, measure the
need before adding a denormalized column. The migration must be applied and
verified in an isolated PostgreSQL database before release.

## 32. Performance

Expected high-value query patterns are recent events, lifecycle queues,
content-by-event, publications-by-event/content, retryable publications, and
ambiguous delivery inspection.

Existing schema/index coverage already includes event timelines, scoring claim
queues, content event/review/claim paths, and publication event/status/claim
paths. Query implementations should confirm plans rather than add speculative
indexes.

Verify indexes for:

- event detected/created timestamps;
- marketplace and event type where list volume requires it;
- disposition and scoring status;
- content event ID, created time, review status;
- publication event/content ID;
- publication channel/status;
- next retry time and scheduled time;
- ambiguous publication filtering.

Use composite indexes that match actual predicates and keyset order. Avoid
loading related records one by one; use bounded joins or batched queries. Avoid
materialized views, a search service, Redis, Kafka, Celery, RabbitMQ, and other
infrastructure until measured load requires them.

## 33. Implementation Breakdown

Keep EPIC 15 to three focused tasks.

### Task 1 - Read-side API foundation

- define Pydantic v2 request/response DTOs;
- define query-side repository contracts and PostgreSQL read implementations;
- add authenticated admin dependencies;
- add event, content, and publication list/detail routes;
- add deterministic filters and keyset pagination;
- add stable errors, request correlation, and layering tests.

No lifecycle mutation or migration is required for this task.

### Task 2 - Administration commands and audit

- implement ContentReviewService;
- implement publication retry and cancellation commands;
- implement ambiguous resolution;
- add guarded repository operations for the missing admin transitions;
- add immutable admin_actions migration and repositories;
- add memory/PostgreSQL lifecycle, concurrency, rollback, and audit tests.

No direct Telegram call is allowed from a command.

### Task 3 - Operational completion

- add dashboard summary query and DTO;
- add liveness/readiness endpoints;
- complete FastAPI composition and OpenAPI protection;
- run isolated PostgreSQL ASGI verification;
- update readiness documentation and resolve known documentation drift.

## 34. Acceptance Criteria

The EPIC is complete only when all of the following are true:

- routes are versioned under /api/v1;
- authentication is required for administration routes;
- seller access is not implied without seller identity/tenant isolation;
- secrets, claim tokens, and raw exceptions are not exposed;
- market events can be listed and inspected;
- typed event payloads are stable and versioned;
- generated content can be listed and inspected;
- publication intents and delivery states can be listed and inspected;
- filters, sorting, and pagination are deterministic;
- content can be approved and rejected safely;
- publications can be retried and cancelled safely;
- ambiguous delivery can be resolved manually without an automatic send;
- optimistic concurrency protects every command;
- compatible repeated commands are idempotent;
- commands do not call Telegram directly;
- routes contain no repository, ORM, or business transition logic;
- immutable audit history exists for administrative mutations;
- dashboard summary is bounded and available;
- errors use stable sanitized envelopes with request IDs;
- PostgreSQL end-to-end verification passes in an isolated database;
- restart persistence and transaction rollback are verified;
- OpenAPI contains no internal ORM schemas or secrets.

## 35. Recommended First Implementation Task

Choose exactly one first task:

**Task 1 - Read-side API foundation: query contracts, typed DTOs, authenticated
event/content/publication list and detail routes, deterministic keyset
pagination, and tests.**

This is the smallest safe slice because it is read-only, does not change domain
lifecycle behavior, does not need a migration, and exposes the durable state
that EPIC 13 and EPIC 14 already verified. It also establishes authentication,
response-shaping, error, and query boundaries before any irreversible
administrative command is introduced.

Do not begin Task 2 in the same change.

## Constraints

- Do not change event identities.
- Do not bypass existing lifecycle services.
- Do not directly mutate publication state in routes.
- Do not expose ORM models.
- Do not call Telegram or AI from read routes or admin commands.
- Do not add inbound Telegram updates.
- Do not implement user registration or OAuth.
- Do not add Redis, Kafka, Elasticsearch, Celery, or RabbitMQ.
- Do not create a frontend.
- Do not send live Telegram messages.
- Do not create a migration as part of this design-only task.
- Preserve UTC-aware timestamps and Decimal semantics.
- Keep repository contracts database-independent.
- Keep external calls outside database transactions.
- Preserve the current EPIC 13 and EPIC 14 verification artifacts.

## Task 1 Implementation Record

### API route structure

The implemented read-only surface is:

- `GET /api/v1/admin/events`
- `GET /api/v1/admin/events/{event_id}`
- `GET /api/v1/admin/events/{event_id}/content`
- `GET /api/v1/admin/events/{event_id}/publications`
- `GET /api/v1/admin/content`
- `GET /api/v1/admin/content/{content_id}`
- `GET /api/v1/admin/publications`
- `GET /api/v1/admin/publications/{publication_id}`
- `GET /api/v1/admin/health`
- `GET /api/v1/admin/readiness`
- `GET /health/live`
- `GET /health/ready`

No POST, PUT, PATCH, or DELETE route is registered.

### Authentication approach

`X-Admin-API-Key` is represented by an OpenAPI API-key security scheme. The
configured value is `SecretStr`-backed and compared with `hmac.compare_digest`.
Disabled or missing-key configurations fail closed. Authentication bypass needs
both an explicit configuration flag and explicit application test mode.

### Seller/admin boundary

The API remains internal administration only. Seller identity, tenant ownership,
user registration, passwords, JWT, OAuth, and role persistence do not exist.

### Event, content, and publication APIs

Dedicated SQLAlchemy-independent query contracts return immutable read DTOs.
PostgreSQL implementations perform deterministic joined/existence queries and
return no ORM rows. Price-drop payloads are explicitly mapped to a stable
`type=price_drop`, `version=1` DTO. Content remains plain text. Publication
destinations are exposed only as short non-reversible references; claim tokens,
provider secrets, raw provider responses, and Telegram credentials are absent.

All three list APIs use allow-listed sorting and deterministic timestamp/UUID
keysets. Opaque cursors contain versioned JSON, are HMAC signed, and are bound to
resource, sort direction, and normalized filters. Page defaults and maxima are
configuration-backed. Date inputs must be timezone-aware and are normalized to
UTC. Supported bounded search uses external ID/title/source URL for events and
generated text for content.

The common error envelope includes a stable code, safe message, bounded details,
and request ID. Correlation middleware accepts only bounded safe request IDs,
otherwise generates one, returns it in `X-Request-ID`, and binds it to structlog
context. Internal exception text is not returned.

### Workflow commands

No content review, publication retry/cancel, or ambiguous-resolution command is
implemented. Existing lifecycle behavior and Scheduler/Telegram paths are
unchanged.

### Audit and query strategy

Task 1 implements dedicated read-side query contracts and PostgreSQL/memory query
adapters. It adds no migration and creates no audit rows.

### Verification

- Focused API/query/security suite: `27 passed`.
- Full Pytest: `291 passed, 54 skipped`.
- Strict MyPy: `258` source files, no issues.
- Ruff: all `33` touched Python files passed.
- Ruff format: all `33` touched Python files formatted.
- Isolated PostgreSQL 16 verifier: `28/28` named checks passed with no Telegram
  network call.
- Alembic current: `0008_content_publications (head)`.
- Alembic check: no new upgrade operations.
- Alembic offline SQL: generated successfully through current head.

### Exact Recommended Task 2

Implement administration commands and immutable audit persistence only:

- add guarded application services for content approve/reject;
- add guarded publication retry/cancel commands;
- add explicit ambiguous-delivery resolution commands;
- add the planned immutable `admin_actions` table and repository contract;
- require actor, bounded reason, expected optimistic version, and request ID;
- commit each state change and audit row atomically;
- keep routes thin and never call Telegram from an administration command.

Dashboard expansion, seller identity, frontend work, and live Telegram delivery
are not part of Task 2.

### Commit and push status

Task 1 is delivered as one focused implementation commit. Push is intentionally
not performed.

## Task 2 Implementation Record

### Administration commands

The implemented guarded mutation surface is:

- `POST /api/v1/admin/content/{content_id}/approve`
- `POST /api/v1/admin/content/{content_id}/reject`
- `POST /api/v1/admin/publications/{publication_id}/retry`
- `POST /api/v1/admin/publications/{publication_id}/cancel`
- `POST /api/v1/admin/publications/{publication_id}/resolve-ambiguous`

All commands require authentication, an idempotency key, request correlation, and
an expected optimistic version. Routes delegate to `AdminMutationService` and do
not call Telegram, AI, Scheduler, or ORM mappings directly.

### Audit persistence

Revision `0009_admin_actions` creates immutable `admin_actions` records with
action/resource allowlists, version checks, a unique idempotency key, and indexes
for resource, actor, request, and created-time lookups. State changes and audit
records commit atomically through the existing repository scope.

### PostgreSQL verification

`scripts/verify_epic15_admin_mutations_postgres.py` passed `26/26` checks against
a temporary isolated PostgreSQL 17.10 database named `epic15_verification`.

Verified scenarios:

- authentication failure and stable sanitized API errors;
- content approval and rejection;
- publication retry and cancellation;
- ambiguous resolution as delivered, not delivered, and cancelled;
- immutable audit rows, request correlation, idempotency replay, and fingerprint
  conflicts;
- optimistic version conflicts and failed-transition audit suppression;
- rollback atomicity when audit insertion fails;
- fresh-session persistence;
- concurrent duplicate idempotency and conflicting commands;
- no Telegram network calls from administration commands.

### Alembic verification

- Clean upgrade through `0009_admin_actions`: passed.
- `alembic current`: `0009_admin_actions (head)`.
- `alembic check`: no new upgrade operations.
- Downgrade to `0008_content_publications` and upgrade back to head: passed.
- Offline `upgrade head --sql`: generated successfully and includes
  `admin_actions`.
- `admin_actions` constraints, indexes, and idempotency uniqueness were verified
  from PostgreSQL catalogs.

### Quality verification

- Focused Task 2 and repository contract tests: `20 passed`.
- Full Pytest with isolated PostgreSQL enabled: `307 passed, 54 skipped`.
- Ruff on Task 2 touched files: passed.
- Ruff format check: `28 files already formatted`.
- MyPy with `--explicit-package-bases`: `281` source files, no issues.

### Exact Recommended Task 3

Proceed with operational completion only: dashboard summary, final health/readiness
polish, OpenAPI/admin docs protection review, and final API verification. Do not
add seller identity, frontend work, Telegram live sending, or new marketplace
logic as part of Task 3.
