# MediaEngine Integration Health Report

Date: 2026-07-23

## Scope and verification

This report covers the implemented marketplace, matching, repository, price
comparison, event, and content-generation paths after introduction of the
Playerok pipeline.

Verification used the project-local Python 3.13.1 environment. Offline demos,
Ruff, MyPy, and Pytest were executed. Real requests were also made through the
GGSEL and Playerok pipelines.

Observed integration results:

- GGSEL returned 60 raw offers through the modular marketplace pipeline.
- All 60 GGSEL offers were normalized and stored in the memory offer repository.
- Zero GGSEL snapshots were built because normalized offers had no price or
  currency.
- The separate `GGSelParser` path returned 66 `ParsedOffer` objects, confirming
  that GGSEL field extraction is duplicated across two paths.
- Playerok responded successfully, but the current pipeline extracted zero
  offers from the default page response.
- The offline manually constructed offer-to-content flow completed successfully.
- Ruff reported 109 violations, MyPy stopped on a duplicate module-name error,
  and Pytest found no tests.

## 1. Architecture status

### Layer separation

The codebase has recognizable layers for HTTP access, marketplace parsing,
normalization, application services, matching, repositories, analytics, domain
objects, and content generation. Fetching, extraction, and normalization are
separate in the new Playerok path, and `PlayerokPipeline` contains orchestration
only.

The boundaries are not yet consistent across the project:

- `ParsedOffer` is defined under `app.parsers` but is used as a domain-level
  contract by matching, repositories, snapshot building, and demos.
- `OfferRepository` therefore depends on the parser layer instead of a
  marketplace-independent domain or application contract.
- `MarketplacePipeline` directly depends on concrete GGSEL fetcher, extractor,
  and normalizer classes despite its generic name.
- The pipeline also requires repository, analytics, scoring, and content
  generation dependencies, making ingestion inseparable from later processing.
- Pure dataclass models and SQLAlchemy models coexist under `app.models`, which
  leaves ownership of domain and persistence models ambiguous.

### Dependency direction

Dependency injection is used in pipelines, matching, and content generation.
Repository provider fields are typed against repository contracts. These are
healthy foundations.

Current dependency-direction violations or leaks are:

- Repository contracts import `ParsedOffer` from the parser layer.
- The generic marketplace service imports concrete GGSEL adapter classes.
- `RepositoryProvider` contains both abstract repository fields and the memory
  composition factory. This is acceptable for the current stage but is not yet
  a dedicated application composition root.
- Domain events depend on Pydantic and use `float` for money while price-domain
  objects use `Decimal`.

No direct circular import was found in the reviewed integration path. MyPy does
fail before type checking because namespace packages cause `app/core/pipeline.py`
and `app/content/pipeline.py` to be detected as the same module name.

### Duplicated logic

- GGSEL fetching, embedded-payload traversal, offer detection, field mapping,
  and URL construction exist both in `GGSelParser` and in the modular
  fetcher/extractor/normalizer path.
- `PriceChangeDetector` exists in both `app.analytics.price_change` and
  `app.analytics.price_change_detector`. The first includes marketplace,
  identifier, and timestamp in `PriceChange`; the second does not.
- `PriceHistoryService` is a functional in-memory history store, while
  `MemoryPriceHistoryRepository` is an empty placeholder for the same area.
- The empty `app.adapters` tree duplicates the location responsibility currently
  implemented under `app.parsers`.

### Confirmed violations and risks

- `MarketplacePipeline` says it operates without persistence but persists every
  normalized offer.
- The pipeline catches all snapshot `ValueError` instances and records only a
  count, so the reason and affected offer are lost.
- Price-change calculation divides by the previous price without handling zero.
- Price comparison does not validate equal marketplace, product identifier, or
  currency when the detector is called directly.
- `SnapshotBuilder` drops title and URL because `PriceSnapshot` cannot carry
  them. `EventBuilder` consequently publishes the external identifier as the
  event title and cannot propagate the offer URL.
- `PriceDropEvent` converts monetary `Decimal` values to `float`, introducing a
  precision boundary in the domain event path.
- Marketplace values are stored as free-form strings even though a
  `Marketplace` enum exists.

## 2. Marketplace status

| Marketplace | Fetcher | Extractor | Normalizer | Pipeline | Matching compatibility |
| --- | --- | --- | --- | --- | --- |
| GGSEL | Implemented for HTML and JSON-compatible responses; real HTML fetch verified | Implemented and verified against live/saved HTML; 60 raw offers extracted | Implemented, but does not read GGSEL price fields from `extra`, does not assign currency, and leaves product URLs relative | Modular pipeline runs and persists offers, but builds 0 snapshots; separate monolithic parser also exists | Structurally compatible because titles reach `ParsedOffer`; matching is not invoked by the pipeline |
| Playerok | Implemented with shared `HttpClient`; real response verified | Supports raw JSON and `__NEXT_DATA__`, but the current default response yields 0 offers; broad recursive offer detection may also accept unrelated objects when payload data is present | Implemented and verified with sample `ParsedOffer` values; shared text and currency rules are reused | Fetch-extract-normalize orchestration is implemented and runs, but currently returns an empty list for the live default URL | Structurally compatible when a title is extracted; matching is not invoked by the pipeline |
| FunPay | Not implemented; only empty adapter scaffolding exists | Not implemented | Not implemented | Not implemented | The common `ParsedOffer` contract would be compatible, but no FunPay data reaches it |

