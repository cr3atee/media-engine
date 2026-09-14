# EPIC 19: Consumer Read API For Market Terminal

## Goal

Expose the existing MediaEngine backend core through stable buyer-facing read
contracts that can power the Market Terminal visual product.

This EPIC must not change marketplace ingestion, matching, comparison,
publication delivery, seller administration, or tenant authorization behavior.

## Working Product Assumptions

- `MediaEngine` remains the backend core name.
- `Market Terminal` is the public visual product name.
- The first visual MVP targets product discovery and price comparison.
- Seller administration remains a separate authenticated area.
- The frontend location is not decided yet, so backend API contracts should be
  stable before UI implementation starts.
- GGSEL, Playerok, and FunPay are the first supported marketplaces.
- Lolz must not be exposed as a supported marketplace until a real adapter exists.

## User-Facing Problem

Users need a simple answer:

> Where is this digital product cheaper right now?

The read API should make that answer easy for the frontend to display through
search, product cards, marketplace offers, price history, and latest price
changes.

## Non-Goals

- No marketplace parser changes.
- No new marketplace integrations.
- No matching redesign.
- No comparator redesign.
- No PostgreSQL schema redesign unless a strictly read-side projection requires
  a later approved task.
- No admin workflow changes.
- No Telegram changes.
- No AI chat implementation.
- No favorites, notifications, payments, subscriptions, or premium features.
- No frontend implementation in this EPIC.

## Current Status

Task 1 is complete: public Pydantic DTOs and bounded query parameter schemas
exist for product cards, product details, offer summaries, comparison results,
price-history points, latest price changes, and categories.

Task 2 is complete: SQLAlchemy-independent public query contracts and immutable
read projections exist for product discovery, offers, comparison results,
price-history points, price changes, and categories.

Task 3 is complete for product reads: `PublicProductReadService` delegates to
the public product query contract and returns product-card/detail projections
without depending on FastAPI, SQLAlchemy, or UI code.

Task 4 is complete for comparison reads: `PublicComparisonReadService` delegates
to the public comparison query contract and returns comparison projections
without recalculating matching, selection, or differences.

Task 5 is complete for price-history reads: `PublicPriceHistoryReadService`
delegates to the public price-history query contract and returns bounded chart
points without mutating lifecycle state.

Task 6 is complete: read-only `/api/v1/public` routes exist for products,
product details, product offers, product comparison, product price history,
latest price changes, and categories. Routes require no seller/admin
authentication and return explicit public DTOs.

Task 7 is complete: a repository-backed public read adapter can project product
cards, offer lists, comparison results, price-history points, latest price
changes, and categories from an existing `RepositoryProvider`.

Task 8 is complete: saved GGSEL, Playerok, and FunPay payloads were verified
through the public DTO/route layer. Product cards, product details, offer
summaries, comparison results, and price-history points can be populated from
saved real marketplace offers. Latest price changes and categories were
route-verified as empty because the saved payloads contain current offers only
and the current `ParsedOffer` contract does not retain marketplace category
fields.

Task 9 is complete: `create_app()` wires a default PostgreSQL-backed public read
scope using the existing `RepositoryProvider` and repository-backed public read
adapter. Tests can still pass `public_read_repository_scope_factory=None` to
verify safe `public_read_api_unavailable` behavior explicitly.

No PostgreSQL-specific direct SQL public query adapter has been implemented.
An early embedded `/terminal` frontend shell now exists for validating the
public read API contract, but it is not yet a production frontend commitment.

## Boundary Rules

- Public consumer routes must not expose admin-only lifecycle state.
- Public consumer routes must not expose claim tokens, retry internals, raw
  credentials, destination secrets, raw database rows, or ORM objects.
- Public consumer routes must use explicit response DTOs.
- Public consumer services should reuse repository/query boundaries and existing
  comparison components.
- Public consumer reads must not mutate lifecycle state.
- Public consumer reads must stay separate from seller/admin APIs.

## Required UI Data

### Home Page

The home page needs:

- popular product cards;
- latest price changes;
- marketplace availability summary;
- category list.

### Search Page

The search page needs:

- product search results;
- category filters;
- marketplace filters;
- price range filters;
- deterministic sorting.

### Product Page

The product page needs:

- canonical product details;
- all marketplace offers;
- selected best offer;
- price differences;
- price history points;
- latest price-change summary.

## Proposed Route Surface

### Product Listing

`GET /api/v1/public/products`

Purpose:

Return product cards for the home page, category pages, and browse views.

Expected query parameters:

- `q`
- `category`
- `marketplace`
- `min_price`
- `max_price`
- `sort`
- `limit`
- `cursor`

### Product Detail

`GET /api/v1/public/products/{product_id}`

Purpose:

Return one public product detail view.

### Product Offers

`GET /api/v1/public/products/{product_id}/offers`

Purpose:

Return marketplace offers attached to one canonical product.

### Product Comparison

`GET /api/v1/public/products/{product_id}/comparison`

Purpose:

Return the existing comparator result in a UI-safe shape.

### Product Price History

`GET /api/v1/public/products/{product_id}/price-history`

Purpose:

Return simple chart points for the product page.

Expected query parameters:

- `period`
- `marketplace`

### Latest Price Changes

`GET /api/v1/public/price-changes`

Purpose:

Return recent price drops or price changes for the home page and product pages.

### Categories

`GET /api/v1/public/categories`

Purpose:

Return categories available for browse and search filters.

## DTO Drafts

### PublicProductCard

Fields:

- `id: UUID`
- `name: str`
- `category: str | None`
- `best_offer: PublicOfferSummary | None`
- `offer_count: int`
- `marketplace_count: int`
- `updated_at: datetime | None`

### PublicProductDetail

Fields:

- `id: UUID`
- `name: str`
- `category: str | None`
- `aliases: list[str]`
- `best_offer: PublicOfferSummary | None`
- `offer_count: int`
- `marketplace_count: int`
- `updated_at: datetime | None`

### PublicOfferSummary

Fields:

- `marketplace: str`
- `external_id: str`
- `title: str`
- `price: Decimal | None`
- `currency: str | None`
- `seller_name: str | None`
- `url: str`

### PublicComparisonResult

Fields:

- `product: PublicProductDetail`
- `offers: list[PublicOfferSummary]`
- `best_offer: PublicOfferSummary | None`
- `differences: list[PublicPriceDifference]`
- `status: str`

### PublicPriceDifference

Fields:

- `offer: PublicOfferSummary`
- `absolute_difference: Decimal | None`
- `percentage_difference: Decimal | None`
- `reason: str | None`

### PublicPriceHistoryPoint

Fields:

- `marketplace: str`
- `price: Decimal`
- `currency: str`
- `collected_at: datetime`

### PublicPriceChange

Fields:

- `product_id: UUID | None`
- `product_name: str`
- `marketplace: str`
- `old_price: Decimal`
- `new_price: Decimal`
- `currency: str`
- `discount_percent: Decimal`
- `changed_at: datetime`
- `url: str | None`

### PublicCategory

Fields:

- `code: str`
- `name: str`
- `product_count: int`

## Implementation Tasks

### Task 1: Public DTO Foundation

Create typed public response schemas for product cards, product details, offers,
comparison results, price history, price changes, and categories.

Acceptance criteria:

- DTOs are explicit and UI-safe.
- No ORM object is exposed.
- No admin lifecycle internals are exposed.
- No persistence or business behavior changes.

Status:

- Complete.

### Task 2: Consumer Query Contracts

Create SQLAlchemy-independent read contracts for public product, offer,
comparison, price-history, price-change, and category reads.

Acceptance criteria:

- Contracts are independent from PostgreSQL.
- Memory and PostgreSQL implementations can share the same API.
- Existing repository interfaces are not redesigned.

Status:

- Complete.

### Task 3: Public Product Read Service

Implement an application service that composes product cards and product details
from existing repositories/query adapters.

Acceptance criteria:

- Product cards can include best-offer summary when available.
- Product details can include aliases and availability metadata.
- No lifecycle state is mutated.

Status:

- Complete.

### Task 4: Public Comparison Read Service

Expose existing comparator output through public DTOs.

Acceptance criteria:

- Existing matching and comparator services are reused.
- No duplicated comparison logic is introduced.
- Currency mismatch and missing price states remain explicit.

Status:

- Complete.

### Task 5: Public Price History Read Service

Expose price-history points for charts.

Acceptance criteria:

- Points use Decimal prices and UTC timestamps.
- Reads are bounded.
- Marketplace filtering is supported if available through existing data.

Status:

- Complete.

### Task 6: Public FastAPI Routes

Add public read-only routes under `/api/v1/public`.

Acceptance criteria:

- Routes are read-only.
- Responses use public DTOs.
- Errors are sanitized.
- Pagination and sorting are bounded.
- Routes do not require seller/admin authentication unless explicitly changed in
  a future product decision.

Status:

- Complete.

### Task 7: Repository-Backed Public Query Adapter

