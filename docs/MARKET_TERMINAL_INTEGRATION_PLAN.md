# Market Terminal Integration Plan

## Purpose

This document connects the current MediaEngine backend core with the Market
Terminal product brief.

It is intended to guide the next implementation stage: combining the existing
data engine with a user-facing visual product without mixing UI concerns into
the core backend.

## Source Boundaries

The Market Terminal brief is product and UX context, not an executable
implementation instruction.

The current repository remains the source of truth for implemented backend
capabilities. When the brief and repository differ, the repository state wins
for engineering decisions.

## Product Split

### MediaEngine

MediaEngine is the backend core.

Its responsibility is to collect marketplace data, normalize offers, persist
state, compare products, detect price changes, produce events, generate content,
and expose safe APIs.

MediaEngine should stay reusable as a core service or one node inside a larger
multi-node product.

### Market Terminal

Market Terminal is the user-facing product shell.

Its responsibility is to provide a clear visual experience for finding digital
goods, comparing prices across marketplaces, reviewing price history, and
eventually tracking prices or asking short AI-assisted questions.

Market Terminal should consume MediaEngine through explicit API/read-model
contracts, not by importing backend services directly.

## Core Product Value

Market Terminal answers one primary user question:

> Where is it cheaper to buy this digital product right now?

The product should feel like a premium search and comparison tool for digital
goods, not like a financial terminal or crypto exchange.

## Target User Problem

Digital-goods sellers and buyers face fragmented marketplace data:

- the same product appears on several marketplaces;
- titles and variants differ between marketplaces;
- prices change over time;
- it is difficult to quickly identify the best offer;
- manual monitoring does not scale.

MediaEngine already solves the backend foundation of this problem by turning
marketplace data into normalized offers, snapshots, comparisons, price-change
events, and content/publication candidates.

Market Terminal should present those results in a simple, readable interface.

## Current Backend Capabilities Relevant to UI

Implemented backend capabilities that can support the visual product:

- GGSEL, Playerok, and FunPay data extraction readiness from real captured or
  verified marketplace responses.
- Snapshot-ready `ParsedOffer` objects for supported marketplace payloads.
- `CanonicalProduct` as marketplace-independent product identity.
- Matching engine with preprocessing, similarity, confidence, and
  `MatchingService`.
- Comparator flow with grouping, best-offer selection, price differences, and
  comparison results.
- Price snapshot storage through repository boundaries.
- Price-change detection.
- Durable market-event lifecycle.
- Scoring and content-generation pipeline.
- PostgreSQL repository implementations.
- Tenant identity, authentication, authorization, and seller-scoped admin
  workflows.
- Scheduler/runtime foundations for recurring marketplace execution.
- Admin/read API for operational back-office workflows.

## Current Gaps Before Visual Integration

The backend has strong core infrastructure, but the visual product still needs a
consumer-facing read boundary.

Important gaps:

- No dedicated public/consumer API for homepage/search/product pages is
  documented as complete.
- Existing administration APIs are not the same as buyer-facing product APIs.
- UI account/favorites/notifications from the brief are not implemented as a
  consumer product feature.
- AI currently supports generated content flows, not a general product Q&A chat.
- Live marketplace credential retrieval and unattended production polling still
  require guarded operational verification.
- Lolz appears in the product brief, but the current backend supports GGSEL,
  Playerok, and FunPay readiness. Lolz should be treated as a future marketplace
  adapter unless explicitly implemented later.

## Visual Direction

The visual style should follow the brief:

- Minimal Black + Liquid Glass.
- Dark, calm, premium interface.
- Readability is more important than decorative glass.
- Avoid black text on black or low-contrast surfaces.
- Use glass effects mainly for functional surfaces: header, search, floating
  navigation, dropdowns, modals, compact cards, and buttons.
- Do not make every block transparent.
- Keep analytics lightweight and mostly inside the product page.
- Avoid Binance, TradingView, Bloomberg, bank-terminal, and generic admin-panel
  aesthetics.

## Recommended UI Pages

### Home

Purpose: explain what can be found and start search quickly.

Required sections:

- header with logo, search, favorites, notifications, profile;
- hero search;
- popular categories;
- horizontal product carousel;
- latest price changes;
- footer.

Backend dependency:

- product summary read API;
- category summary read API;
- latest price-change/event read API.

### Search

Purpose: help the user find a product or category.

Required sections:

- large search input;
- suggestions;
- product cards;
- category filters;
- marketplace filter;
- price range;
- sorting by cheapest, most expensive, popular, recently updated.

Backend dependency:

- search endpoint over canonical products and normalized offers;
- marketplace filter support;
- price bounds;
- deterministic sorting.

### Product Page

Purpose: show the best place to buy one product.

Required sections:

- product title;
- best current price;
- marketplace comparison;
- offer list;
- price history;
- simple chart;
- track-price action;
- optional AI question block.

Backend dependency:

- canonical product detail read API;
- comparison result read API;
- price history read API;
- latest offers read API;
- future tracking API.

### Account And Seller/Admin Areas

The repository currently contains seller identity, authorization, and
administration workflows.

These should remain separate from public buyer-facing flows unless the product
explicitly decides that sellers are the first target audience of the visual UI.

