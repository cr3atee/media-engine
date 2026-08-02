# Playerok Implementation Decision

## Status

Document date: 2026-07-22.

Decision: **C) Build our own implementation**.

This document evaluates the third-party Playerok solutions mentioned in `docs/PLAYEROK_TECH_SPEC.md`. It is documentation only and does not modify application code.

## Evaluation Criteria

Each option is evaluated by:

- license;
- last update;
- maintenance status;
- supported functionality;
- authentication support;
- marketplace coverage;
- API stability;
- production safety;
- pros;
- cons.

## Summary

| Solution | Type | Production Recommendation |
| --- | --- | --- |
| PyPlayerokAPI | Unofficial Python SDK | Do not use directly; reference only |
| playerok-requests-api | Unofficial Python client | Do not use directly; reference only |
| Parse.bot Playerok API | Managed third-party API | Keep as paid fallback, not primary implementation |

## PyPlayerokAPI

### 1. License

Declared license: MIT License on PyPI.

Important nuance: GitHub API did not report a detected SPDX license for the repository during this review, while PyPI metadata declares MIT. Before any fork or code reuse, the repository license file should be checked directly and preserved.

### 2. Last Update

Latest PyPI release: `1.1.5`, uploaded on 2026-03-08.

Repository metadata checked through GitHub API:

- created: 2026-03-02;
- pushed: 2026-03-08;
- updated: 2026-07-04;
- latest commit message: `1.1.5`;
- stars: 6;
- forks: 1;
- open issues: 1.

### 3. Maintenance Status

Maintenance status: active but young and small.

The project was created and released quickly in March 2026. It has recent metadata activity, but the repository is small, has a low number of commits, and appears to depend on one main maintainer. This creates bus-factor and maturity risks.

### 4. Supported Functionality

Documented functionality:

- asynchronous Playerok API client;
- GraphQL requests;
- persisted queries;
- streaming/event handling;
- account automation;
- chat/deal monitoring;
- transaction handling;
- proxy support;
- Cloudflare-compatible custom transport;
- Pydantic-based models.

This is broader than MediaEngine currently needs. MediaEngine only needs public marketplace offer extraction for price monitoring.

### 5. Authentication Support

Authentication is token-based.

The package documentation requires a Playerok account token from the `.playerok.com` cookie named `token`. Examples pass the token into `AccountClient`. User-Agent and proxy are documented as optional but recommended for avoiding blocks.

### 6. Marketplace Coverage

Coverage is Playerok-specific.

The library focuses on Playerok GraphQL and streaming. It does not provide a marketplace-independent abstraction and does not cover GGSEL or FunPay.

### 7. API Stability

API stability is medium to low for MediaEngine purposes.

Reasons:

- it targets an unofficial Playerok GraphQL surface;
- it may rely on persisted queries and internal endpoint behavior;
- it includes custom anti-bot transport dependencies;
- Playerok can change schema, persisted query hashes, Cloudflare behavior, or auth requirements without notice.

### 8. Production Safety

Safe to use directly in production: **No, not for MediaEngine at this stage**.

Reasons:

- Requires account token for normal usage.
- Expands the dependency graph with `curl-cffi` and exact-pinned `pydantic==2.12.5`.
- Solves more than the current problem and would couple MediaEngine to account automation concerns.
- Low maturity and low bus factor.
- Cloudflare-compatible transport is operationally sensitive and should not enter the project before legal/product approval.

It can be used as a research reference for endpoint shape, persisted queries and transport behavior.

### 9. Pros

- Modern async design.
- Explicit GraphQL support.
- Mentions persisted queries, which is relevant to Playerok.
- Has token auth and streaming support if those are ever needed.
- MIT-declared package metadata.
- More recent than `playerok-requests-api`.

### 10. Cons

- Requires account token for documented usage.
- Not focused on public catalog extraction.
- Heavy/low-level transport dependencies.
- Exact dependency pins can conflict with MediaEngine.
- Small project, small community, low maturity.
- Potential ToS/account-risk concerns.
- Would import Playerok-specific account concepts into a project that currently needs public offer monitoring.

