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

### Task 28: Offline Embedded Shell Integration Verification

Extend the saved-payload readiness proof through the embedded terminal delivery
surface without adding browser automation or a second verification path.

Acceptance criteria:

- The existing saved-payload verifier serves `/terminal` and both static assets
  through the real FastAPI application.
- The delivered script remains bound to every current public product, offer,
  comparison, history, category, and price-change route.
- The delivered document retains its strict same-origin CSP without
  `unsafe-inline`.
- GGSEL, Playerok, and FunPay saved payloads continue through repository-backed
  public route DTOs in the same run.
- Missing historical price changes and retained category data remain explicit
  notes rather than fabricated UI data.
- No browser dependency, marketplace behavior, persistence, or API change.

Status:

- Complete.

Verification:

- `scripts/verify_public_ui_readiness.py` passed `42` checks.
- GGSEL: `60` raw, `60` parsed, `60` snapshot-ready offers.
- Playerok: `20` raw, `20` parsed, `20` snapshot-ready offers.
- FunPay: `1` raw, `1` parsed, `1` snapshot-ready offer.
- This verifier proves offline delivery and binding, not browser layout or live
  marketplace polling.

### Task 29: PostgreSQL-Backed Public UI Verification

Verify the delivered public shell and read API through the default PostgreSQL
composition root rather than an injected memory provider.

Acceptance criteria:

- An isolated PostgreSQL 17 database upgrades from an empty schema to the
  current Alembic head.
- Saved real GGSEL, Playerok, and FunPay examples are persisted through existing
  repository contracts.
- The unmodified `create_app()` public read scope returns product, offer,
  comparison, and price-history DTOs from PostgreSQL.
- Marketplace filters remain isolated and current payloads do not fabricate
  unavailable price-change or category data.
- A disposed engine pool and fresh application client can read the committed
  records again.
- No application behavior, public API contract, migration, or dependency
  changes are introduced.

Status:

- Complete.

Verification:

- `scripts/verify_epic19_public_ui_postgres.py` passed `63/63` checks against a
  temporary PostgreSQL 17.10 database.
- `alembic current` reported `0014_scheduler_leases (head)`.
- `alembic check` reported no new upgrade operations.
- Offline `upgrade head --sql` generation completed successfully.
- The same saved marketplace readiness remained GGSEL `60/60/60`, Playerok
  `20/20/20`, and FunPay `1/1/1` for raw/parsed/snapshot-ready records.

### Task 30: Russian Consumer UI Copy

Align the embedded Market Terminal language with the approved Russian consumer
product brief without changing its visual hierarchy or behavior.

Acceptance criteria:

- The document language, navigation, search, filters, summaries, product detail,
  empty states, loading states, and accessibility labels use Russian copy.
- Comparison statuses and unavailable-difference reasons are translated only at
  the presentation boundary.
- Russian plural forms are deterministic for offer, marketplace, and history
  counts.
- Dates render explicitly with the `ru-RU` locale.
- Marketplace, product, currency, and other source-owned names remain unchanged.
- Public API contracts, request flow, repository behavior, and styling remain
  unchanged.

Status:

- Complete.

Verification:

- `node --check app/web/market_terminal/app.js` passed.
- Focused terminal shell tests passed: `2 passed`.
- Saved-payload public UI readiness remained `42/42`.

### Task 31: Local Real-Data Preview Entrypoint

Make the embedded Market Terminal directly reviewable in a browser without
requiring a local PostgreSQL service or introducing mock product data.

Acceptance criteria:

- One command builds a preview from the existing saved real GGSEL, Playerok, and
  FunPay payloads.
- Existing normalizers, repository contracts, public read adapter, and FastAPI
  application factory are reused.
- The preview uses memory repositories only and binds Uvicorn to
  `127.0.0.1`.
- Admin API and API documentation are disabled in the preview composition.
- Missing or drifted saved payloads produce a clear failure instead of fake
  successful data.
- A `--check` mode verifies shell and product routes without starting a
  long-running server.
- Production composition and application behavior remain unchanged.

Status:

- Complete.

Verification:

- `python scripts/run_market_terminal_preview.py --check` passed with three
  products built from saved marketplace payloads.
- A real loopback Uvicorn run returned HTTP 200 for `/terminal` and
  `/api/v1/public/products`; the delivered document retained `lang="ru"`.

