# EPIC 16 - Seller Identity, Tenant Scoping and Authorization

Status: design only.

Baseline commit: `5341b1cda4bfc81c04e4e72f453ee7907685c732`.

This document designs the next safe product boundary after EPIC 15. It does not
implement authentication, migrations, frontend routes, marketplace credentials,
Telegram live delivery, billing, or subscriptions.

EPIC 15 is functionally complete for the internal administration API boundary.
The current `/api/v1/admin` surface is intentionally internal: it exposes
PostgreSQL-verified reads, dashboard summary, protected OpenAPI, guarded content
review commands, publication commands, ambiguous-delivery resolution, and
immutable `admin_actions` audit rows behind `X-Admin-API-Key`.

MediaEngine still has no seller identity, tenant ownership, seller-facing
authorization, user membership, tenant-scoped marketplace credentials, or
tenant-aware audit attribution. A public seller dashboard or seller API must not
be exposed before this EPIC is implemented and verified.

## 1. Current Verified Boundary

The current implementation has these verified durable capabilities:

- Marketplace offers and price snapshots are persisted through repository
  contracts.
- Deterministic market events are persisted and scored through claim-based
  processing.
- Generated-content attempts and channel-independent publication intents are
  persisted.
- Telegram delivery orchestration is durable, channel-scoped, retry-aware, and
  verified offline against PostgreSQL; live test-chat delivery remains
  unperformed.
- Scheduler jobs delegate only to application services.
- Internal administration reads and commands are PostgreSQL-verified at
  migration head `0009_admin_actions`.
- Current FastAPI composition keeps routes thin and uses repository scopes from
  the application composition root.

The important limitation is that all durable business records are currently
tenant-blind. Existing unique constraints are global for offer identity, event
identity, generated-content idempotency, publication idempotency, and admin
mutation idempotency.

## 2. Canonical Product Terminology

Use `Tenant` as the canonical codebase term.

Rationale:

- `Tenant` clearly means an isolation and ownership boundary.
- It maps naturally to `tenant_id` columns, `TenantContext`, tenant-scoped
  repositories, and future PostgreSQL isolation verification.
- `Workspace` is a good product/UI label later, but it is less precise in code.
- `Organization` implies company structure and billing complexity that is not
  part of the MVP.

Recommended exact terms:

| Concept | Code term | Meaning |
| --- | --- | --- |
| Human login identity | `User` | A person who can authenticate. |
| Isolation boundary | `Tenant` | Owns marketplace integrations, offers, snapshots, events, content, publications, destinations, and tenant settings. |
| User-to-tenant link | `Membership` | Grants a role in one tenant. |
| Authorization level | `TenantRole` | Role held by a user within a tenant. |
| Internal operator | `PlatformAdministrator` | Cross-tenant operator using a separate authorization path. |
| Marketplace account/config | `MarketplaceIntegration` | Tenant-owned marketplace access/configuration. |
| Telegram destination/config | `TelegramDestination` | Tenant-owned publication target. |

Avoid these conflations:

- A seller is not the same as a login account.
- A tenant is not the same as one person.
- A marketplace account is not the same as a tenant.
- An internal admin is not a tenant role.

## 3. MVP Multi-Tenancy Model

The smallest safe model is:

- One `User` may belong to many tenants.
- One `Tenant` may have many users.
- Every seller-owned business record belongs to exactly one tenant.
- Marketplace credentials and integration settings belong to a tenant.
- Telegram destinations belong to a tenant.
- Generated content, publications, events, snapshots, and offers carry explicit
  durable tenant ownership.
- Internal platform administration uses a separate elevated path and must never
  be silently treated as a tenant membership.

Billing, subscriptions, plan limits, invoice ownership, and marketplace revenue
settlement are outside EPIC 16 unless a later task explicitly adds them.

## 4. Authentication Approach

Recommended MVP approach: email/password authentication with Argon2id password
hashing, short-lived signed access tokens, and rotating opaque refresh tokens
stored as hashes.

Why this approach:

- It does not require an external identity provider for the first seller
  dashboard.
- It works for web and desktop clients.
- It allows local development and deterministic PostgreSQL verification.
- Refresh token revocation and reuse detection can be tested without a third
  party.
- Future OIDC/SSO can map external identities onto the local `User` record.

Authentication design:

| Area | Decision |
| --- | --- |
| Password hashing | Argon2id with unique salts and configurable work factor. |
| Password policy | Minimum 12 characters; reject common leaked-password integration can be future work. |
| Email verification | Required before accepting invitations or creating production tenants. |
| Password reset | Reset tokens are random, single-use, TTL-bound, and stored hashed at rest. |
| Access token | Signed bearer token, 15 minute lifetime. |
| Refresh token | Opaque random token, 30 day lifetime, stored hashed, rotated on use. |
| Logout | Revoke the current refresh token/session. |
| Reset side effect | Revoke all active sessions for the user unless explicitly scoped later. |
| Account disable | Blocks login, refresh, and seller API access. |
| Rate limiting | Apply to login, refresh, reset, invitation acceptance, and mutations. |
| Secrets | No passwords, hashes, reset tokens, access tokens, refresh tokens, marketplace credentials, or bot tokens in logs/API responses. |

Token model:

- Access token issuer: `mediaengine`.
- Access token audience: `mediaengine-seller-api`.
- Minimum token content: `sub` user ID, `sid` session ID, `iat`, `exp`, `iss`,
  `aud`.
- Do not put marketplace credentials, tenant secrets, or large permission state
  in the token.
- Do not trust role claims alone for authorization. Tenant membership and role
  must be checked from PostgreSQL on every seller-facing request.