Create a public read adapter that uses the existing `RepositoryProvider` and
repository contracts to populate public read projections.

Acceptance criteria:

- Product cards are derived from `CanonicalProduct`, `ParsedOffer`, and price
  history repositories.
- Offer lists are derived from persisted `ParsedOffer` objects.
- Comparison results reuse the existing selector, difference calculator, and
  result builder.
- Latest price changes are projected only from already durable eligible
  price-drop events.
- Categories are derived from canonical products.
- No lifecycle state is mutated.
- No FastAPI, SQLAlchemy, or UI dependency is introduced into the adapter.

Status:

- Complete.

### Task 8: Saved-Payload UI Readiness Verification

Verify that GGSEL, Playerok, and FunPay saved or verified marketplace payloads
can populate the public DTOs required by Market Terminal.

Acceptance criteria:

- Product card DTOs can be created.
- Offer summary DTOs can be created.
- Comparison DTOs can be created when canonical product candidates are present.
- Any missing data is documented rather than invented.

Status:

- Complete.

Verification:

- `scripts/verify_public_ui_readiness.py` passed `25` public DTO/route checks.
- GGSEL saved payload: `60` raw, `60` parsed, `60` snapshot-ready offers.
- Playerok saved payload: `20` raw, `20` parsed, `20` snapshot-ready offers.
- FunPay saved payload: `1` raw, `1` parsed, `1` snapshot-ready offer.
- Latest price-change feed remains empty from saved payloads because no previous
  snapshot/durable scored event is present in those payloads.
- Category feed remains empty from saved payloads because category data is not
  retained by the current `ParsedOffer` contract.

### Task 9: Application Bootstrap Wiring

Wire the public read provider into the default FastAPI composition root without
changing route behavior or adding a separate SQL adapter.

Acceptance criteria:

- `create_app()` configures a default PostgreSQL-backed public read scope.
- The default scope reuses `RepositoryProvider` and the repository-backed public
  read adapter.
- Explicit `public_read_repository_scope_factory=None` remains available for
  unavailable-provider tests.
- No marketplace, comparator, admin, Telegram, or tenant behavior changes.

Status:

- Complete.

### Task 10: Embedded Market Terminal Shell

Add a minimal embedded visual shell that consumes the public read API without
introducing a separate frontend build stack.

Acceptance criteria:

- FastAPI serves `/terminal`, `/terminal/styles.css`, and `/terminal/app.js`.
- The shell uses only `/api/v1/public` routes.
- No marketplace, repository, comparator, tenant, admin, Telegram, or AI
  behavior changes.
- The UI remains an early integration shell, not a production frontend
  commitment.

Status:

- Complete.

### Task 11: Market Terminal Runtime Summary

Expose a compact visual summary of the public catalog response without adding
new backend contracts or duplicating query logic in the UI.

Acceptance criteria:

- The shell reports products, indexed offers, categories, and recent price
  drops from the existing public API responses.
- Search and refresh controls expose a clear busy state while requests run.
- The summary remains compact and responsive on desktop and mobile.
- No public API, marketplace, repository, comparator, or domain behavior
  changes.

Status:

- Complete.

### Task 12: Public Catalog Controls

Connect the embedded catalog controls to filtering and sorting capabilities
already exposed by the public product endpoint.

Acceptance criteria:

- Buyers can filter visible products by GGSEL, Playerok, or FunPay.
- Buyers can sort by latest update, lowest price, highest price, or product name.
- The shell sends only documented public product query parameters.
- Controls remain accessible, responsive, and disabled while requests run.
- No backend query, marketplace, matching, or comparator behavior changes.

Status:

- Complete.

### Task 13: Category Browse Interaction

Connect category summaries to the existing public product category filter.

Acceptance criteria:

- Available categories are rendered as accessible filter buttons.
- Selecting a category reloads products through the documented `category`
  query parameter.
- The active category is visible and can be reset without a page reload.
- Category controls share the existing request busy state.
- No category inference, parser changes, or frontend-owned matching logic.

Status:

- Complete.

### Task 14: Public Price Range Control

Connect minimum and maximum price controls to the existing public product
query contract.

Acceptance criteria:

- Buyers can submit optional non-negative minimum and maximum prices.
- The UI prevents a reversed explicit range before making a request.
- Exact decimal validation remains owned by the public API schema.
- Controls share the existing accessible request busy state.
- No currency conversion or frontend-owned price comparison logic.

Status:

- Complete.

### Task 15: Shareable Terminal State

