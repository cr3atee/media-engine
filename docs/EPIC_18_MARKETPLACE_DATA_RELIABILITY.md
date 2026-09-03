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

Status: partial.

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

Status: blocked.

The project has `PlayerokFetcher`, `PlayerokExtractor`, `PlayerokNormalizer`,
and `PlayerokPipeline`, but a saved real Playerok marketplace response is not
present in the current workspace. Existing documentation states that the exact
Playerok public listing response shape is not confirmed yet.

Remaining gaps:

- capture a real public listing response or approved API response;
- confirm the exact source fields for id, title, price, currency, URL and
  seller;
- prove extraction into `ParsedOffer`;
- prove snapshot readiness.

### FunPay

Status: not implemented.

The repository currently contains empty adapter scaffolding for FunPay only.
There is no FunPay fetcher, extractor, normalizer, or pipeline.

Remaining gaps:

- complete technical source investigation;
- choose allowed data access strategy;
- implement fetch/extract/normalize boundaries;
- prove conversion into `ParsedOffer`.

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

## Implementation Order

1. Stabilize GGSEL modular mapping so normalized offers contain absolute URLs
   when the raw payload provides relative slugs. Done.
2. Add focused tests for GGSEL extractor and normalizer against a small
   representative payload.
3. Capture and document one real Playerok category/listing response.
4. Harden Playerok extraction only after the response shape is confirmed.
5. Research FunPay data access and document the selected source.
6. Implement FunPay fetcher, extractor, and normalizer.
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
