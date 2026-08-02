# Architecture Review #2

Date: 2026-07-24

## Scope

This review covers the MediaEngine implementation after completion of the first end-to-end GGSEL vertical slice.

Reviewed areas:

- marketplace ingestion for GGSEL and Playerok;
- parser contracts, extractors, normalizers, and pipelines;
- domain models used by the vertical slice;
- repository contracts and in-memory implementations;
- matching, analytics, event, scoring, and content-generation boundaries;
- demonstration pipelines that exercise the current architecture.

Application code was not modified during this review.

## 1. Overall Architecture

### Architecture Fit

The implementation still broadly follows the original architecture. The project has recognizable boundaries for:

- marketplace data retrieval and extraction;
- normalization into internal offer models;
- domain snapshots and events;
- analytics and scoring;
- matching;
- repository contracts;
- orchestration services;
- AI provider abstraction and prompt generation.

The current architecture is strong enough for continued vertical-slice development. The main architectural pressure now comes from duplicated early-stage components and a few boundaries that are still named or placed according to their first use rather than their long-term role.

### Layer Separation

Layer separation is mostly preserved:

- Fetchers download raw source data.
- Extractors locate marketplace payloads.
- Normalizers create internal offer objects.
- Builders convert between application-level models.
- Analytics detect price changes.
- Events represent publishable domain facts.
- Content generation depends on the AI provider interface.
- Repositories expose storage contracts without database code.

Confirmed boundary leaks:

- `ParsedOffer` is defined in `app.parsers.models`, but it is used by services, repositories, matching, snapshot building, and demos as a central application contract.
- `MarketplacePipeline` has a generic name but imports concrete GGSEL classes.
- Price history is split between `PriceHistoryService` and the empty `PriceHistoryRepository` contract.
- Dataclass domain-style models and SQLAlchemy persistence models coexist under `app.models`, which makes model ownership less clear.

### Dependency Direction

The dependency direction is mostly healthy:

- Repository provider fields are typed against repository interfaces.
- Matching depends on marketplace-independent models and deterministic components.
- Content generation depends on `AIProvider`, not a concrete external AI implementation.
- Parser code does not write directly to repositories or databases.

Current dependency issues:

- Repository contracts import `ParsedOffer` from the parser layer.
- The common marketplace pipeline imports GGSEL-specific classes directly.
- The event/content path depends on `PriceDropEvent` carrying enough display data, but the analytics-to-event path currently loses offer context before event creation.

No circular dependency was identified in the reviewed vertical-slice path.

### SOLID and SRP

Most small components follow SRP:

- `SnapshotBuilder` only builds snapshots.
- `PriceChangeDetector` only compares snapshots.
- `EventBuilder` only builds events from changes.
- `ContentGenerator` only coordinates prompt creation and AI generation.
- Matching components are split into normalization, tokenization, stop-word filtering, alias expansion, similarity, and confidence classification.

SRP pressure points:

- `MarketplacePipeline` orchestrates fetching, extraction, normalization, persistence, snapshot building, history updates, price change detection, event building, scoring, and content generation. This is acceptable as a demo/application orchestrator, but too broad as a long-term reusable marketplace service.
- `GGSelParser` combines legacy fetching, payload traversal, and ParsedOffer mapping while a newer modular GGSEL path already exists.
- `PricePipeline` overlaps with the newer `PriceChangeDetector` plus `EventBuilder` flow.

### Tight Coupling

Current tight coupling is not severe, but it is visible:

- The main marketplace pipeline is coupled to GGSEL despite its generic name.
- `EventBuilder` depends on `PriceChange.product_identifier` being suitable as a publication title.
- `SnapshotBuilder` requires `ParsedOffer` fields directly and cannot carry title or URL forward.
- Marketplace identity is represented as free-form strings in most runtime models even though a `Marketplace` enum exists.

## 2. Marketplace Architecture

### GGSEL

Current GGSEL implementation has two paths:

- Modular path: `GGSelFetcher` -> `GGSelExtractor` -> `OfferNormalizer`.
- Legacy path: `GGSelParser`.