## playerok-requests-api

### 1. License

Declared license: MIT License.

PyPI metadata uses an MIT license expression, and the GitHub page rendered by browser shows an MIT license label.

### 2. Last Update

Latest PyPI release: `0.1.6`, uploaded on 2025-05-09.

Release history shows versions `0.1.2` through `0.1.6` released on 2025-05-08 and 2025-05-09.

The package homepage points to `https://github.com/lydyxxx/PlayerokRequestsApi`, but GitHub API returned `404 Not Found` for that repository during this review. The browser-rendered GitHub page was visible through indexed content, but API metadata could not be confirmed.

### 3. Maintenance Status

Maintenance status: low or unknown.

Reasons:

- Last package release is over a year old as of 2026-07-22.
- Releases were clustered across two days, with no visible release cadence after that.
- The declared GitHub repository could not be verified through GitHub API.
- One maintainer is listed on PyPI.

### 4. Supported Functionality

Documented modules:

- users;
- deals;
- items;
- chats.

Documented item functionality includes:

- fetching completed lots;
- fetching exhibited lots;
- fetching all exhibited lots;
- copying product data from a link;
- increasing item priority;
- refilling/relisting an item;
- getting product data by link;
- checking item search position.

The package is oriented toward account management and seller operations, not clean public marketplace ingestion.

### 5. Authentication Support

Authentication is cookie-file based.

The package expects a `cookies.json` file and uses cookies for account-authenticated GraphQL requests.

### 6. Marketplace Coverage

Coverage is Playerok-specific.

It does not abstract multiple marketplaces and does not cover GGSEL or FunPay.

### 7. API Stability

API stability is low.

Reasons:

- unofficial GraphQL client;
- older release;
- unknown current repository availability;
- cookie-based auth requirement;
- likely tied to internal Playerok operations;
- methods return generic dictionaries, tuples, `None`, empty strings or empty lists depending on errors.

### 8. Production Safety

Safe to use directly in production: **No**.

Reasons:

- Requires cookie-file authentication.
- Depends on `wrapper-tls-requests==1.1.2`, which is not part of the current MediaEngine stack.
- Error handling is documented as returning `None`, empty values or printing/logging, which is too weak for reliable ingestion.
- Repository availability is uncertain.
- The functionality is mostly account/private-operation oriented.

### 9. Pros

- MIT-declared package.
- Small package.
- Documents several Playerok GraphQL workflows.
- Contains item-related methods that may help understand query shapes.

### 10. Cons

- Old and likely not actively maintained.
- Requires cookies.
- Not designed for public catalog extraction.
- Weak return contracts.
- Adds a non-standard TLS/request dependency.
- Repository metadata could not be reliably verified.
- Account automation scope is broader and riskier than MediaEngine needs.

## Parse.bot Playerok API

### 1. License

License: proprietary/commercial SaaS terms, not an open-source library license.

Parse.bot is a hosted API service. It cannot be forked like a Python library. Usage is governed by Parse terms and pricing.

### 2. Last Update

The Playerok API page is marked live and updated `2mo ago`.

The page content states it was last updated on 2026-05-21.

### 3. Maintenance Status

Maintenance status: managed and active.

Parse describes the Playerok API as a monitored managed endpoint with health checks and automated repair workflow when the source site changes. This is stronger operational maintenance than the two unofficial Python libraries.

### 4. Supported Functionality

Documented endpoints:

- `list_items`;
- `get_item`;
- `search_games`;
- `list_categories`;
- `get_top_items`.

Documented features:

- product listing;
- product detail retrieval;
- game search;
- category browsing;
- featured/top items;
- filters by game/category;
- sorting by fields such as price or creation date;
- cursor-based pagination;
- typed Python client generation;
- OpenAPI/MCP-style access.

This is close to MediaEngine's public offer extraction use case.

### 5. Authentication Support

Authentication is via Parse API key:

- `X-API-Key: $PARSE_API_KEY`

This authenticates with Parse, not with Playerok.

No Playerok account token is required by the documented marketplace API.

### 6. Marketplace Coverage

Coverage is Playerok-specific for this API page.

