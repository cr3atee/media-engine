# EPIC 14 - Telegram Publication Adapter and Delivery Workflow

## Purpose

EPIC 14 adds the first real outbound delivery channel to MediaEngine. It takes a
durable `Publication` prepared by EPIC 13, sends its immutable generated content
to Telegram, and records a durable delivery outcome without moving business
logic into Telegram-specific code.

This document records the implemented Task 1 adapter foundation and the design
for the remaining durable delivery work. Task 1 introduces no database
migrations, credentials, new dependencies, runtime publication processing, or
live messages.

## Scope

In scope:

- a narrow Telegram Bot API adapter;
- a channel-independent delivery service;
- safe rendering and Telegram message validation;
- durable success, failure, retry, and ambiguous-outcome handling;
- scheduler integration through a reusable job;
- offline verification and a separately gated live test-chat verification;
- minimal repository contract changes required for channel-safe claiming.

Out of scope:

- Telegram bot update handling, commands, webhooks, and polling;
- Telegram channel administration or subscriber management;
- content generation changes;
- manual review UI;
- delivery to channels other than Telegram;
- exactly-once guarantees that Telegram Bot API cannot provide;
- PostgreSQL schema changes unless later implementation proves them necessary;
- production credentials or production messages.

## Current Foundation

The current implementation already provides the durable foundation needed by
this EPIC:

- immutable generated content attempts;
- durable publication intents and deterministic idempotency keys;
- publication states `pending`, `in_progress`, `published`, `failed`,
  `ambiguous`, and `cancelled`;
- claim token, lease, version, attempt count, retry time, external message ID,
  and processing-error fields;
- memory and PostgreSQL publication repositories;
- PostgreSQL `FOR UPDATE SKIP LOCKED` claim behavior;
- compare-and-set completion through claim token and version;
- stale publication claim recovery to `ambiguous`;
- scheduler jobs that delegate work rather than contain business logic.

The historical EPIC 13 design contains an outdated statement that content and
publication recovery were not implemented. The current code and final EPIC 13
verification show that `StaleContentClaimRecoveryJob` and
`StalePublicationClaimRecoveryJob` exist. Current implementation is the source
of truth for EPIC 14.

## Task 1 Implementation Status

**Status: completed.**

Implemented boundaries:

- `app.delivery` defines immutable channel-independent `DeliveryMessage`,
  `DeliveryResult`, typed outcome/error enums, and the async
  `PublicationDeliveryAdapter` protocol;
- `TelegramPlainTextFormatter` consumes approved final generated text plus
  explicit safe metadata, normalizes only line endings/control whitespace, and
  returns one plain-text `DeliveryMessage`;
- optional source URL and fixed footer are appended only from explicit structured
  input; title, marketplace, prices, and discount are not recomputed from prose;
- empty content, unsupported channel, invalid numeric destination, invalid source
  URL, empty explicit footer, and messages above 4096 characters are rejected;
- no truncation, splitting, HTML, Markdown, parse mode, destination inference,
  invisible correlation marker, or hidden dry-run behavior exists;
- `TelegramBotApiClient` owns or borrows one reusable `httpx.AsyncClient`, sends
  one direct `sendMessage` JSON request, and never retries or sleeps;
- current Bot API request uses `chat_id`, `text`, and
  `link_preview_options.is_disabled`; it sends no `parse_mode`;
- typed narrow response parsing keeps only status, acceptance flag, message/chat
  IDs, provider error code, safe description, retry-after seconds, and malformed
  category;
- `TelegramDeliveryClassifier` distinguishes confirmed success, retryable
  pre-send/rate/server failure, permanent rejection, invalid local request, and
  ambiguous potentially delivered outcomes;
- connect/pool failures are retryable; write/read/remote-response uncertainty is
  ambiguous; `400`/`401`/`403`/`404` are permanent; `429` preserves non-negative
  `retry_after`; `5xx` is retryable;
- destination mismatch and malformed successful responses are ambiguous;
- the bot token is held as `SecretStr`, omitted from object representations,
  removed from provider descriptions, and never exposed through adapter results
  or logs;
- logs contain only publication/correlation IDs, a destination hash, typed
  outcome, safe provider codes, confirmed external message ID, and duration;
- tests and `verify_epic14_telegram_adapter.py` use only `httpx.MockTransport`;
- no repository, Scheduler, publication lifecycle, migration, or active runtime
  path was connected to Telegram.

Verification evidence:

- focused Telegram suite: 78 tests passed, covering formatter, client, adapter,
  settings secrecy, and import boundaries;
- offline verifier: 16/16 named checks passed and cannot perform an external
  request because every client receives a mock transport;
- formatter and adapter reject invalid input before transport invocation;
- internal and external HTTP client ownership, reuse, explicit close, and
  post-close failure are covered;
