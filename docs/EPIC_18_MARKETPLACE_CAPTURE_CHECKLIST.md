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

Current status: blocked by missing captured source response.

Existing implementation:

- `PlayerokFetcher`;
- `PlayerokExtractor`;
- `PlayerokNormalizer`;
- `PlayerokPipeline`.

Required proof:

- capture one real public listing/category response;
- save it as `tmp/playerok_response.html`, `tmp/playerok_response.json`, or
  `tmp/playerok_response.txt`;
- run the extractor demo;
- run the marketplace readiness verifier;
- confirm exact fields for id, title, price, currency, URL, and seller.

Verification commands:

```powershell
.venv\Scripts\python.exe scripts/demo_playerok_fetch.py
.venv\Scripts\python.exe scripts/analyze_playerok_response.py
.venv\Scripts\python.exe scripts/demo_playerok_extractor.py
.venv\Scripts\python.exe scripts/verify_marketplace_data_readiness.py
```

If the public homepage or category response does not contain offers, do not
broaden the extractor heuristics. Capture the actual GraphQL, REST, BFF, or
hydration response used by the browser and update the Playerok source
documentation first.

## FunPay

Current status: extraction boundary prepared.

Existing implementation:

- `FunPayFetcher`;
- `FunPayExtractor`;
- `FunPayNormalizer`;
- `FunPayPipeline`;
- `scripts/demo_funpay_fetch.py`.

Required proof:

- capture one real public listing/category response;
- save it as `tmp/funpay_response.html`;
- review the payload structure before implementing extraction;
- prove conversion into snapshot-ready `ParsedOffer`.

Verification commands:

```powershell
.venv\Scripts\python.exe scripts/demo_funpay_fetch.py
.venv\Scripts\python.exe scripts/analyze_funpay_response.py
.venv\Scripts\python.exe scripts/verify_marketplace_data_readiness.py
```

Until an extractor exists, FunPay must not be represented as marketplace-ready.

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
Playerok -> ready or explicitly blocked by documented source restriction
FunPay  -> ready or explicitly blocked by documented source restriction
```

The core should not be called marketplace-complete until this gate is satisfied.