Parse also offers a broader marketplace catalog, but this decision only evaluates the Playerok API. It does not provide MediaEngine's internal marketplace abstraction.

### 7. API Stability

API stability is medium to high from the consumer side, but with vendor dependence.

Strengths:

- documented endpoint contract;
- documented response shape;
- cursor-based pagination;
- managed monitoring and repair claims;
- can provide typed generated clients.

Risks:

- not an official Playerok API;
- depends on Parse staying available and maintaining the adapter;
- pricing/credits/rate limits can change;
- data correctness depends on an external vendor;
- terms require the user to ensure third-party access is compliant.

### 8. Production Safety

Safe to use directly in production: **Conditionally yes, but not as the primary architecture choice**.

It is the safest third-party option operationally because it avoids maintaining scraper internals and does not require Playerok account cookies. However, it introduces:

- vendor lock-in;
- recurring cost;
- external availability risk;
- data processing by a third party;
- dependency on Parse's contract and business continuity;
- limited customization unless using Parse's revision workflow.

For MediaEngine, it is suitable as a fallback or validation source, not as the default implementation.

### 9. Pros

- Closest match to public marketplace offer extraction.
- No Playerok account token required in the documented flow.
- Clear endpoint contract.
- Cursor pagination is documented.
- Includes product, seller, game and category data.
- Managed monitoring and repair are advertised.
- Faster MVP validation if vendor dependency is acceptable.

### 10. Cons

- Proprietary hosted service.
- Requires Parse API key and account.
- Paid/credit-based limits.
- Not forkable.
- Not official Playerok API.
- Hard dependency on third-party uptime and terms.
- May hide important extraction details that MediaEngine needs to own long term.

## Production Decision

Decision: **C) Build our own implementation**.

Rationale:

- MediaEngine already has a clean marketplace pipeline and `ParsedOffer` contract.
- The next implementation step is narrow: public Playerok offer extraction, not account automation.
- Existing Python libraries solve a broader and riskier problem than needed.
- Direct library adoption would add dependencies, auth assumptions and transport complexity too early.
- Parse.bot is operationally attractive but creates vendor lock-in and cost before MediaEngine has proven its own extraction boundary.
- A small first-party Playerok adapter can reuse the existing `HttpClient`, keep Playerok logic isolated, and map only universal fields into `ParsedOffer`.

## Recommended Use of Third-Party Work

Use third-party solutions only as references:

- Use `PyPlayerokAPI` to understand modern Playerok GraphQL, persisted-query and streaming concepts.
- Use `playerok-requests-api` to inspect historical item/query workflows if source code remains accessible.
- Use Parse.bot as a response-shape reference and optional fallback for validation.

Do not add these packages as dependencies at this stage.

## Recommended Implementation Path

1. Capture browser network traffic for one public Playerok category.
2. Identify the exact public listing GraphQL operation or REST/BFF endpoint.
3. Store request payloads and response samples in documentation.
4. Implement a first-party `PlayerokClient` using existing project HTTP infrastructure.
5. Implement a first-party `PlayerokFetcher` that returns raw Playerok items.
6. Implement a first-party `PlayerokNormalizer` that produces `ParsedOffer`.
7. Keep authentication out of the initial implementation.
8. Add conservative rate limits and diagnostics.
9. Compare output against Parse.bot manually only if needed.
10. Revisit third-party fallback only if native public extraction is blocked.

## Sources

- Technical baseline: `docs/PLAYEROK_TECH_SPEC.md`
- PyPlayerokAPI PyPI: https://pypi.org/project/PyPlayerokAPI/
- PyPlayerokAPI GitHub: https://github.com/kekch127/PyPlayerokAPI
- playerok-requests-api PyPI: https://pypi.org/project/playerok-requests-api/
- playerok-requests-api GitHub: https://github.com/lydyxxx/PlayerokRequestsApi
- Parse.bot Playerok API: https://parse.bot/marketplace/8249b39b-9327-4c88-b9d5-d88f8de6bafc/playerok-com-api
- Parse.bot terms: https://parse.bot/terms
- Parse.bot pricing: https://parse.bot/pricing