- Ruff passed for all 14 touched Python files;
- Ruff format check confirmed all 14 touched Python files are formatted;
- full MyPy with explicit package bases passed for 222 source files;
- full Pytest passed with 257 tests and 52 environment/integration skips.

Pre-existing quality-tool note: the Makefile command `uv run mypy app` does not
set explicit package bases and reports duplicate module names for existing
namespace-package files such as `app/analytics/models.py` and
`app/comparator/models.py`. Task 1 did not introduce that layout or modify the
Makefile. The full verification therefore used
`uv run mypy --explicit-package-bases app scripts tests` and did not perform an
unrelated packaging cleanup.

## Task 2 Implementation Status

**Status: implemented in code and verified offline without Telegram network.**

Implemented boundaries:

- `PublicationRepository.claim_pending()` now supports an optional generic
  `channel` filter and an optional attempt budget while preserving existing
  callers;
- memory and PostgreSQL publication repositories apply the same channel and
  attempt-budget semantics;
- PostgreSQL applies the channel predicate before `FOR UPDATE SKIP LOCKED`
  selection;
- `PublicationDeliveryService` claims one Telegram publication at a time,
  reloads durable content/event data, formats the message, calls the adapter
  outside repository scopes, and completes success/failure/ambiguous outcomes in
  short guarded transactions;
- successful delivery persists `external_message_id` and `published_at`;
- retryable outcomes persist sanitized errors and bounded retry timestamps;
- Telegram `429` honors provider `retry_after` and stops the current batch;
- permanent failures are terminal and do not schedule retry;
- ambiguous outcomes are terminal for automatic delivery and are excluded from
  normal pending claims;
- dry-run loads one explicit publication, validates and renders it, calls no
  adapter, and performs zero durable mutation;
- `PendingPublicationDeliveryJob` delegates only to
  `PublicationDeliveryService.process_batch()`;
- Telegram delivery settings now include disabled-by-default delivery flags,
  dry-run default, allowlist, batch size, lease duration, attempt budget, and
  retry delays;
- `scripts/verify_epic14_delivery_service_postgres.py` provides the offline
  PostgreSQL/mock-Telegram verification entry point and refuses to fabricate a
  PostgreSQL result when no isolated `EPIC14_DATABASE_URL` is configured.

Verification evidence in this environment:

- focused repository, service, scheduler, and Telegram tests passed;
- Task 1 offline adapter verifier still passed `16/16` checks;
- Task 2 PostgreSQL verifier guard ran and reported that
  `EPIC14_DATABASE_URL` is required for live isolated PostgreSQL verification;
- full MyPy passed with explicit package bases for 226 source files;
- full Pytest passed with 264 tests and 54 environment/integration skips;
- Ruff check and Ruff format check passed for all touched Python files.

## Task 3 Verification Status

**Status: not complete in this environment.**

Implemented verification artifacts:

- `scripts/verify_epic14_delivery_service_postgres.py` now includes additional
  checks for due retry resumption, completion rollback after successful adapter
  response, stale-claim recovery, one-publication/two-worker claim exclusivity,
  and token redaction;
- `scripts/verify_epic14_live_telegram.py` provides the guarded live test-chat
  verification path and performs no Telegram network call by default;
- live mode requires explicit flags, a configured test chat, exact CLI
  confirmation, allowlist membership, an isolated `EPIC14_DATABASE_URL`, a bot
  token, and disabled dry-run mode.

Execution status:

- Task 1 offline adapter verifier passed `16/16` checks;
- the PostgreSQL verifier could not run because Docker/PostgreSQL is unavailable
  in this environment and `EPIC14_DATABASE_URL` is not configured;
- live Telegram verification was not performed because credentials, test chat,
  confirmation, live flags, and PostgreSQL verification database were not
  supplied;
- production delivery remains disabled by default and inbound bot functionality
  remains out of scope.

## Design Principles

1. A Telegram adapter sends one prepared message and reports one typed outcome.
2. The delivery service owns orchestration and publication lifecycle changes.
3. Repository transactions are short and never include a network request.
4. Retry policy lives in the delivery layer, not in the HTTP adapter or job.
5. An uncertain send result is `ambiguous`, not automatically retried.
6. Dry-run is read-only and cannot consume a pending publication.
7. Live delivery is disabled by default and restricted to explicit destinations.
8. Tokens, raw Telegram responses, and token-bearing URLs are never logged.
9. Existing content, event, repository, and scheduler contracts are reused.
10. No framework is introduced before a second delivery channel requires it.

## 1. Telegram Adapter Boundary

Introduce a small channel-independent outbound port:

```python
class PublicationDeliveryAdapter(Protocol):
    async def send(self, message: DeliveryMessage) -> DeliveryResult: ...
```

`TelegramPublicationAdapter` implements this port. The adapter is responsible
only for translating `DeliveryMessage` into one Telegram `sendMessage` request
and translating the response or transport exception into `DeliveryResult`.