Keep public catalog filters and explicit product selection in the browser URL
without introducing a frontend router or new backend contracts.

Acceptance criteria:

- Search, marketplace, category, sort, direction, and price bounds survive a
  page reload.
- Explicit product selection is addressable through a URL parameter.
- Browser Back and Forward restore the corresponding public read state.
- Unknown select values safely fall back to documented defaults.
- No server-side session, consumer identity, or persistence changes.

Status:

- Complete.

### Task 16: Currency-Safe Price History View

Improve the existing history presentation without changing price-history data
or introducing client-owned analytics.

Acceptance criteria:

- History points are never plotted in one numeric series across currencies.
- Each currency series reports its own low, high, and latest displayed value.
- Point labels identify marketplace, price, and collection date.
- The UI uses only the existing public price-history response.
- No conversion rates, persisted aggregates, or backend behavior changes.

Status:

- Complete.

### Task 17: Price-Drop Detail Navigation

Connect public price-drop cards to the existing product detail flow when a
canonical product identifier is available.

Acceptance criteria:

- Each price-drop card shows marketplace, date, old price, new price, and
  discount percentage from the existing response.
- Entries with `product_id` open the existing comparison/detail panel.
- Entries without `product_id` remain readable and are not presented as links.
- Explicit selection reuses shareable product URL state.
- Reduced-motion preferences are respected for page navigation.
- No event, comparison, or price-change calculations are duplicated.

Status:

- Complete.

### Task 18: Embedded Shell Security Boundary

Harden the dependency-free browser shell at its HTML rendering and response
boundaries without changing public API data.

Acceptance criteria:

- Dynamic money, currency, product, category, and comparison labels are escaped
  before insertion through `innerHTML`.
- External marketplace links accept only HTTP(S), use an escaped attribute, and
  isolate opened tabs with `noopener noreferrer`.
- The terminal document sets a same-origin Content Security Policy, denies
  framing and unused browser permissions, and enables MIME sniffing protection.
- Static CSS and JavaScript responses enable MIME sniffing protection.
- No global middleware, authentication, API DTO, or marketplace behavior changes.

Status:

- Complete.

### Task 19: Product Detail Request Consistency

Prevent an older asynchronous product response from replacing the detail view
for a newer buyer selection.

Acceptance criteria:

- Each detail selection carries a monotonically increasing local request
  version.
- Offers, comparison, and history render only when both request version and
  selected product still match.
- Stale success and failure responses are ignored.
- The detail region exposes an accessible busy state and clear loading copy.
- Product cards remain available so the buyer can change selection.
- No API cancellation contract, backend state, or product behavior changes.

Status:

- Complete.

### Task 20: Catalog Request Consistency

Prevent an older asynchronous product-list response from replacing catalog
results for newer search, filter, refresh, or browser-history state.

Acceptance criteria:

- Each catalog request carries a monotonically increasing local request
  version.
- Product results, API errors, default product selection, and catalog summary
  updates are applied only by the current request.
- A stale request cannot clear the busy state of a newer request.
- Dashboard refresh and focused product search share the same consistency
  boundary.
- No request cancellation contract, API change, or frontend-owned search logic.

Status:

- Complete.

### Task 21: Product Detail Partial-Failure Isolation

Keep successfully loaded product information visible when one independent
detail endpoint is temporarily unavailable.

Acceptance criteria:

- Product summary, offers, comparison, and price history settle independently.
- A failed request renders a local error only in its corresponding section.
- Successfully loaded sections remain visible and interactive.
- Existing stale-response protection applies before any settled result renders.
- Unexpected rendering failures retain the existing safe whole-panel fallback.
- No API, retry, persistence, or comparison behavior changes.

Status:

- Complete.

### Task 22: Bounded Browser API Requests

Prevent an unavailable public endpoint from leaving the embedded terminal in an
indefinite loading state.

Acceptance criteria:

- Every browser request through the shared public JSON boundary has one explicit
  timeout.
- Timeout cancellation covers response-body reading as well as connection setup.
- Buyers receive a stable retry-oriented timeout message.
- The timeout resource is released after success, HTTP failure, parse failure,
  or cancellation.
- Existing stale-response and partial-failure handling remains unchanged.
- No automatic retries, backend timeout changes, or new dependencies.

Status:

- Complete.

### Task 23: Safe Public JSON Response Boundary

Keep proxy failures and malformed public responses from leaking low-level parse
errors into the buyer interface.

Acceptance criteria:

- Successful public responses must contain a non-empty JSON object and a JSON or
  structured-suffix JSON content type.