- Signing keys need key IDs and rotation support. Old keys remain accepted only
  until their maximum token lifetime expires.
- Allow a small clock skew, for example 60 seconds.

External OIDC can be added later by linking a verified provider subject to a
local `User`. It should not replace local tenant membership checks.

## 5. Internal Admin Authentication Transition

Keep the current `X-Admin-API-Key` boundary during EPIC 16, but restrict its
meaning:

- It is an internal automation/operations credential.
- It is not a seller identity.
- It is not a tenant role.
- It is not a replacement for platform-admin user authentication.

Safe transition path:

1. Preserve existing `/api/v1/admin` behavior for verified EPIC 15 workflows.
2. Add seller authentication and tenant-scoped routes under a separate boundary.
3. Add platform-admin user authentication as a separate principal type.
4. Audit API-key actions as `actor_type=api_key`.
5. Audit platform-admin actions as `actor_type=platform_admin`.
6. Later, require platform-admin auth for human admin workflows and leave API
   keys only for explicit automation.

Do not merge platform admins into tenant memberships. A platform administrator
uses explicit elevated access and is always audited as elevated.

## 6. Tenant Selection Strategy

Recommended MVP strategy: tenant ID in the route path.

Route shape:

```text
/api/v1/tenants/{tenant_id}/...
```

Why:

- Tenant context is explicit and easy to verify.
- It works for web, desktop, and scripts.
- It keeps tokens small and avoids mutable "active tenant" session state.
- It prevents accidental reliance on resource IDs as proof of ownership.

Rejected for MVP:

- `X-Tenant-ID` header: easy to omit and less visible in OpenAPI.
- Active tenant inside token/session: role changes and membership removal become
  harder to enforce immediately.
- Subdomains: useful later, unnecessary for API foundation.
- Global mutable current-tenant variable: unsafe with async execution and tests.

Policy:

- A user must be an active member of the selected tenant.
- Tenant context is resolved before query/command service execution.
- Application services receive `AuthenticatedPrincipal` and `TenantContext`.
- Ordinary users receive `404` for resources that exist only in another tenant.
- Members with insufficient permission receive `403`.
- Platform admins use explicit elevated routes and never rely on hidden tenant
  inference.

## 7. Roles and Permission Matrix

Use a minimal role model:

| Role | Meaning |
| --- | --- |
| `OWNER` | Full tenant control, memberships, integrations, destinations, review, publication operations, tenant lifecycle. |
| `ADMINISTRATOR` | Operational management without ownership transfer or hard deletion. |
| `REVIEWER` | Read data and approve/reject generated content. |
| `OPERATOR` | Read data and operate publication failures/retries/ambiguous outcomes. |
| `VIEWER` | Read-only access. |

Permission matrix:

| Permission | Owner | Administrator | Reviewer | Operator | Viewer |
| --- | --- | --- | --- | --- | --- |
| Events read | yes | yes | yes | yes | yes |
| Content read | yes | yes | yes | yes | yes |
| Approve/reject content | yes | yes | yes | no | no |
| Publications read | yes | yes | yes | yes | yes |
| Retry/cancel publications | yes | yes | no | yes | no |
| Resolve ambiguous publication | yes | yes | no | yes | no |
| Audit read | yes | yes | no | no | no |
| Dashboard read | yes | yes | yes | yes | yes |
| Marketplace integration management | yes | yes | no | no | no |
| Telegram destination management | yes | yes | no | no | no |
| Membership management | yes | no | no | no | no |
| Tenant settings | yes | limited | no | no | no |
| Tenant deactivation | yes | no | no | no | no |
| Ownership transfer | yes | no | no | no | no |

Keep fine-grained custom permissions out of the MVP. Add them only after real
operator behavior shows a need.

## 8. Authorization Architecture

Create a centralized authorization layer. Routes must not contain ad hoc role
comparisons.

Recommended abstractions:

| Abstraction | Responsibility |
| --- | --- |
| `AuthenticatedPrincipal` | The authenticated caller, with actor type and user/session identifiers. |
| `TenantContext` | The selected tenant, membership, and role validated for this request. |
| `Permission` | Stable enum of allowed actions. |
| `AuthorizationService` | Checks membership, role, tenant state, and permission. |
| FastAPI dependencies | HTTP adaptation only: parse token, resolve tenant, call auth service. |
| Application services | Re-check resource ownership and required permission for commands. |

Preferred flow:

```text
Bearer/API credential
-> AuthenticatedPrincipal
-> tenant path resolution
-> membership lookup
-> permission check
-> query/command service
-> tenant-scoped repository
```

Application services must still enforce authorization when invoked outside HTTP.
Frontend button hiding is not an authorization mechanism.

## 9. Tenant Ownership Model

Tenant-owned records should carry direct `tenant_id` where they are queried,
claimed, or mutated independently. Deriving tenant through mutable joins is not
safe enough for the first public seller API.

Recommended ownership:

| Resource | Ownership decision |
| --- | --- |
| `tenants` | Global table, primary tenant identity. |
| `users` | Global user identity table. |
| `tenant_memberships` | Links users to tenants and roles. |
| `marketplace_integrations` | Direct `tenant_id`. |
| `canonical_products` | Direct `tenant_id` for tenant-owned catalog identities. A future global catalog can be separate. |
| `offers` | Direct `tenant_id`; identity unique per tenant. |
| `price_snapshots` | Direct `tenant_id`; history unique per tenant. |
| `market_events` | Direct `tenant_id`; identity unique per tenant. |
| `generated_contents` | Direct `tenant_id`, even though event has tenant, for query safety and performance. |
| `publications` | Direct `tenant_id`, plus tenant-owned destination validation. |
| `admin_actions` / future audit | Add tenant/actor attribution for tenant-scoped commands. |
| Scheduler run records if introduced | Direct `tenant_id` for tenant integration runs, otherwise explicit `system` scope. |
| Telegram destinations | Direct `tenant_id`. |
| AI settings/templates | Direct `tenant_id`. |