The adapter must not:

- load repositories;
- open a database session or transaction;
- claim or complete a `Publication`;
- calculate retries or mutate `next_retry_at`;
- call the scheduler;
- generate or score content;
- inspect ORM models;
- retry a send internally.

The generic port is justified because the durable `Publication` model is already
channel-independent. Only one Telegram implementation is needed now. Do not add
an adapter registry, plugin framework, or abstract factory in EPIC 14.

### DeliveryMessage

Use an immutable, transport-neutral DTO:

```python
@dataclass(slots=True, frozen=True)
class DeliveryMessage:
    publication_id: UUID
    channel: str
    destination_id: str
    rendered_text: str
    parse_mode: str | None
    disable_web_page_preview: bool
    correlation_id: str
    reference_id: str | None = None
```

The DTO deliberately excludes bot credentials, repository entities, claims,
sessions, HTTP clients, and retry policy. `destination_id` is a string at the
domain boundary but must contain a numeric Telegram chat ID for the first MVP.

## 2. Telegram Client

### Selected approach

Use a dedicated `TelegramBotApiClient` around one long-lived
`httpx.AsyncClient` per adapter instance. Call the official HTTPS Bot API
`sendMessage` method directly with JSON.

This is preferred because:

- `httpx` is already a project dependency;
- delivery is outbound-only and does not require polling, update dispatch,
  handlers, FSM, or webhook infrastructure;
- the wire contract is small and stable enough to model explicitly;
- transport exception types can be classified precisely;
- the client lifecycle remains explicit and testable with `MockTransport`.

Do not add `aiogram` or `python-telegram-bot` for this EPIC. Both are capable
libraries, but their bot application and update-processing features exceed the
outbound-only requirement and increase dependency and lifecycle surface.

Do not reuse the current shared `HttpClient` for `sendMessage`. It retries
request errors and server errors automatically. A retry after a write or read
failure can duplicate a Telegram message when the first request was accepted
but its response was lost.

### Client lifecycle

- Construct one `httpx.AsyncClient` outside `send()`.
- Reuse it for all sends performed by the adapter instance.
- Expose explicit `aclose()` and async context-manager support.
- Configure connect, write, read, and pool timeouts explicitly.
- Allow an optional proxy through configuration only if deployment needs it.
- Never instantiate a client in the scheduler loop or for each message.

### Secret-safe request construction

Telegram Bot API puts the token in the request URL. Therefore:

- build the token-bearing URL only inside the client;
- never log the full request URL;
- never include the token in exceptions returned to upper layers;
- never persist raw request or response bodies;
- sanitize `httpx` exception text before creating `ProcessingError`;
- log only operation name, publication ID, destination ID, safe status code,
  Telegram error code, and correlation ID.

## 3. Configuration

The existing settings already provide a Telegram bot token and chat ID. EPIC 14
should extend the Telegram settings only with values required by safe delivery:

| Setting | Suggested default | Purpose |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | unset | Secret Bot API credential. |
| `TELEGRAM_CHAT_ID` | unset | Default numeric destination for approved publications. |
| `TELEGRAM_API_BASE_URL` | `https://api.telegram.org` | Bot API base; official HTTPS endpoint required in production. |
| `TELEGRAM_REQUEST_TIMEOUT_SECONDS` | `10` | Per-request timeout baseline. |
| `TELEGRAM_PROXY_URL` | unset | Optional deployment-specific proxy. |
| `TELEGRAM_PARSE_MODE` | unset | Plain text for the first MVP. |
| `TELEGRAM_DISABLE_WEB_PAGE_PREVIEW` | `true` | Prevent unwanted automatic previews. |
| `TELEGRAM_MAX_MESSAGE_LENGTH` | `4096` | Local limit, never above Telegram's limit. |
| `TELEGRAM_DELIVERY_ENABLED` | `false` | Master delivery switch. |
| `TELEGRAM_ALLOW_LIVE_DELIVERY` | `false` | Additional explicit live-send gate. |
| `TELEGRAM_DRY_RUN` | `true` | Read-only rendering and validation mode. |
| `TELEGRAM_ENVIRONMENT` | `development` | Environment safety classification. |
| `TELEGRAM_ALLOWED_DESTINATION_IDS` | empty | Exact destination allowlist. |
| `TELEGRAM_DELIVERY_BATCH_SIZE` | `10` | Maximum publications examined per run. |
| `TELEGRAM_PUBLICATION_LEASE_SECONDS` | `60` | Claim lease; must exceed request timeout. |
| `TELEGRAM_MAXIMUM_ATTEMPTS` | `5` | Durable attempt budget. |
| `TELEGRAM_INITIAL_RETRY_SECONDS` | `30` | First retry delay. |
| `TELEGRAM_MAXIMUM_RETRY_SECONDS` | `1800` | Retry-delay cap, except server minimum. |
| `TELEGRAM_LIVE_TEST_ENABLED` | `false` | Dedicated test-chat gate. |
| `TELEGRAM_TEST_CHAT_ID` | unset | Exact test destination. |