### Task 32: Cross-Marketplace Matching Readiness Evidence

Measure whether the saved real marketplace offers can demonstrate the core
same-product comparison value without inventing canonical-product links or
weakening the existing deterministic matching thresholds.

Acceptance criteria:

- Every normalized offer from the saved GGSEL, Playerok, and FunPay payloads is
  included, not only the examples selected for the UI preview.
- Only offers from different marketplaces are compared.
- Existing `MatchingPreprocessor`, `SimilarityEngine`, and `ConfidenceEngine`
  behavior is reused without threshold or business-logic changes.
- Empty titles cannot become false exact matches.
- Results are deterministic and report automatic, review, and no-match counts
  plus the highest-scoring candidates.
- The local UI preview explicitly states that its source examples are seeded as
  separate canonical products and do not prove cross-marketplace identity.

Status:

- Complete.

Verification:

- `81` real saved offers produced `1,280` cross-marketplace title pairs.
- Current matching classified `0` pairs as `AUTO_MATCH`, `0` as `REVIEW`, and
  `1,280` as `NO_MATCH`; the highest similarity was `0.294`.
- The result proves that curated canonical catalog/bootstrap work is required
  before the saved-payload preview can demonstrate a real same-product price
  comparison.
- Matching thresholds and comparator behavior remain unchanged.
- Focused tests passed: `7 passed`; full Pytest passed: `412 passed, 58
  skipped`; MyPy passed for `388` source files; focused Ruff and Ruff format
  checks passed.

### Task 33: Playerok Category-Scoped Source Verification

Add the missing source-selection primitive needed to collect aligned Playerok
offers without changing matching, comparison, or public read contracts.

Acceptance criteria:

- The existing public GraphQL `items` request optionally accepts verified
  `gameId` and `gameCategoryId` filters.
- Omitting both filters preserves the existing all-approved-items payload.
- A real category demo performs extraction and normalization without persistence
  or mock data.
- Empty, invalid, or non-snapshot-ready responses fail visibly.
- No matching threshold, canonical-product link, or category field is invented.

Status:

- Complete.

Verification:

- The public Minecraft `Keys` request returned HTTP 200 and JSON.
- Playerok reported `208` source offers; the first page produced `20` extracted
  and `20` snapshot-ready normalized offers.
- The response included a real Minecraft Java and Bedrock key offer suitable for
  later cross-marketplace identity review.
- Category metadata remains marketplace-source context and is not yet retained
  by the universal `ParsedOffer` contract.

### Task 34: Aligned Marketplace Category Evidence

Verify one equivalent public category across GGSEL, Playerok, and FunPay before
any canonical-product bootstrap or matching adjustment.

Acceptance criteria:

- Existing fetcher, extractor, and normalizer implementations are reused.
- GGSEL and FunPay use public Minecraft PC key category URLs; Playerok uses the
  verified Minecraft Keys GraphQL filter.
- Only real public responses are accepted and no payload is committed.
- Every source reports parsed and snapshot-ready counts independently.
- Existing deterministic matching components analyze cross-source titles
  without threshold changes or invented identity links.

Status:

- Complete.

Verification:

- GGSEL produced `60/60` parsed and snapshot-ready offers.
- Playerok produced `20/20` first-page offers from a live source total of `209`.
- FunPay produced `1,313/1,313` parsed and snapshot-ready offers.
- The `1,393` aligned-category offers produced `106,240` cross-marketplace title
  pairs: `0` `AUTO_MATCH`, `0` `REVIEW`, and a highest similarity of `0.714`.
- The strongest candidates are visibly related Minecraft Java and Bedrock PC
  key variants, but category alignment alone is not treated as product identity
  proof.

### Task 35: Curated Canonical Offer Links

Make explicit reviewed offer links effective in the existing comparison flow
without weakening automatic title matching.

Acceptance criteria:

- A tenant-scoped application service links one existing offer to one existing
  canonical product through repository scopes.
- Linking the same pair is idempotent.
- Missing products/offers, cross-tenant targets, and silent reassignment fail
  without mutation.
- `OfferGroupingService` treats a valid persisted `canonical_product_id` as
  authoritative and uses existing `MatchingService` only for unlinked offers.
- Automatic matching considers canonical candidates from the offer's tenant
  only.
- No schema, matching threshold, marketplace parser, or API change is made.