Direct tenant IDs are denormalization by design. Repositories and verifiers must
prove consistency between parent and child tenant ownership.

## 10. Tenant Propagation Through Ingestion

A marketplace run must start from a tenant-owned `MarketplaceIntegration`.

Required run context:

- `tenant_id`;
- `marketplace`;
- `marketplace_integration_id`;
- external account identity when available;
- enabled/configuration state;
- source URL/API endpoint;
- rate-limit metadata;
- system actor/worker identity.

Ingestion requirements:

- Ingestion cannot produce unscoped offers, snapshots, or events.
- Offer upserts include `tenant_id`.
- Snapshot writes include `tenant_id`.
- Price-history lookup uses `(tenant_id, marketplace, external_id)`.
- Event creation uses tenant-scoped snapshot identities.
- Scheduler jobs select tenant-owned integrations and carry tenant context.
- One tenant failure rolls back only that tenant's current run transaction.
- One tenant's duplicate external marketplace ID must not suppress another
  tenant's offer or event.

Current code impact:

- `MarketplaceApplicationRunner` already has a clean run boundary and
  repository scope. EPIC 16 should add tenant/integration context there rather
  than pushing tenant logic into parsers.
- `MarketplacePipeline` currently calls repository methods without tenant
  arguments. The repository/service contracts must become tenant-scoped before
  seller exposure.
- Parsers and normalizers should remain tenant-unaware. They produce marketplace
  data, not ownership decisions.

## 11. Tenant and Event Identity

Current durable event identity version is `1`. It hashes:

```text
v1 | event_type | marketplace | external_id | previous_snapshot_identity | current_snapshot_identity
```

This was correct for the single-tenant/internal state verified in EPIC 13-15.
It is not sufficient as the future public logical event identity because two
tenants can track the same marketplace `external_id` and observe the same price
transition while requiring independent content, scoring, publication, and audit
lifecycles.

Decision: introduce tenant-scoped event identity version `2` for new
tenant-aware events.

Recommended `v2` identity input:

```text
v2 | tenant_id | event_type | marketplace | external_id | previous_snapshot_identity_v2 | current_snapshot_identity_v2
```

Snapshot identity v2 includes:

```text
tenant_id | marketplace | external_id | collected_at | price | currency
```

Compatibility plan:

- Do not rewrite EPIC 13 identity semantics casually.
- Assign existing unscoped data to a default legacy tenant during migration.
- Keep existing `identity_version=1` rows stable.
- Add support for `identity_version=2` for new tenant-scoped events.
- Change event uniqueness from global `UNIQUE(identity_key)` to
  `UNIQUE(tenant_id, identity_key)`.
- Ensure event transition uniqueness also includes `tenant_id`.
- Verification must prove two tenants can create logically identical external
  events without collision.

## 12. Marketplace Integration Ownership

Introduce tenant-owned marketplace integration records.

Recommended fields:

| Field | Purpose |
| --- | --- |
| `id` | Technical integration ID. |
| `tenant_id` | Owner tenant. |
| `marketplace` | `ggsel`, `playerok`, `funpay`, etc. |
| `external_account_id` | Marketplace account identity when available. |
| `display_name` | Safe label for UI. |
| `enabled` | Controls Scheduler selection. |
| `credentials_reference` | Reference to encrypted secret or external secret manager entry. |
| `configuration` | Non-secret marketplace settings. |
| `last_successful_run_at` | Operational visibility. |
| `last_failure_at` | Operational visibility. |
| `last_failure_code` | Safe bounded failure category. |
| `rate_limit_state` | Optional bounded scheduling metadata. |
| `created_at`, `updated_at` | UTC timestamps. |

Credentials:

- Do not store credentials in plaintext.
- Production-safe target is an external secret manager or encrypted database
  fields backed by a managed key.
- Development can use environment variables or local-only encrypted test
  values, but docs and APIs must never treat that as production storage.
- Credential references belong to the tenant integration, not to raw offers.

Unique constraints:

- `UNIQUE(tenant_id, marketplace, external_account_id)` when external account is
  known.
- Optionally one default enabled integration per `(tenant_id, marketplace)` if
  product rules require it later.

## 13. Telegram Destination Ownership

Recommended MVP: platform-managed shared bot with tenant-owned destination
allowlists.

Why:

- It matches the existing Telegram adapter and delivery architecture.
- It avoids collecting tenant bot tokens in the first seller identity EPIC.
- It keeps operational safety centralized.
- It still prevents one tenant from publishing to another tenant's destination
  through tenant-owned destination records.

Tenant-owned destination model:

| Field | Purpose |
| --- | --- |
| `id` | Destination ID. |
| `tenant_id` | Owning tenant. |
| `channel` | `telegram` for MVP. |
| `destination_key` | Stored raw only if encrypted; otherwise store secret reference/hash plus safe label. |
| `destination_reference` | Non-reversible display/reference hash. |
| `display_label` | Human-readable label. |
| `enabled` | Controls delivery eligibility. |
| `verification_status` | `unverified`, `test_verified`, `production_verified`, `disabled`. |
| `is_default_test` | Optional default test target. |
| `is_default_production` | Optional default production target. |
| `created_at`, `updated_at` | UTC timestamps. |

Alternative: tenant-owned bots. This gives stronger isolation, but it requires
per-tenant bot-token storage, token rotation, bot permission verification, and
more complicated support. Defer it until product demand exists.

