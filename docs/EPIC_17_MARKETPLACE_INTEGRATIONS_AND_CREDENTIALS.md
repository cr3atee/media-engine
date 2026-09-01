# EPIC 17 - Marketplace Integrations and Credentials

Status: design ready; implementation not started.

EPIC 17 defines tenant-owned marketplace integration configuration and the
credential boundary required before tenant-specific ingestion can be exposed to
seller users.

This document is documentation only. It does not implement code, migrations,
credentials, live marketplace authentication, billing, Telegram delivery, or
seller UI.

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
| `credential_reference` | Opaque reference to stored credential material, not the secret itself. |
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

- Add marketplace integration domain contracts.
- Add repository interfaces and memory implementations.
- Add PostgreSQL table and migration after `0011_auth_boundary`.
- Add tenant-scoped uniqueness, indexes, foreign keys, and optimistic version
  constraints.
- Verify memory/PostgreSQL behavior alignment.

### Task 2 - Credential metadata and redaction boundary

- Add credential-reference metadata without plaintext secret exposure.
- Add redaction helpers and safe DTOs.
- Add audit-safe credential rotation intent.
- Verify no secret values are returned or logged.

### Task 3 - Seller integration API

- Add tenant-scoped seller routes for integration metadata.
- Enforce centralized permissions through `TenantContext`.
- Preserve stable sanitized API errors.
- Verify cross-tenant isolation, version conflicts, and rollback.

### Task 4 - Scheduler integration selection

- Add an orchestration path that selects enabled tenant integrations.
- Pass tenant/integration context into existing marketplace application runner.
- Keep parsers tenant-unaware.
- Verify disabled/deactivated integration exclusion and fresh-session behavior.

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

## 15. Recommended First Implementation Task

Start with **Task 1 - Integration domain and schema foundation**.

Do not implement live credential storage in Task 1. First create the tenant-owned
integration identity and persistence boundary, then layer credential handling on
top of that verified foundation.