Status:

- Complete.

Verification:

- Focused tests cover explicit grouping, idempotency, conflicts, missing
  records, unresolved links, automatic fallback, and tenant isolation.
- The memory demo links two differently titled marketplace offers and the
  existing selector/difference/result chain returns one `complete` comparison
  with the lower-priced offer selected.
- The linking primitive is internal only. Admin review endpoints, immutable
  decision audit, and rejected-pair suppression are not claimed by this task.

### Task 36: Tenant-Safe Canonical Link Persistence

Protect curated canonical offer links at the PostgreSQL boundary without
changing repository or comparator contracts.

Acceptance criteria:

- A composite foreign key requires an offer link to reference a canonical
  product owned by the same tenant.
- Existing cross-tenant links stop migration `0015_tenant_canonical_links`
  with a diagnostic instead of being silently rewritten.
- A partial tenant/canonical-product index supports grouped reads.
- Existing canonical-product deletion semantics continue to clear optional
  offer links.
- The migration is reversible and SQLAlchemy metadata matches PostgreSQL.

Status:

- Complete.

Verification:

- `scripts/verify_canonical_links_postgres.py` passed `15/15` checks against an
  isolated PostgreSQL 17 test database.
- Same-tenant linking, idempotent replay, fresh-session persistence, explicit
  comparator grouping, service-level tenant isolation, database-level tenant
  isolation, rollback, and `ON DELETE SET NULL` behavior passed.
- Alembic current/check, downgrade to `0014_scheduler_leases`, upgrade back to
  `0015_tenant_canonical_links`, and offline upgrade SQL passed.
- This task protects reviewed links; it does not create catalog records,
  approve matches automatically, or add an administration workflow.

### Task 37: Persistent Canonical Offer Review Foundation

Persist explicit confirm/reject decisions for one tenant-owned offer and
canonical-product pair without coupling matching to HTTP or PostgreSQL.

Acceptance criteria:

- Immutable decisions record tenant, pair identity, outcome, actor, reason,
  request correlation, idempotency key, fingerprint, and UTC creation time.
- Memory and PostgreSQL repositories expose the same append-only contract
  through `RepositoryProvider`.
- Confirmation writes the durable decision and existing offer link atomically.
- Rejection records a terminal pair decision without changing the offer.
- Replays require the original idempotency key; conflicting keys or outcomes
  fail without mutation.
- Cross-tenant references, concurrent conflicting decisions, and partial writes
  are rejected or rolled back.

Status:

- Complete for domain, repository, and application-service foundations.

Verification:

- Migration `0016_canonical_offer_decisions` adds tenant/product foreign keys,
  pair and idempotency uniqueness, bounded checks, and offer-history indexing.
- `scripts/verify_canonical_offer_review_postgres.py` passed `20/20` checks on
  isolated PostgreSQL 17.
- Alembic current/check, downgrade to `0015_tenant_canonical_links`, upgrade
  back to head, and offline SQL passed.
- Reviewed canonical products are delete-restricted so immutable decision
  evidence cannot be removed accidentally; failed deletion rolls back.
- Full Pytest passed `430` tests with `58` expected skips; MyPy checked `402`
  source files; Ruff and Ruff format passed for all touched Python files.
- Seller/admin routes and rejected-pair candidate filtering are implemented by
  Task 38; no automatic matching behavior changed in this foundation task.

### Task 38: Tenant-Authorized Canonical Offer Review API

Expose the existing deterministic review and immutable decision boundaries to
authorized seller users without moving matching or persistence policy into
FastAPI.

Acceptance criteria:

- Owner, administrator, and reviewer roles receive an explicit
  `catalog_review` permission; viewer and operator roles do not.
- The tenant review queue reuses `MatchingService` and includes only unresolved
  candidates already classified as `REVIEW` by the unchanged thresholds.
- Persisted terminal pairs are removed before matching so a rejected best pair
  can reveal the next eligible candidate.
- Terminal decisions are loaded once per tenant rather than queried once per
  offer, avoiding an N+1 read path for real marketplace batches.
- Confirm and reject routes delegate to `CanonicalOfferReviewService`, require
  `Idempotency-Key`, retain request/actor evidence, and return sanitized errors.
- Confirmation atomically links the offer; rejection leaves it unlinked.
- The API remains tenant-isolated and does not call marketplace sources, AI, or
  Telegram.