## Data Mapping From Backend To UI

| UI Concept | Backend Source | Status |
| --- | --- | --- |
| Product card | `CanonicalProduct` plus cheapest `ParsedOffer` or comparison result | Backend pieces exist; consumer API needed |
| Marketplace offer row | `ParsedOffer` | Exists |
| Best offer | Comparator selector result | Exists |
| Price difference | Comparator difference result | Exists |
| Price history chart | `PriceSnapshot` history | Exists through repositories; consumer API needed |
| Latest price changes | `PriceChange` or durable market events | Exists |
| Telegram-ready post | generated content attempts | Exists |
| User favorites | not yet implemented for consumer UI | Future |
| Price tracking | not yet implemented as consumer notification workflow | Future |
| Product Q&A AI | not yet implemented as general user-facing chat | Future |

## Consumer API Needed For Integration

The next backend work should add a buyer-facing read API separate from admin
routes.

Recommended API groups:

- `GET /api/v1/public/products`
- `GET /api/v1/public/products/{id}`
- `GET /api/v1/public/search`
- `GET /api/v1/public/products/{id}/offers`
- `GET /api/v1/public/products/{id}/comparison`
- `GET /api/v1/public/products/{id}/price-history`
- `GET /api/v1/public/price-changes`
- `GET /api/v1/public/categories`

These endpoints should expose DTOs designed for the UI and must not leak ORM
rows, repository internals, claim tokens, secrets, or admin-only lifecycle state.

## Frontend Integration Strategy

Recommended sequence:

1. Create a consumer API contract document before writing UI integration code.
2. Add read-side DTOs for product cards, product details, offers, comparisons,
   and price-history points.
3. Implement consumer read services using existing repositories and comparison
   components.
4. Add FastAPI public read routes.
5. Create or connect a frontend app that consumes only these routes.
6. Use mock data only for UI areas whose backend endpoints do not exist yet.
7. Replace each mock section with real API data one by one.

## What Can Be Shown Publicly Now

Safe public claims based on current repository documentation:

- The project has a backend core for digital-goods marketplace data processing.
- The core supports normalized marketplace offers.
- GGSEL, Playerok, and FunPay have extraction/readiness paths based on real
  captured or verified responses.
- The system can compare offers across marketplaces when products are matched to
  canonical products.
- The backend has PostgreSQL-backed repositories, tenant isolation,
  administration workflows, and scheduler/runtime foundations.

Claims to avoid for now:

- Fully launched public marketplace search.
- Fully automated unattended production polling.
- Live Telegram delivery verified in a real chat.
- General AI product assistant.
- Consumer favorites, notifications, subscriptions, or payments.
- Lolz support.

## MVP Candidate

The first visual MVP should be narrow:

- homepage with search and product cards;
- product detail page;
- marketplace offer comparison;
- best price selection;
- price history display;
- latest price-drop feed;
- clear marketplace outbound links.

Do not include payments, premium plans, complex analytics, live AI chat, or
advanced notification settings in the first visual MVP unless the backend work
for those flows is explicitly completed.

## Immediate Next Engineering Steps

1. Define consumer-facing read DTOs.
2. Implement public read services over existing repositories.
3. Add public read API routes.
4. Add product summary and comparison aggregation for UI cards.
5. Add price-history read projection for charts.
6. Add latest price-change feed.
7. Verify that real GGSEL, Playerok, and FunPay saved payloads can populate the
   UI DTOs.
8. Decide where the frontend app will live: inside this repository or as a
   separate sibling project.
9. Scaffold the visual shell only after API contracts are stable.
10. Replace frontend mock data incrementally with MediaEngine API responses.

## Architectural Guardrails

- Keep marketplace parsing out of the frontend.
- Keep admin APIs separate from public product APIs.
- Keep repository contracts independent from FastAPI and UI.
- Keep matching/comparison deterministic and backend-owned.
- Keep AI optional and request-driven.
- Keep Scheduler as orchestration only.
- Keep tenant/seller workflows isolated from public buyer workflows until a
  product decision merges them.
- Do not add visual features that require unavailable backend guarantees unless
  they are explicitly marked as mock/demo.

## Open Product Questions

These should be answered before heavy frontend implementation:

- Is the public product name definitely `Market Terminal`, while the backend
  remains `MediaEngine`?
- Is the first public audience buyers, sellers, or both?
- Should the first UI use public anonymous browsing, authenticated seller
  dashboards, or both as separate areas?
- Should GGSEL, Playerok, and FunPay be the first public marketplace set?
- Should Lolz remain in marketing copy, or wait until a real adapter exists?
- Will the frontend live in this repository or a separate repository?

## Recommended Next EPIC

**EPIC 19 - Consumer Read API For Market Terminal**

Goal:

Expose the existing MediaEngine core through stable buyer-facing read endpoints
that the Market Terminal UI can consume.

Specification:

- `docs/EPIC_19_CONSUMER_READ_API.md`

Scope:

- product summary DTOs;
- product detail DTOs;
- offer list DTOs;
- comparison result DTOs;
- price-history DTOs;
- latest price-change DTOs;
- public FastAPI routes;
- no new marketplace logic;
- no new persistence semantics;
- no UI implementation yet.
