# Playerok Finance / Current Workspace Audit

Audit date: 2026-07-21

Auditor role: Principal Software Engineer / Tech Lead

## Scope Note

The current workspace contains a Python project named `MediaEngine`, not a React + Tauri + Rust + SQLite application named `Playerok Finance`.

The repository does not contain:

- `package.json`
- React source files
- Zustand stores
- `src-tauri`
- Rust crates
- SQLite migrations or schema files

Therefore, frontend, Tauri, Rust, and SQLite findings below are limited to the fact that those parts are absent from the inspected workspace. I did not modify application code.

## Executive Summary

The current project is a fast-moving backend foundation with useful boundaries already emerging: parser extraction, parsed offers, matching preprocessing, repository contracts, memory repositories, and marketplace pipeline orchestration.

The main risk is that the project is not yet internally consistent enough for the next major development phase. Several abstractions exist, but some are not wired end-to-end or are duplicated. The biggest concrete blockers are missing price normalization from GGSEL payloads, incomplete price-history repository contract, pipeline coupling to GGSEL classes, lack of tests, and absence of the requested Playerok Finance frontend/Tauri/Rust/SQLite code.

## Findings

### 1. Workspace Does Not Match Requested Product

Severity: Critical

Why this is a problem:
The requested audit is for Playerok Finance with React, Zustand, Tauri, Rust, and SQLite. The current workspace is MediaEngine, a Python/FastAPI-oriented project. Any release-readiness conclusion for Playerok Finance cannot be trusted without the actual codebase.

How to fix:
Open or provide the correct Playerok Finance repository, then repeat the audit against that codebase.

Fix now or later:
Now, before making product-level release decisions.

### 2. Frontend Layer Is Missing

Severity: Critical

Why this is a problem:
React best practices, Zustand usage, render performance, hooks, memoization, and frontend type safety cannot be audited because there is no frontend code in this workspace.

How to fix:
Add or switch to the repository containing the frontend implementation.

Fix now or later:
Now, if Playerok Finance is expected to ship as a desktop/UI product.

### 3. Tauri Layer Is Missing

Severity: Critical

Why this is a problem:
Tauri command security, `invoke` organization, DTO serialization, and command error handling cannot be validated without `src-tauri` or Rust command code.

How to fix:
Audit the actual Tauri project before enabling local filesystem, shell, network, or credential-related capabilities.

Fix now or later:
Now, before MVP release.

### 4. Rust Backend Layer Is Missing

Severity: Critical

Why this is a problem:
`DatabaseService`, repositories, transaction layer, Rust error handling, ownership/lifetime risks, and performance characteristics cannot be assessed because there is no Rust code.

How to fix:
Provide the Rust/Tauri backend code and audit it separately.

Fix now or later:
Now, before any Rust-backed release.

### 5. SQLite Persistence Layer Is Missing

Severity: Critical

Why this is a problem:
The requested SQLite schema, indexes, foreign keys, migrations, and scaling behavior cannot be validated. The current project uses PostgreSQL dependencies and Alembic, not SQLite.

How to fix:
Provide SQLite migrations/schema or clarify that the product has moved to PostgreSQL.

Fix now or later:
Now, because persistence choices affect architecture and migration strategy.

### 6. MarketplacePipeline Is Coupled To GGSEL Implementations

Severity: High

Why this is a problem:
`MarketplacePipeline` directly depends on `GGSelFetcher` and `GGSelExtractor`. This limits marketplace independence and violates the intended reusable pipeline direction.

How to fix:
Introduce small protocol interfaces for fetcher/extractor inputs later, or generalize constructor types once a second marketplace implementation exists.

Fix now or later:
Later, but before adding Playerok/FunPay pipeline implementations.

### 7. Price Normalization From GGSEL Is Not Complete

Severity: High

Why this is a problem:
GGSEL extracted products store price fields such as `price_wmr` and `price_brl` in `RawMarketplaceOffer.extra`. `OfferNormalizer` only reads `raw_offer.price` and `raw_offer.currency`, so parsed offers often have no normalized price/currency. As a result, snapshots are skipped and downstream price-change logic does not run.

How to fix:
Add a marketplace-specific mapping step that converts known GGSEL price fields into typed raw or parsed price fields without mixing extraction and business logic.

Fix now or later:
Now, if the next stage depends on real price tracking.

### 8. PriceHistoryRepository Contract Is Empty

Severity: High