The modular path is the better architectural direction. It separates raw download, embedded payload extraction, typed raw marketplace offer creation, and conversion into `ParsedOffer`.

Current status:

- HTML fetching exists through the shared `HttpClient`.
- Extraction from embedded React Server Components payloads exists.
- Raw products are typed as `RawMarketplaceOffer`.
- Price fields from GGSEL payloads are mapped into raw offers when available.
- Normalization can produce `ParsedOffer` objects with the fields required by `SnapshotBuilder`.
- The saved GGSEL response can drive the complete demo vertical slice from offer to generated content.

Limitations:

- `GGSelParser` duplicates extraction and mapping logic.
- URL handling remains source-shaped; if GGSEL returns relative URLs, canonical absolute URL normalization is not guaranteed by the shared normalizer.
- The working vertical slice uses a controlled previous snapshot to demonstrate price-change behavior because only one real collection point exists locally.
- The generic `MarketplacePipeline` is currently GGSEL-specific.

### Playerok

Current Playerok implementation is more consistently staged:

- `PlayerokFetcher` downloads raw response text.
- `PlayerokExtractor` extracts `ParsedOffer` objects from JSON or `__NEXT_DATA__`.
- `PlayerokNormalizer` normalizes extracted offers.
- `PlayerokPipeline` orchestrates fetch, extract, normalize, and return.

Current status:

- The fetcher uses the shared `HttpClient`.
- The pipeline is intentionally limited to ParsedOffer production.
- The implementation does not persist, match, compare prices, generate events, or create content.

Limitations:

- Extraction relies on generic recursive detection of offer-like objects.
- The real listing data source is not yet proven as stable.
- Playerok does not currently use the typed `RawMarketplaceOffer` boundary used by GGSEL.
- Playerok is not integrated into the broader offer-to-content pipeline.

### Consistency Between GGSEL and Playerok

The two marketplace implementations are not yet consistent:

- GGSEL uses `RawMarketplaceOffer` before `ParsedOffer`.
- Playerok extracts directly into `ParsedOffer`.
- GGSEL has both a legacy parser and modular components.
- Playerok has only the modular fetch/extract/normalize pipeline.
- GGSEL can feed the complete demo vertical slice.
- Playerok currently stops at normalized offers.

This inconsistency is acceptable for research-stage integration, but it should be resolved before adding FunPay or introducing persistence-backed marketplace runs.

## 3. Domain Model

### ParsedOffer

`ParsedOffer` currently acts as the central marketplace offer contract.

Strengths:

- It supports nullable marketplace data without inventing missing values.
- It includes marketplace, external ID, title, URL, price, currency, seller fields, and optional canonical product link.
- It is database-independent.

Issues:

- It lives under `app.parsers`, although it is used across repositories, services, matching, and analytics preparation.
- Requiredness is deferred to downstream builders. This is flexible, but runtime failures can happen when a later stage requires missing fields.
- It does not currently carry category, image, description, or availability. That is acceptable only if those fields are not needed by current vertical slices.

### CanonicalProduct

`CanonicalProduct` is marketplace-independent and immutable enough for current matching use.

Strengths:

- Uses `UUID` identity.
- Uses `tuple[str, ...]` for aliases.
- Has no marketplace coupling.

Current limitation:

- Matching uses only `name`; aliases on `CanonicalProduct` are not yet consumed by `MatchingService`.

### PriceSnapshot

`PriceSnapshot` is intentionally small and database-independent.

Strengths:

- Uses `Decimal` for price.
- Uses collected timestamp.
- Does not depend on SQLAlchemy or Pydantic.

Issue:

- It stores only marketplace, external ID, price, currency, and timestamp. Title and URL are lost after snapshot creation, so later events cannot produce rich content without external context.

### PriceHistory

`PriceHistoryService` provides working in-memory history.

Strengths:

- Simple keying by marketplace and external ID.
- Supports adding snapshots, reading last snapshot, previous snapshot, and history.
- Works for demos.

Issues:

- It is not connected to `PriceHistoryRepository`.
- The repository contract for price history is empty.
- The service is not yet replaceable with PostgreSQL through the repository provider.

### PriceChange

`PriceChange` captures the comparison result clearly.