Use `SecretStr` or equivalent secret-safe representation for the token. The
token is optional when delivery is disabled or a read-only dry-run is used.

Startup validation for live delivery must require:

- both delivery and live-delivery switches enabled;
- a non-empty bot token;
- a numeric configured destination;
- the destination present in the allowlist;
- official HTTPS API base in production;
- message length in `1..4096`;
- a positive timeout and lease longer than the request timeout;
- a valid retry policy and positive batch size.

Configuration errors must fail startup before any publication is claimed.

## 4. Delivery DTO

The adapter result must describe transport outcome without exposing Telegram
internals to the domain:

```python
class DeliveryOutcome(StrEnum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"


@dataclass(slots=True, frozen=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    external_message_id: str | None
    provider_status_code: int | None
    provider_error_code: str | None
    retry_after: timedelta | None
    safe_error: str | None
```

`safe_error` is bounded, sanitized, and credential-free. The result must not
contain a raw `httpx.Response`, raw Telegram payload, client object, token, URL,
repository entity, or exception instance.

## 5. Formatting

### Selected strategy

Send plain text with `parse_mode=None` for the first MVP. Generated content is
already defined as final publication text, so Telegram formatting must be a
thin deterministic boundary rather than a second content-generation step.

Plain text is preferred because it:

- cannot fail because of malformed HTML or MarkdownV2 escaping;
- does not allow generated text to create hidden links;
- preserves Unicode without markup-specific transformations;
- is safe across current FakeAI and future provider output;
- avoids duplicated title, price, and discount rendering.

The formatter may only:

- normalize line endings to `\n`;
- remove disallowed control characters while preserving normal Unicode;
- trim trailing whitespace and outer blank lines;
- reject an empty result;
- append a fixed trusted footer or source URL only when supplied from durable,
  structured application data;
- produce the immutable `DeliveryMessage`.

The formatter must not infer data from generated prose, regenerate content,
alter prices, add unsupported claims, select a destination, or read credentials.

### Link previews

Set `link_preview_options={"is_disabled": true}` when previews are disabled.
URLs in plain text remain visible. A later product decision may enable previews,
but that is not part of the first safe delivery implementation.

## 6. Message Length

Telegram `sendMessage` accepts text up to 4096 characters after entity parsing.
The first implementation uses one publication intent for exactly one Telegram
message.

Policy:

- validate the rendered text before the network call;
- reject text longer than the configured maximum;
- never configure a maximum above 4096;
- do not truncate text silently;
- do not split one publication into multiple messages;
- do not create message bundles or threads;
- classify invalid length as a permanent content failure.

The current price-drop prompt targets a much smaller post, but adapter validation
is still mandatory because future content providers or manual edits can exceed
that target.

## 7. PublicationDeliveryService

Create a channel-independent `PublicationDeliveryService`. It orchestrates
repositories, formatting, adapter invocation, lifecycle transitions, and retry
policy. It should receive dependencies through its constructor:

- `RepositoryScopeFactory`;
- `PublicationDeliveryAdapter`;
- deterministic message formatter;
- retry policy;
- expected channel, initially `telegram`;
- destination safety policy;
- clock if the project already uses an injectable clock boundary.

### Single-publication flow

1. Open a short repository scope.
2. Claim one due publication for the expected channel.
3. Commit the claim and close the scope.
4. Open a short read scope to load immutable content and related event.
5. Revalidate eligibility, destination, review state, and content.
6. Close the read scope.
7. Format and validate the message outside a transaction.
8. Call the adapter outside a transaction.
9. Open a fresh short scope.
10. Complete the publication using claim token and expected version.
11. Commit and return a typed application result.

Claim one item at a time even when a batch limit is configured. This avoids
holding leases for unsent publications and allows the service to stop immediately
when Telegram returns a rate-limit response.

### Transaction boundary

No database transaction may remain open during formatting or HTTP I/O. Claim and
completion use separate short transactions. A process crash after Telegram has
accepted a message but before completion leaves a stale `in_progress` claim; the
existing recovery policy converts it to `ambiguous` rather than risking a
duplicate automatic send.

## 8. Eligibility

A publication is eligible only when all checks pass:

| Check | Required state |
|---|---|
| Channel | Exactly `telegram`. |
| Publication status | Due `pending`, or due retryable `failed`. |
| Schedule | `scheduled_at` is absent or due. |
| Retry schedule | `next_retry_at` is absent or due. |
| Claim | No active claim. |
| Attempts | Below configured attempt budget. |
| Content | Exists and is in generated state. |
| Review | Not required or explicitly approved. |
| Event | Active or approved for publication. |
| Destination | Numeric, configured, and allowlisted. |
| Text | Non-empty and within configured limit. |