Why this is a problem:
There is a repository contract named `PriceHistoryRepository`, but it defines no methods. Meanwhile `MarketplacePipeline` still uses `PriceHistoryService` directly. This weakens the repository boundary and creates two persistence directions.

How to fix:
Define repository methods for adding snapshots and retrieving previous/history snapshots, then adapt the memory implementation and pipeline.

Fix now or later:
Now, before implementing PostgreSQL persistence.

### 9. Pipeline Uses Two Persistence Mechanisms

Severity: High

Why this is a problem:
Parsed offers are saved via `RepositoryProvider`, but snapshots are kept in `PriceHistoryService`. This creates inconsistent persistence boundaries and complicates replacement with a real database later.

How to fix:
Move snapshot history access behind `RepositoryProvider.price_history` once the contract is defined.

Fix now or later:
Now, before expanding price analytics.

### 10. Duplicate PriceChangeDetector Implementations

Severity: Medium

Why this is a problem:
There are two detectors: `app/analytics/price_change.py` and `app/analytics/price_change_detector.py`. They return similar models but populate different fields. This can cause inconsistent downstream events and scoring.

How to fix:
Choose one canonical detector and deprecate/remove the other after checking all imports.

Fix now or later:
Now, because it is already causing architectural ambiguity.

### 11. EventBuilder Loses Product Title Semantics

Severity: Medium

Why this is a problem:
`EventBuilder` maps `PriceChange.product_identifier` into `PriceDropEvent.title`. Product identifier is currently based on `external_id`, not a human-readable product title. This can produce poor generated content.

How to fix:
Carry title through `PriceSnapshot` or through a richer price-change context object.

Fix now or later:
Later, but before publishing user-facing content.

### 12. Money Values Are Converted To Float In Events

Severity: Medium

Why this is a problem:
`PriceDropEvent` uses floats for `old_price` and `new_price`, while price snapshots and changes use `Decimal`. This can introduce rounding issues in financial comparisons and generated content.

How to fix:
Use `Decimal` in domain events or introduce a serializable money value object.

Fix now or later:
Now, before real financial calculations are trusted.

### 13. Similarity Ignores Token Multiplicity And Aliases On CanonicalProduct.aliases

Severity: Medium

Why this is a problem:
`SimilarityEngine` uses set-based Jaccard similarity, which ignores repeated meaningful tokens. `MatchingService` only compares `offer.title` to `candidate.name`; it does not evaluate `CanonicalProduct.aliases`.

How to fix:
Keep current similarity as baseline, but include candidate aliases as additional candidate titles or merged token sets.

Fix now or later:
Later, after baseline matching behavior is measured.

### 14. Confidence Thresholds Are Hardcoded

Severity: Medium

Why this is a problem:
`ConfidenceEngine` uses fixed thresholds. This is acceptable for a first pass, but thresholds will likely need tuning after real marketplace data is collected.

How to fix:
Move thresholds into configuration or constructor parameters when real evaluation data exists.

Fix now or later:
Later.

### 15. Repository Contracts Are Synchronous

Severity: Medium

Why this is a problem:
Current repository interfaces are synchronous, but the project stack includes async SQLAlchemy/PostgreSQL. Future async DB implementations may either block or require interface changes.

How to fix:
Decide whether repository contracts should be async before PostgreSQL implementations are introduced.

Fix now or later:
Now, before adding database-backed repositories.

### 16. In-Memory OfferRepository Has No Upsert Or Identity Semantics

Severity: Medium

Why this is a problem:
`MemoryOfferRepository.save()` always appends. Re-running pipelines can duplicate the same marketplace offer indefinitely.

How to fix:
Define identity rules for offers, likely `(marketplace, external_id)`, and decide whether `save` means append or upsert.

Fix now or later:
Now, before processing repeated marketplace runs.

### 17. Database Schema Lacks Important Indexes

Severity: High

Why this is a problem:
The migration creates `products`, `prices`, and `marketplaces`, but there are no indexes for common lookups such as marketplace code, product external ID, product marketplace, or price history by product/time.

How to fix:
Add indexes when DB persistence becomes active:
`marketplaces.code`, `(marketplace_id, external_id)`, `prices.product_id`, and `(product_id, collected_at)`.

Fix now or later:
Before any production DB usage.

### 18. Database Schema Lacks Uniqueness For Product Identity

Severity: High

Why this is a problem:
`Product.external_id` is not unique per marketplace. The same marketplace product can be inserted multiple times.

