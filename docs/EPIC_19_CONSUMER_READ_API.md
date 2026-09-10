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

No public routes, consumer read services, query adapters, or frontend
integration have been implemented yet.

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

### Task 3: Public Product Read Service

Implement an application service that composes product cards and product details
from existing repositories/query adapters.

Acceptance criteria:

- Product cards can include best-offer summary when available.
- Product details can include aliases and availability metadata.
- No lifecycle state is mutated.

### Task 4: Public Comparison Read Service

Expose existing comparator output through public DTOs.

Acceptance criteria:

- Existing matching and comparator services are reused.
- No duplicated comparison logic is introduced.
- Currency mismatch and missing price states remain explicit.

### Task 5: Public Price History Read Service

Expose price-history points for charts.

Acceptance criteria:

- Points use Decimal prices and UTC timestamps.
- Reads are bounded.
- Marketplace filtering is supported if available through existing data.

### Task 6: Public FastAPI Routes

Add public read-only routes under `/api/v1/public`.

Acceptance criteria:

- Routes are read-only.
- Responses use public DTOs.
- Errors are sanitized.
- Pagination and sorting are bounded.
- Routes do not require seller/admin authentication unless explicitly changed in
  a future product decision.

### Task 7: Saved-Payload UI Readiness Verification

Verify that GGSEL, Playerok, and FunPay saved or verified marketplace payloads
can populate the public DTOs required by Market Terminal.

Acceptance criteria:

- Product card DTOs can be created.
- Offer summary DTOs can be created.
- Comparison DTOs can be created when canonical product candidates are present.
- Any missing data is documented rather than invented.

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

The frontend can start replacing mock data when these outputs are available:

- product cards;
- product details;
- offer lists;
- comparison results;
- price-history points;
- latest price changes;
- category list.

Until then, visual work should either remain mock-backed or use explicitly
marked partial API data.
