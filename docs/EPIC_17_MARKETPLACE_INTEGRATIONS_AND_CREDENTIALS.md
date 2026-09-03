# EPIC 17 - Marketplace Integrations and Credentials

Status: Task 1 integration domain and schema foundation, Task 2 credential
metadata/redaction boundary, and Task 3 seller integration API are implemented
and verified against isolated PostgreSQL 17.10. Task 4 Scheduler integration
selection is implemented and offline-verified; live PostgreSQL verification is
blocked until Docker Desktop or an isolated `EPIC17_DATABASE_URL` is available.

EPIC 17 defines tenant-owned marketplace integration configuration and the
credential boundary required before tenant-specific ingestion can be exposed to
seller users.

Task 1 implements integration identity, repository contracts,
memory/PostgreSQL persistence, provider wiring, migration
`0012_marketplace_integrations`, focused tests, and guarded PostgreSQL
verification.

Task 2 implements opaque credential-reference metadata, redacted safe DTOs,
audit-safe credential rotation intent, repository credential-reference updates,
migration `0013_marketplace_credentials`, focused tests, and guarded PostgreSQL
verification. It does not implement plaintext credential storage, live
marketplace authentication, billing, Telegram delivery, seller routes, or seller
UI.

Task 3 implements tenant-scoped seller routes for listing, reading, creating,
updating, disabling, and rotating credential references for marketplace
integrations. It enforces centralized `TenantContext` permissions, returns
stable sanitized API errors, and exposes only redacted credential metadata. It
does not implement Scheduler selection, live credential use, plaintext secret
storage, billing, Telegram delivery, or seller UI.

Task 4 implements an orchestration-only service and Scheduler job that select
enabled marketplace integrations, exclude inactive tenants, and delegate to
existing marketplace runners through injected factories. It does not implement
live marketplace credential use, parser changes, repository redesign,
PostgreSQL migrations, billing, Telegram delivery, or seller UI.

## Task 1 Verification

Task 1 verification used a temporary `postgres:17-alpine` container with
PostgreSQL 17.10 and isolated database `epic17_task1_verify` on
`127.0.0.1:55434`. No project or production database was used.

Verified:

- PostgreSQL verifier `scripts/verify_epic17_marketplace_integrations_postgres.py`:
  `12/12` checks passed;
- focused marketplace integration tests: `7 passed`;
- focused repository tests: `27 passed`;
- full Pytest: `325 passed, 58 skipped`;
- full MyPy: `312 source files`;
- Ruff and Ruff format checks for EPIC 17 touched files;
- Alembic clean upgrade through `0012_marketplace_integrations`;
- `alembic current`: `0012_marketplace_integrations (head)`;
- `alembic check`: no new upgrade operations;
- downgrade from `0012_marketplace_integrations` to `0011_auth_boundary`;
- upgrade back to head;
- offline `upgrade head --sql`.

## Task 2 Verification

Task 2 verification used a temporary `postgres:17-alpine` container with
PostgreSQL 17.10 and isolated database `epic17_task2_verify` on
`127.0.0.1:55435`. No project or production database was used.

Verified:

- PostgreSQL verifier `scripts/verify_epic17_marketplace_integrations_postgres.py`:
  `18/18` checks passed;
- focused marketplace integration repository tests: `11 passed`;
- full Pytest: `329 passed, 58 skipped`;
- full MyPy: `326 source files`;
- Ruff and Ruff format checks for EPIC 17 Task 2 touched files;
- Alembic clean upgrade through `0013_marketplace_credentials`;
- `alembic current`: `0013_marketplace_credentials (head)`;
- `alembic check`: no new upgrade operations;
- downgrade from `0013_marketplace_credentials` to
  `0012_marketplace_integrations`;
- upgrade back to head;
- offline `upgrade head --sql`.

The verifier covers credential metadata columns, constraints and indexes,
tenant-scoped integration behavior, credential-reference persistence,
redacted update responses, stale version rejection, fresh-session persistence,
rollback safety, and tenant-scoped uniqueness.

