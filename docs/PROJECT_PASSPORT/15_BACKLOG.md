# Backlog

## Purpose

This document lists only confirmed work remaining after backend core release
candidate verification.

## Immediate

- Promote the bounded human-reviewed EPIC 23 catalog from the isolated review
  workspace into the intended target environment only after a fresh source and
  outbound-link audit. The retained local evidence contains two canonical
  products, six immutable decisions, five active links, and one retired link;
  it must not auto-approve the unresolved catalog. Current saved real payloads
  have no `AUTO_MATCH` or
  `REVIEW` result across `1,280` cross-marketplace title pairs, so weakening
  matching thresholds or inventing preview links is not acceptable. Equivalent
  Minecraft key categories are live-verified for all three sources, but all
  `114,640` current aligned-category pairs remain below `REVIEW`. Use the
  tenant-scoped `CanonicalOfferLinkService` to populate only reviewed exact
  variants. The PostgreSQL schema prevents cross-tenant canonical links;
  catalog population remains. Immutable confirm/reject persistence and atomic
  review orchestration exist. Current live candidates do not reach the
  unchanged `REVIEW` threshold, so source evidence and explicit proposal
  decisions remain authoritative. Curated aliases participate in matching;
  add them only from verified product evidence rather than arbitrary listing
  titles. The authenticated catalog-review workspace exposes proposal
  confirmation and existing-product resolution. Its saved-data preview exposes
  all `81` captured real offers as unresolved proposals without pre-seeding
  products or links, and PostgreSQL verification proves replay-safe persistence
  and restart recovery. Current evidence is recorded in
  `docs/CATALOG_REVIEW_EVIDENCE.md`; the exact five-offer batch is recorded in
  `docs/EPIC_23_CATALOG_LAUNCH_BATCH.md`. The isolated PostgreSQL runner retains
  the bounded human decisions across application restarts, and the read-only
  verifier passes `45/45`. Offers outside that decision set remain unapproved;
  do not infer completion from a queue page limit.
- Decide whether the embedded Market Terminal shell remains inside this
  repository or moves to a separate frontend project before public launch.
- Add PostgreSQL-specific public query adapters only if direct SQL read
  optimization is explicitly approved after the repository-backed adapter is
  exercised.
- Run the guarded Playerok session verifier from the target VDS with an
  authorized account, stable outbound IP, same-session User-Agent/cookies, and
  tenant-scoped deployment secret. Prove final-cursor coverage against
  `totalCount`, then complete a 48-72 hour low-frequency soak; do not treat
  offline connector verification as proof that Playerok will allow a
  particular VDS. The current unauthenticated live attempt is explicitly
  access-protection blocked.
- If explicitly approved credentials and a test chat are available, run exactly
  one guarded live Telegram test-chat verification.

## Delivery

- Keep production Telegram delivery disabled until PostgreSQL verification,
  optional live test-chat verification, monitoring, and operational
  reconciliation are approved.

## Operational

- Deploy the configured Prometheus textfile collector and redacted structured
  alert logs into the target monitoring stack. The initial retention duration,
  newest-per-integration protection, batch, and schedule are explicit; revisit
  them only with observed volume/audit evidence. Durable cross-replica alert
  acknowledgement remains owned by the external alert manager.

## Known Marketplace Gap

- GGSEL and FunPay have current complete-source live proof (`110/110` and
  `1442/1442`). Playerok has captured-response proof and a complete-evidence
  runtime contract, but still requires guarded authorized-session proof on the
  target VDS. Production scheduling has explicit deployment policy and a passed
  PostgreSQL operations gate; it still needs target collector rollout and
  authenticated-source credentials.
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
