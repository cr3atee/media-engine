# Backlog

## Purpose

This document lists only confirmed work remaining after backend core release
candidate verification.

## Immediate

- Bootstrap a curated canonical catalog and confirmed same-product marketplace
  links. Current saved real payloads have no `AUTO_MATCH` or `REVIEW` result
  across `1,280` cross-marketplace title pairs, so weakening matching thresholds
  or inventing preview links is not acceptable. Equivalent Minecraft key
  categories are now live-verified for all three sources, but all `108,880`
  aligned-category pairs remain below `REVIEW`. Use the tenant-scoped
  `CanonicalOfferLinkService` to populate only reviewed exact variants. The
  PostgreSQL schema now prevents cross-tenant canonical links; catalog
  population remains. Immutable confirm/reject persistence and atomic review
  orchestration now exist. The tenant-authorized HTTP review queue excludes
  terminal pairs before matching; use it to populate production links only when
  source candidates reach the unchanged `REVIEW` threshold. Curated aliases now
  participate in matching, so catalog bootstrap should add aliases only from
  verified product evidence rather than copying arbitrary marketplace titles.
  Authorized sellers can now read stable source-backed proposals for
  `NO_MATCH` offers and atomically confirm a new product plus its source link.
  They can also resolve a proposal to its displayed existing canonical product
  with immutable human evidence, without creating duplicates or lowering
  thresholds. The authenticated catalog-review workspace now exposes these
  completed commands. Its saved-data preview now exposes all `81` captured real
  offers as unresolved proposals without pre-seeding products or links, and the
  PostgreSQL onboarding verifier proves replay-safe persistence and restart
  recovery. Use the review workspace to make evidence-backed catalog decisions,
  then populate production only through explicitly approved operator actions
  and record source coverage. The current live candidate evidence is recorded
  in `docs/CATALOG_REVIEW_EVIDENCE.md`; all candidates remain unapproved.
- Decide whether the embedded Market Terminal shell remains inside this
  repository or moves to a separate frontend project before public launch.
- Decide whether public category browse must require parser/category retention
  before launch; saved marketplace payloads currently do not populate category
  DTOs.
- Add PostgreSQL-specific public query adapters only if direct SQL read
  optimization is explicitly approved after the repository-backed adapter is
  exercised.
- Add live marketplace polling monitoring and production runtime integration
  configuration before relying on GGSEL, Playerok, or FunPay for scheduled
  ingestion.
- Define the next EPIC before implementing live marketplace credential storage
  or execution-time credential retrieval.
- Keep tenant-owned marketplace integrations redacted and metadata-only until a
  secret-storage design is explicitly approved.
- If explicitly approved credentials and a test chat are available, run exactly
  one guarded live Telegram test-chat verification.

## Delivery

- Keep production Telegram delivery disabled until PostgreSQL verification,
  optional live test-chat verification, monitoring, and operational
  reconciliation are approved.

## Operational

- Add production metrics export and alert routing for retained worker failures,
  skipped integrations, processing-error counts, and marketplace source drift.
  Tenant-scoped per-run diagnostics are now durable; retention/pruning policy
  should be selected from observed production volume.
- Add production monitoring and alerting for exhausted content attempts and
  ambiguous publications.

## Known Marketplace Gap

- GGSEL, Playerok, and FunPay are ready from captured-response proof, strict
  saved-payload verification, and guarded live polling verification. Production
  scheduling still needs monitoring, alerting, and deployment configuration.
- Real source extraction readiness does not imply same-product comparison
  readiness. The current saved payloads contain `81` snapshot-ready offers but
  no deterministic cross-marketplace match under the existing confidence rules.

## Release Candidate Boundary

- The backend core release gate is complete and repeatable. Do not reopen core
  architecture merely to address catalog population, deployment configuration,
  monitoring, frontend ownership, or category-exposure product decisions.
- A public launch remains blocked by the immediate and operational items above;
  release-candidate status must not be presented as an unattended production
  launch.