Strengths:

- Uses `Decimal` for all price calculations.
- Carries previous price, current price, signed difference, percentage, drop flag, marketplace, product identifier, and timestamp.
- Provides compatibility properties such as `old_price`, `new_price`, and `absolute_difference`.

Issues:

- There are two `PriceChangeDetector` implementations.
- One detector includes marketplace, product identifier, and timestamp; the older one does not.
- Division by zero is not handled if a previous snapshot has price `0`.
- Currency and product identity consistency are expected from the caller, not validated by the detector.

### Events

`PriceDropEvent` is currently usable for content generation.

Strengths:

- Uses Pydantic v2.
- Automatically sets `created_at`.
- Computes `discount_percent`.
- Works with `EventScorer`, prompt builders, and fake content generation.

Issues:

- Monetary values are converted from `Decimal` to `float`.
- Event title currently becomes the external product identifier when built from `PriceChange`.
- Event does not carry URL, external ID, canonical product ID, or seller context.

## 4. Repository Layer

### Current Readiness

The repository layer is ready for early demos and service composition:

- `CanonicalProductRepository` exists.
- `OfferRepository` exists.
- `RepositoryProvider` exists.
- Memory implementations exist for canonical products and offers.
- `MarketplacePipeline` persists parsed offers through `RepositoryProvider.offers`.

Current gaps:

- `PriceHistoryRepository` is an empty interface.
- `MemoryPriceHistoryRepository` is an empty placeholder.
- Runtime price history still uses `PriceHistoryService` directly.
- `OfferRepository.save()` appends in memory and does not define identity, update, or deduplication behavior.

### Future PostgreSQL Compatibility

The repository layer is directionally compatible with PostgreSQL because contracts are database-independent. Before PostgreSQL implementation, these decisions should be made:

- whether repository contracts remain synchronous or become async;
- how offer identity and deduplication are defined;
- how price history is represented in a repository contract;
- whether a Unit of Work or transaction boundary is required;
- where `ParsedOffer` should live if repositories continue to depend on it.

PostgreSQL should not be introduced until price-history contract semantics are clarified.

## 5. Pipeline Review

### MarketplacePipeline

`MarketplacePipeline` currently executes the broadest path:

1. Fetch GGSEL HTML.
2. Extract raw offers.
3. Normalize offers.
4. Persist parsed offers.
5. Build snapshots.
6. Update in-memory price history.
7. Detect price changes.
8. Build price-drop events.
9. Score events.
10. Generate content.

Strengths:

- Reuses existing services.
- Keeps individual transformation logic outside the pipeline.
- Demonstrates the intended vertical flow.

Issues:

- It is GGSEL-specific despite its generic name.
- It mixes ingestion, persistence, analytics, event creation, scoring, and content generation in one orchestrator.
- It uses `PriceHistoryService` instead of `RepositoryProvider.price_history`.
- It silently skips snapshot-building failures by count only.
- The class docstring says it runs without persistence, but the implementation persists offers.
- `scripts/demo_marketplace_pipeline.py` is not aligned with the current constructor because it does not pass `repository_provider`.

### PlayerokPipeline

`PlayerokPipeline` is narrow and clean:

1. Fetch.
2. Extract.
3. Normalize.
4. Return parsed offers.

Strengths:

- Good SRP for an early marketplace pipeline.
- Does not mix persistence or analytics.
- Keeps Playerok behavior marketplace-specific.

Limitations:

- It is not integrated into the shared offer-to-content workflow.
- It depends on extractor behavior that is not yet proven against stable listing data.

### PricePipeline

`PricePipeline` overlaps with `PriceChangeDetector` plus `EventBuilder`.

Issue:

- It uses the older detector module and duplicates responsibility now covered by the newer analytics-to-event path.

Recommendation:

- Keep it untouched for now, but mark it as a candidate for removal or migration once the preferred price-change flow is finalized.

### Demo Pipelines

The final vertical slice demo demonstrates the intended path successfully from saved GGSEL HTML to generated content.

Important context:

- The previous price is controlled in the demo because only one real GGSEL snapshot exists locally.
- This proves component compatibility, not historical production behavior.
- Several scripts represent earlier stages and now overlap with newer demos.

