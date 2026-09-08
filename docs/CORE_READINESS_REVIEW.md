# MediaEngine Core Readiness Review

Date: 2026-09-08

## Scope

This review evaluates MediaEngine as a reusable backend core and multi-node
runtime foundation. It does not evaluate UI polish, marketing readiness, or
public launch readiness.

Reviewed areas:

- marketplace ingestion;
- repository and PostgreSQL persistence boundaries;
- transaction scope;
- tenant identity and authorization;
- event, scoring, content, and publication lifecycle;
- Scheduler orchestration and multi-node leases;
- administration API boundary;
- marketplace payload readiness.

## Executive Verdict

MediaEngine core is functionally ready as a backend foundation for continued
product development.

The core is not yet production-launch ready. The remaining gaps are operational
and integration-facing rather than core domain architecture blockers:

- production process entrypoint;
- live marketplace credential retrieval;
- live polling monitoring;
- guarded live Telegram test-chat verification;
- production AI provider wiring;
- full repository-wide Ruff cleanup;
- CI-portable marketplace fixtures or guarded live source checks.

## Core Capabilities Confirmed

### Marketplace Data

Current saved/live marketplace readiness:

| Marketplace | Status | Raw | Parsed | Snapshot-ready |
| --- | ---: | ---: | ---: | ---: |
| GGSEL | ready | 60 | 60 | 60 |
| Playerok | ready | 20 | 20 | 20 |
| FunPay | ready | 1 | 1 | 1 |

The current marketplace adapters can produce `ParsedOffer` objects with enough
universal data for snapshot creation.

Important caveats:

- GGSEL and FunPay readiness depends on saved real payloads in `tmp/`.
- Playerok uses the public GraphQL `items` operation.
- Playerok GraphQL does not expose `currency` directly; the adapter uses the
  documented source-backed `RUB` fallback based on frontend bundle evidence.
- The strict saved-payload verifier is useful locally but is not CI-portable
  until sanitized committed fixtures or explicit live verification guards are
  added.

### Persistence

The repository layer is mature enough for core runtime use:

- repository contracts are async and database-independent;
- memory and PostgreSQL implementations exist;
- PostgreSQL repositories share caller-owned `AsyncSession` scope;
- transaction commit/rollback ownership is centralized in repository scopes;
- durable market events, generated content, publications, admin actions,
  tenants, auth, marketplace integrations, and scheduler leases have PostgreSQL
  support.

### Tenant Isolation

Tenant identity is a core boundary, not an afterthought:

- durable tenants, users, and memberships exist;
- legacy ownership is deterministic;
- seller routes resolve tenant context;
- repository primitives are tenant-aware;
- tenant isolation has passed isolated PostgreSQL verification.

### Marketplace Integration Metadata

Tenant-owned marketplace integrations are implemented as metadata and selection
records:

- integrations can be listed, created, updated, disabled, and selected;
- credential references are opaque and redacted;
- raw live credentials are not stored or retrieved yet;
- Scheduler can select enabled integrations without owning marketplace logic.

### Event And Content Lifecycle

The durable post-ingestion lifecycle is production-shaped:

- price snapshots produce deterministic durable market events;
- event claiming and scoring are durable and retryable;
- content generation runs outside open database transactions;
- generated content and publication intents persist atomically where required;
- publication delivery has channel-scoped claims, retry, permanent failure, and
  ambiguous-state handling.

### Scheduler

Scheduler is orchestration-only:

- jobs call existing services;
- retry and timeout handling live in the scheduler layer;
- multi-node same-job overlap can be guarded with leases;
- memory and PostgreSQL lease repositories exist;
- production deployments must use stable owner IDs and PostgreSQL-backed leases.

## Architecture Assessment

### Strengths

- Business services depend on repository abstractions rather than concrete
  database classes.
