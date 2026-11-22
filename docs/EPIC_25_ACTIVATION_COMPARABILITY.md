# EPIC 25 - Activation Compatibility

## Product Decision

Confirmed by the user on 2026-11-22: include all regions, but compare prices only
within the same activation conditions. No implicit Russia-only restriction is
introduced. A low source price is a sourcing lead, not proof of resale profit.

## Implemented Boundary

`ParsedOffer.activation_conditions` is optional. `None` means unknown, not
worldwide, no VPN, reusable account or unlimited activation time.
`ActivationConditions` is an immutable, versioned value containing:

- Explicit country codes, or an explicit worldwide `*` scope with exclusions.
- Device and plan codes.
- Subscription period, such as `P1M` or `P30D`. These are not silently equated.
- Delivery method: key, activation on own account, or a new account.
- Required account history: new only, existing only, or any.
- Whether VPN is required.
- Activation window in seconds; explicit `None` means no deadline.

All constructor fields must be supplied. Country-code validation checks syntax,
not whether a seller's assertion is true. Regions are uppercased, deduplicated
and sorted; equality is conservative. A subset of countries is not considered
the same scope as a superset, and worldwide-with-exclusions is not worldwide.
Unknown source facts must not be filled with permissive defaults.

The existing grouping service partitions a canonical product by the complete
condition value. Existing price selection and difference calculation reject a
multi-offer comparison with unknown or conflicting conditions. Canonical identity
alone does not prove activation compatibility.

New result statuses are `activation_conditions_unknown` and
`activation_conditions_mismatch`; no best offer or price differences are returned
for these states. Public repository-backed reads use the same guard and the
existing interface displays the reason. A single offer retains its source price
without claiming cross-offer savings.

The public API still returns one result per canonical product. If that result
contains several different condition profiles, it reports a mismatch and leaves
offers individually visible. A public variant picker and per-variant API response
are not implemented by this step. The processing pipeline can already produce
separate grouped results for explicit profiles.

The FunPay discovery verifier explicitly opts into price-only lead selection;
it neither confirms equivalence nor calculates profit. The difference service
independently rejects incompatible terms even if supplied such a selection.

## Persistence And Migration

Revision `0027_offer_activation_conditions` adds a nullable JSONB column to
`offers`. Existing rows remain SQL NULL; there is no invented legacy backfill.
Memory and PostgreSQL repositories preserve supplied condition values. An update
without current condition evidence clears an old profile instead of silently
trusting stale terms. Strict decoding rejects partial/unknown JSON versions.

Repository interfaces, tenant ownership, canonical IDs and human review decisions
are unchanged. No source connector was taught to guess complete profiles from
marketing text. Existing marketplace rows therefore still have unknown conditions.

## Actual Verification

- Full Pytest: `866 passed, 65 skipped`; existing guarded skips and the existing
  TestClient warning are not represented as passed or fixed.
- Strict MyPy: `571` files. Changed-file Ruff/format and JavaScript syntax pass.
- Browser: `127` existing catalog checks passed, including mobile, keyboard,
  native 200% zoom and recovery; no runtime/CSP errors and only application GETs.
- PostgreSQL `17.10`: a dedicated `epic25_activation_20261122_1` test database,
  never either user-facing local database, exercised synthetic fixtures.
- The opt-in `scripts/verify_activation_conditions_postgres.py` passed all `9`
  checks on repeated separate-process runs: fresh-engine JSONB reads, idempotent
  upserts, tenant isolation, minimum price, Decimal difference, rollback, region
  mismatch, clearing stale conditions and unknown-condition protection.
- Clean migrations through `0026`, insertion of a synthetic legacy row, upgrade
  to `0027`, current/check, downgrade/upgrade and offline upgrade SQL passed. The
  old row retained its identity/price and unknown conditions.
- Before migrating the two existing local databases, readable custom-format
  backups were saved outside Git. Backup restore is not claimed for these new
  archives. Both databases then passed upgrade/current/check at `0027`.
- Old offer payloads excluding the new nullable field, canonical products and
  immutable review decisions retained their exact checksums in both local bases.
- Both servers were restarted without reseeding, using their previous database
  and session-signing settings. Public API still has exactly three products and
  prices `599`, `50`, `250 RUB`; source review remains `4 offers / 3 links /
  1 proposal / 3 decisions`.
- Existing read-only post-review verification passed `55/55`, including fresh
  engine public reads. No new FunPay offer, link or review decision was created.

Run the PostgreSQL verifier only after applying migrations to a disposable
loopback database named `epic25_activation_*`, supplied via
`ACTIVATION_TEST_DATABASE_URL`. Missing configuration exits nonzero, not a
successful skip. Production databases are rejected.
The existing PostgreSQL CI job also provisions a separate
`epic25_activation_ci` database, migrates it and runs this verifier without skip.

## Remaining Work

Structured human review entry is now implemented and verified in
[activation review](EPIC_25_ACTIVATION_REVIEW.md), including condition-only CAS,
immutable audit, tenant permissions and browser confirmation/retry. Migration
`0028` follows this document's original `0027` foundation; current checks are
recorded in that review document. No real terms were auto-confirmed.

Complete source-evidence collection before enabling cross-offer comparisons
for the subscription assortment. This does not provide a free-text region
recognizer, automatic complete profiles, condition-aware promotion manifests,
a variant-filtering interface, resale
permission checks or a margin calculator. Historical snapshot/event identities
have not been redesigned to track changes in activation conditions; do not claim
condition-aware historical analytics. No AI, Telegram, scheduler or purchasing
automation was added.