The empty `app.adapters/{ggsel,playerok,funpay}` files are not used by either
implemented marketplace path.

## 3. Repository status

- `CanonicalProductRepository` and `OfferRepository` define usable synchronous
  contracts.
- Their memory implementations work and preserve insertion order.
- `MemoryOfferRepository.save` always appends; it does not implement update or
  deduplication semantics despite the contract describing save as persist or
  update.
- `PriceHistoryRepository` has no methods, and
  `MemoryPriceHistoryRepository` has no storage behavior.
- `RepositoryProvider` exposes all three repository contracts and can create
  memory-backed implementations.
- `MarketplacePipeline` stores parsed offers through the provider.
- Price history bypasses the provider and uses the separate
  `PriceHistoryService` directly.
- No PostgreSQL repository implementations or repository transaction boundary
  exist for these domain contracts.

Repository readiness is sufficient for demos of canonical products and offers,
but not for persistent or replaceable price history.

## 4. Pipeline compatibility

| Transition | Status | Actual limitation |
| --- | --- | --- |
| GGSEL response to raw offers | Working | Payload structure remains an external compatibility risk |
| GGSEL raw offers to `ParsedOffer` | Partial | Price, currency, and absolute URL mapping are incomplete |
| Playerok response to `ParsedOffer` | Blocked | Live default response currently produces zero offers |
| `ParsedOffer` to matching | Compatible in isolation | `MatchingService` is not wired into either marketplace pipeline |
| `ParsedOffer` to `PriceSnapshot` | Conditional | Requires non-null external ID, price, and currency |
| Snapshot history to `PriceChange` | Working in memory | Duplicate detector implementations and no zero-price guard |
| `PriceChange` to `PriceDropEvent` | Partial | Title becomes external ID; URL is lost; money changes to `float` |
| Event scoring and fake content generation | Working offline | Not reached by current real marketplace data flows |
| Offer persistence | Working in memory | No deduplication and no database implementation |
| Price-history persistence | Not implemented | Provider repository is an empty placeholder and is bypassed |

The manually constructed full pipeline is compatible, but there is currently no
verified real marketplace path from fetch through price comparison and event
generation.

## 5. Demo scripts

### Runnable and verified

The following demos completed under the project Python 3.13 environment:

- `analyze_ggsel_html.py`
- `demo_alias_engine.py`
- `demo_canonical_product.py`
- `demo_confidence.py`
- `demo_content_generation.py`
- `demo_content_template.py`
- `demo_event_builder.py`
- `demo_full_pipeline.py`
- `demo_ggsel_extractor.py` using the saved GGSEL response
- `demo_ggsell_parsed_offers.py` with live network access
- `demo_matching_service.py`
- `demo_memory_repositories.py`
- `demo_normalizer.py`
- `demo_pipeline_persistence.py` with live network access; it saved 60 offers
  but produced no snapshots
- `demo_playerok_normalizer.py`
- `demo_preprocessor.py`
- `demo_price_change.py`
- `demo_price_history.py`
- `demo_repository_contracts.py`
- `demo_repository_provider.py`
- `demo_similarity.py`
- `demo_snapshot_builder.py`
- `demo_stop_words.py`
- `demo_title_normalizer.py`
- `demo_title_tokenizer.py`

### Runnable but operationally incomplete

| Script | Status | Reason |
| --- | --- | --- |
| `demo_playerok_pipeline.py` | Runs, no offers | Live fetch succeeds but current extraction returns zero offers |
| `demo_playerok_fetch.py` | Network-dependent | Fetcher is verified through the pipeline; this script additionally writes a raw response file |
| `demo_playerok_extractor.py` | Blocked by input | `tmp/playerok_response.html` or `.txt` is absent |
| `demo_ggsel_pipeline.py` | Network-dependent diagnostic | Downloads and saves HTML but does not execute offer transformation |
| `demo_ggsel_fetch.py` | Expected diagnostic, not successful data flow | Calls the JSON fetch method with the HTML catalog URL |
| `demo_pipeline_persistence.py` | Partial pipeline | Offers persist, but all snapshots are skipped due to missing price/currency |
| `demo_openrouter.py` | Environment-dependent | Requires import-path setup, API key, and external API access; it is outside the offline integration path |

### Broken entry points

