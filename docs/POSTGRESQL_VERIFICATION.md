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
- Business pipelines still need explicit integration with async PostgreSQL repositories before they can be switched wholesale.
- Existing marketplace demos can still run on memory repositories.
- A running PostgreSQL instance with Alembic migrations applied is required for the verification script.
- The script verifies repository-backed backend flow, not live marketplace HTTP reliability.

## Readiness Assessment

- RepositoryProvider PostgreSQL selection: ready for controlled use.
- PostgreSQL offer persistence: ready for integration testing.
- PostgreSQL canonical product persistence: ready for integration testing.
- PostgreSQL price history persistence: ready for integration testing.
- Full backend with PostgreSQL repositories: partially ready.
- Production persistence readiness: not complete until business pipelines are adapted to async repository usage and run against migrated PostgreSQL.