- Empty, malformed, array, primitive, and non-JSON success responses fail with a
  stable public-facing message.
- HTTP errors reuse only non-empty string messages from the documented JSON error
  shapes.
- Non-JSON and structurally unknown HTTP errors use a status-based fallback and
  never reflect an HTML response body or browser status text.
- Timeout classification and timer cleanup remain unchanged.
- No response-schema duplication, backend behavior change, or new dependency.

Status:

- Complete.

### Task 24: Accessible Async Result Announcements

Expose asynchronous terminal updates to assistive technology without changing
the visual hierarchy or request behavior.

Acceptance criteria:

- API connectivity is exposed through one polite atomic status region.
- Product, category, and price-drop result containers announce updates politely.
- Offer, comparison, and price-history outputs are separate named regions tied
  to their visible headings.
- Detail result regions announce loading, success, empty, and local failure copy.
- No assertive announcement, focus theft, visual redesign, or API change.

Status:

- Complete.

### Task 25: Strict Style Content Security Policy

Remove the remaining inline-style dependency from the price-history visual so
the embedded terminal no longer requires `style-src 'unsafe-inline'`.

Acceptance criteria:

- Price-history bar heights use a bounded deterministic CSS class scale.
- The relative low-to-high visual remains available without style attributes.
- The terminal CSP permits styles only from the same origin.
- Static shell verification rejects a future `unsafe-inline` regression.
- No chart dependency, API change, or price-history calculation change.

Status:

- Complete.

### Task 26: Dashboard Feed Request Consistency

Prevent older category and price-drop responses from replacing fresher dashboard
feed data after overlapping refresh or browser-history loads.

Acceptance criteria:

- Category and price-drop requests use independent monotonically increasing
  versions.
- Only the latest response for each feed may mutate state, summary counts, or
  rendered content.
- Stale success and failure results are ignored.
- Catalog and product-detail request boundaries remain independent.
- No cancellation contract, polling behavior, API change, or new dependency.

Status:

- Complete.

### Task 27: Keyboard Navigation And Focus Continuity

Keep keyboard and assistive-technology users oriented when bypassing navigation
or opening product details from the price-drop feed.

Acceptance criteria:

- A visible-on-focus skip link moves directly to the public catalog region.
- The catalog target is programmatically focusable and named by its visible
  heading.
- Opening a linked price drop moves focus to the selected product heading before
  scrolling the detail panel.
- Programmatic targets retain an explicit visible focus indicator.
- Sticky navigation does not obscure fragment targets.
- Existing reduced-motion handling applies to the new navigation path.
- No product selection, API, or URL-state behavior changes.

Status:

- Complete.

## Deferred Runtime Constraint

The repository-backed public read adapter currently returns bounded first
pages with `next_cursor=None`. The shared cursor position carries a timestamp
and UUID, which is insufficient for stable continuation of every public
product sort, including name and price. Cursor pagination should be completed
only through an explicit contract design; the embedded shell does not add an
offset or synthetic-cursor workaround.

## Documentation Updates

When this EPIC is implemented, update:

- `docs/MARKET_TERMINAL_INTEGRATION_PLAN.md`
- `docs/PROJECT_PASSPORT/02_ARCHITECTURE.md`
- `docs/PROJECT_PASSPORT/03_DOMAIN_MODEL.md`
- `docs/PROJECT_PASSPORT/11_ROADMAP.md`
- `docs/PROJECT_PASSPORT/13_CURRENT_STATE.md`
- `docs/PROJECT_PASSPORT/15_BACKLOG.md`
- `docs/PROJECT_PASSPORT/16_TECH_LEAD_NOTES.md` if architectural notes are
  required
- `docs/PROJECT_PASSPORT/CHANGELOG.md`

## Verification

Each implementation task should run only relevant focused checks first.

Before marking the EPIC complete, run:

- focused tests for public DTOs and public read services;
- FastAPI route tests;
- marketplace saved-payload UI readiness verifier;
- full Pytest;
- MyPy;
- Ruff for touched files;
- Ruff format for touched files;
- PostgreSQL verification if a PostgreSQL query adapter is changed;
- Alembic checks only if a migration is introduced by an approved task.

## First Frontend-Ready Milestone

The embedded `/terminal` shell can now consume these public outputs directly:

- product cards;
- product details;
- offer lists;
- comparison results;
- price-history points;
- latest price changes;
- category list.

The next visual step is production UX hardening and deciding whether the
embedded shell remains in MediaEngine or moves into a dedicated frontend
repository.
