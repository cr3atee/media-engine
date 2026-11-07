# EPIC 24 - Controlled Catalog Promotion

## Status

Tasks 1 through 4 are complete: the deterministic promotion manifest, read-only
target preflight, guarded atomic importer, and two-phase target release gate are
implemented. Production target rollout has not been performed.

## Purpose

Move only a bounded, human-reviewed catalog toward a target environment without
copying unresolved marketplace state or weakening the existing review boundary.
The handoff starts with an immutable export description built from one
consistent tenant repository scope.

## Manifest Contract

`CatalogPromotionManifestService` exports:

- canonical products referenced by active reviewed links;
- active marketplace identity as `marketplace + external_id`;
- the current source title, URL, category evidence, and optional catalog rule
  classification;
- the immutable confirmation decision ID, fingerprint, timestamp, and reason;
- source-state counts for audit and reconciliation;
- a deterministic SHA-256 digest over canonical JSON payload data.

The digest detects accidental or unreviewed payload changes. It is an integrity
checksum, not an authenticity signature.

## Fail-Closed Rules

Manifest generation fails when:

- there are no active reviewed links;
- an active canonical link lacks an immutable confirmed decision;
- the referenced canonical product is unavailable;
- marketplace identity, external ID, source title, or source URL is absent;
- a promoted canonical product has no launch category.

Rejected pairs, unresolved offers, inactive source observations, and manually
retired offers are never promoted. A prior confirmed decision for a retired
offer remains counted as excluded audit evidence.

## Manifest Safety Boundary

Manifest generation and target preflight are read-only. They do not create
target tenants, import offers, copy credentials, rewrite canonical links, call
marketplaces, or mutate source repositories. Source URLs are target evidence;
they are not trusted as proof that an outbound listing is still available.

## Target Preflight

`CatalogPromotionPreflightService` validates the manifest digest and inspects one
explicit target tenant without writing. It returns `ready`, `no_changes`, or
`blocked`, together with deterministic product/link actions and sanitized issue
codes. It blocks missing or inactive tenants, product ownership/definition
conflicts, absent target source evidence, source fingerprint drift, retired
offers, and links already assigned to another product.

A fresh target offer must exist before a link can be proposed. Price changes do
not invalidate identity evidence because prices are intentionally outside the
promotion identity fingerprint. In a shared database, a canonical UUID already
owned by the source tenant is reported as a blocking ownership conflict; it is
never silently reassigned.

## Atomic Import

`CatalogPromotionImportService` accepts only the exact manifest and unchanged
`ready` preflight reviewed by the operator. The command requires a target- and
digest-bound approval phrase, tenant-scoped command context, idempotency key,
and human reason. Inside one repository transaction it serializes imports for
the target manifest, recomputes preflight, creates only proposed products,
links only proposed target offers through the existing linking service, and
appends one immutable `catalog_promotion` admin action.

Digest changes, target drift, tenant mismatch, non-ready plans, conflicting
idempotency reuse, and concurrent duplicate imports fail closed. A failed audit
append rolls back product and link writes. An accepted command can be replayed
after restart without creating duplicate records. The importer never creates
target offers, copies credentials, calls a marketplace, or changes unresolved
review decisions.

## Verification

On 2026-11-04:

- focused Pytest passed `13` tests;
- focused Ruff and Ruff format passed;
- strict MyPy passed for all four touched Python files;
- a clean isolated PostgreSQL 17 database migrated to
  `0024_offer_catalog_fields`;
- the guarded PostgreSQL verifier passed `14/14` checks;
- memory/PostgreSQL output parity, deterministic rerun, tenant isolation,
  retired/rejected exclusion, fail-closed behavior, no repository mutation,
  and fresh-engine persistence passed;
- Alembic `current`, `check`, and offline upgrade SQL passed;
- the temporary PostgreSQL container and volume were removed.

No production database or target tenant was used.

On 2026-11-05, Task 2 focused verification passed `19` tests with clean Ruff,
Ruff format, and strict MyPy. The isolated PostgreSQL 17 verifier passed `20/20`
checks, including memory/PostgreSQL plan parity, deterministic rerun, target
read-only behavior, same-database ownership conflict detection, and fresh-engine
persistence. Full Pytest passed `733` tests with `64` guarded skips, and MyPy
passed across `520` source files. Temporary Docker resources were removed.

On 2026-11-05, Task 3 added five focused importer tests and passed the combined
`19`-test importer/preflight/admin suite. A clean isolated PostgreSQL `17.10`
database migrated to `0025_catalog_promotion_audit`; the verifier passed `29/29`
checks covering atomic apply, exact durable replay, tenant ownership, immutable
audit, forced rollback, concurrent-worker serialization, conflict detection,
and fresh-engine persistence. Alembic `current`, `check`, downgrade/upgrade,
and offline SQL passed. Focused Ruff and format passed, full Pytest passed `738`
tests with `64` guarded skips, and strict MyPy passed across `548` source files.
No production database or tenant was used.

On 2026-11-07, Task 4 added the cross-environment release service and guarded
operator CLI documented in `EPIC_24_CATALOG_RELEASE_RUNBOOK.md`. Two clean
PostgreSQL `17.10` databases at `0025_catalog_promotion_audit` passed `12/12`
release checks: mutation-free preview, missing-guard rejection, atomic apply,
source immutability, target convergence, public-read visibility, immutable
audit, and fresh-engine replay without duplicates. Source and target Alembic
`current/check` plus offline SQL passed. Focused tests passed `20`, full Pytest
passed `747` with `64` guarded skips, and strict MyPy passed across `553` files.
No production rollout was performed.

## Next Task

Commission the intended target environment: provide managed database access and
tenant identities, verify the real backup and monitoring stack, refresh target
marketplace evidence, and review the release gate's fresh preview. Invoke apply
only for that exact digest and target. Do not treat isolated verification as a
production rollout.