Status:

- Complete.

Verification:

- New memory service/API tests pass `6/6`; the focused canonical review suite
  passes `14/14`.
- `scripts/verify_catalog_review_api_postgres.py` passes `12/12` checks against
  isolated PostgreSQL 17, including permissions, tenant hiding, rejected-pair
  fallback, idempotency conflict redaction, linking, replay, and fresh-engine
  persistence.
- Alembic current/check, downgrade to `0015_tenant_canonical_links`, upgrade
  back to `0016_canonical_offer_decisions`, and offline SQL pass.
- Full Pytest passes `436` tests with `58` expected skips; MyPy checks `408`
  source files; focused Ruff and Ruff format checks pass.

### Task 39: Alias-Aware Canonical Matching

Use the aliases already stored on `CanonicalProduct` as curated matching input
without changing deterministic preprocessing, similarity, confidence, or result
contracts.

Acceptance criteria:

- `MatchingService` scores each candidate against its canonical name and every
  non-empty alias, then keeps that candidate's strongest score.
- Candidate ordering remains the deterministic tie-break across equal scores.
- Blank aliases cannot turn an empty offer title into a false match.
- Existing `AUTO_MATCH`, `REVIEW`, and `NO_MATCH` thresholds remain unchanged.
- The review queue receives alias-backed `REVIEW` candidates through the same
  `MatchingService`; no API or repository-specific matching logic is added.
- Aliases remain curated catalog metadata and are not inferred from source
  titles by this task.

Status:

- Complete.

Verification:

- Focused matching, review-queue, and curated-link tests pass `16/16`.
- The saved real-data preview still passes with three source products; the
  existing `81`-offer evidence remains `0 AUTO_MATCH / 0 REVIEW`, proving that
  this task does not invent aliases or product identity.
- Full Pytest passes `441` tests with `58` expected skips; MyPy checks `409`
  source files; focused Ruff and Ruff format checks pass.

### Task 40: Read-Only Canonical Product Proposal Queue

Expose deterministic system proposals for unmatched tenant offers without
turning catalog bootstrap into manual CRUD or automatic product creation.

Acceptance criteria:

- The tenant-authorized catalog boundary exposes only unresolved offers already
  classified as `NO_MATCH` by the unchanged `MatchingService`.
- Existing terminal offer/product decisions are excluded before selecting the
  nearest remaining canonical product, using the same bulk tenant read as the
  review queue.
- Proposal identity is deterministic for tenant, marketplace, and external
  offer identity and remains stable across repeated reads and fresh sessions.
- The proposed name is derived only by collapsing whitespace in the source
  title; aliases remain empty and no marketplace facts are invented.
- The endpoint is read-only: it does not create a canonical product, persist a
  proposal, link an offer, or change confidence thresholds.

Status:

- Complete.

Verification:

- Focused queue and seller API tests pass `10/10`, including tenant isolation,
  permission checks, stable identity, incomplete/linked offer exclusion, and
  rematching after terminal evidence.
- `scripts/verify_catalog_review_api_postgres.py` passes `16/16` checks against
  an isolated PostgreSQL 17 database, including proposal source facts,
  deterministic replay, and fresh-engine reproduction.
- Alembic reports `0016_canonical_offer_decisions (head)` with no metadata
  drift; no migration is required for this read-only projection.
- Full Pytest passes `444` tests with `58` expected skips; MyPy checks `409`
  source files; focused Ruff and Ruff format checks pass.

### Task 41: Atomic Canonical Product Proposal Confirmation

Allow an authorized reviewer to accept one still-current system proposal
without introducing manual catalog CRUD or weakening deterministic matching.

Acceptance criteria:

- A catalog reviewer confirms a proposal through an idempotent tenant-scoped
  command protected by the existing `catalog_review` permission.
- The service recomputes the proposal inside the write transaction and rejects
  stale identities, linked offers, and offers no longer classified `NO_MATCH`.
- The stable proposal UUID becomes the created canonical-product UUID. A shared
  offer lock precedes the pair lock so proposal creation and existing-product
  confirmation cannot race to write different links for the same offer.
- The new product uses only the source-derived proposed name, `category=None`,
  and empty aliases; the command invents no catalog metadata.
- Product creation, source-offer linking, and immutable `confirmed` decision
  evidence commit in one repository scope or roll back together.