Repository claim logic enforces due status, schedule, retry time, active claim,
and attempt budget. The delivery service must revalidate content, event, review,
destination, and rendered text after claiming.

If a claimed item fails a deterministic eligibility check, complete it as a
terminal `failed` publication with no automatic retry and a sanitized error
category. Do not call Telegram.

## 9. Success

A Telegram response is successful only when all are true:

- HTTP and Bot API processing succeeded;
- the response has `ok=true`;
- `result.message_id` is present;
- `result.chat.id` is present;
- returned chat ID exactly equals the requested numeric destination ID.

On success:

- call existing `mark_published` with the claim token and expected version;
- persist `message_id` as `external_message_id`;
- set `published_at` using the application clock;
- clear claim and transient error state through the existing lifecycle;
- return a typed published result.

The existing repository behavior should preserve idempotent completion when the
same claim is completed again with the same external message ID. A conflicting
message ID is not accepted as success.

Store only the Telegram message ID, not the entire response payload. For the
first MVP, numeric `destination_key` is both the requested and verified chat ID,
so no additional destination column is required.

## 10. Error Classification

Errors must be classified before publication state is changed.

### Retryable failure

Use `RETRYABLE_FAILURE` only when the outcome is known to be unsent or Telegram
explicitly asks the client to retry:

- connection establishment failure;
- DNS failure before connection;
- connect timeout;
- pool timeout before request transmission;
- explicit Telegram HTTP `429` with optional `retry_after`;
- explicit server response in the `5xx` range.

Persist `failed` with a calculated `next_retry_at`, unless the attempt budget is
exhausted.

### Permanent failure

Use `PERMANENT_FAILURE` when an automatic retry cannot correct the input or
configuration:

- empty or oversized content;
- invalid or disallowed destination;
- Telegram `400` caused by invalid request or content;
- Telegram `401` invalid credentials;
- Telegram `403` permissions or blocked bot;
- Telegram `404` endpoint or destination configuration error;
- missing generated content or ineligible review/event state.

Persist `failed` with no `next_retry_at`.

### Ambiguous failure

Use `AMBIGUOUS` when Telegram may have accepted the message but the client cannot
prove the final result:

- write timeout or write error after transmission may have started;
- read timeout or read error after the request was sent;
- remote protocol error after request transmission;
- malformed or incomplete successful response;
- successful response whose returned chat ID differs from the request;
- process interruption after send and before durable completion.

Persist `ambiguous` with no automatic retry.

Error summaries must be bounded and sanitized. They may contain a safe category,
HTTP status, Telegram numeric error code, and correlation ID. They must never
contain bot token, request URL, full response body, generated content, proxy
credentials, or stack trace.

## 11. Ambiguous Delivery

Telegram `sendMessage` does not accept the application's idempotency key and
does not provide an exactly-once send contract. MediaEngine therefore cannot
prove that a timed-out request was not delivered.

The first safe policy is:

1. Mark the publication `ambiguous`.
2. Do not schedule an automatic retry.
3. Keep the durable content, destination, claim history fields, error category,
   and correlation ID available for operator investigation.
4. Require a future explicit administrative action to classify it as delivered,
   retryable, or cancelled.

Do not query unrelated recent messages and guess by text. Do not add invisible
markers. A visible test correlation marker may help test-chat verification, but
it is not an exactly-once mechanism and should not be added to production posts
without a product decision.

The current repository supports cancellation and lifecycle transitions used by
automated delivery. A future administration workflow may need generic operations
to resolve `ambiguous` to `published` or back to `pending`. Those operations are
not required for the outbound adapter itself and must not be Telegram-specific.

## 12. Retry Policy

Use durable, application-level retry only:

| Parameter | Initial policy |
|---|---:|
| Maximum attempts | 5 |
| Initial delay | 30 seconds |
| Maximum delay | 30 minutes |
| Formula | Exponential by durable attempt count |

Rules:

- the adapter performs exactly one send attempt;
- the scheduler does not retry a failed HTTP call directly;
- retry eligibility is represented by publication state and `next_retry_at`;
- a `429 retry_after` is a server minimum, so use the later of policy delay and
  Telegram's requested delay;
- never cap a server-provided wait below its requested value;
- permanent and ambiguous failures are not automatically retried;
- exhausted retryable failures remain `failed` with no next retry time;
- service restart must not reset attempts or retry schedule;
- manual retry is a future operator action, not an implicit scheduler behavior.

Add no jitter until concurrent production workers require it. If introduced,
jitter must be bounded and testable rather than using hidden randomness.

## 13. Rate Limiting

The initial rate-limit strategy is intentionally conservative:

- process messages sequentially within one service execution;
- claim one publication immediately before processing it;
- use a bounded batch size;
- honor Telegram `retry_after` exactly;
- after a `429`, stop claiming more publications in the current run;
- leave all unclaimed publications durable and eligible for a later run;
- do not hardcode undocumented messages-per-second assumptions;
- do not add Redis, distributed token buckets, or queue infrastructure.

An optional in-process monotonic next-send gate may prevent immediate repeats in
one worker, but durable `next_retry_at` remains authoritative.

Limitation: multiple application instances can respect publication claims while
still exceeding an aggregate Telegram or per-chat rate limit. That is acceptable
for a single-worker MVP and must be reassessed before horizontally scaling the
delivery workers.

## 14. Scheduler Jobs

Add one generic `PendingPublicationDeliveryJob` that calls
`PublicationDeliveryService.process_pending()` and records only the service's
summary result. It must not know Telegram HTTP details, content formatting,
repository lifecycle operations, retry formulas, or error classification.

Reuse `StalePublicationClaimRecoveryJob` unchanged for expired claims. Do not add
a separate retry job: due retryable failures are selected by the same repository
claim operation used for pending publications.

Expected job behavior:

- one scheduler execution invokes one bounded service batch;
- expected delivery failures are returned as typed results and do not crash the
  scheduler;
- unexpected programming or infrastructure failures are sanitized before they
  reach scheduler logs;
- scheduler-level job retry must not bypass durable publication state.

## 15. Claim and Lease Behavior

Existing publication claim semantics remain authoritative:

- active claims cannot be stolen;
- concurrent workers use repository locking and compare-and-set completion;
- a stale worker cannot complete after another transition changed version;
- lease duration must exceed the configured HTTP timeout plus local completion
  overhead;
- network I/O occurs after the claim transaction commits;
- successful, failed, and ambiguous completion requires the original claim token
  and expected version.

The current model cannot prove whether an expired claim crashed before sending or
after Telegram accepted the message. Conservatively recover every expired
delivery claim to `ambiguous`. This may require manual recovery for a message that
was never sent, but it prevents an automatic duplicate for one that was sent.

A separate send-phase field cannot fully close the crash boundary between remote
acceptance and local commit. Do not add one in EPIC 14 unless a stronger external
idempotency mechanism becomes available.

## 16. Delivery Audit

The current publication row is sufficient for first-MVP operational safety. It
already records:

- deterministic publication identity;
- event, content, channel, and destination;
- current status and durable attempt count;
- active claim token, worker, acquisition, and expiry;
- current retry time;
- external Telegram message ID on success;
- published, created, and updated timestamps;
- current or terminal sanitized processing error;
- optimistic version.

Map Telegram HTTP status and provider error code into the existing sanitized
processing error code and summary. Represent Telegram `retry_after` through
`next_retry_at`. Keep immutable generated text in the existing content record.

Do not add a `publication_attempts` table in the first implementation. The
current model does not preserve a complete immutable history of every prior
attempt, worker, and provider response after later retries. Add such a generic
audit table only when operator reconciliation, compliance, or multi-channel
support demonstrates a real need.

## 17. Dry-Run Policy

Dry-run must be incapable of consuming or mutating a publication.

Implement it as a separate read-only verification path:

1. Select an explicit publication ID.
2. Load its publication, generated content, and event without claiming it.
3. Run eligibility checks that do not require an active claim.
4. Format and validate the final `DeliveryMessage`.
5. Return a typed `DRY_RUN` result with safe metadata and rendered text.
6. Do not call Telegram.
7. Do not change status, version, attempt count, claim, error, or timestamps.

Dry-run must not scan and consume the pending queue. It needs no database table
or persisted dry-run state. Production text should be treated as potentially
sensitive and printed only in an explicitly invoked local verification command.

## 18. Live Test-Chat Safety

Live verification must be a separate opt-in mode and can target only one exact
test chat.

Required gates:

- `TELEGRAM_LIVE_TEST_ENABLED=true`;
- `TELEGRAM_DELIVERY_ENABLED=true`;
- `TELEGRAM_ALLOW_LIVE_DELIVERY=true`;
- non-empty bot token;
- numeric `TELEGRAM_TEST_CHAT_ID`;
- test chat present in `TELEGRAM_ALLOWED_DESTINATION_IDS`;
- test chat differs from a configured production destination unless an explicit
  environment-specific override is approved;
- explicit CLI `--live` flag;
- exact confirmation value such as `--confirm-chat-id <id>`.

The live test message should have a visible `[MediaEngine TEST]` prefix and a
correlation ID. It must not reuse production pending publications. Use a dedicated
test event, generated content, and publication in an isolated environment or
transactionally controlled test dataset.

Do not print credentials. Do not require a personal Telegram account. The bot
must already have permission to send to the test chat. Automatic deletion may be
added only behind another explicit flag and only after the success record is
verified.

## 19. Formatting and Content Policy

The delivery layer publishes approved generated content; it does not author it.

Policy boundaries:

