# EPIC 24 - Controlled Catalog Promotion

## Status

Task 1, the deterministic read-only promotion manifest, is complete. Target
preflight, import, and deployment rollout have not started.

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

## Next Task

Implement a guarded target preflight and import plan that consumes this exact
schema, re-fetches or validates source identities in the target environment,
reports conflicts without partial writes, and requires an explicit operator
approval before any target mutation. Import must remain separate from export.
