# Integration Review

Date: 2026-07-24

## 1. Is The Current Backend Flow Unified?

Partially yes.

The marketplace-to-comparator backend flow is now unified:

GGSEL

-> ParsedOffer

-> RepositoryProvider.offers

-> MatchingService

-> Comparator

-> ComparisonResult

Playerok can participate in the same comparison flow by producing `ParsedOffer` objects and delegating comparison to the existing comparator path.

The full product flow is not yet fully unified:

GGSEL

-> Playerok

-> Repository

-> Matching

-> Comparator

-> ComparisonResult

-> Event

-> Content

The gap is after `ComparisonResult`. Event and content generation currently work through the price snapshot and price-change path, not from comparator results.

## 2. Which Parts Still Operate As Isolated Demos?

The following parts still operate mainly as demos:

- GGSEL vertical slice from saved HTML to generated content.
- Repository-backed comparator demo with manually seeded offers.
- Multi-marketplace comparator demo with manually seeded GGSEL and Playerok offers.
- Content generation through `FakeAIProvider`.
- Snapshot history through `PriceHistoryService`.

The following are integrated beyond isolated demos:

- `MarketplacePipeline` persists parsed offers through `RepositoryProvider.offers`.
- `MarketplacePipeline.compare_repository_offers()` reads offers through the repository abstraction.
- `PlayerokPipeline.compare_repository_offers()` delegates into the same comparison path.

## 3. Which Services Are Now Fully Reusable?

Fully reusable services:

- `MatchingService`
- `OfferGroupingService`
- `BestOfferSelector`
- `PriceDifferenceService`
- `ComparisonResultBuilder`
- `RepositoryProvider`
- `OfferRepository` contract
- `CanonicalProductRepository` contract
- `PlayerokPipeline` for fetch/extract/normalize
- `MarketplacePipeline.compare_offers()`
- `MarketplacePipeline.compare_repository_offers()`

Reusable but still tied to current implementation constraints:

- `MarketplacePipeline` as a full run pipeline, because it remains GGSEL-specific in its constructor dependencies.
- `PriceHistoryService`, because it is in-memory and not behind the repository contract yet.
- `ContentGenerator`, because it is reusable but still depends on event production happening elsewhere.

## 4. Are There Duplicated Orchestration Paths?

Some duplication remains, but comparator logic itself is not duplicated.

Current duplicated or overlapping orchestration:

- `MarketplacePipeline` and `PlayerokPipeline` both have marketplace-specific orchestration, but Playerok delegates comparison to `MarketplacePipeline`.
- Demo scripts repeat setup code for providers, canonical products, and sample offers.
- The GGSEL legacy parser path still overlaps with the modular GGSEL fetch/extract/normalize path.

What is not duplicated:

- Matching.
- Grouping.
- Best-offer selection.
- Price difference calculation.
- Comparison result assembly.

## 5. Can PostgreSQL Now Be Introduced Without Changing Business Logic?

Yes, for parsed offers and canonical products.

Reason:

- The comparator reads offers through `RepositoryProvider.offers`.
- The comparator reads canonical products through `RepositoryProvider.canonical_products`.
- Matching and comparator services do not depend on in-memory repositories.
- `MarketplacePipeline.compare_repository_offers()` already uses the repository abstraction.

Not yet fully yes for price history.

Reason:

- `PriceHistoryRepository` still has no methods.
- Runtime price history still uses `PriceHistoryService`.
- Snapshot comparison and event generation are not repository-backed yet.

PostgreSQL can be introduced behind existing repository contracts for offers and canonical products without changing comparator business logic. Price history needs its repository contract completed first.

## 6. Remaining Integration Gaps

Real remaining gaps:

- Playerok live extraction is not yet proven with stable marketplace offer data.
- Event creation does not consume `ComparisonResult`.
- Content generation does not consume `ComparisonResult`.
- Price history is not repository-backed.
- `PriceHistoryRepository` and `MemoryPriceHistoryRepository` are not functional contracts yet.
- `MarketplacePipeline` remains GGSEL-specific despite hosting the shared comparison orchestration.
- Full multi-marketplace comparison currently depends on manually seeded demo offers.
- PostgreSQL repositories do not exist.
- Scheduler does not exist.
- Telegram delivery does not exist.
- Legacy GGSEL parsing still overlaps with the modular GGSEL integration.

## 7. Readiness Estimate

- Repository Layer: 45%
- Marketplace Flow: 55%
- Comparator Flow: 85%
- Persistence: 25%
- Overall Backend: 55%

## 8. Final Recommendation

Next EPIC should be: A) PostgreSQL.

Reason:

The unified comparator now reaches the repository abstraction. That makes PostgreSQL the highest-value next step because it can replace in-memory offer and canonical-product storage without changing matching or comparator business logic.

Recommended scope for the PostgreSQL EPIC:

- implement PostgreSQL repositories for offers and canonical products;
- keep repository contracts unchanged unless a missing method is required;
- keep comparator services unchanged;
- prove that repository-backed comparator demos still work with database-backed repositories.

Scheduler, Telegram, and marketplace expansion should wait until durable repository-backed data is available. Otherwise they will automate or publish flows that still depend on temporary in-memory state.