How to fix:
Add a unique constraint on `(marketplace_id, external_id)`.

Fix now or later:
Before production ingestion.

### 19. Foreign Keys May Not Enforce Desired Delete Behavior

Severity: Medium

Why this is a problem:
Foreign keys exist, but cascade/restrict behavior is not explicitly documented or configured. Deleting products or marketplaces could leave unclear operational behavior.

How to fix:
Define delete policy explicitly in migrations and repository behavior.

Fix now or later:
Later, before admin deletion workflows.

### 20. Settings Are Instantiated Globally At Import Time

Severity: Medium

Why this is a problem:
`settings = Settings()` and the async DB engine are created at import time. This makes tests, alternate environments, and runtime overrides harder.

How to fix:
Use a factory or cached dependency for settings and engine creation.

Fix now or later:
Later, unless tests become painful immediately.

### 21. OpenRouterProvider Manages AsyncClient Manually

Severity: Medium

Why this is a problem:
`OpenRouterProvider` owns an `httpx.AsyncClient`, but does not implement async context manager. If callers forget `aclose()`, connections can remain open.

How to fix:
Implement `__aenter__` and `__aexit__`, or inject a shared HTTP client.

Fix now or later:
Before production AI calls.

### 22. OpenRouterProvider Does Not Validate Missing API Key Before Request

Severity: Medium

Why this is a problem:
If `OPENROUTER_API_KEY` is empty, the request still goes out with an invalid bearer token. This creates unclear errors and accidental external calls.

How to fix:
Raise `AIProviderError` before request when the key is missing.

Fix now or later:
Before production AI calls.

### 23. HTTP Client Retries Only Request Errors And 5xx

Severity: Low

Why this is a problem:
The retry policy does not handle 429 rate limits or response-specific retry-after behavior. This may be inadequate for marketplace scraping/fetching.

How to fix:
Add explicit 429 handling and optional retry-after support.

Fix now or later:
Later, when real rate limits are observed.

### 24. GGSEL HTML Extraction Is Fragile

Severity: High

Why this is a problem:
`GGSelExtractor` depends on embedded React payload shape and `.push(...)` patterns. Any frontend deploy by GGSEL can break extraction.

How to fix:
Prefer official/private API when available. If HTML extraction remains necessary, isolate fixture-based tests and add diagnostics.

Fix now or later:
Now, before relying on GGSEL as a production data source.

### 25. Raw HTML Artifact Is Untracked But Present

Severity: Low

Why this is a problem:
`tmp/ggsel_response.html` exists locally and is large. It may accidentally be committed or leak marketplace response data.

How to fix:
Ensure `tmp/` is ignored or store sanitized fixtures intentionally under tests later.

Fix now or later:
Now, as a hygiene fix.

### 26. Dockerfile Does Not Start The Application

Severity: Medium

Why this is a problem:
The Docker command is `uv run python -V`, so the container exits after printing the Python version instead of running FastAPI.

How to fix:
Set the command to run the actual app server when ready, for example `uvicorn app.main:app`.

Fix now or later:
Before deploying or using Docker for integration testing.

### 27. Docker Build Does Not Copy uv.lock Before uv sync

Severity: Medium

Why this is a problem:
The Dockerfile copies only `pyproject.toml` before `uv sync --no-dev`. This can produce non-reproducible dependency resolution if the lock file is not used.

How to fix:
Copy `uv.lock` before `uv sync`.

Fix now or later:
Before CI/CD or deployment.

### 28. No Tests Are Present

Severity: High

Why this is a problem:
`pytest` is configured, but `tests/` has no test files. Critical matching, extraction, repository, and price-change behavior is unprotected.

How to fix:
Add focused unit tests for matching preprocessors, similarity/confidence, extractor fixtures, repositories, and price-change logic.

Fix now or later:
Now, before more features are added.

### 29. Scripts Duplicate Composition Logic

Severity: Low

Why this is a problem:
Many demo scripts manually wire the same dependencies. This is acceptable during exploration but can drift from real application wiring.

How to fix:
Keep demos, but introduce small demo factories or reuse provider/factory functions when patterns stabilize.

Fix now or later:
Later.

### 30. MarketplacePipeline Has Too Many Constructor Dependencies

Severity: Medium

Why this is a problem:
The constructor takes many concrete collaborators, which makes composition verbose and increases wiring errors, as seen by older demo scripts missing newer dependencies.

How to fix:
Introduce a pipeline factory after interfaces stabilize.