## 6. Technical Debt

Actual current debt:

- Duplicate GGSEL implementation: `GGSelParser` and modular GGSEL components.
- Duplicate price-change detector modules.
- `ParsedOffer` is located in the parser layer but owned by multiple application layers.
- `PriceHistoryService` and `PriceHistoryRepository` represent the same future boundary, but only the service works.
- `MarketplacePipeline` is named generically while depending on GGSEL-specific classes.
- `MarketplacePipeline` docstring is stale regarding persistence.
- `demo_marketplace_pipeline.py` is stale against the current constructor.
- Money is represented as `Decimal` in snapshots and price changes, but as `float` in events.
- Marketplace identity is mostly free-form strings despite the existing `Marketplace` enum.
- Event creation loses product title and URL context.
- Playerok extractor depends on broad heuristics before a stable source payload is confirmed.
- Existing project-state documentation still contains pre-completion GGSEL gaps that are now stale.

No evidence of harmful cyclic imports was found in the reviewed path.

## 7. Refactoring Opportunities

Worthwhile improvements:

1. Promote `ParsedOffer` and related marketplace-neutral DTOs out of `app.parsers` into a domain or application contract module.
2. Choose the modular GGSEL implementation as the supported path and retire or quarantine `GGSelParser`.
3. Merge the two price-change detector modules into one supported implementation.
4. Define `PriceHistoryRepository` methods and move `PriceHistoryService` behind that contract.
5. Rename or split `MarketplacePipeline` so ingestion, comparison, and content generation can evolve independently.
6. Preserve title and URL context through snapshot/change/event building.
7. Keep money as `Decimal` until the final serialization boundary.
8. Standardize marketplace identifiers on the existing `Marketplace` enum.
9. Align demo scripts with current constructors and remove obsolete demo paths when replacement demos exist.
10. Make Playerok follow the same raw-offer-to-normalized-offer boundary as GGSEL after its data source is confirmed.

Not urgent:

- Adding a generic marketplace adapter protocol. It is better to wait until Playerok has one proven real offer flow.
- Introducing PostgreSQL implementations before price-history semantics are defined.
- Adding AI or Telegram delivery before comparison and persistence are stable.

## 8. MVP Readiness

| Area | Readiness | Assessment |
| --- | ---: | --- |
| Foundation | 75% | Project structure, async HTTP, domain DTOs, repositories, matching, analytics, events, and content generation are in place. Tooling and documentation drift still need cleanup. |
| Marketplace Support | 45% | GGSEL has a working saved-response vertical slice. Playerok has fetch/extract/normalize infrastructure but no proven stable offer source. FunPay is not implemented. |
| Matching | 70% | Deterministic matching service is implemented and cleanly separated. It is not yet connected to marketplace pipelines or canonical-product repositories. |
| Persistence | 30% | Offer and canonical product memory repositories exist. Price history still bypasses repository contracts, and there is no PostgreSQL implementation. |
| Analytics | 60% | Price-change detection and event building work in demos. Duplicate detectors and missing edge-case validation remain. |
| Content Generation | 65% | Prompt builder, fake provider, and content generator work. Production AI wiring exists separately but is not part of the reviewed vertical path. |
| Overall MVP | 45% | The first vertical slice is demonstrated, but real historical comparison, repository-backed price history, stable marketplace coverage, and automated regression checks are still missing. |

## 9. Recommendation

Recommended next direction: **B. Repository improvements**.

Reasoning:

- The first GGSEL vertical slice proves that the components can connect.
- The next bottleneck is not content generation or scheduling; it is durable, replaceable price history.
- Without a real price-history repository contract, the comparator will remain tied to in-memory demo state.
- PostgreSQL should come after repository semantics are clear, especially identity, deduplication, and history retrieval.
- Scheduler work should wait until one persisted marketplace comparison path exists.

Recommended sequence:

1. Repository improvements.
2. Comparator integration against repository-backed history.
3. PostgreSQL implementations.
4. Scheduler.

This order keeps development grounded in the completed vertical slice while reducing the risk of building scheduling or database code around unstable contracts.