- generated text is the primary body;
- prices, discount, marketplace, and title are not recomputed from prose;
- a trusted source URL may be appended only from durable structured data;
- generated URLs are not converted into hidden links;
- no HTML or MarkdownV2 in the first MVP;
- no emoji rewriting, hashtag injection, or clickbait transformations;
- no automatic translation;
- no unapproved seller or marketplace claims;
- no destination instructions may be taken from generated content;
- review-required content must be approved before delivery;
- rejected or cancelled material is never sent.

Any later rich-format template belongs in a versioned, deterministic formatter
with dedicated escaping tests. It must not be embedded in the HTTP client.

## 20. Application Result DTOs

The delivery service should return typed immutable results independent of HTTPX
and ORM entities.

Suggested result statuses:

- `PUBLISHED`;
- `RETRY_SCHEDULED`;
- `PERMANENT_FAILURE`;
- `AMBIGUOUS`;
- `SKIPPED_NOT_ELIGIBLE`;
- `SKIPPED_NOT_DUE`;
- `CLAIM_LOST`;
- `VERSION_CONFLICT`;
- `RATE_LIMITED`;
- `DRY_RUN`.

A single-item result should include publication ID, status, external message ID,
attempt count, next retry time, correlation ID, and a safe error code. A batch
summary should include examined, claimed, published, retry scheduled, permanent
failed, ambiguous, skipped, and rate-limited counts.

Do not return repository sessions, claim secrets, generated content by default,
raw provider payloads, or exception objects.

## 21. Repository Contract Changes

One minimal generic contract change is required before the delivery worker is
safe for multiple channels.

The existing `claim_pending` operation is not channel-scoped. A Telegram worker
could therefore claim a future email or another-channel publication and only
discover the mismatch after the claim.

Extend the existing generic method with an optional channel filter while
preserving current callers:

```python
async def claim_pending(
    self,
    *,
    now: datetime,
    worker_id: str,
    lease_duration: timedelta,
    maximum_attempts: int,
    channel: str | None = None,
) -> Publication | None: ...
```

Implement the same semantics in memory and PostgreSQL repositories. PostgreSQL
must include the channel predicate inside the locking selection query, not filter
after claiming. An optional matching filter may be added to `list_pending` only
if administration or observability needs it; it is not required by the delivery
worker.

No Telegram-specific repository interface or method is permitted. Existing
`mark_published`, `mark_failed`, `mark_ambiguous`, stale-claim listing, and
cancellation operations already cover automated delivery. No schema migration is
required for the first EPIC 14 implementation.

## 22. Test Plan

### Unit tests

- plain-text formatter preserves Unicode and normalizes line endings;
- empty content is rejected;
- content at the configured boundary is accepted;
- oversized content is rejected without truncation or splitting;
- untrusted content cannot select destination or parse mode;
- Telegram success maps message and chat IDs correctly;
- returned chat mismatch is ambiguous;
- `400`, `401`, `403`, and `404` map to permanent failure;
- `429` maps to retryable failure and captures `retry_after`;
- explicit `5xx` maps to retryable failure;
- connect failures map to retryable failure;
- write/read uncertainty maps to ambiguous;
- malformed success payload maps to ambiguous;
- token-bearing URL and raw payload are absent from safe errors and logs;
- retry delay and exhaustion are deterministic;
- dry-run performs no adapter call and no mutation.

### Repository contract tests

- channel-scoped claim never claims another channel;
- concurrent claim returns one owner;
- active claim cannot be stolen;
- stale worker cannot complete after version changes;
- success persists external message ID once;
- duplicate same-message completion is idempotent;
- conflicting completion is rejected;
- retryable failure becomes due only at `next_retry_at`;
- ambiguous publication is not claimable automatically;
- memory and PostgreSQL implementations have equivalent behavior.

### Service integration tests

- eligible publication follows claim -> send -> published;
- invalid content follows claim -> permanent failed without network;
- rate limit schedules retry and stops the current batch;
- retryable transport failure schedules durable retry;
- uncertain transport outcome becomes ambiguous;
- crash-shaped stale claim recovery becomes ambiguous;
- approved review-gated content can send;
- unapproved review-gated content cannot send;
- cancelled publication cannot send;
- transaction is not held during adapter invocation;
- restart with fresh services resumes due work from repositories.

### Scheduler tests

- delivery job delegates only to the service;
- one failed publication does not stop the scheduler;
- recovery job remains independent from delivery job;
- scheduler cancellation does not corrupt a durable claim;
- service result counts are reported without content or credentials.

## 23. Verification Script Design

Create `scripts/verify_epic14_telegram_delivery.py` during implementation. Its
default mode must be fully offline and use an HTTPX `MockTransport` or equivalent
local fake Telegram server. It must not contact Telegram.

Offline verification should exercise at least:

1. Configuration with delivery disabled by default.
2. Creation of eligible durable content and publication.
3. Channel-scoped claim behavior.
4. Deterministic plain-text rendering.
5. Successful mock `sendMessage` response.
6. Exact destination verification.
7. Durable `published` transition and external message ID.
8. Duplicate completion idempotency.
9. Mock `429` and `retry_after` persistence.
10. Mock permanent `403` failure.
11. Mock read timeout becoming `ambiguous`.
12. Oversized message blocked before HTTP.
13. Dry-run with zero repository mutation.
14. Stale claim recovery to `ambiguous`.
15. Scheduler job delegation and statistics.
16. Fresh service/repository instances observing durable state when PostgreSQL
    mode is enabled.
17. Secret-redaction assertions for errors and logs.

Optional `--live` mode must require every test-chat gate from section 18. It sends
exactly one visibly marked test message, verifies returned chat and message IDs,
verifies durable publication state, prints only safe identifiers, and exits. It
must never fall back to a production destination.

## 24. Implementation Plan

### Task 1 - Delivery contracts, formatter, and Telegram adapter

- add immutable generic delivery DTOs and adapter protocol;
- implement deterministic plain-text formatter and validation;
- implement dedicated direct Bot API client on one `httpx.AsyncClient`;
- implement `TelegramPublicationAdapter` with typed error classification;
- add offline adapter and formatter tests using mock transport;
- add no repository or scheduler behavior in this task.

### Task 2 - Durable delivery orchestration

- add optional generic channel filtering to `claim_pending` in contracts, memory,
  and PostgreSQL implementations;
- implement `PublicationDeliveryService` with short claim/read/completion scopes;
- implement eligibility checks, durable retry policy, ambiguity policy, and
  typed application results;
- add `PendingPublicationDeliveryJob` and reuse existing stale-claim recovery;
- add repository parity and service integration tests;
- add the default offline verification script.

### Task 3 - Guarded live test-chat verification

- add required Telegram settings and startup validation;
- add explicit live-test mode to the verification script;
- verify one isolated test publication against an allowlisted test chat;
- verify durable message ID and publication status;
- document observed Bot API and operational limitations;
- keep production delivery disabled by default.

## 25. Acceptance Checklist

- [x] No Telegram framework dependency was added.
- [x] One long-lived async HTTP client is reused per adapter instance.
- [x] Existing retrying `HttpClient` is not used for `sendMessage`.
- [x] Adapter performs one request and no retries.
- [x] Delivery service owns lifecycle and retry decisions.
- [x] Network calls occur outside database transactions.
- [x] Pending claims are filtered by channel before locking.
- [x] Memory and PostgreSQL repository behavior remains equivalent.
- [x] Plain text is the default and rich markup is disabled.
- [x] Empty and oversized messages are rejected before network access.
- [x] Successful responses verify destination and message ID.
- [x] Success persists `external_message_id` and `published_at`.
- [x] Adapter returns the confirmed external message ID without persisting it.
- [x] Retryable, permanent, and ambiguous outcomes are distinct.
- [x] Adapter parses and returns `429 retry_after` without calculating policy.
- [x] Adapter never retries ambiguous outcomes or any other outcome.
- [x] Stale delivery claims recover conservatively to `ambiguous`.
- [x] Active claim and version protections remain enforced.
- [x] Dry-run is read-only and does not claim publications.
- [x] Live delivery is disabled by default.
- [x] Live test mode requires an allowlisted exact test chat and CLI confirmation.
- [x] Tokens, token-bearing URLs, and raw responses are absent from logs/errors.
- [x] Scheduler job contains orchestration only.
- [x] Offline verification performs no external network request.
- [ ] Optional live verification sends exactly one marked test message.
- [x] No content-generation, event, matching, or comparator behavior changed.
- [x] Task 1 introduced no schema migration.

## 27. Retry Result (2026-07-31)

The verification retry did not reach a live PostgreSQL-backed delivery run.
Docker Desktop was present but could not be started in this session, and no
isolated `EPIC14_DATABASE_URL` was supplied. The guarded live verifier therefore
remained in offline mode and the PostgreSQL delivery verifier continued to skip
instead of fabricating success.

## 26. Recommended Next Implementation Task

Complete **EPIC 14 final verification** in an environment with an isolated
PostgreSQL database. If approved Telegram test-chat credentials are available,
run the guarded live verification script exactly once with the required live
flags and exact chat confirmation. Do not proceed to production broadcast until
PostgreSQL verification and the live-test decision are explicitly resolved.

## References

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [HTTPX async client documentation](https://www.python-httpx.org/async/)
- [HTTPX exception hierarchy](https://www.python-httpx.org/exceptions/)
- [aiogram documentation](https://docs.aiogram.dev/en/dev-3.x/)
- [python-telegram-bot Bot API documentation](https://docs.python-telegram-bot.org/en/latest/telegram.bot.html)
