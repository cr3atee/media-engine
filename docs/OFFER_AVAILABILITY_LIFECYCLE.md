# Marketplace Offer Availability Lifecycle

Date: 2026-10-27.

## Status

The durable availability foundation is implemented at PostgreSQL revision
`0020_offer_source_observations`. Runtime integrations record which source saw
an offer and when. Public repository reads hide an offer only when every known
source observation is inactive.

Automatic missing-offer reconciliation is intentionally disabled for current
runtime factories. It may be enabled for an integration only when its ingestion
result proves that the observed snapshot is complete. A successful HTTP request
or a non-empty first page is not proof of completeness.

## Problem

Previously, `OfferRepository.save()` updated offers that reappeared but had no
representation for offers that disappeared. A removed listing could therefore
remain indefinitely in public product and comparison reads.

The lifecycle must also support several integrations observing one marketplace
offer. One source losing the offer must not hide it while another source still
observes it.

## Persistence Model

`offer_source_observations` is keyed by tenant, marketplace integration, and
persisted offer. Each row retains first/last observation time, ordered state
time, active state, and unavailability time. Composite foreign keys enforce
tenant ownership for both the integration and offer.

An offer remains visible when it has no source metadata (legacy compatibility)
or at least one active source observation. Revision `0020` backfills a legacy
offer only when exactly one integration exists for the same tenant and
marketplace. Ambiguous rows remain visible and are not assigned to an invented
source.

## Runtime Rules

- Every integration-backed run upserts observations for returned stable offer
  identities.
- A later observation reactivates an unavailable offer.
- An older delayed run cannot overwrite newer state.
- Reconciliation and downstream snapshot/event processing share one repository
  transaction and roll back together.
- An empty result never mass-deactivates offers.
- Missing identities are reconciled only when the runner explicitly declares a
  complete source snapshot.
- Public products, offers, comparisons, and review queues consume active offers
  through the existing repository contract; no UI-specific filtering was added.

## Verification

Isolated PostgreSQL `17.10` verification passed `16/16` checks for two-source
visibility, source-scoped deactivation, empty-result protection, reactivation,
out-of-order execution, rollback, durable inactive evidence, fresh-engine
persistence, and public-read filtering.

Alembic clean upgrade, `current`, `check`, downgrade to
`0019_diagnostic_incidents`, re-upgrade to head, and offline SQL generation pass.
Full project verification reports `613 passed, 60 skipped`; MyPy reports `502`
source files without errors; focused Ruff and Ruff format pass.

## Current Catalog Link Audit

The six outbound links in the isolated local review catalog were checked on
2026-10-27:

| Marketplace | External ID | Result |
| --- | --- | --- |
| FunPay | `25007196` | HTTP 200 |
| FunPay | `80145738` | HTTP 404 |
| GGSEL | `102083633` | HTTP 200 |
| GGSEL | `102169338` | HTTP 200 |
| Playerok | `1f18a730-4e8b-6df0-3e3f-036291433084` | HTTP 200 |
| Playerok | `1f1cc4e5-23b9-6d30-58cc-63af659be6dd` | HTTP 200 |

This local review database contains six manually seeded offers and no
`marketplace_integrations`, so revision `0020` cannot safely invent observation
ownership for them. FunPay `80145738` remains an explicit seed-catalog blocker.
It must be corrected through an audited operator workflow, not direct SQL or a
fabricated replacement URL.

## Remaining Work

1. Make each collector return explicit pagination/completeness evidence.
2. Traverse Playerok cursor pagination; the current verified path reads the
   first `20` items while the response can report a larger total.
3. Enable `source_snapshot_complete` only for adapters whose complete-source
   behavior is verified.
4. Add an authorized, auditable operator command to retire an unavailable
   manually seeded offer without deleting price/event history.
5. Re-run the outbound-link audit immediately before public release.

Until those items are complete, offer availability is persistence-ready but is
not a passed unattended-production release gate.
