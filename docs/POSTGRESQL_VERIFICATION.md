# PostgreSQL Verification

## Purpose

This document records the first end-to-end backend verification path using PostgreSQL-backed repositories through `RepositoryProvider`.

## Components Verified

- `RepositoryProvider` with PostgreSQL repository selection.
- `PostgresCanonicalProductRepository`.
- `PostgresOfferRepository`.
- `PostgresPriceHistoryRepository`.
- Existing `MatchingService`.
- Existing comparator services: grouping, best-offer selection, price difference, comparison result building.
- Existing price history flow through `PriceSnapshot`.
- Existing `PriceChangeDetector`.
- Existing `EventBuilder`.
- Existing `EventScorer`.
- Existing `ContentGenerator` with `FakeAIProvider`.

## Components Exercised

The verification script exercises this flow:

1. GGSEL and Playerok marketplace outputs are represented as parsed offers.
2. Parsed offers are persisted through PostgreSQL repositories.
3. Canonical products are persisted through PostgreSQL repositories.
4. Persisted offers and canonical products are loaded back from PostgreSQL.
5. Matching and comparator services run on repository-loaded data.
6. Price snapshots are persisted and loaded from PostgreSQL price history.
7. Price change detection creates a price-change result.
8. Event builder creates a price-drop event.
9. Event scorer calculates event priority.
10. Content generator produces deterministic publication text through `FakeAIProvider`.

## Remaining PostgreSQL Limitations

- PostgreSQL repositories are available but are not the default provider.
- Marketplace runtime price history now uses the async repository contract through `RepositoryProvider`.
- A complete marketplace run still does not own one shared `AsyncSession` transaction boundary.
- Existing marketplace demos can still run on memory repositories.
- Exact snapshot duplicate suppression is not protected against concurrent writes by a database uniqueness constraint.
- A running PostgreSQL instance with Alembic migrations applied is required for the verification script.
- The script verifies repository-backed backend flow, not live marketplace HTTP reliability.

## Readiness Assessment

- RepositoryProvider PostgreSQL selection: ready for controlled use.
- PostgreSQL offer persistence: ready for integration testing.
- PostgreSQL canonical product persistence: ready for integration testing.
- PostgreSQL price history persistence: ready for integration testing.
- Full backend with PostgreSQL repositories: structurally compatible, with runtime transaction composition still pending.
- Production persistence readiness: not complete until session ownership, transaction boundaries, and concurrent duplicate protection are implemented and verified.