Fix now or later:
Later, after the second marketplace is integrated.

### 31. Existing Demo May Be Broken After Pipeline Constructor Change

Severity: Medium

Why this is a problem:
`scripts/demo_marketplace_pipeline.py` constructs `MarketplacePipeline` without `repository_provider`, while the pipeline constructor now requires it. This script likely fails.

How to fix:
Update the demo to use `create_memory_provider()`.

Fix now or later:
Now, because demos are part of current verification.

### 32. Matching Service Does Not Update ParsedOffer Link

Severity: Low

Why this is a problem:
`MatchingService` returns `MatchResult`, but it does not update `ParsedOffer.canonical_product_id`. This is clean separation, but the next orchestration step must not forget to persist the selected link.

How to fix:
Add a separate command/service later that applies approved matches.

Fix now or later:
Later.

### 33. RepositoryProvider Is Not Yet Used Across All Business Services

Severity: Medium

Why this is a problem:
The provider exists, but only parsed offer persistence is integrated. Other services still use direct in-memory collaborators.

How to fix:
Adopt the provider gradually for price history and canonical product access.

Fix now or later:
Now for price history, later for optional services.

### 34. Clean Architecture Boundaries Are Incomplete

Severity: Medium

Why this is a problem:
Domain dataclasses, SQLAlchemy models, repository contracts, and parser DTOs coexist under broad `app/models` and `app/parsers/models.py`. The direction is understandable, but boundaries are not yet strict.

How to fix:
Clarify naming and package boundaries before the model count grows.

Fix now or later:
Later, but before a large domain expansion.

### 35. No Input Validation For Marketplace URLs In Demos/Pipeline

Severity: Medium

Why this is a problem:
Pipeline demos pass URLs directly to HTTP clients. If reused in app code, this can become SSRF-like behavior or accidental arbitrary outbound requests.

How to fix:
Whitelist marketplace base URLs in production orchestration.

Fix now or later:
Before exposing URL input to users or APIs.

### 36. No Secret Storage Strategy

Severity: Medium

Why this is a problem:
Secrets are currently environment variables. That is fine for server apps, but the requested Playerok Finance context mentions future master-password risks. No desktop secret storage or encryption strategy exists in this workspace.

How to fix:
For desktop/Tauri, define key derivation, encrypted local storage, rotation, and lock timeout before implementing master password.

Fix now or later:
Now, if the next stage includes credentials or secrets.

### 37. No Observability Around Pipeline Failures

Severity: Medium

Why this is a problem:
Pipeline stages report strings through a callback. There is no structured event/error model for stage failures, skipped snapshots, or extraction quality.

How to fix:
Return a pipeline result object with counts and errors, while still allowing logging callbacks.

Fix now or later:
Later, but before production monitoring.

### 38. `PriceChangeDetector` Can Divide By Zero

Severity: Medium

Why this is a problem:
If previous price is zero, percentage calculation divides by zero.

How to fix:
Handle zero previous price explicitly.

Fix now or later:
Now, because it is a correctness bug.

### 39. Pydantic Events Use Float For Financial Data

Severity: Medium

Why this is a problem:
Financial event payloads should preserve precision. Float formatting can produce subtle rounding errors.

How to fix:
Use `Decimal` or a dedicated money DTO in event models.

Fix now or later:
Before production event generation.

### 40. No CI Evidence

Severity: Medium

Why this is a problem:
There is no visible CI configuration. With no tests and no CI, regressions can enter quickly.

How to fix:
Add CI for ruff, mypy, pytest, and alembic migration checks.

Fix now or later:
Now, before team development accelerates.

## Frontend Audit

Status: Not auditable in this workspace.

Findings:

- No React code found.
- No Zustand stores found.
- No frontend type configuration found.
- No build or lint scripts for frontend found.

Release impact:
Critical if Playerok Finance is expected to include a UI.

## Tauri Audit

Status: Not auditable in this workspace.

Findings:

- No `src-tauri` found.
- No Tauri commands found.
- No Rust DTO serialization code found.
- No Tauri security config found.

Release impact:
Critical if Playerok Finance is a Tauri desktop app.

## Rust Audit

Status: Not auditable in this workspace.

Findings:

- No Rust source found.
- No `DatabaseService`, repository, or transaction layer found.
- No Rust error model found.

Release impact:
Critical for a Rust-backed desktop application.

## SQLite Audit

Status: Not auditable in this workspace.

