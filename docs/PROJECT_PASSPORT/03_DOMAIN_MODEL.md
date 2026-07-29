# Domain Model

## Purpose

This document records the domain and data-transfer models currently used by MediaEngine.

## CanonicalProduct

`CanonicalProduct` is the marketplace-independent representation of a product.

Fields:

- `id`: unique product identifier.
- `name`: canonical product name.
- `category`: optional category name.
- `aliases`: immutable tuple of known product aliases.

`CanonicalProduct` is a dataclass and does not depend on a database or marketplace.

## RawMarketplaceOffer

`RawMarketplaceOffer` is the typed raw marketplace payload boundary before normalization.

Fields:

- `id_goods`: source product identifier.
- `name`: raw product name.
- `url`: raw source URL or slug.
- `seller_name`: seller display name from the source.
- `id_section`: source section identifier.
- `image`: optional image URL.
- `price`: optional raw price when available in the generic field.
- `currency`: optional raw currency when available in the generic field.
- `extra`: unknown source fields preserved without interpretation.

## ParsedOffer

`ParsedOffer` is the internal normalized offer format produced by marketplace parsing.

Fields:

- `marketplace`: marketplace code.
- `external_id`: source-side offer identifier.
- `title`: source offer title.
- `url`: source offer URL.
- `price`: offer price as `Decimal`, when available.
- `currency`: price currency, when available.
- `seller_id`: optional source seller identifier.
- `seller_name`: optional source seller display name.
- `canonical_product_id`: optional link to `CanonicalProduct`.

`ParsedOffer` is not a database model and does not contain matching logic.

## PriceSnapshot

`PriceSnapshot` stores a database-independent snapshot of a marketplace price at collection time.

Fields:

- `marketplace`
- `external_id`
- `price`
- `currency`
- `collected_at`

Snapshots are identified for history lookup by `(marketplace, external_id)`.
History is ordered by `collected_at`; equal timestamps use backend insertion
identity as a deterministic tie-break. Exact duplicate snapshots are ignored.
PostgreSQL stores `collected_at` as a timezone-aware value; runtime timestamps
are UTC.

## PriceHistoryRepository

`PriceHistoryRepository` is the active persistence boundary for price snapshots.
It supports adding snapshots and loading the latest, previous, or complete ordered
history. Memory and PostgreSQL implementations expose the same asynchronous
contract through `RepositoryProvider.price_history`. `add()` returns `True` when
a new snapshot is inserted and `False` when an exact duplicate is suppressed.

## PriceChange

`PriceChange` represents a calculated difference between two `PriceSnapshot` objects.

It contains previous/current prices, difference, percentage, drop flag, marketplace, product identifier, and timestamp.

## PriceDropEvent

`PriceDropEvent` is the temporary Pydantic application DTO used by the existing
post-commit scoring and content flow.

It includes product title, marketplace, old price, new price, currency, and computed discount percentage.

## Persistent MarketEvent

`MarketEvent[PriceDropPayload]` is the immutable durable source of truth for a
detected price drop. It uses `Decimal`, UTC-aware timestamps, a versioned
deterministic identity, optional canonical-product context, and exact previous and
current `SnapshotIdentity` values.

Identity is derived from event type, marketplace, external ID, and exact snapshot
facts. Title, URL, canonical product, score, and generated content are excluded.
The PostgreSQL repository resolves the exact snapshot rows internally, so ORM IDs
do not leak into the domain.

Only a newly created durable event is adapted to `PriceDropEvent` after commit.
Scoring state and generated content are not yet persisted.

## Matching Models

`MatchResult` is returned by `MatchingService`.

Fields:

- `decision`: `MatchDecision`.
- `similarity`: calculated similarity score.
- `canonical_product`: best matching `CanonicalProduct`, or `None`.

`MatchDecision` values:

- `AUTO_MATCH`
- `REVIEW`
- `NO_MATCH`
