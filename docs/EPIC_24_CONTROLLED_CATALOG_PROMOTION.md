# EPIC 24 - Controlled Catalog Promotion

## Status

Tasks 1 and 2 are complete: the deterministic promotion manifest and read-only
target preflight are implemented. Import and deployment rollout have not started.

## Purpose

Move only a bounded, human-reviewed catalog toward a target environment without
copying unresolved marketplace state or weakening the existing review boundary.
The first step is an immutable export description built from one consistent
tenant repository scope.

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

## Safety Boundary

This task is read-only. It does not create target tenants, import offers, copy
credentials, rewrite canonical links, call marketplaces, or mutate source
repositories. Source URLs are evidence for a later target preflight; they are
not trusted as proof that an outbound listing is still available.

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

## Next Task

Implement an atomic importer that accepts only an unchanged `ready` preflight
plan plus explicit operator approval. It must re-check the digest and target
state inside the write transaction, abort on drift, write only proposed actions,
and persist auditable import identity. Import remains separate from export and
preflight.