Findings:

- No SQLite schema or migrations found.
- Current project uses PostgreSQL-oriented dependencies and Alembic.

Release impact:
Critical if SQLite is the intended production storage.

## UX Audit

Current repository has no UI, so UX audit is limited to developer/demo workflows.

Key issues:

- Several demos depend on live GGSEL availability.
- Older demos can drift after constructor/API changes.
- Pipeline reports status through plain text rather than structured results.
- No user-facing error model exists.

## Scalability Risks At 50,000 Sales / Offers

- In-memory repositories will grow without limits.
- Offer repository append-only behavior can duplicate repeated marketplace runs.
- No DB indexes are ready for product or price-history lookups.
- GGSEL HTML extraction can become CPU-heavy if repeated frequently.
- Pipeline processes offers sequentially.
- No batching strategy exists for repository writes.
- No backpressure/rate-limit strategy exists for external sources.
- No archival strategy exists for historical price snapshots.

## Performance Risks

- Recursive traversal of large embedded HTML payloads can be expensive.
- Set-based similarity is cheap, but matching is O(offers * candidates).
- No candidate pre-filtering exists before matching.
- No indexing of canonical products by normalized tokens exists.
- Pipeline does not batch persistence.

## Code Quality Risks

- Duplicate price-change detectors.
- Empty repository contract for price history.
- Demo scripts duplicate dependency wiring.
- Some abstractions are created before full usage, increasing drift risk.
- No automated tests.
- Some naming is ambiguous between domain models, SQLAlchemy models, and DTOs.

## Top 20 Priority Improvements

1. Verify the correct Playerok Finance repository is being audited.
2. Add tests for matching preprocessing, similarity, confidence, and matching service.
3. Fix GGSEL price/currency normalization from extracted payload fields.
4. Define `PriceHistoryRepository` methods.
5. Move pipeline price-history usage behind `RepositoryProvider`.
6. Remove or consolidate duplicate `PriceChangeDetector` implementations.
7. Fix divide-by-zero handling in price-change percentage calculation.
8. Update broken demos after `MarketplacePipeline` constructor changes.
9. Add unique constraint for product identity: `(marketplace_id, external_id)`.
10. Add indexes for product and price-history access patterns.
11. Copy `uv.lock` in Dockerfile before dependency sync.
12. Change Docker command to run the application when Docker is used for app execution.
13. Add CI for ruff, mypy, pytest, and migration checks.
14. Decide sync vs async repository contracts before PostgreSQL implementation.
15. Add structured pipeline result object for counts/errors.
16. Add API-first or fixture-backed strategy for GGSEL extraction stability.
17. Include `CanonicalProduct.aliases` in matching candidate evaluation.
18. Replace float money fields in events with `Decimal` or a money DTO.
19. Introduce offer identity/upsert semantics.
20. Define secret-storage strategy before implementing master-password or credential features.

## Architecture Score

Current inspected repository score: 5.5 / 10.

Reasoning:
The project has useful foundations and clear intent, but major pieces are still exploratory. Boundaries exist, but are not consistently applied end-to-end. The absence of tests, incomplete persistence contracts, and incomplete price normalization are the largest blockers.

Playerok Finance requested-scope score: Not assignable from this workspace.

Reasoning:
React, Tauri, Rust, and SQLite code are absent.

## MVP Release Readiness

Current inspected repository: Not ready for MVP release.

Main reasons:

- No tests.
- Real price snapshot flow is blocked by incomplete price normalization.
- Persistence is in-memory only.
- Pipeline has demo drift risk.
- No production delivery path exists.

Playerok Finance requested scope: Not ready to assess.

Main reason:
The required frontend/Tauri/Rust/SQLite code is not present.

## Long-Term Development Readiness

Current inspected repository: Partially ready.

Strengths:

- Clear incremental layering.
- Repository contracts exist.
- Matching components are deterministic and small.
- Parser extraction and normalization are separated.

Weaknesses:

- Contracts are incomplete.
- Persistence strategy is not fully aligned.
- No tests/CI.
- Some service boundaries are still concrete and marketplace-specific.
- Financial precision needs cleanup before real use.

## Final Recommendation

Do not start the next feature-heavy development phase until the high-priority consistency items are addressed:

- correct repository/workspace confirmation;
- tests;
- GGSEL price normalization;
- price-history repository contract;
- pipeline persistence alignment;
- duplicate detector cleanup;
- CI setup.