- Same-key replay returns the original result; fingerprint reuse and competing
  keys fail without creating duplicate products.
- Existing repository contracts, schema, confidence thresholds, and public
  buyer APIs remain unchanged.

Status:

- Complete.

Verification:

- Focused catalog service/API tests pass `25/25`, including success, replay,
  stale and threshold guards, tenant isolation, memory rollback, permissions,
  sanitized conflicts, and concurrent different keys.
- `scripts/verify_canonical_product_proposal_postgres.py` passes `19/19`
  checks against an isolated PostgreSQL 17 database, including atomic writes,
  rollback after a controlled audit failure, same-command and cross-command
  advisory-lock serialization, and fresh-engine persistence.
- Alembic remains at `0016_canonical_offer_decisions (head)` and `check` reports
  no new upgrade operations; no migration is required.
- Full Pytest passes `451` tests with `58` expected skips; MyPy checks `412`
  source files; focused Ruff and Ruff format checks pass.

### Task 42: Existing-Product Resolution for Unmatched Proposals

Allow an authorized reviewer to resolve one still-current `NO_MATCH` proposal
to the existing canonical product displayed by that proposal, without lowering
matching thresholds or creating a duplicate product.

Acceptance criteria:

- The tenant-authorized command requires non-empty human evidence and an
  idempotency key.
- The service recomputes the proposal inside the write transaction and accepts
  only its current nearest canonical product; arbitrary product selection,
  stale proposals, linked offers, and changed matching outcomes fail closed.
- The existing canonical product is reused. No product, alias, category, or
  marketplace fact is invented.
- Source-offer linking and immutable `confirmed` evidence commit atomically or
  roll back together.
- Proposal creation, existing-product resolution, and normal review commands
  share the tenant/marketplace/external-ID offer lock before pair locking.
- Same-key replay returns the original result; changed fingerprints and
  concurrent competing commands cannot create duplicate links or decisions.

Status:

- Complete.

Verification:

- Focused proposal service and seller API tests pass `16/16`, including
  evidence validation, current-target enforcement, replay, fingerprint
  conflicts, no-duplicate behavior, and create/resolve contention.
- `scripts/verify_canonical_product_proposal_postgres.py` passes `27/27`
  checks against an isolated PostgreSQL 17 database, including rollback,
  tenant isolation, shared offer-lock serialization, and fresh-engine
  persistence for existing-product resolution.
- Alembic remains at `0016_canonical_offer_decisions (head)`; `check` reports
  no metadata drift and offline SQL generation succeeds. No migration is
  required.
- Full Pytest passes `456` tests with `58` expected skips; MyPy checks `412`
  source files; focused Ruff and Ruff format checks pass.

### Task 43: Authenticated Catalog Review Workspace

Connect the completed seller catalog-review API to a dedicated embedded UI
without moving matching, proposal, linking, or audit policy into the browser.

Acceptance criteria:

- FastAPI serves a separate `/terminal/review` workspace so authenticated
  seller controls do not become part of the anonymous public catalog.
- Login, refresh, logout, `/me`, and explicit tenant context use the existing
  seller-auth API. Access and refresh tokens remain in memory and are never
  written to browser storage.
- A single shared refresh operation protects parallel queue requests from
  rotating the same refresh token concurrently.
- The workspace lists existing `REVIEW` candidates and `NO_MATCH` proposals,
  then delegates confirm, reject, create-new, and resolve-existing actions to
  the existing tenant-authorized endpoints.
- Every mutation carries an `Idempotency-Key`; ambiguous network/server
  outcomes retain that key for an exact retry instead of silently issuing a
  new command.
- Source values are escaped, external links are protocol-checked, required
  evidence is validated before submission, and the layout remains keyboard,
  screen-reader, desktop, and mobile usable.

Status:

- Complete.

Verification:

- `node --check app/web/market_terminal/review.js` passes.
- Focused terminal/auth/catalog API tests pass `13/13`; full Pytest passes
  `458` tests with `58` expected skips.
- `scripts/run_catalog_review_preview.py --check` verifies login, tenant
  context, `catalog_review`, one review candidate, and one product proposal in
  an isolated memory-only application.
- Full MyPy checks `413` source files; focused Ruff and Ruff format checks pass.
- No repository, schema, matching, or migration change is required. Existing
  PostgreSQL catalog-command verification remains `27/27`.

