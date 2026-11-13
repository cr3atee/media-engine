# EPIC 25 - Three Product MVP

## Goal

Release the smallest useful public catalog: three subscription services and
exactly three canonical products. Real-source verification, human review,
target promotion, and browser acceptance remain as simple as possible.

## Launch Assortment

| Hub | Canonical product | Duration | Section |
| --- | --- | ---: | --- |
| ExitLag | ExitLag - 1 month | 1 month | `subscriptions` |
| Duolingo | Duolingo Super - 1 month | 1 month | `subscriptions` |
| Spotify | Spotify Premium Individual - 1 month | 1 month | `subscriptions` |

Three-, six-, and twelve-month plans are explicitly deferred. They must not
appear in the first release merely to fill the catalog.

## Data Rules

- A canonical product may reach the public catalog only after at least one real
  marketplace offer has been collected and explicitly reviewed.
- Prices, discounts, seller identity, availability, marketplace logos, and
  outbound URLs must come from persisted source evidence. No placeholder offer
  or invented commercial value is allowed.
- Source-category rules classify each service hub and the stable
  `subscriptions` section. The one-month duration remains part of canonical
  product identity, not a guessed marketplace category.
- The production target receives only the reviewed three-product manifest
  through the existing EPIC 24 preview, preflight, atomic import, and release
  gate.

## Delivery Sequence

1. Expose ExitLag, Duolingo, and Spotify in the shared catalog taxonomy.
2. Collect one current real one-month offer for each service from available
   integrations.
3. Review names, durations, URLs, prices, and source evidence; create or link
   exactly three canonical products.
4. Produce a three-product promotion manifest and require a clean target
   preflight.
5. Apply the guarded target release, then verify repository-backed public reads.
6. Run desktop/mobile browser acceptance for hubs, product cards, comparisons,
   outbound links, empty/error states, and the three-card upper bound.

## Acceptance Criteria

- Public navigation contains the ExitLag, Duolingo, and Spotify hubs.
- The launch tenant exposes exactly three product cards, one per hub.
- Every card has at least one active real offer with marketplace, price,
  currency, and outbound URL evidence.
- No longer-duration card, Minecraft launch card, placeholder offer, or
  unreviewed source appears in the launch catalog.
- Re-running ingestion or the release command creates no duplicate products,
  links, or audit records.
- Full quality, PostgreSQL release, and browser gates pass on the release SHA.

## Current Status

Task 1 is implemented in the working branch: the three service hubs are part of
the shared taxonomy and explicit ExitLag/Duolingo/Spotify titles resolve to the
subscription category. Existing Minecraft taxonomy remains available for saved
rules but is not part of this launch assortment. Real offer collection and the
three human review decisions remain outstanding.
