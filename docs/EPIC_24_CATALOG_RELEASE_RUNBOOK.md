# EPIC 24 - Catalog Release Runbook

## Purpose

Promote one bounded, human-reviewed catalog manifest from a source PostgreSQL
environment into a distinct target PostgreSQL environment. The release command
reuses the existing manifest, preflight, atomic importer, immutable admin audit,
and repository-backed public reads. It does not copy offers, credentials,
marketplace integrations, review decisions, or secrets.

## Preconditions

- Source and target databases are distinct and both are at the repository
  Alembic head.
- The source tenant contains only the reviewed catalog intended for promotion.
- The target tenant already exists and has fresh marketplace offers with the
  identities and source evidence referenced by the manifest.
- A target database backup has been created and independently verified.
- Target metrics and alert routing are ready and have been independently
  verified.
- The operator has a stable actor ID, request ID, idempotency key, and human
  release reason.

The CLI confirmation strings are attestations. It cannot create or validate an
external backup or monitoring stack by itself.

## Production Compose Boundary

`docker-compose.production.yml` exposes the release command only through the
dedicated `catalog-release` profile. The service is a one-shot, non-restarting
operator command with no ports or persistent volumes. It is never started with
the API or worker services. Preview remains the default, while apply requires
both the `--apply` argument and every independent environment guard described
below.

Copy `docker/production.env.example` to an operator-controlled file outside
source control and populate only that copy. The committed example deliberately
contains no URLs, tenant IDs, approval phrases, or operator identities. Normal
API and worker deployment does not require catalog-release variables.

## Preview

Set connection URLs and tenant IDs in the process environment. Do not put
database passwords in command-line arguments.

```powershell
$env:MEDIAENGINE_CATALOG_PROMOTION_SOURCE_DATABASE_URL = '<source asyncpg URL>'
$env:MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE_URL = '<target asyncpg URL>'
$env:MEDIAENGINE_CATALOG_PROMOTION_SOURCE_TENANT_ID = '<source tenant UUID>'
$env:MEDIAENGINE_CATALOG_PROMOTION_TARGET_TENANT_ID = '<target tenant UUID>'
.\.venv\Scripts\python.exe scripts\run_catalog_promotion_release.py
```

Preview mode is the default and performs no writes. Review:

- source and target database names;
- source and target tenant UUIDs;
- manifest digest;
- product and link counts;
- preflight status and required mutation count;
- every sanitized blocking issue.

A blocked preview exits without an import. Correct target source evidence and
run preview again; do not bypass the issue or alter the manifest digest.

The equivalent production-image preview is:

```powershell
docker compose `
  --env-file C:\secure\mediaengine-catalog-release.env `
  -f docker-compose.production.yml `
  --profile catalog-release run --rm catalog-release
```

This explicit profile does not start API, worker, migrations, or metrics.

## Apply

After independently verifying backup and monitoring readiness, set the exact
values printed by the current preview:

```powershell
$env:MEDIAENGINE_CATALOG_PROMOTION_APPLY = '1'
$env:MEDIAENGINE_CATALOG_PROMOTION_TARGET_DATABASE = '<printed target database>'
$env:MEDIAENGINE_CATALOG_PROMOTION_BACKUP_CONFIRMATION = '<printed backup phrase>'
$env:MEDIAENGINE_CATALOG_PROMOTION_MONITORING_CONFIRMATION = '<printed monitoring phrase>'
$env:MEDIAENGINE_CATALOG_PROMOTION_APPROVAL_PHRASE = '<printed approval phrase>'
$env:MEDIAENGINE_CATALOG_PROMOTION_ACTOR_ID = '<operator identity>'
$env:MEDIAENGINE_CATALOG_PROMOTION_REQUEST_ID = '<release request identity>'
$env:MEDIAENGINE_CATALOG_PROMOTION_IDEMPOTENCY_KEY = '<stable retry key>'
$env:MEDIAENGINE_CATALOG_PROMOTION_REASON = '<reviewed release reason>'
.\.venv\Scripts\python.exe scripts\run_catalog_promotion_release.py --apply
```

With the reviewed values stored in the external operator environment file, run
the same guarded apply through the immutable production image:

```powershell
docker compose `
  --env-file C:\secure\mediaengine-catalog-release.env `
  -f docker-compose.production.yml `
  --profile catalog-release run --rm catalog-release --apply
```

Do not use `up` for this profile. Do not place connection URLs or confirmation
phrases in shell history as command-line arguments.

All guards must match the newly recomputed preview. A stale digest, target
database mismatch, missing attestation, blocked preflight, or changed target
state fails closed before import. Product creation, offer linking, and immutable
audit append commit in one target transaction.

## Post-Commit Verification

The command succeeds only after it verifies:

- target preflight converged to `no_changes`;
- every manifest product is tenant-owned in the target;
- every manifest offer is linked to the expected product;
- the immutable catalog-promotion audit action is present;
- every promoted product is visible through repository-backed public reads.

If import commits but a postcondition fails, stop the rollout and investigate.
Do not create a new idempotency key to force another import.

## Retry And Recovery

Reuse the original idempotency key, actor identity, reason, and current exact
approval phrase after an ambiguous client or process failure. A fresh process
recognizes the durable action and verifies the existing target state without
creating duplicate products, links, or audit rows. A different key cannot claim
an already completed `no_changes` target as its own release.

## Output And Secrets

The command prints database names, tenant UUIDs, counts, digest, status, and
sanitized issue codes. It does not print connection URLs or database passwords.
Database and unexpected SQL errors are reduced to sanitized failure codes.

## Verification Evidence

On 2026-11-07, two clean isolated PostgreSQL `17.10` databases were migrated to
`0025_catalog_promotion_audit`. The production-shaped verifier passed `12/12`
checks covering mutation-free preview, incomplete-guard rejection, guarded
apply, source immutability, target convergence, immutable audit, public reads,
fresh-engine replay, and duplicate prevention. Alembic `current` and `check`
passed independently for source and target, and offline SQL generation passed.
The follow-up production Compose integration verifier passed `31/31`, including
normal deployment interpolation, dedicated-profile isolation, one-shot
execution, no exposed ports/storage, and empty committed operator values.
Focused tests passed `20`; full Pytest passed `749` with `64` guarded skips;
Ruff, format, and strict MyPy across `553` files passed. Temporary databases,
container, and volume were removed. No production state was used.

## Remaining Operator Action

No production rollout has been performed. Before one can occur, an operator
must provide the intended source and target database URLs and tenant UUIDs,
verify the real backup and monitoring stack, review the fresh preview, and
approve that exact digest and target.
