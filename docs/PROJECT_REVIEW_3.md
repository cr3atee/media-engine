# Project Review #3

Date: 2026-07-24

## 1. Overall Project Status

MediaEngine now has a real end-to-end GGSEL vertical slice and a working comparator stack.

What is already working:

- GGSEL HTML can be fetched and analyzed through the shared HTTP client.
- GGSEL embedded payloads can be extracted into typed raw offers.
- Raw GGSEL offers can be normalized into `ParsedOffer`.
- `ParsedOffer` can be converted into `PriceSnapshot` when price and currency are present.
- `PriceHistoryService` can store and retrieve snapshot history in memory.
- `PriceChangeDetector` can compare two snapshots and produce a `PriceChange`.
- `EventBuilder` can turn a price drop into `PriceDropEvent`.
- `EventScorer` can score events deterministically.
- Prompt building, fake AI generation, and content generation work end to end.
- Matching preprocessing, similarity, confidence classification, and `MatchingService` are implemented.
- Comparator grouping, best-offer selection, price difference calculation, and comparison result assembly are implemented.

What is still only infrastructure:

- PostgreSQL persistence.
- Scheduler orchestration.
- Telegram delivery.
- Production AI provider wiring.
- FunPay integration.
- A stable Playerok extraction path from live marketplace data.
- Repository-backed price history.

The project has moved past pure foundation work. It can already demonstrate core product value, but most persistence and automation concerns remain infrastructure-only.

## 2. End-to-End User Flows

### GGSEL flow

GGSEL

-> Offer

-> Snapshot

-> Price Change

-> Event

-> Content

Status: fully working in demo form.

The GGSEL vertical slice is the strongest completed flow. It works from saved real GGSEL HTML and can drive the whole chain through generated content. The flow is verified through the demo scripts and the existing services.

### Comparator flow

Matching

-> Grouping

-> Best Offer

-> Price Difference

-> Comparison Result

Status: fully working as an internal comparator flow.

The comparator is complete as a deterministic application layer. It can accept marketplace offers, match them to canonical products, group them, select the best offer, compute differences, and produce an immutable comparison result.

### Playerok flow

Playerok fetch

-> extract

-> normalize

Status: partial.

The Playerok pipeline exists structurally and is cleanly separated, but the live default response currently does not produce a reliable offer stream comparable to GGSEL. Playerok is therefore infrastructure-complete but not yet a fully proven marketplace vertical.

### Missing complete flows

- Playerok -> Offer -> Snapshot -> Price Change -> Event -> Content is not complete.
- Live multi-marketplace comparison from real marketplace data is not fully complete because only GGSEL currently feeds the full downstream chain with real data.

## 3. Marketplace Coverage

### GGSEL

Current readiness: high.

What exists:

- Fetcher.
- Extractor.
- Normalizer.
- Marketplace pipeline.
- Real GGSEL demo coverage.
- Integration into snapshot, price change, event, and content flow.

Remaining work:

- Remove or quarantine duplicate legacy GGSEL parsing path.
- Finish price normalization edge cases.
- Improve long-term stability around source payload changes.

### Playerok

Current readiness: medium.

What exists:

- Fetcher.
- Extractor.
- Normalizer.
- Pipeline.
- Documentation around source analysis and mapping.

Remaining work:

- Confirm a stable live offer source.
- Harden extraction against real payload variability.
- Connect Playerok into the same downstream vertical slice that GGSEL already reaches.

## 4. Repository Layer

Current maturity: early but usable.

What works:

- Repository contracts exist for canonical products, offers, and price history.
- Memory repositories work for canonical products and offers.
- `RepositoryProvider` centralizes repository access.
- Marketplace pipeline persists parsed offers through the provider.

What remains:

- `PriceHistoryRepository` is still only an interface shell.
- `MemoryPriceHistoryRepository` is still a placeholder.
- There is no PostgreSQL implementation.
- There is no explicit transaction boundary.
- Offer update/deduplication semantics are still not formalized.

Production readiness: low.

The repository layer is good enough for demos and early development, but not yet for durable production data. Price history is the clearest missing contract.

