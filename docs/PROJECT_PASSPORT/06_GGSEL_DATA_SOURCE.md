# GGSEL Data Source

## Purpose

This document records the first technical investigation for obtaining real GGSEL offers in MediaEngine.

The goal is to choose a stable data access approach before implementing production fetching or parsing.

## Current Local Integration

The current GGSEL integration is represented by:

- `app/parsers/ggsel_parser.py`
- `app/parsers/models.py`
- `app/core/http_client.py`
- `app/adapters/ggsel/`

Current parser preparation already uses the shared `HttpClient` and targets `https://ggsel.net/catalog`.

The parser currently assumes that offer-like data may be extracted from JSON payloads embedded inside catalog page scripts. This is useful as an exploratory fallback, but it should not be treated as the preferred long-term integration source.

## Available Data Access Methods

## Official GGSEL API

GGSEL publicly advertises a private API that provides access to goods, categories, and sellers.

Source:

- https://ggsel.net/api-ggsel
- https://ggsel.net/en/api-ggsel

This is the preferred direction because it is explicitly described by GGSEL as an API for the required data domain.

Access is not self-service in the public page. GGSEL instructs developers to request API documentation and access through their listed contact channel.

## Seller Office API

GGSEL also publishes Seller Office API documentation.

Relevant sources:

- https://seller.ggsel.com/docs/v2/list-products
- https://seller.ggsel.com/docs/schemas/offer-list-object
- https://seller.ggsel.com/docs/schemas/offer-object

This API exposes structured JSON-like schemas with product and offer fields such as:

- product ID;
- product name;
- price;
- currency;
- product URL;
- seller data;
- stock and availability fields;
- sale information.

However, the documented endpoints are seller-office oriented and include unauthorized responses. They appear intended for authenticated seller account operations rather than public marketplace catalog ingestion.

## Public JSON Endpoints

No stable public JSON endpoint for anonymous marketplace-wide catalog ingestion was confirmed during this investigation.

If such an endpoint is later discovered through browser network inspection or official GGSEL guidance, it can be added as the first implementation target, provided it is stable and does not require HTML scraping.

## HTML Parsing

HTML access is technically possible through public catalog pages.

The current parser already has exploratory infrastructure for reading script payloads from catalog HTML and searching for offer-like objects. This can work for early discovery, but it is brittle because page structure and frontend payload format can change without API versioning.

HTML parsing must remain a fallback only.

The project must not use Selenium or Playwright for GGSEL ingestion at this stage.

## Selected Approach

Selected approach:

Use the official/private GGSEL API as the target integration path.

Fallback approach:

If API access is not available yet, continue using simple HTTP retrieval of public catalog HTML only for investigation and diagnostics, without implementing full HTML parsing as production logic.

## Reasons for Selection

The official/private API is selected because:

- it is explicitly advertised by GGSEL for goods, categories, and sellers;
- it is more stable than frontend HTML structures;
- it should provide structured data suitable for mapping into `ParsedOffer`;
- it avoids browser automation;
- it aligns with the existing `HttpClient` abstraction;
- it reduces the risk of brittle parsing logic in the domain pipeline.

The Seller Office API is not selected as the primary source yet because:

- it appears focused on seller account workflows;
- documented endpoints can require authorization;
- it may expose only seller-owned resources rather than marketplace-wide public offers.

HTML parsing is not selected because:

- it couples MediaEngine to GGSEL frontend internals;
- it has no explicit contract;
- it can break silently after frontend releases;
- it adds parsing complexity before the API path is confirmed.

## Limitations

Current limitations:

- official API documentation is not publicly available without contacting GGSEL;
- authentication method, rate limits, pagination, filters, and response schemas are not yet known;
- no stable anonymous JSON catalog endpoint has been confirmed;
- the current local parser still contains exploratory HTML/script payload extraction;
- no production fetcher should be implemented until the API contract is known.

## Implementation Plan

1. Request official GGSEL API access and documentation through the contact listed by GGSEL.

2. Confirm the API contract for:

- listing categories;
- listing offers by category;
- pagination;
- currencies;
- seller fields;
- product URL fields;
- rate limits;
- authentication;
- error responses.

3. Add minimal GGSEL client preparation only after the API contract is known.

4. Map API response fields into existing `ParsedOffer` universal fields:

- `marketplace`;
- `external_id`;
- `title`;
- `url`;
- `price`;
- `currency`;
- `seller_id`;
- `seller_name`.

5. Keep parsing and mapping isolated inside the GGSEL integration layer.

6. Do not save offers to the database inside the parser.

7. Do not create events inside the parser.

8. Do not introduce Selenium, Playwright, or browser automation.

9. If API access is denied or delayed, document a separate decision before implementing any HTML-based fallback.