| Script | Reason |
| --- | --- |
| `demo_marketplace_pipeline.py` | Does not pass the required `repository_provider` constructor argument |
| `demo_pipeline.py` | Fails with `ModuleNotFoundError: app` when run as documented from the repository root |
| `demo_price_pipeline.py` | Fails with `ModuleNotFoundError: app` when run as documented from the repository root |
| `demo_ggsell_fetch.py` | Reports missing `app` because project-root import setup is absent |

## 6. Remaining blockers before MVP

1. No real marketplace completes the path from fetch to a valid price snapshot.
2. GGSEL price, currency, and URL mapping in the modular path is incomplete.
3. Playerok uses a response that currently contains no extractable offers; the
   actual listing data source and pagination path are not implemented.
4. FunPay has no implementation.
5. Price history has no functional repository contract or persistent
   implementation.
6. Matching is not connected to marketplace processing or canonical-product
   retrieval.
7. Product title and URL are lost before event construction.
8. There are no automated tests for marketplace payloads, normalization,
   matching thresholds, repository behavior, or price comparison.
9. Ruff and MyPy quality gates are not green; MyPy cannot currently complete a
   project scan.
10. Multiple demo entry points are broken or represent obsolete integration
    paths.

## 7. Technical debt

- Two competing GGSEL implementations with different field behavior.
- Two incompatible `PriceChangeDetector` implementations.
- Two price-history abstractions, only one of which is functional.
- Unused empty adapter scaffolding alongside active parser integrations.
- Marketplace-specific concrete dependencies in the generic pipeline.
- `ParsedOffer` located in the parser layer despite cross-layer ownership.
- Inconsistent use of `Marketplace` enum versus strings.
- Mixed `Decimal` and `float` monetary representations.
- No typed error result for skipped snapshots or extraction diagnostics.
- Broad recursive Playerok offer heuristic without a confirmed payload schema.
- Memory offer storage has no identity or deduplication policy.
- Missing package markers/configuration prevent MyPy from running fully.
- Ruff reports 109 issues, dominated by demo import placement plus several
  application import, typing-modernization, and line-length violations.
- Demo scripts use inconsistent project-root bootstrapping.
- No tests are collected by Pytest.

## 8. Recommendations

### Critical

1. Complete the modular GGSEL mapping for price, currency, and absolute URL,
   then verify that real offers produce snapshots.
2. Replace the Playerok homepage extraction assumption with the confirmed
   listing data source and payload schema, then verify at least one real offer.
3. Add a minimal automated integration fixture suite for GGSEL and Playerok and
   unit coverage for normalization and snapshot eligibility.
4. Establish one supported marketplace-to-snapshot path and retire or isolate
   the duplicate GGSEL path before adding more marketplaces.

### Important

1. Define methods on `PriceHistoryRepository`, implement them in memory, and
   make the processing pipeline use the provider contract.
2. Consolidate the two price-change detectors and add zero-price, identity, and
   currency validation.
3. Preserve product title and URL through snapshot/change/event construction.
4. Keep monetary values as `Decimal` through event creation; convert only at an
   external serialization boundary if required.
5. Integrate canonical-product lookup and `MatchingService` before comparing
   offers across marketplaces.
6. Repair the broken demos and remove or clearly label diagnostic and obsolete
   scripts.
7. Fix package discovery so MyPy can run, then make Ruff, MyPy, and Pytest
   mandatory green checks.
8. Decide whether marketplace implementations live under `app.parsers` or
   `app.adapters`; remove the unused duplicate structure after migration.

### Optional

1. Introduce a common marketplace ingestion protocol after GGSEL and Playerok
   contracts have stabilized.
2. Separate ingestion, comparison, and publication orchestration so each can be
   run independently.
3. Standardize marketplace identifiers on the existing `Marketplace` enum.
4. Add structured per-offer diagnostics for skipped normalization and snapshot
   construction.

## 9. Overall project readiness

| Area | Readiness | Assessment |
| --- | ---: | --- |
| Foundation | 70% | Core project structure, dependencies, async HTTP, configuration, and tooling exist; quality gates and package discovery need repair |
| Core Engine | 65% | Matching, snapshot, comparison, scoring, and fake content components work in isolation; contracts and data propagation remain inconsistent |
| Marketplace Support | 30% | GGSEL fetch/extract works but cannot produce snapshots; Playerok fetches but produces no offers; FunPay is absent |
| Persistence | 20% | Offer and canonical-product memory repositories work; price history and database repositories are not implemented |
| Comparison Engine | 50% | Manual snapshot comparison works; real marketplace data does not reach it, and edge-case validation is incomplete |
| MVP readiness | 25% | Demonstrable offline flow exists, but no complete real-data marketplace vertical, durable history, or automated regression protection exists |

The project has a useful foundation and several working isolated components, but
it is not ready for an MVP release. The next milestone should be one verified,
tested real marketplace vertical through snapshot creation and price comparison,
before expanding marketplace coverage or publication features.
