# Marketplace Offer Availability Lifecycle

Date: 2026-10-29.

## Status

The durable source-observation foundation is implemented at PostgreSQL revision
`0020_offer_source_observations`. Revision `0021_offer_manual_availability`
adds an independent operator-controlled `active`/`retired` lifecycle with
optimistic versions and immutable admin audit records. Public repository reads
require both manual availability and at least one active known source.

Automatic missing-offer reconciliation is controlled by evidence from each
individual ingestion result. GGSEL, Playerok, and FunPay report source count,
parsed count, an optional declared total, a completeness decision, and its
reason. A successful HTTP request or a non-empty first page is never treated as
proof of completeness.

The 2026-10-29 live category check verifies GGSEL `110/110` through the current
public `/buybox/goods` pagination contract and FunPay `1442/1442` through its
closed unpaginated showcase. Both adapters can therefore enable
integration-scoped reconciliation for those complete responses. Playerok now
traverses bounded GraphQL cursors and verifies the final cursor, `totalCount`,
parser coverage, and unique identities before returning complete evidence. The
current unauthenticated live check was blocked by Playerok access protection,
so no live completeness claim is made and reconciliation remains fail-closed
until a guarded authorized-session run succeeds on the target VDS.

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
pass. After complete-source traversal integration, full project verification
reports `660 passed, 60 skipped`; MyPy reports `492` source files without
errors; focused Ruff and Ruff format pass.

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
ownership for them. On 2026-10-29, an authenticated reviewer retired FunPay
`80145738` through the revision `0021` API with required evidence, expected
version, and idempotency key. The replay returned the same action, ordinary
reads now hide the link, and the offer, canonical decision, and history remain
stored. No direct SQL or fabricated replacement URL was used.

A repeat automated GET audit on 2026-10-28 returned HTTP 200 for both GGSEL
offers and FunPay `25007196`, HTTP 404 again for FunPay `80145738`, and HTTP 403
for both Playerok URLs from the non-browser client. The prior interactive audit
had opened both Playerok pages successfully, so those protected URLs require a
manual browser check immediately before release; they are not reclassified as
missing from the automated 403 alone. No offer record was mutated by the audit.

The 2026-10-29 post-review audit returned HTTP 200 for FunPay `25007196`, HTTP
404 for the already identified FunPay `80145738`, HTTP 401 for both GGSEL URLs,
and HTTP 403 for both Playerok URLs. Only the repeated unambiguous 404 was used
for retirement. The protected GGSEL and Playerok responses remain manual
browser checks rather than false missing-offer evidence. Read-only PostgreSQL
verification then passed `45/45` across decision integrity, active visibility,
public comparison truth, retired-link exclusion, and fresh-engine persistence.

## Remaining Work

1. Run the guarded Playerok session verifier on the target VDS and prove one
   complete final-cursor traversal against `totalCount` before enabling
   reconciliation for that deployment.
2. Keep the GGSEL pagination and FunPay structural contracts under
   saved-response and live drift verification; any pagination, truncated
   document, malformed identity, or parser/source mismatch must fail closed.
3. Re-run the outbound-link audit immediately before public release and repeat
   the authorized retirement only if the same stale row exists in the target
   deployment.

GGSEL and FunPay source reconciliation are runtime-ready under their verified
contracts. Cross-marketplace offer availability remains an incomplete
unattended-production release gate until Playerok passes equivalent guarded
target-environment evidence.