## Task 3 Verification

Task 3 verification used a temporary `postgres:17-alpine` container with
PostgreSQL 17.10 and isolated database `epic17_task3_verify` on
`127.0.0.1:55436`. No project or production database was used.

Verified:

- PostgreSQL seller API verifier
  `scripts/verify_epic17_seller_integrations_postgres.py`: `16/16` checks
  passed;
- focused seller integration API and marketplace integration repository tests:
  `16 passed`;
- full Pytest: `334 passed, 58 skipped`;
- full MyPy: `331 source files`;
- Ruff and Ruff format checks for EPIC 17 Task 3 touched files;
- Alembic current at `0013_marketplace_credentials (head)`;
- `alembic check`: no new upgrade operations;
- downgrade from `0013_marketplace_credentials` to
  `0012_marketplace_integrations`;
- upgrade back to head;
- offline `upgrade head --sql`.

The verifier covers missing authentication, permission denial, tenant-scoped
reads, cross-tenant hiding, create/update/disable operations, credential
rotation redaction, stale version rejection, invalid payload sanitization,
tenant-scoped uniqueness, duplicate rollback safety, and fresh-session
credential metadata persistence.

## Task 4 Verification

Task 4 offline verification passed:

- focused marketplace integration execution tests: `2 passed`;
- focused marketplace integration execution and repository tests: `13 passed`;
- demo `scripts/demo_marketplace_integration_scheduler.py`;
- full Pytest: `336 passed, 58 skipped`;
- full MyPy: `335 source files`;
- Ruff and Ruff format checks for EPIC 17 Task 4 touched files;
- offline `upgrade head --sql`.

`scripts/verify_epic17_scheduler_integrations_postgres.py` is implemented and
guarded by `EPIC17_DATABASE_URL`. It was not executed against PostgreSQL in the
current environment because Docker Desktop daemon was unavailable and
`EPIC17_DATABASE_URL` was not set. The verifier exits with an explicit skip
instead of fabricating success.

## 1. Goal

Create a safe tenant-owned integration layer for marketplace accounts and
marketplace data-source configuration.

The layer must allow future marketplace runs to start from durable tenant-owned
configuration instead of hardcoded demo URLs or process-level assumptions.

## 2. Non-Goals

EPIC 17 must not introduce:

- live credential use before safe storage and redaction are verified;
- marketplace-specific parsing changes;
- new comparison, matching, event, content, or Telegram behavior;
- billing, plan limits, subscriptions, or quotas;
- frontend seller UI;
- external secret manager integration unless explicitly approved;
- plaintext credential persistence.

## 3. Architectural Boundary

Marketplace parsers and normalizers remain tenant-unaware.

Tenant ownership belongs at the orchestration/configuration layer:

```text
Tenant
-> MarketplaceIntegration
-> MarketplaceApplicationRunner
-> ParsedOffer tenant stamping
-> PriceSnapshot tenant stamping
-> MarketEvent identity v2
```

The runner remains the tenant propagation point. Integrations select what to
run; parsers still only retrieve and normalize marketplace data.

## 4. Core Decisions

- A marketplace integration is owned by exactly one tenant.
- One tenant may have multiple integrations for the same marketplace only if the
  external account or source configuration differs.
- Credentials are never stored in plaintext business columns.
- Credential values must never appear in logs, API responses, readiness,
  OpenAPI examples, audit metadata, or verification output.
- Public seller routes may manage integration metadata only after authorization
  checks.
- Background jobs may run integrations only for active tenants and enabled
  integrations.
- Deactivated tenants must be excluded from new automatic marketplace work.
- Integration configuration is separate from parsed offers, snapshots, events,
  content, and publications.

## 5. MarketplaceIntegration Domain Contract

The future domain contract should represent one tenant-owned marketplace data
source.

Recommended fields:

| Field | Purpose |
| --- | --- |
| `id` | Stable integration ID. |
| `tenant_id` | Owning tenant. |
| `marketplace` | Marketplace code such as `ggsel`, `playerok`, or `funpay`. |
| `display_name` | Human-readable label inside the tenant workspace. |
| `enabled` | Whether automatic runs are allowed. |
| `status` | Operational state such as `draft`, `active`, `disabled`, or `error`. |
| `external_account_id` | Marketplace account identifier when available. |
| `source_url` | Public/category/source URL when the marketplace flow uses one. |
| `auth_type` | Credential mode, for example `none`, `api_key`, `cookie`, or `session`. |
| `credential_reference` | Opaque reference to stored credential material, not the secret itself. Returned only through redacted safe DTOs. |
| `last_successful_run_at` | Last successful ingestion timestamp. |
| `last_failed_run_at` | Last failed ingestion timestamp. |
| `last_error_code` | Safe machine-readable error code. |
| `last_error_summary` | Redacted human-readable summary. |
| `created_at` | UTC creation timestamp. |
| `updated_at` | UTC update timestamp. |
| `version` | Optimistic concurrency version. |

## 6. Credential Boundary

Credentials need a dedicated boundary before any live seller marketplace account
can be used.

Minimum safe requirements:

- credentials are stored hashed only when they are verification tokens;
- credentials are stored encrypted or by external secret reference when they
  must be sent back to a marketplace;
- repositories return redacted credential metadata by default;
- full secret material is available only to the execution path that needs it;
- secret access is audited with tenant, actor type, integration ID, and safe
  reason metadata;
- credential rotation creates a new version and invalidates stale use where
  appropriate;
- failed credential validation must not expose the secret value.

If an external secret manager is not selected, the implementation must still
avoid plaintext columns and document the encryption/key-management approach
before storing live credentials.

## 7. PostgreSQL Schema Direction

Recommended table:

```text
marketplace_integrations
```

Required properties:

- `tenant_id NOT NULL` with `ON DELETE RESTRICT`;
- unique integration identity scoped by tenant;
- indexes for enabled tenant runs;
- indexes for tenant-scoped seller reads;
- optimistic version checks;
- timestamp order checks;
- constrained marketplace/status/auth type values.

Recommended uniqueness:

```text
UNIQUE (tenant_id, marketplace, external_account_id)
WHERE external_account_id IS NOT NULL
```

For URL-only public sources:

```text
UNIQUE (tenant_id, marketplace, source_url)
WHERE source_url IS NOT NULL
```

Do not make marketplace identity globally unique across tenants.

## 8. Repository Contracts

Add repository interfaces before PostgreSQL implementations.

Minimum repository behavior:

- save integration metadata;
- get by ID within tenant;
- list enabled integrations for a tenant;
- list all due enabled integrations for Scheduler;
- update operational status and safe error state;
- update credential reference metadata without returning secret values.

Repository contracts must stay database-independent and async-compatible.

## 9. Seller API Boundary

Seller-facing integration routes should live under the existing tenant path:

```text
/api/v1/tenants/{tenant_id}/marketplace-integrations
```

Minimum permissions:

- read integrations: all active tenant roles except where product policy says
  otherwise;
- create/update/disable integrations: owner and administrator;
- credential rotation: owner and administrator;
- delete or hard-remove integrations: not in MVP unless explicitly approved.

Routes must return stable sanitized errors and must not expose secret values.

## 10. Scheduler Integration

Scheduler jobs should query enabled marketplace integrations and call existing
application services with explicit tenant/integration context.

Scheduler must not own:

- credential parsing;
- marketplace business logic;
- offer normalization;
- price comparison;
- event creation;
- content generation;
- Telegram delivery.

## 11. Marketplace-Specific Notes

### GGSEL

Current GGSEL work can operate from public/source URLs. Credentials are not
required for the currently documented public data retrieval path.

