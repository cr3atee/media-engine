# Playerok Data Extraction Technical Specification

## Status

Document date: 2026-07-22.

This document describes the technical approach for extracting public marketplace offers from Playerok into the MediaEngine pipeline. It is a research specification only. No application code is changed by this document.

## Research Scope

Checked areas:

- Playerok public marketplace pages.
- Next.js hydration data.
- Client-side JavaScript bundles.
- GraphQL endpoint indicators.
- REST/public endpoint indicators.
- WebSocket/subscription indicators.
- Authentication and anti-bot signals.
- Existing MediaEngine `ParsedOffer` contract.

## 1. Available Data Sources

### Public Website HTML

Playerok public pages are available as HTML under:

- `https://playerok.com/`
- `https://playerok.com/products/{slug}`

Observed public pages render marketplace categories, product cards, product prices, product links and product detail information. However, raw initial HTML contains only a minimal `__NEXT_DATA__` payload:

- `dehydratedState.queries` is empty.
- `apolloState` is empty.
- product arrays are not reliably present in the initial hydration JSON.

Conclusion: HTML can be used as a fallback discovery source, but it should not be the preferred structured extraction source.

### Next.js Hydration

The site uses Next.js assets under `/_next/static/...` and exposes `__NEXT_DATA__`.

Current finding:

- `__NEXT_DATA__` exists.
- It does not currently contain complete product listing data.
- It includes build metadata, page metadata and empty Apollo/cache state.

Conclusion: hydration JSON is useful for confirming app framework and build state, but not sufficient as the primary product data source.

### GraphQL Endpoints

Client JavaScript bundles expose GraphQL-related endpoints:

- Main endpoint: `https://playerok.com/graphql`
- Steam endpoint: `https://steam.playerok.com/graphql`
- WebSocket endpoint observed in client bundle: `wss://ws.playerok.com/graphql`
- A public subscription-related URL is also referenced by public discussion as `wss://playerok.com/subscriptions`.

Client bundle observations:

- The app contains Apollo/GraphQL client code.
- The app config includes `API_HOST: "playerok.com"` and `API_URI: "/graphql"`.
- The app defines endpoint objects for `Main` and `Steam`.
- The client uses `credentials: "include"`.
- If a `token` cookie exists, the client adds `Authorization: Bearer <token>`.

Basic unauthenticated health-check against `https://playerok.com/graphql` returned `500 Internal Server Error` for a minimal `{ __typename }` query. This does not disprove endpoint usage; it suggests the endpoint may require the exact client request shape, persisted queries, valid operation names, session context, anti-bot headers, or a non-trivial GraphQL document.

Conclusion: GraphQL is the most likely native data source, but the exact list/search operation must be captured from browser network traffic before implementation.

### Public REST/BFF Endpoints

Client JavaScript bundles expose:

- `https://playerok.com/rest-api/public`
- `https://bff.playerok.com/rest-api/public`

No stable product-list REST path was confirmed during this research. These endpoints should be investigated in browser DevTools while browsing categories and pressing pagination controls.

Conclusion: REST/BFF may support public reads, but no concrete product-list endpoint is confirmed yet.

### Third-Party Managed API

Parse publishes an independent Playerok marketplace API with endpoints such as:

- `list_items`
- `get_item`
- `search_games`
- `list_categories`
- `get_top_items`

It documents cursor-based pagination, `products`, `page_info`, `total_count`, item `id`, `slug`, `name`, `price`, `raw_price`, `seller`, `game`, `category`, and rate limits. It also states this is not an official Playerok API.

Conclusion: Parse can be used as a reference for expected data shape and as an optional external fallback, but it introduces a paid third-party dependency and should not be the first implementation choice inside MediaEngine.

### Unofficial Python Libraries

Public PyPI packages confirm an unofficial ecosystem around Playerok GraphQL:

- `PyPlayerokAPI` describes GraphQL, persisted queries, streaming events, token authentication, proxy support and Cloudflare-compatible transport.
- `playerok-requests-api` describes GraphQL usage through cookies-based authentication.

Conclusion: unofficial libraries support the finding that Playerok uses GraphQL, but they should not be added as dependencies. They are useful only as research references.

## 2. Preferred Extraction Strategy

Preferred strategy: use Playerok native GraphQL over HTTPS after capturing the exact public product listing operation from browser DevTools.

Why:

- GraphQL is exposed by the official frontend bundle.
- It is the closest available structured data source.
- It avoids fragile HTML parsing.
- It maps cleanly into `ParsedOffer`.
- It can support cursor pagination if the query follows the same connection model observed in external references.
- It keeps MediaEngine architecture aligned with existing marketplace adapters: fetch raw data, normalize to `ParsedOffer`, then pass downstream.

Initial implementation should not attempt account automation. It should first target only public marketplace listings that are visible without login.

## 3. Fallback Strategy

Fallback order:

1. Use public REST/BFF endpoints if browser network traffic reveals a stable product-list endpoint.
2. Use Next.js/HTML only to discover links and embedded state, not as the primary parser.
3. Use third-party managed APIs only if native public access is blocked and the project explicitly accepts the external dependency and cost.
4. Do not use Selenium or Playwright for the backend extraction layer.

HTML parsing should remain a last resort because Playerok product data is client-rendered and may change markup frequently.

## 4. Required Request Headers

For public GraphQL/REST requests, start with browser-like but minimal headers:

- `Accept: application/json`
- `Content-Type: application/json`
- `Origin: https://playerok.com`
- `Referer: https://playerok.com/`
- `User-Agent: <realistic desktop browser user agent>`
- `Accept-Language: ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7`

For authenticated requests, if ever approved for future work:

- `Cookie: token=<playerok token>; ...`
- `Authorization: Bearer <token>`

Authentication headers must never be hardcoded. They must come from environment/settings or a future secure secret storage mechanism.

## 5. Authentication Requirements

Public marketplace browsing should be attempted without authentication first.

Authentication is likely required for:

- profile data;
- chats;
- deals;
- seller management;
- item creation or editing;
- private account streams;
- some GraphQL mutations and subscriptions.

The current MediaEngine use case is public price monitoring, so the initial implementation should avoid requiring a Playerok account unless public data access is impossible.

If authentication becomes necessary later:

- Use a dedicated technical account.
- Store token outside source control.
- Rotate token periodically.
- Separate authenticated fetchers from public marketplace fetchers.
- Do not reuse user personal browser cookies in production.

## 6. Pagination Strategy

Expected strategy: cursor-based pagination.

Reasons:

- External Playerok API references expose `page_info.has_next_page`, `page_info.end_cursor`, `page_info.start_cursor`, and `page_info.has_previous_page`.
- Client bundle contains Apollo cache logic that ignores or handles a `pagination` variable.
- Product-list APIs for marketplaces commonly use GraphQL connection-style pagination.

Recommended page loop:

1. Request first page with a conservative `first` or `limit` value.
2. Normalize only returned product nodes/items.
3. Store `end_cursor`.
4. Continue while `has_next_page` is true.
5. Stop on empty page, repeated cursor, HTTP error, GraphQL error, or configured max pages.

Initial safe limits:

- `limit`: 20-50 items per page.
- max pages per run: configurable.
- delay between pages: configurable.

Do not assume offset pagination unless browser traffic proves it.

## 7. Risks

### Anti-Bot and Cloudflare

There are public reports of Playerok WebSocket access returning `403` with Cloudflare/bot-protection symptoms. Unofficial libraries mention Cloudflare-compatible transports, proxies and browser-like request handling.

Risk:

- Direct server-side requests may be blocked.
- WebSocket/subscription access is likely more protected than simple public catalog reads.
- Request headers alone may not be sufficient.

Mitigation:

- Start with public HTTPS GraphQL listing requests only.
- Use low request rate.
- Avoid WebSocket in the extraction layer.
- Log exact HTTP status, response content type and GraphQL errors.
- Keep retries conservative.

### Unofficial API Surface

Playerok does not appear to publish a stable official public developer API for catalog extraction.

Risk:

- GraphQL schema and operation names may change.
- Persisted query hashes may change with frontend deployments.
- Existing browser bundle build IDs rotate.

Mitigation:

- Keep Playerok adapter isolated.
- Keep request payload definitions in one module.
- Add diagnostics for schema/operation failures.
- Document every captured operation with date and source page.

### Authentication Boundary

Using account tokens changes risk profile.

Risk:

- Account lock or rate limits.
- Secret leakage.
- Terms-of-service concerns.

Mitigation:

- Prefer unauthenticated public data.
- Do not implement account automation in the initial extractor.
- Add explicit product decision before authenticated extraction.