- Database transactions are separated from network calls and AI calls.
- Scheduler does not contain business logic.
- Marketplace-specific details remain in adapter/parser layers.
- Tenant identity propagates through durable data boundaries.
- Most critical lifecycle flows have dedicated PostgreSQL verifiers.

### Acceptable Current Tradeoffs

- `ParsedOffer` still lives under `app.parsers` while being used as a wider
  application contract. This is tolerable for now because the public interface
  is stable, but it should eventually move to an application/domain contract
  module.
- `MarketplacePipeline` still has GGSEL-specific constructor types. This is
  legacy shape from the first marketplace vertical; newer Playerok/FunPay
  pipelines are thinner. Do not redesign this until production composition is
  introduced.
- Saved real payloads in `tmp/` are intentionally not committed. This protects
  raw marketplace data but limits reproducibility.

### Real Technical Debt

- Full repository-wide Ruff is not green because of older unrelated lint issues.
- Marketplace payload verification is local-payload-based, not CI-portable.
- Live marketplace polling monitoring is not implemented.
- Production process entrypoint is not wired.
- Live marketplace credential retrieval is not implemented.
- Live Telegram delivery has not sent and persisted an approved test-chat
  message.
- Production AI provider is not wired into runtime content generation.

## MVP Core Readiness

| Area | Readiness | Notes |
| --- | ---: | --- |
| Foundation | 95% | Project, async runtime, config, logging, DB, Alembic, tooling exist. |
| PostgreSQL persistence | 90% | Core repositories and migrations exist; production bootstrap remains. |
| Tenant and auth | 90% | Tenant isolation and auth boundary verified. |
| Marketplace data | 80% | Three marketplaces are snapshot-ready from current proof; live monitoring remains. |
| Matching and comparator | 85% | Deterministic core exists; production catalog operations remain later work. |
| Events and scoring | 90% | Durable event/scoring lifecycle verified. |
| Content generation | 80% | Durable lifecycle exists; production AI wiring remains. |
| Telegram delivery | 75% | Durable delivery orchestration exists; live test-chat not performed. |
| Scheduler | 85% | Jobs, retry, periodic execution, leases exist; production entrypoint remains. |
| Overall core | 85% | Ready as a reusable backend core, not as a public production launch. |

## Release Readiness

MediaEngine can demonstrate core product value:

- real marketplace data can become normalized offers;
- offers can become snapshots;
- snapshots can produce price changes and durable events;
- events can be scored;
- content can be generated through the provider abstraction;
- publication intents and delivery state can be persisted;
- tenant-scoped administration can read and mutate lifecycle state;
- Scheduler can orchestrate work without owning business logic.

MediaEngine is not ready for public production launch until:

- production runtime configuration is defined;
- live credentials and secret-storage policy are implemented;
- live polling monitoring exists;
- one guarded Telegram test-chat message is sent and persisted;
- production AI provider use is explicitly wired and verified;
- CI has stable marketplace fixtures or guarded live checks;
- full Ruff debt is either fixed or intentionally scoped.

## Recommended Next Work

1. Production process entrypoint.
   Use the runtime bootstrap foundation to wire PostgreSQL repository scopes,
   Scheduler factory construction, marketplace integration selection, and safe
   shutdown in the deployment process.

2. Marketplace live polling verification.
   Add guarded live checks for GGSEL, Playerok, and FunPay with exact diagnostics,
   no fake success, and rate-safe execution.

3. Secret storage and marketplace credential retrieval.
   Keep credential references opaque; add approved retrieval only at execution
   time.

4. Telegram guarded live test-chat verification.
   Send exactly one approved message, persist external message ID, and prove
   idempotent rerun.

5. CI quality cleanup.
   Make full Ruff green and decide how marketplace payload contracts should run
   in CI.

## Final Decision

The MediaEngine core can be considered complete enough to serve as the backend
kernel for the next product stage.

The next stage should not be another domain redesign. It should be production
runtime hardening: process entrypoint, monitored polling, credentials, and
guarded live delivery verification.