## 5. Matching & Comparator

### Matching

The matching layer is clean and deterministic:

- title normalization.
- tokenization.
- stop-word filtering.
- alias expansion.
- similarity scoring.
- confidence classification.
- `MatchingService` selection.

Design quality: good.

The main limitation is deliberate simplicity. Jaccard similarity is deterministic and easy to reason about, but it is still a shallow first-pass matcher.

### Grouping

Grouping is structurally sound and uses `MatchingService` exactly as implemented.

### Selection

Best-offer selection is deterministic and stable, with clear handling for:

- no valid prices.
- currency mismatch.
- one-off groups.
- lowest-price selection.

### Price Difference

Price difference calculation is clean and Decimal-based.

The only important limitation is that no currency conversion exists by design, so currency mismatch must remain an unavailable state.

### Comparison Result

The comparison result layer is a good aggregator:

- immutable.
- explicit status.
- built from existing DTOs.
- does not duplicate comparison logic.

Overall design quality: strong for a first comparator milestone.

## 6. Technical Debt

Only real debt:

- Duplicate GGSEL implementation remains: legacy `GGSelParser` and modular fetch/extract/normalize path.
- `ParsedOffer` still lives in the parser layer even though it is used as a cross-cutting application contract.
- `PriceHistoryRepository` exists only as an empty contract, while real history is handled by a service.
- `MarketplacePipeline` is still GGSEL-specific in practice even though its name is generic.
- Price and money values move between `Decimal` and `float` at different boundaries.
- `PriceDropEvent` still loses some offer context before publication.
- `Playerok` extraction is not yet proven on a stable live offer stream.
- Several docs still describe an earlier state of the project and no longer reflect the completed comparator work.

## 7. Documentation

Outdated PROJECT_PASSPORT documents that should be updated:

- `02_ARCHITECTURE.md`
- `03_DOMAIN_MODEL.md`
- `05_MARKETPLACES.md`
- `11_ROADMAP.md`
- `13_CURRENT_STATE.md`
- `16_TECH_LEAD_NOTES.md`

Why they need updates:

- They do not fully reflect the completed comparator stack.
- They understate the maturity of GGSEL and the comparator flow.
- They still present some earlier GGSEL and project-state assumptions as current.

## 8. Production Readiness

Percentages:

- Architecture: 75%
- Marketplace Integrations: 55%
- Matching: 80%
- Comparator: 85%
- Repositories: 40%
- Persistence: 25%
- Scheduler: 0%
- Telegram: 0%
- Overall MVP: 50%

Interpretation:

- The architecture is solid enough for continued development.
- The core application logic is already convincing.
- Production readiness is still held back by persistence, automation, and delivery layers.

## 9. Top Priorities

Recommended next five EPICs by business value:

1. PostgreSQL persistence and repository implementation.
   This is the highest-value next step because it turns the working demo state into durable product state and unlocks real history retention.

2. Playerok stabilization and live offer extraction.
   Multi-marketplace value depends on a second real source. Playerok is the most obvious next marketplace to harden.

3. Comparator integration against persisted history.
   The comparator already works in memory; wiring it to durable offer and price history will make the comparison flow production-shaped.

4. FunPay integration.
   Adding a third marketplace increases coverage and validates that the architecture is actually marketplace-neutral.

5. Scheduler and automated pipeline execution.
   Once sources and persistence are stable, scheduling becomes valuable for recurring price tracking and content generation.

## 10. Final Verdict

Yes, MediaEngine can already demonstrate its core product value.

Why:

- It can fetch real GGSEL data.
- It can normalize that data into internal offers.
- It can build snapshots and detect price changes.
- It can create events, score them, and generate publication text.
- It can also group offers, select the best one, compute price differences, and assemble a comparison result.

What is still missing for production:

- durable persistence,
- stable Playerok live extraction,
- another marketplace fully integrated into the same downstream path,
- scheduler,
- Telegram delivery,
- and a real PostgreSQL-backed repository layer.

The product value is demonstrable now, but the system is not yet operationally complete.
