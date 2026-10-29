# Marketplace Offer Availability Lifecycle

Date: 2026-10-29.

## Status

The durable source-observation foundation is implemented at PostgreSQL revision
`0020_offer_source_observations`. Revision `0021_offer_manual_availability`
adds an independent operator-controlled `active`/`retired` lifecycle with
optimistic versions and immutable admin audit records. Public repository reads
require both manual availability and at least one active known source.

Automatic missing-offer reconciliation is now controlled by evidence from each
individual ingestion result. GGSEL and FunPay extractors report source count,
parsed count, an optional declared total, a completeness decision, and its
reason. A successful HTTP request or a non-empty first page is never treated as
proof of completeness.

The 2026-10-29 live category check reports GGSEL `60/110` and Playerok `20/194`,
so both are partial and cannot deactivate missing offers. FunPay reports
`1406/1406`; its closed document contains exactly one unpaginated showcase and
every unique source offer identity is represented by an extracted offer. The
FunPay runtime therefore enables integration-scoped reconciliation for that
response. Playerok runtime remains fail-closed until its already bounded cursor
traversal returns the same explicit evidence contract.

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
- Missing identities are reconciled only when the ingestion result carries
  explicit complete-source evidence. An explicit incomplete result overrides
  the legacy runner flag.
- Public products, offers, comparisons, and review queues consume active offers
  through the existing repository contract; no UI-specific filtering was added.
- An authorized catalog reviewer may retire or restore an offer through the
  seller API. Every command requires a reason, expected version, and idempotency
  key; the state transition and immutable admin action commit atomically.
- Source sightings never override a manual retirement. Restoration is another
  explicit audited command and still does not override inactive source evidence.
- Retirement preserves the offer, canonical link, snapshots, events, and audit
  history; it only removes the offer from ordinary active reads.

## Operator UI

The authenticated Market Terminal cabinet now exposes a tenant-scoped
`Управление объявлением` section. A catalog reviewer selects the marketplace,
enters the stable external ID, reads the current state and optimistic version,
provides a required reason, and confirms either retirement or restoration.

The browser never deletes an offer and does not persist protected lifecycle
state in web storage. A network or server failure retains the same idempotency
key for an explicit retry; a definitive client error clears stale details. A
tenant switch, permission loss, account disablement, or logout immediately
purges the panel state and any open confirmation.

## Verification

Isolated PostgreSQL `17` verification passed `30/30` checks for two-source
visibility, source-scoped deactivation, empty-result protection, reactivation,
out-of-order execution, rollback, durable inactive evidence, manual retirement,
idempotent replay, tenant isolation, concurrent restoration, atomic audit
rollback, fresh-engine persistence, and public-read filtering.

Alembic clean upgrade through `0020`, legacy-row backfill into `0021`, `current`,
`check`, downgrade to `0020`, re-upgrade to head, and offline SQL generation
pass. After source-evidence integration, full project verification reports `645
passed, 60 skipped`; MyPy reports `491` source files without errors; focused
Ruff and Ruff format pass.

The real cabinet browser verifier passes `72` checks with isolated API fixtures,
including the active-to-retired operator flow, required evidence, confirmation
focus, a 503 followed by an explicit retry with the same idempotency key,
retired-to-active restoration with a new command key, responsive widths, native
200% zoom and reduced motion. It performs no database mutation and therefore
does not claim that a known stale production or local tenant row has been
retired.

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
The required authorized API workflow now exists, but that specific row has not
been claimed as corrected: an authenticated reviewer must execute the retire
command against the owning tenant database. Direct SQL and fabricated
replacement URLs remain forbidden.

A repeat automated GET audit on 2026-10-28 returned HTTP 200 for both GGSEL
offers and FunPay `25007196`, HTTP 404 again for FunPay `80145738`, and HTTP 403
for both Playerok URLs from the non-browser client. The prior interactive audit
had opened both Playerok pages successfully, so those protected URLs require a
manual browser check immediately before release; they are not reclassified as
missing from the automated 403 alone. No offer record was mutated by the audit.

## Remaining Work

1. Traverse all GGSEL category pages through a verified public contract; the
   current HTML embeds only the first `60` of `110` products.
2. Add the explicit evidence result to Playerok runtime ingestion and verify
   that the merged bounded cursor result matches `totalCount` before enabling
   reconciliation.
3. Keep the FunPay structural contract under saved-response and live drift
   verification; any pagination, truncated document, malformed identity, or
   parser/source mismatch must fail closed.
4. Use the authenticated cabinet lifecycle panel to retire FunPay `80145738` in
   the owning tenant database and retain its reason and immutable action ID as
   release evidence.
5. Re-run the outbound-link audit immediately before public release.

FunPay source reconciliation is runtime-ready under the verified contract.
Cross-marketplace offer availability remains an incomplete unattended-production
release gate until GGSEL and Playerok provide equivalent evidence.