Publication rules:

- `publications.tenant_id` must match `telegram_destinations.tenant_id`.
- Delivery service must resolve destination configuration by tenant and channel.
- Dry-run must validate tenant destination ownership without mutating state.
- No publication may be created against a destination from another tenant.

## 14. Generated Content and AI Configuration

Generated content is tenant-owned because review, approval, publication, brand
voice, and audit are tenant-owned.

EPIC 16 should design tenant scope for:

- generated content attempts;
- prompt templates or prompt versions;
- AI provider/model selection;
- tone/brand settings;
- language;
- approval requirements;
- publication footer;
- publication target defaults.

AI output must never define tenant identity, tenant role, destination ownership,
or authorization. AI provider credentials must be stored as tenant-owned secret
references or platform-managed configuration, never in generated-content rows.

Keep a full template editor out of EPIC 16 unless explicitly requested. The MVP
can use tenant settings and immutable prompt-version labels.

## 15. Audit Trail

Current `admin_actions` records internal admin mutations with action, resource,
actor ID, request ID, idempotency key, fingerprint, expected/result versions,
reason, metadata, and UTC timestamp.

Do not delete or weaken this verified table. Extend the audit concept
carefully.

Recommended strategy:

- Keep `admin_actions` for current internal API-key operations during transition.
- Add tenant-aware fields or introduce a generalized `audit_actions` table in a
  focused migration after code design confirms the safest path.
- Prefer a generalized audit domain model for all future actions, even if the
  physical table remains `admin_actions` for backward compatibility at first.

Required future audit fields:

| Field | Purpose |
| --- | --- |
| `tenant_id` | Tenant affected, nullable only for true platform/system actions. |
| `actor_type` | `user`, `platform_admin`, `api_key`, `system`, `worker`, `migration`. |
| `actor_id` | User ID, platform admin ID, API key label, or worker ID. |
| `elevated` | Whether platform-admin elevation was used. |
| `action` | Stable action enum. |
| `resource_type`, `resource_id` | Mutated resource. |
| `previous_state`, `resulting_state` | Lifecycle transition. |
| `expected_version`, `resulting_version` | Optimistic concurrency evidence. |
| `request_id` | Correlation ID. |
| `idempotency_key` | Replay boundary. |
| `request_fingerprint` | Semantics bound to the idempotency key. |
| `reason` | Bounded human reason when required. |
| `metadata` | Bounded, secret-free extra facts. |
| `created_at` | UTC timestamp. |

Audit records remain append-only and immutable. Automated jobs must not
fabricate human actors.

## 16. Database Row-Level Isolation

Recommendation for first implementation: application-enforced tenant predicates
with mandatory tenant-scoped repositories, not PostgreSQL RLS yet.

Why not RLS first:

- The current repository layer already centralizes persistence and query
  contracts; adding tenant predicates there is explicit and testable.
- Async SQLAlchemy connection pools require careful per-transaction session
  context handling for RLS.
- Platform-admin bypass and background workers need explicit policy design.
- RLS can create false confidence if application joins still cross tenant
  boundaries.

Compensating controls for MVP:

- Every seller-facing repository contract requires `TenantContext`.
- No seller-facing repository method accepts optional tenant filtering.
- Platform-admin query contracts are separate.
- Direct `tenant_id` columns and foreign keys exist on tenant-owned records.
- Unique constraints include tenant scope where required.
- PostgreSQL verifier creates at least two tenants and proves isolation.
- Code review rejects unscoped seller queries.

Path to RLS:

- Add RLS only after tenant context is set per transaction.
- Prove connection-pool context does not leak between requests.
- Keep application predicates even with RLS.
- Add explicit platform-admin bypass and maintenance job policies.
- Verify rollback clears context.

## 17. Query Repository Changes

Seller-facing read repositories must require tenant context.

Examples:

```text
list_events(tenant: TenantContext, query: EventQuery, page: PageRequest)
get_event(tenant: TenantContext, event_id)
list_content(tenant: TenantContext, query, page)
get_content(tenant: TenantContext, content_id)
list_publications(tenant: TenantContext, query, page)
get_publication(tenant: TenantContext, publication_id)
get_dashboard_summary(tenant: TenantContext, window)
list_audit_actions(tenant: TenantContext, query, page)
```

Do not add `tenant_id: UUID | None` to existing query methods. Optional tenant
filters are too easy to call unsafely.

Separate contracts:

- `TenantEventQueryRepository`
- `TenantContentQueryRepository`
- `TenantPublicationQueryRepository`
- `TenantDashboardQueryRepository`
- `TenantAuditQueryRepository`
- `PlatformAdminQueryRepository` for explicit cross-tenant inspection

The current admin query contracts can remain internal and unscoped until they
are either retired or moved behind platform-admin authorization.

## 18. Command Service Changes

All seller-facing command services require:

- authenticated actor;
- tenant context;
- permission;
- expected version;
- idempotency context where relevant;
- bounded reason where required;
- request/correlation ID.

Commands:

- approve content;
- reject content;
- retry publication;
- cancel publication;
- resolve ambiguous publication;
- manage marketplace integrations;
- manage Telegram destinations;
- manage memberships and roles.

Services must verify the resource belongs to the selected tenant before mutation.
Route-level filtering is not enough. The command result must be safe and must
not expose secrets, claim tokens, ORM rows, or raw provider errors.

## 19. Cross-Tenant Access Semantics

Policy:

| Scenario | Ordinary seller response | Reason |
| --- | --- | --- |
| Tenant ID does not exist | `404 tenant_not_found` | Avoid exposing tenancy inventory. |
| User is not a member | `404 tenant_not_found` or `404 resource_not_found` | Hide tenant/resource existence. |
| Resource exists in another tenant | `404 resource_not_found` | Prevent cross-tenant probing. |
| User is member but lacks permission | `403 permission_denied` | Membership is known, permission is insufficient. |
| Account disabled | `403 account_disabled` | Authenticated but blocked. |
| Token invalid/expired/revoked | `401 authentication_required` / `401 token_expired` / `401 token_revoked` | Authentication failure. |
| Platform admin elevated access | `200` or domain error, audited as elevated | Explicit cross-tenant path only. |

Suspicious cross-tenant attempts should be security-logged with safe resource
references and request ID, without revealing the foreign resource to the caller.

## 20. Seller API Route Strategy

Recommended seller route prefix:

```text
/api/v1/tenants/{tenant_id}
```

Planned routes:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/me` | Current authenticated user. |
| `GET` | `/api/v1/me/tenants` | Memberships available to the current user. |
| `POST` | `/api/v1/tenants` | Create a tenant. |
| `GET` | `/api/v1/tenants/{tenant_id}` | Inspect selected tenant. |
| `PATCH` | `/api/v1/tenants/{tenant_id}` | Rename/update allowed settings. |
| `GET` | `/api/v1/tenants/{tenant_id}/events` | Tenant-scoped event reads. |
| `GET` | `/api/v1/tenants/{tenant_id}/events/{event_id}` | Tenant-scoped event detail. |
| `GET` | `/api/v1/tenants/{tenant_id}/content` | Tenant-scoped content reads. |
| `POST` | `/api/v1/tenants/{tenant_id}/content/{content_id}/approve` | Tenant-scoped approval. |
| `POST` | `/api/v1/tenants/{tenant_id}/content/{content_id}/reject` | Tenant-scoped rejection. |
| `GET` | `/api/v1/tenants/{tenant_id}/publications` | Tenant-scoped publication reads. |
| `POST` | `/api/v1/tenants/{tenant_id}/publications/{publication_id}/retry` | Tenant-scoped retry. |
| `POST` | `/api/v1/tenants/{tenant_id}/publications/{publication_id}/cancel` | Tenant-scoped cancellation. |
| `POST` | `/api/v1/tenants/{tenant_id}/publications/{publication_id}/resolve-ambiguous` | Tenant-scoped ambiguous resolution. |
| `GET` | `/api/v1/tenants/{tenant_id}/dashboard/summary` | Tenant-scoped dashboard. |
| `GET` | `/api/v1/tenants/{tenant_id}/audit` | Tenant audit if role permits. |
| `GET/POST/PATCH` | `/api/v1/tenants/{tenant_id}/marketplace-integrations` | Tenant integration management. |
| `GET/POST/PATCH` | `/api/v1/tenants/{tenant_id}/telegram-destinations` | Tenant Telegram destination management. |

Keep internal platform administration under a distinct boundary, for example:

```text
/api/v1/platform/tenants/{tenant_id}/...
```

Do not expose seller aliases for `/api/v1/admin`.

## 21. User and Membership API

EPIC 16 MVP should include:

- current authenticated user;
- list current user tenants;
- create tenant;
- inspect tenant membership;
- invite member;
- accept invitation;
- remove member;
- change role;
- logout and refresh;
- password reset boundary.

Defer:

- ownership transfer unless needed for MVP operations;
- hard tenant deletion;
- billing user management;
- SSO/OIDC;
- full email delivery implementation if the backend can create hashed
  invitation tokens and expose a safe testing boundary first.

Invitation tokens:

- random, single-use, TTL-bound;
- stored hashed at rest;
- scoped to tenant, invited email, role, creator, and request ID;
- no account enumeration in public responses;
- acceptance requires authenticated verified email or a safe registration flow.

## 22. Tenant Lifecycle

MVP lifecycle:

- create tenant;
- rename tenant;
- deactivate tenant;
- optionally reactivate tenant by owner/platform admin;
- no hard delete.

Hard deletion is high risk because durable offers, snapshots, events, generated
content, publications, and audit records are part of historical evidence.

Deactivation effects:

- New ingestion is blocked.
- Scheduler does not select the tenant's integrations for new work.
- New content generation/publication creation is blocked.
- Pending automatic work should either finish with existing claims or be moved
  to a safe terminal/retry state by an explicit policy.
- Existing reads remain available to owners/admins unless product policy says
  otherwise.
- Platform admin access remains explicit and audited.

## 23. Existing Data Migration

Recommendation: create one default legacy tenant and assign all current
unscoped durable records to it.

Why:

- The project is still before public seller launch.
- It preserves current PostgreSQL verification data semantics.
- It avoids permanently nullable tenant ownership.
- It allows new tenant-aware code to operate uniformly.

Migration order:

1. Create `users`, `tenants`, `tenant_memberships`, auth/session tables, and
   tenant configuration tables.
2. Create a default legacy tenant.
3. Add nullable `tenant_id` columns to tenant-owned existing tables.
4. Backfill existing rows to the legacy tenant.
5. Add foreign keys and tenant-aware indexes.
6. Update application/repository code to always write tenant IDs.
7. Validate no tenant-owned business row has `tenant_id IS NULL`.
8. Convert tenant IDs to `NOT NULL`.
9. Replace global unique constraints with tenant-scoped constraints.
10. Introduce event identity v2 for new tenant-scoped events.
11. Verify downgrade/upgrade/offline SQL and tenant isolation.

Rollback limitation: once existing data is backfilled and constraints are
converted to tenant-aware `NOT NULL`, downgrade should be treated as a
development rollback only unless a production data restore plan exists.

Do not leave seller-owned business records permanently nullable by tenant.

## 24. Migration Inventory

Likely new tables:

| Table | Purpose |
| --- | --- |
| `users` | Human identities. |
| `tenants` | Tenant/workspace identities. |
| `tenant_memberships` | User role in tenant. |
| `tenant_invitations` | Hashed invitation tokens and role grants. |
| `auth_sessions` | Refresh-token/session state. |
| `password_reset_tokens` | Hashed reset tokens with TTL. |
| `marketplace_integrations` | Tenant-owned marketplace configuration. |
| `telegram_destinations` | Tenant-owned Telegram publication destinations. |
| `tenant_ai_settings` | Optional tenant AI/content settings. |
| `audit_actions` or extended `admin_actions` | Tenant-aware immutable audit. |

Likely new columns:

| Table | New column |
| --- | --- |
| `canonical_products` | `tenant_id` |
| `offers` | `tenant_id`, optionally `marketplace_integration_id` |
| `price_snapshots` | `tenant_id` |
| `market_events` | `tenant_id` |
| `generated_contents` | `tenant_id` |
| `publications` | `tenant_id`, optionally `telegram_destination_id` |
| `admin_actions` | `tenant_id`, `actor_type`, `actor_uuid`, `elevated` |

All timestamps remain timezone-aware UTC.

## 25. Unique Constraint Changes

Current global constraints must be reviewed before public multi-tenancy.

| Current area | Current behavior | EPIC 16 target |
| --- | --- | --- |
| Offers | Unique partial index on `(marketplace, external_id)` when `external_id IS NOT NULL`. | Unique partial index on `(tenant_id, marketplace, external_id)`. |
| Price snapshots | Unique exact identity on `(marketplace, external_id, collected_at, price, currency)`. | Unique exact identity on `(tenant_id, marketplace, external_id, collected_at, price, currency)`. |
| Market events | `UNIQUE(identity_key)`. | `UNIQUE(tenant_id, identity_key)`, with new v2 identity containing tenant. |
| Market event snapshot transition | Unique `(event_type, previous_snapshot_id, current_snapshot_id)`. | Include `tenant_id` or rely on tenant-owned snapshot FKs plus verifier checks; prefer explicit `(tenant_id, event_type, previous_snapshot_id, current_snapshot_id)`. |
| Generated-content idempotency | `UNIQUE(idempotency_key)`. | `UNIQUE(tenant_id, idempotency_key)` or deterministic key generated with tenant input. |
| Generated content event attempt | Unique `(event_id, content_type, language, prompt_version, attempt_number)`. | Existing event FK is tenant-owned; add direct `tenant_id` for query and optional consistency checks. |
| Active content generation | Unique active generation by event/content/language/prompt. | Preserve semantics, include tenant where practical for query/index locality. |
| Publications idempotency | `UNIQUE(idempotency_key)`. | `UNIQUE(tenant_id, idempotency_key)` or deterministic key generated with tenant input. |
| Publication content/channel/destination | Unique `(content_id, channel, destination_key)`. | Prefer `(tenant_id, content_id, channel, telegram_destination_id)`; avoid raw destination key in uniqueness when encrypted/reference-backed. |
| Admin action idempotency | `UNIQUE(idempotency_key)`. | Seller commands use `UNIQUE(tenant_id, actor_id, idempotency_key)`; platform/admin API-key actions remain separately scoped. |

Global uniqueness that should remain global:

- `users.email_normalized`, if email/password local auth is chosen.
- Token hashes for refresh/reset/invitation tokens.
- Primary keys.
- Tenant slug if a globally unique slug is introduced.

## 26. Scheduler and Workers

Tenant-aware scheduling design:

- Scheduler remains one orchestration service, not one instance per tenant.
- Marketplace jobs select enabled `MarketplaceIntegration` records.
- Each integration run carries `tenant_id` and `marketplace_integration_id`.
- Batches should be bounded and fair so one tenant cannot starve others.
- Deactivated tenants are excluded from new marketplace ingestion and new
  automatic work.
- Existing active claims follow an explicit policy: finish, recover, or cancel.
- Scheduler job logs include tenant/integration safe identifiers when relevant.

No business logic moves into Scheduler jobs. Jobs continue to call application
services.

## 27. Background Processing Claims

Claimed work remains durable and tenant-owned.

Scoring:

- Global workers may claim events across tenants.
- Claimed event rows include tenant ownership.
- Completion checks claim token, expected version, and tenant consistency.

Content generation:

- Claims include tenant-owned generated-content rows.
- AI call runs outside repository transaction as today.
- Completion writes back to the same tenant-owned attempt.

Publication delivery:

- Claims include tenant-owned publication rows.
- Destination validation checks tenant-owned Telegram destination.
- Telegram call remains outside DB transaction.
- Completion writes back to the same tenant-owned publication.

Fairness:

- Initial MVP can use bounded batches ordered by due time.
- Add per-tenant batch caps if one tenant dominates queues.
- Multi-process coordination still needs explicit overlap policy from existing
  Scheduler notes.

## 28. System Actors and Background Authorization

Background jobs do not have a human user. Use explicit system principals.

Recommended actor types:

- `user`;
- `platform_admin`;
- `api_key`;
- `system`;
- `worker`;
- `migration`.

Automated audit records should include:

- actor type;
- worker/service name where available;
- tenant ID if work is tenant-owned;
- request/run ID;
- action;
- resource;
- safe metadata.

Never fabricate a human user for automated work.

## 29. Password and Credential Security

Password requirements:

- Argon2id, unique salts, configurable memory/time/parallelism parameters.
- No reversible password storage.
- Password reset tokens stored as hashes.
- Session invalidation after password reset.
- Login/reset/refresh rate limiting.
- No hashes or tokens in API responses.

Refresh tokens:

- Opaque random tokens.
- Hash at rest.
- Rotate on every refresh.
- Reuse detection revokes the session family.
- Revocation by session, user, and global account disable.

Marketplace and Telegram credentials:

- Store references to an external secret manager or encrypted database fields.
- Never store plaintext credentials in ordinary configuration columns.
- Redact secrets from logs, readiness, OpenAPI examples, audit metadata, and
  error details.

## 30. Rate Limiting and Abuse Controls

Minimum protection:

| Area | MVP control |
| --- | --- |
| Login | Per-IP and per-email throttling. |
| Password reset | Per-IP and per-email throttling; enumeration-safe response. |
| Invitation acceptance | Per-token and per-IP throttling. |
| Refresh | Per-session/user throttling and reuse detection. |
| Tenant switching | Membership lookup, optional per-user request throttling. |
| Mutations | Per-user/tenant mutation rate limits and idempotency keys. |
| Admin/platform elevation | Separate stricter throttling and audit. |

MVP can use in-process throttling plus reverse-proxy/gateway rules. Document
that in-process limiting is not sufficient for multi-instance production. Do
not add Redis in EPIC 16 unless explicitly required by deployment.

## 31. Error Model

Extend stable API error codes:

| Code | Use |
| --- | --- |
| `authentication_required` | Missing/invalid authentication. |
| `invalid_credentials` | Login failed without revealing which field failed. |
| `account_disabled` | User exists but cannot act. |
| `email_not_verified` | Verified email required. |
| `token_expired` | Access token expired. |
| `token_revoked` | Session/token revoked. |
| `tenant_not_found` | Tenant absent or hidden from caller. |
| `membership_required` | Internal service code; public response may be 404. |
| `permission_denied` | Member lacks required permission. |
| `invitation_invalid` | Invalid or malformed invitation. |
| `invitation_expired` | Expired invitation. |
| `resource_not_found` | Missing or foreign resource. |
| `ownership_conflict` | Resource belongs to a different tenant or destination. |
| `idempotency_conflict` | Key reused with different command semantics. |
| `optimistic_concurrency_conflict` | Expected version mismatch. |
| `rate_limited` | Abuse/rate limit. |

Do not expose whether an email address exists in registration/reset flows.

## 32. Correlation and Security Logging

Security events to log:

- login success/failure;
- token refresh;
- token reuse detection;
- logout;
- password reset requested/completed;
- invitation created/accepted/expired;
- membership added/removed;
- role changed;
- denied permission;
- cross-tenant access attempt;
- platform-admin elevation;
- tenant deactivated/reactivated;
- marketplace credential changed;
- Telegram destination changed;
- Scheduler tenant work failure.

Logs must not contain:

- passwords;
- access tokens;
- refresh tokens;
- invitation tokens;
- reset tokens;
- marketplace credentials;
- Telegram bot tokens;
- raw destination IDs unless explicitly allowed;
- database credentials.

## 33. OpenAPI Security

Add a seller bearer-token scheme while keeping the admin API-key scheme
separate.

OpenAPI schemes:

- `SellerBearerAuth`: bearer access token for `/api/v1/me` and
  `/api/v1/tenants/{tenant_id}` routes.
- `AdminApiKey`: existing `X-Admin-API-Key` for `/api/v1/admin`.
- Future `PlatformAdminBearerAuth`: platform-admin user routes if separated from
  seller auth.

Document that tenant context comes from the path. Examples must use fake tokens,
fake tenant IDs, and safe destination references only.

## 34. Health and Readiness

Existing liveness/readiness is sanitized and does not call Telegram. EPIC 16 can
extend readiness with safe checks:

- identity tables exist at migration head;
- signing-key configuration present;
- password hashing configuration valid;
- refresh-token secret/configuration present if used;
- secret/encryption provider configured;
- repository provider can compose tenant-aware repositories;
- Scheduler configuration can load enabled tenant integrations;
- Telegram destination configuration is syntactically valid without calling
  Telegram.

Do not call external identity providers, email providers, Telegram, or
marketplace APIs in liveness.

## 35. Testing Strategy

Authentication tests:

- valid login;
- invalid login;
- disabled user;
- unverified email policy;
- token expiry;
- token refresh;
- refresh rotation;
- revoked token;
- logout;
- reset token hashing;
- secret redaction.

Membership tests:

- one tenant;
- multiple tenants;
- removed membership;
- role change takes effect immediately;
- deactivated tenant;
- owner-only operations.

Tenant isolation tests:

- tenant A event inaccessible to tenant B;
- tenant A content inaccessible to tenant B;
- tenant A publication inaccessible to tenant B;
- tenant A audit inaccessible to tenant B;
- dashboard counts isolated;
- search isolated;
- pagination cursor tenant-bound;
- idempotency keys scoped safely.

Command tests:

- approve/reject own tenant only;
- retry/cancel own tenant only;
- ambiguous resolution own tenant only;
- role restrictions;
- stale version;
- idempotency replay;
- idempotency conflict;
- no Telegram call from admin/seller command route.

Background processing tests:

- ingestion preserves tenant ownership;
- scoring preserves tenant ownership;
- content generation preserves tenant ownership;
- publication creation preserves tenant ownership;
- delivery validates tenant destination ownership;
- restart/fresh-session persistence;
- concurrent workers do not cross tenants.

Internal admin tests:

- API key remains separate;
- platform admin can inspect an explicitly selected tenant;
- ordinary seller cannot use `/api/v1/admin`;
- elevated access is audited.

## 36. PostgreSQL Isolation Verification

Create:

```text
scripts/verify_epic16_tenant_isolation_postgres.py
```

Use an isolated PostgreSQL database only. Do not use production data.

Minimum verification checks:

1. Create two tenants.
2. Create multiple users.
3. Create memberships with different roles.
4. Authenticate users.
5. List memberships for a user.
6. Tenant A event visible to tenant A member.
7. Tenant A event hidden from tenant B member.
8. Tenant A content hidden from tenant B member.
9. Tenant A publication hidden from tenant B member.
10. Tenant dashboard counts isolated.
11. Pagination cursor cannot cross tenants.
12. Search cannot cross tenants.
13. Reviewer can approve content in own tenant.
14. Viewer approval denied.
15. Operator can retry eligible publication.
16. Reviewer retry denied.
17. Operator can resolve ambiguous publication.
18. Membership removal takes effect.
19. Role change takes effect.
20. Tenant deactivation blocks new work.
21. Background ingestion preserves tenant ownership.
22. Scoring/content/publication processing preserves tenant ownership.
23. Audit actor and tenant attribution recorded.
24. Platform-admin explicit cross-tenant access works and is audited.
25. No secret leakage in API/log-safe outputs.
26. Restart/fresh-session persistence.
27. Concurrency between conflicting tenant commands.
28. Migration/backfill verification.
29. Two tenants can store the same marketplace external ID.
30. Two tenants can store equivalent price-drop event facts without identity
    collision.

## 37. RLS Verification Plan

RLS is deferred for first implementation.

Compensating verification:

- Every seller repository call requires tenant context.
- Query SQL includes tenant predicate.
- Command lookup and mutation include tenant ownership.
- Platform-admin contracts are separate.
- Tenant-scoped unique constraints are verified from PostgreSQL catalogs.
- Cross-tenant rows cannot be read/mutated through seller services.

If RLS is later selected, add tests proving:

- tenant context is set per transaction;
- connection pool does not leak prior tenant context;
- rollback clears context;
- platform-admin bypass is explicit;
- maintenance/migration jobs work;
- application predicates remain in place.

## 38. Performance and Indexes

High-value tenant indexes:

- `(tenant_id, created_at DESC, id DESC)` for events/content/publications.
- `(tenant_id, detected_at DESC, id DESC)` for events.
- `(tenant_id, marketplace, external_id)` for offers/snapshots/events.
- `(tenant_id, canonical_product_id, occurred_at DESC)` for market events.
- `(tenant_id, scoring_status, next_retry_at, created_at, id)` for event claims.
- `(tenant_id, generation_status, next_retry_at, created_at, id)` for content
  claims.
- `(tenant_id, publication_status, scheduled_at, next_retry_at, created_at, id)`
  for publication claims.
- `(user_id, tenant_id)` and `(tenant_id, role)` for memberships.
- `(tenant_id, actor_id, created_at DESC, id DESC)` for audit.
- `(tenant_id, idempotency_key)` or `(tenant_id, actor_id, idempotency_key)` for
  command idempotency.

Avoid adding indexes for every possible filter before query plans show a need.

## 39. Implementation Breakdown

Keep EPIC 16 to four focused tasks.

### Task 1 - Tenant identity and schema foundation

- Add `User`, `Tenant`, `Membership`, and role domain contracts.
- Add auth/session domain contracts only as needed for schema.
- Add migrations for identity tables and tenant ownership columns.
- Create default legacy tenant.
- Backfill existing durable rows.
- Convert tenant-owned rows to `NOT NULL`.
- Add tenant-scoped constraints and indexes.
- Add tenant-aware repository foundations without exposing seller routes.

### Task 2 - Authentication and authorization boundary

- Implement login, refresh, logout, password reset boundary, and token handling.
- Add `AuthenticatedPrincipal`, `TenantContext`, `Permission`, and
  `AuthorizationService`.
- Add `/api/v1/me` and membership/tenant-context routes.
- Verify membership removal, role changes, token revocation, and secret
  redaction.

### Task 3 - Tenant-scope existing workflows

- Add seller-facing tenant-scoped read routes.
- Add tenant-scoped content/publication commands.
- Update ingestion/background services to carry tenant context.
- Add tenant-aware audit attribution.
- Preserve existing internal admin API behavior during transition.

### Task 4 - Final isolation verification and readiness

- Run full PostgreSQL tenant isolation verifier.
- Run Alembic lifecycle and offline SQL.
- Run full Pytest, MyPy, Ruff, and format checks.
- Update documentation and readiness assessment.
- Record remaining limitations before public seller UI.

## 40. Acceptance Criteria

EPIC 16 is complete only when:

- Canonical `Tenant` model exists.
- Users can authenticate.
- Memberships are durable.
- Roles and permissions are centralized.
- Seller APIs require tenant context.
- Every seller-owned resource is tenant-scoped.
- Ingestion preserves tenant ownership.
- Event/content/publication workflows preserve tenant ownership.
- Event identity v2 is tenant-aware for new tenant events.
- Cross-tenant reads are blocked.
- Cross-tenant mutations are blocked.
- Dashboard counts are isolated.
- Audit records include actor and tenant.
- Platform-admin access is explicit and audited.
- Legacy data migration is safe and verified.
- PostgreSQL isolation verification passes.
- No secrets are exposed.
- Existing EPIC 13-15 semantics are not silently weakened.

## 41. Recommended First Implementation Task

Start with **Task 1 - Tenant identity and schema foundation**.

It is the smallest safe first implementation task because public seller auth
cannot be correct until durable resources have tenant ownership, tenant-scoped
constraints, and a verified legacy-data backfill. Starting with routes or
frontend would create a public boundary before the database can enforce or prove
isolation.

Do not begin authentication, seller dashboard, or public seller routes before
Task 1 is complete and verified.