EPIC 17 should still represent GGSEL as a tenant-owned integration so that
different tenants can choose different categories/sources independently.

### Playerok

Playerok extraction may require authenticated access depending on the final
data-source strategy. Do not store live Playerok credentials until the credential
boundary is implemented and verified.

### FunPay

FunPay remains planned. Do not add FunPay-specific credential behavior until a
technical data-source specification exists.

## 12. Verification Requirements

EPIC 17 is complete only when verification proves:

- tenant A cannot read or mutate tenant B integrations;
- integration uniqueness is tenant-scoped;
- disabled integrations are not selected for automatic runs;
- deactivated tenants are not selected for automatic runs;
- credentials are redacted from API responses, logs, readiness, and audit
  metadata;
- credential references survive fresh sessions;
- repository behavior is aligned between memory and PostgreSQL;
- optimistic version conflicts are stable;
- rollback leaves no partial integration or credential-reference update;
- Scheduler can select and execute enabled integrations without moving business
  logic into Scheduler;
- no live marketplace credential is used without explicit test credentials and
  guards.

## 13. Implementation Breakdown

### Task 1 - Integration domain and schema foundation

- Marketplace integration domain contracts are implemented.
- Repository interface, memory implementation, and PostgreSQL implementation are
  implemented.
- PostgreSQL table and migration `0012_marketplace_integrations` after
  `0011_auth_boundary` are implemented.
- Tenant-scoped uniqueness, indexes, foreign keys, and optimistic version
  constraints are implemented.
- Memory/PostgreSQL behavior alignment is verified.

### Task 2 - Credential metadata and redaction boundary

- Credential-reference metadata without plaintext secret exposure is
  implemented.
- Redaction helpers and safe DTOs are implemented.
- Audit-safe credential rotation intent is implemented.
- Memory and PostgreSQL repository updates return only redacted metadata.
- Migration `0013_marketplace_credentials` is implemented and verified.
- PostgreSQL verification proves fresh-session persistence, optimistic version
  conflict handling, rollback safety, and credential redaction.

### Task 3 - Seller integration API

- Tenant-scoped seller routes for integration metadata are implemented.
- Centralized permissions are enforced through `TenantContext`.
- Stable sanitized API errors are preserved.
- Cross-tenant isolation, version conflicts, rollback, and redacted credential
  responses are verified.

### Task 4 - Scheduler integration selection

- An orchestration path that selects enabled tenant integrations is implemented.
- Tenant/integration context is passed to injected marketplace runner factories.
- Parsers remain tenant-unaware.
- Disabled integrations and inactive tenants are excluded by the service.
- Fresh-session PostgreSQL behavior still requires live isolated PostgreSQL
  verification.

### Task 5 - Final PostgreSQL verification

- Run isolated PostgreSQL verification through the new migration head.
- Run Alembic current/check, downgrade/upgrade, and offline SQL.
- Run full Pytest, MyPy, Ruff, and format checks.
- Update Project Passport and PostgreSQL verification documentation.

## 14. Acceptance Criteria

EPIC 17 is complete only when:

- marketplace integrations are tenant-owned;
- repository contracts and PostgreSQL implementations are verified;
- seller API routes are tenant-scoped and permission-checked;
- Scheduler selects only active tenant-owned enabled integrations;
- no plaintext credentials are stored or exposed;
- secret redaction is verified;
- memory and PostgreSQL implementations behave consistently;
- rollback, idempotency, optimistic concurrency, and fresh-session persistence
  are verified;
- existing marketplace parsing, matching, comparator, event, content, and
  Telegram behavior remain unchanged.

## 15. Recommended Next Implementation Task

Continue with **Task 4 live PostgreSQL verification** once Docker Desktop or an
isolated `EPIC17_DATABASE_URL` is available.

Do not implement live credential use or Scheduler-driven authenticated
marketplace ingestion until enabled tenant integration selection is implemented,
disabled/deactivated integrations are excluded, and the orchestration path is
verified against PostgreSQL.
