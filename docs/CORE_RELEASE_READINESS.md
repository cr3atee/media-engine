# MediaEngine Core Release Readiness

## Status

The MediaEngine backend core is a verified release candidate.

This status applies to the reusable backend core and its current embedded
integration shell. It does not claim that the public Market Terminal product is
ready for an unattended production launch.

## Repeatable Gate

The release coordinator is:

```powershell
$env:MEDIAENGINE_CORE_RELEASE_DATABASE_URL = `
  "postgresql+asyncpg://...@127.0.0.1/.../epic19_history_release_verify"
python scripts/verify_core_release_readiness.py
```

The full command accepts only local PostgreSQL databases named with the
`epic19_history_release_` prefix. Every PostgreSQL verifier may recreate the
database's `public` schema, so the URL must never target shared or production
data.

An explicit offline subset is also available:

```powershell
python scripts/verify_core_release_readiness.py --offline
```

The coordinator delegates to existing verifiers. It contains no marketplace,
matching, comparison, persistence, Scheduler, or catalog business logic.

## Verified Evidence

The final gate passed `4/4` stages on 2026-10-06:

1. Saved marketplace payload contracts passed with GGSEL `60/60/60`, Playerok
   `20/20/20`, and FunPay `1/1/1` raw/parsed/snapshot-ready offers.
2. Repository-backed public UI readiness passed `42` checks.
3. PostgreSQL public UI readiness passed `63/63` checks, including persisted
   offers, snapshots, comparisons, marketplace filters, strict terminal CSP,
   and fresh-engine reads.
4. Durable marketplace polling history passed `25/25` checks, including tenant
   isolation, safe diagnostics, atomic rollback, schema constraints, bounded
   ordering, and fresh-engine persistence.

The full run used an isolated local PostgreSQL `17.10` database named
`epic19_history_release_verify`. It made no live marketplace, Telegram, or AI
request. The disposable container was removed after verification.

## Migration And Quality Results

- Alembic current: `0017_marketplace_polling_runs (head)`.
- Alembic check: no new upgrade operations detected.
- Downgrade to `0016_canonical_offer_decisions`: passed.
- Re-upgrade to head: passed.
- Offline `upgrade head --sql`: passed.
- Focused release tests: `13 passed`.
- Full Pytest: `477 passed, 58 skipped`.
- Full MyPy: `424` source files, no issues.
- Focused Ruff: passed.
- Focused Ruff format check: passed.
- One pre-existing `StarletteDeprecationWarning` from FastAPI's TestClient
  remains unrelated to this release gate.

## Safety Boundaries

- Saved marketplace evidence is real captured source data, not fabricated
  successful responses.
- The release gate does not fetch live marketplace data; guarded live polling
  has its own verifier and previous recorded evidence.
- Each marketplace example remains a separate canonical product unless a human
  confirms exact product identity.
- No similarity threshold, alias, canonical link, or review decision is created
  by the release gate.
- No live Telegram message is sent.
- No production AI provider is called.
- No production database or credential is accepted by the gate.

## Release Boundary

Ready as core:

- tenant-aware memory and PostgreSQL persistence;
- marketplace ingestion for GGSEL, Playerok, and FunPay;
- snapshots, price-change events, scoring, content attempts, and publication
  orchestration;
- Scheduler execution, leases, failure isolation, and durable polling history;
- authenticated seller/admin workflows;
- deterministic matching, human review commands, and comparator components;
- public read API and embedded Market Terminal integration shell.

Still required before an unattended public launch:

- human-approved canonical catalog and exact cross-marketplace offer links;
- production metrics export, alert routing, and polling-history retention;
- deployment configuration and secret retrieval for authenticated sources;
- a decision on production frontend ownership and category-data exposure;
- optional guarded live Telegram test-chat verification if Telegram delivery is
  part of the launch scope.

These remaining items are launch and catalog work, not reasons to redesign the
verified backend core.