### Task 44: Saved Real-Data Catalog Review Preview

Exercise the authenticated seller workspace with the existing captured
marketplace payloads without manufacturing catalog identity.

Acceptance criteria:

- `scripts/run_catalog_review_preview.py --saved-data` reuses the existing
  GGSEL, Playerok, and FunPay saved-payload loaders.
- Loaded offers are reassigned only to the isolated preview tenant and stored
  in memory; source identifiers, titles, prices, currencies, and URLs remain
  source-backed.
- Duplicate marketplace/external-ID identities are seeded once, and missing
  source payloads fail with an explicit diagnostic.
- No canonical products, aliases, links, review decisions, or automatic
  matches are seeded for the saved-data mode.
- The original deterministic synthetic preview remains the default.

Status:

- Complete.

Verification:

- The default `--check` mode still verifies one `REVIEW` candidate and one
  `NO_MATCH` proposal.
- `--saved-data --check` loads `60` GGSEL, `20` Playerok, and `1` FunPay offer
  and exposes all `81` as tenant-scoped `NO_MATCH` proposals, with zero
  fabricated `REVIEW` candidates.
- The preview is loopback-only and memory-only; it does not mutate production
  data or claim that any two offers represent the same product.
- Focused seller/UI API tests pass `10/10`; full Pytest passes `458` tests with
  `58` expected skips, MyPy checks `413` source files, and focused Ruff and
  Ruff format checks pass.

### Task 45: PostgreSQL Catalog Onboarding Verification

Prove that the saved real marketplace offers can enter the persistent seller
review boundary without changing application behavior or manufacturing catalog
identity.

Acceptance criteria:

- `scripts/verify_catalog_onboarding_postgres.py` accepts only an isolated
  PostgreSQL database named `epic19_catalog_onboarding_*`.
- A clean Alembic head receives all deduplicated saved GGSEL, Playerok, and
  FunPay offers through the existing PostgreSQL repository scope.
- Replaying the same source batch does not create duplicate offer identities.
- Seller auth, tenant context, the review workspace, and the proposal API work
  over the committed records while foreign tenants remain hidden.
- Onboarding creates no canonical products, aliases, links, or review
  decisions; controlled failure rolls back the complete transaction.
- A fresh engine reproduces the same offer count and deterministic proposal
  identities.

Status:

- Complete.

Verification:

- Isolated PostgreSQL 17 verification passes `20/20` checks for `60` GGSEL,
  `20` Playerok, and `1` FunPay offer.
- All `81` offers remain unlinked source-backed proposals after replay and
  fresh-engine restart; zero review candidates or catalog mutations are
  fabricated.
- Alembic reports `0016_canonical_offer_decisions (head)`, metadata drift is
  absent, and full offline upgrade SQL generation succeeds. No migration is
  required.
- Full Pytest passes `458` tests with `58` expected skips, MyPy checks `414`
  source files, and focused Ruff and Ruff format checks pass.

### Task 46: Cross-Marketplace Review Evidence

Give a human reviewer complete source context for aligned marketplace
candidates without changing confidence thresholds or creating links.

Acceptance criteria:

- Matching candidates retain marketplace ID, title, price, currency, seller,
  and source URL for both sides.
- Live aligned-category output includes the global top candidates and a bounded
  top-five list for every marketplace pair, so one noisy pair cannot hide a
  source.
- Evidence remains diagnostic only; no repository, canonical product, alias,
  link, or review decision is mutated.
- Actual observations and unresolved risks are recorded in
  `docs/CATALOG_REVIEW_EVIDENCE.md`.

Status:

- Complete.

Verification:

- A live public run produced `60/60` GGSEL, `20/20` Playerok, and
  `1,346/1,346` FunPay parsed/snapshot-ready offers.
- All `108,880` aligned title pairs remain `NO_MATCH`; the top-five evidence
  for each of GGSEL/Playerok, GGSEL/FunPay, and Playerok/FunPay includes source
  IDs, current prices, currencies, sellers, and URLs.
- The report identifies one false strongest GGSEL/Playerok pair as `DO NOT
  LINK` and leaves plausible base-edition pairs explicitly unapproved.
- Focused tests pass `4/4`; full Pytest passes `458` tests with `58` expected
  skips, MyPy checks `414` source files, and Ruff/Ruff format pass.

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
