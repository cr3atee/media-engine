# EPIC 18 Marketplace Capture Checklist

## Purpose

This checklist defines how MediaEngine proves that marketplace data is real,
extractable, and usable by the shared core runtime.

The checklist is intentionally evidence-based. A marketplace is not considered
ready because a class exists; it is ready only when a real response can be
converted into snapshot-ready `ParsedOffer` objects.

## Common Rules

- Use the local project Python runtime, for example
  `.venv\Scripts\python.exe`.
- Do not use production credentials.
- Do not commit raw marketplace responses from `tmp/`.
- Do not create fake successful responses.
- Do not parse a marketplace until its source payload is captured and reviewed.
- Do not add Selenium or Playwright.
- Do not add dependencies for source capture.
- Record blocking HTTP status codes and content types exactly.

## Readiness Criteria

A marketplace is core-ready when all of the following are true:

- at least one real marketplace response has been captured;
- extraction returns marketplace offers from that response;
- normalization returns `ParsedOffer` objects;
- at least one `ParsedOffer` has `external_id`, `price`, and `currency`;
- URLs are usable by downstream content or admin views;
- missing fields are explicit and not invented;
- source limitations are documented.

## GGSEL

Current status: ready from saved response.

Evidence:

- `tmp/ggsel_response.html` exists locally;
- `GGSelExtractor` extracts real raw marketplace offers;
- `OfferNormalizer` returns snapshot-ready `ParsedOffer` objects;
- `scripts/verify_marketplace_data_readiness.py` reports 60 raw items, 60 parsed
  offers, and 60 snapshot-ready offers from the saved response.

Verification command:

```powershell
.venv\Scripts\python.exe scripts/verify_marketplace_data_readiness.py
```

Remaining proof needed:

- rerun live GGSEL capture in an environment where outbound marketplace network
  access is allowed;
- keep the saved payload out of git unless a sanitized fixture is explicitly
  approved.

## Playerok

Current status: ready from live GraphQL response.

Existing implementation:

- `PlayerokFetcher`;
- `PlayerokExtractor`;
- `PlayerokNormalizer`;
- `PlayerokPipeline`.

Contract coverage verifies structured JSON and `__NEXT_DATA__` mapping behavior.
Real public HTML responses were captured, but their hydration payloads do not
contain extractable offers. The selected source is the public GraphQL
`https://playerok.com/graphql` `items` operation with an `APPROVED` status
filter.

Completed proof:

- captured one real GraphQL item-list response as `tmp/playerok_response.json`;
- `scripts/demo_playerok_fetch.py` returned HTTP 200 with JSON content;
- `scripts/demo_playerok_pipeline.py` produced 20 real `ParsedOffer` objects;
- Playerok frontend bundle verification confirms item price tracking with
  `currency: "RUB"`;
- `PlayerokNormalizer` applies the documented source-backed `RUB` default;
- `scripts/verify_marketplace_data_readiness.py` reports 20 raw items, 20 parsed
  offers, and 20 snapshot-ready offers.

Remaining proof:

- add payload/source drift monitoring before scheduled production ingestion;
- capture additional categories before expanding marketplace coverage.

Verification commands:

```powershell
.venv\Scripts\python.exe scripts/demo_playerok_fetch.py
.venv\Scripts\python.exe scripts/analyze_playerok_response.py
.venv\Scripts\python.exe scripts/demo_playerok_extractor.py
.venv\Scripts\python.exe scripts/verify_marketplace_data_readiness.py
```

If the public GraphQL response shape changes, do not broaden extractor
heuristics until the new payload is captured and reviewed. Nested category/game
objects must not be treated as offers unless they expose offer-level pricing
fields.

## FunPay

Current status: ready from captured listing response.

Existing implementation:

- `FunPayFetcher`;
- `FunPayExtractor`;
- `FunPayNormalizer`;
- `FunPayPipeline`;
- `scripts/demo_funpay_fetch.py`.

Completed proof:

- captured one real public listing/category response;
- saved it as `tmp/funpay_response.html`;
- reviewed the payload structure with `scripts/analyze_funpay_response.py`;
- proved conversion into one snapshot-ready `ParsedOffer`.

Verification commands:

```powershell
.venv\Scripts\python.exe scripts/demo_funpay_fetch.py
.venv\Scripts\python.exe scripts/analyze_funpay_response.py
.venv\Scripts\python.exe scripts/verify_marketplace_data_readiness.py
```

Before scheduled production ingestion, add payload drift monitoring and capture
additional categories.

## Failure Handling

If a marketplace cannot be reached:

- print the actual error;
- keep the readiness status blocked or raw-only;
- do not create fake offers;
- do not mark the marketplace as complete.

If a marketplace returns anti-bot or authentication errors:

- document the exact status code and content type;
- do not add credential usage without a separate approved EPIC;
- do not use browser automation as a hidden workaround.

## Next Acceptance Gate

The next core acceptance gate is:

```text
GGSEL   -> ready
Playerok -> ready
FunPay  -> ready
```

The current saved-response gate is satisfied. The production scheduling gate
still requires drift monitoring and explicit runtime marketplace configuration.
