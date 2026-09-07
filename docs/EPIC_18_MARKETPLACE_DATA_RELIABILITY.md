# EPIC 18 Marketplace Data Reliability

## Goal

Finish the marketplace data side of the MediaEngine core by proving that every
supported marketplace can provide real, usable offer data for the shared
repository-backed runtime.

This EPIC is about core reliability, not new product features.

## Core Definition

The MediaEngine core can be considered complete when marketplace ingestion can
reliably produce tenant-owned `ParsedOffer` objects with enough universal data
to feed:

- repository-backed offer persistence;
- price snapshot creation;
- price-change detection;
- durable market-event creation;
- scoring;
- content generation;
- Scheduler orchestration.

## Current Marketplace Status

### GGSEL

Status: ready from saved response.

Current implementation can extract real GGSEL products from the saved
`tmp/ggsel_response.html` payload. The extractor produces typed raw marketplace
offers, and the shared normalizer can produce `ParsedOffer` objects with price
and currency when those fields are present in the embedded payload. Relative
GGSEL slugs are normalized into absolute catalog URLs before entering
`ParsedOffer`.

Remaining gaps:

- live network verification is environment-dependent;
- the older `GGSelParser` path still overlaps with the modular
  fetcher/extractor/normalizer path;
- payload drift detection is not automated yet.

### Playerok

Status: ready from live GraphQL response.

The project has `PlayerokFetcher`, `PlayerokExtractor`, `PlayerokNormalizer`,
and `PlayerokPipeline`. The public homepage and product-page HTML responses were
captured and analyzed, but their `__NEXT_DATA__` hydration payloads do not
contain extractable offers.

The marketplace frontend exposes a public GraphQL `/graphql` `items` operation.
`PlayerokFetcher` now uses that operation with an `APPROVED` status filter and
returns the raw JSON response without parsing it inside the fetcher. A live
capture saved as `tmp/playerok_response.json` produced 20 real item offers
through `PlayerokPipeline`.

The extractor has focused contract coverage for structured JSON and
`__NEXT_DATA__` payloads and avoids treating nested seller/user/category/game
objects as offers.

The GraphQL item profile does not expose `currency` directly. During source
verification, the Playerok frontend bundle was checked and item ecommerce
tracking formats the same item `price`/`rawPrice` values with
`currency: "RUB"`. The Playerok normalizer therefore applies a source-backed
`RUB` default at the marketplace adapter boundary instead of changing shared
domain, snapshot, or business services.

Current verifier result:

- raw items: 20;
- parsed offers: 20;
- snapshot-ready offers: 20.

Remaining gaps:

- GraphQL item profiles expose id, slug, title, price, raw price, status,
  seller, category, game, and attachment URL.
- GraphQL validation rejects a direct `currency` field on both `MyItemProfile`
  and `ForeignItemProfile`.
- No currency value is present in the captured JSON response itself.
- Keep the `RUB` fallback documented and monitor Playerok frontend/source drift
  before scheduled production ingestion.

### FunPay

Status: ready from saved listing response.

`FunPayFetcher` can download raw marketplace responses through the shared
`HttpClient`, `FunPayExtractor` can read public offer anchors from listing HTML,
and `FunPayNormalizer` can produce normalized `ParsedOffer` objects. The
implementation is covered by representative parser tests and has been proven
against a captured real FunPay listing response saved in `tmp/funpay_response.html`.
The readiness verifier reports one raw offer, one parsed offer, and one
snapshot-ready offer from that response.

Remaining gaps:

- add payload drift monitoring before scheduled production ingestion;
- capture additional categories before expanding marketplace coverage.

## Verification

`scripts/verify_marketplace_data_readiness.py` provides an offline readiness
check for the current marketplace data state. It does not perform network calls
and does not create business data.

The verifier reports:

- raw item count;
- parsed offer count;
- snapshot-ready offer count;
- current blockers;
- representative parsed offers.

`scripts/verify_marketplace_payload_contracts.py` is the strict saved-payload
drift guard. It reuses the readiness checks and exits with a non-zero status
when any supported marketplace is no longer `ready` or no longer produces at
least one raw item, one parsed offer, and one snapshot-ready offer.

See `docs/EPIC_18_MARKETPLACE_CAPTURE_CHECKLIST.md` for the evidence required
before a marketplace can be marked ready.

## Implementation Order

1. Stabilize GGSEL modular mapping so normalized offers contain absolute URLs
   when the raw payload provides relative slugs. Done.
2. Add focused tests for GGSEL extractor and normalizer against a small
   representative payload. Done.
3. Capture and document one real Playerok category/listing or API response.
   Done through the public GraphQL `items` operation.
4. Harden Playerok extraction only after the response shape is confirmed. Done
   for item offers.
5. Prove FunPay extractor and normalizer against a captured real response. Done.
6. Add payload drift monitoring for ready marketplaces. Done for saved real
   payloads through `scripts/verify_marketplace_payload_contracts.py`.
7. Add a live-optional marketplace data verifier guarded by explicit flags.
8. Wire verified marketplace integrations into Scheduler execution with
   tenant-owned integration configuration.

## Non-Goals

- No Selenium or Playwright.
- No database redesign.
- No matching redesign.
- No comparator redesign.
- No AI provider changes.
- No Telegram delivery changes.
- No production credential retrieval in this EPIC unless explicitly approved.