### Price Semantics

Playerok may expose both `price` and `raw_price`.

Risk:

- `raw_price` may represent original/pre-discount price, not current sell price.
- Discounts shown on UI may be promotional, not actual historical price drops.

Mitigation:

- Map `ParsedOffer.price` only from current effective price.
- Preserve old/current comparison in MediaEngine snapshots, not from marketplace `raw_price`.

## 8. Recommended Architecture

Recommended Playerok adapter boundaries:

- `PlayerokClient`: performs low-level HTTP requests to GraphQL/REST.
- `PlayerokQueries`: stores GraphQL documents or persisted query payloads.
- `PlayerokFetcher`: retrieves raw marketplace responses for one category/search.
- `PlayerokNormalizer`: converts raw Playerok item objects into `ParsedOffer`.
- Existing `MarketplacePipeline`: consumes `ParsedOffer` and persists/offloads downstream stages.

Responsibilities:

- Client knows transport, headers, endpoint and errors.
- Fetcher knows marketplace pagination and raw response shape.
- Normalizer knows field mapping into MediaEngine contracts.
- Pipeline remains marketplace-independent orchestration.

Do not place Playerok-specific logic into domain models, analytics, matching, repositories or AI services.

## 9. Data Mapping to ParsedOffer

Current `ParsedOffer` fields:

- `marketplace: str`
- `external_id: str | None`
- `title: str | None`
- `url: str | None`
- `price: Decimal | None`
- `currency: str | None`
- `seller_id: str | None`
- `seller_name: str | None`
- `canonical_product_id: UUID | None`

Recommended mapping:

| ParsedOffer field | Playerok source |
| --- | --- |
| `marketplace` | constant `"playerok"` |
| `external_id` | product `id`; fallback to `slug` if `id` is unavailable |
| `title` | product `name` or `title` |
| `url` | `https://playerok.com/products/{slug}` when `slug` is present; otherwise public product URL from response |
| `price` | current effective `price`, converted to `Decimal` from string/int, never float arithmetic |
| `currency` | response currency if present; otherwise `"RUB"` only if verified for the endpoint |
| `seller_id` | `seller.id` if present |
| `seller_name` | `seller.username`, `seller.name`, or equivalent public seller display field |
| `canonical_product_id` | leave `None`; matching engine fills this later |

Fields that should remain outside `ParsedOffer` unless a universal need appears:

- seller rating;
- testimonial count;
- priority;
- status;
- image URL;
- game/category metadata;
- fee multiplier;
- view count;
- marketplace-specific delivery/obtaining type.

These fields may be preserved in a raw typed Playerok model or `extra` structure later, but should not expand the universal contract prematurely.

## 10. Recommended Implementation Order

1. Capture browser network traffic for one public category page.
2. Identify the exact GraphQL operation or public REST endpoint used for product listing.
3. Save a sanitized example request and response in documentation.
4. Implement a small Playerok raw fetcher using existing HTTP infrastructure.
5. Add explicit diagnostics for HTTP status, content type, GraphQL errors and empty result sets.
6. Implement a Playerok raw response model only after the response shape is confirmed.
7. Implement `PlayerokNormalizer` to produce `ParsedOffer`.
8. Add a demo script that prints first real `ParsedOffer` objects.
9. Integrate Playerok fetcher into marketplace pipeline only after stable extraction is confirmed.
10. Add rate limiting/backoff configuration before scheduled polling.

## Open Questions

- Exact GraphQL operation name for public item listing.
- Whether Playerok requires persisted query hashes for listing requests.
- Whether unauthenticated listing requests are stable outside browser context.
- Exact category/game filters for initial MVP monitoring.
- Whether `price` always represents RUB or whether explicit currency exists in response.

## Sources

- Playerok public website: https://playerok.com/
- Playerok public product page example: https://playerok.com/products/7ef09cc1f86c-60-uc-po-aydi
- Parse Playerok API reference: https://parse.bot/marketplace/8249b39b-9327-4c88-b9d5-d88f8de6bafc/playerok-com-api
- PyPlayerokAPI package page: https://pypi.org/project/PyPlayerokAPI/
- playerok-requests-api package page: https://pypi.org/project/playerok-requests-api/
- Stack Overflow discussion about Playerok WebSocket and Cloudflare symptoms: https://stackoverflow.com/questions/79656959/python-bypass-cloudflare-connecting-to-websocket
