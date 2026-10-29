# EPIC 23 - Guarded Catalog Launch Batch

## Goal

Prepare a small, source-backed catalog batch for human review without changing
matching thresholds, inventing product identity, or mutating the canonical
catalog automatically.

## Guardrails

- The existing GGSEL, Playerok, and FunPay adapters are the only data sources.
- The existing deterministic matcher and confidence thresholds remain
  unchanged.
- Category alignment and title similarity are evidence, not proof of identical
  products.
- Every selected offer remains a `NO_MATCH` proposal until an authorized
  operator records a decision through `/terminal/review`.
- Price comparison is unavailable when currencies differ.
- No offer, canonical product, alias, link, or review decision is persisted by
  the preparation commands.

## Verified Live Input

Observed on 2026-10-22 through the existing public adapter boundaries:

| Marketplace | Source count | Parsed | Snapshot-ready |
| --- | ---: | ---: | ---: |
| GGSEL | 60 | 60 | 60 |
| Playerok | 201 | 20 | 20 |
| FunPay | 1,418 | 1,418 | 1,418 |

The three batches contain `1,498` snapshot-ready offers and produce `114,640`
cross-marketplace pairs. Existing matching classifies every pair as
`NO_MATCH`; the highest similarity is `0.714`. The complete three-source
verification passed.

## Bounded Review Batch

The existing aligned-live preview selected the highest-scoring pair for each
available marketplace pairing and deduplicated repeated offers. Its check
passed with five proposals and zero automatic catalog mutations.

| Marketplace | External ID | Price | Source title | Review state |
| --- | --- | ---: | --- | --- |
| FunPay | `25007196` | `22.60 EUR` | Minecraft: Java & Bedrock Edition PC, key plus VPN | Inspect activation and region |
| GGSEL | `102169338` | `1899.0 RUB` | Minecraft: Java & Bedrock Edition, PC, GLOBAL | Inspect activation and region |
| FunPay | `75886527` | `35.12 EUR` | Minecraft: Java & Bedrock Edition, PC, digital key | Do not link from title alone |
| Playerok | `1f1cdf3f-373d-6e00-b2b0-a0e7e51b90e5` | `1190 RUB` | Minecraft Java & Bedrock mega cape bundle | Likely different bundle; reject unless source evidence disproves this |
| GGSEL | `102083633` | `1745.0 RUB` | Minecraft Java & Bedrock Edition, PC, GLOBAL activation key | Do not link to the cape bundle |

Observed source URLs:

- FunPay `25007196`: <https://funpay.com/lots/offer?id=25007196>
- GGSEL `102169338`:
  <https://ggsel.net/catalog/minecraft-java-bedrock-edition-pc-globalnyi-102169338>
- FunPay `75886527`: <https://funpay.com/lots/offer?id=75886527>
- Playerok `1f1cdf3f-373d-6e00-b2b0-a0e7e51b90e5`:
  <https://playerok.com/products/a0e7e51b90e5-mega-nabor-plashchey-klyuch-minecraft-java-bedrock>
- GGSEL `102083633`:
  <https://ggsel.net/catalog/minecraft-java-bedrock-edition-pc-global-key-kliuc-aktivacii-102083633>

These URLs remain visible in the authenticated review workspace. They must be
opened immediately before a decision because listing availability and terms can
change.

## Operator Decision Procedure

1. Provision an isolated loopback PostgreSQL database whose name starts with
   `epic23_catalog_review_`.
2. Set `EPIC23_CATALOG_REVIEW_DATABASE_URL` for that database and start the
   durable workspace with
   `python scripts/run_catalog_review_postgres.py --aligned-live-data`.
3. Sign in with the local reviewer credentials printed by the command.
4. Open every source URL and verify edition, included content, platform,
   region, delivery model, availability, and currency.
5. Confirm a new canonical product only when the source offer itself is clear.
6. Resolve a later proposal to an existing product only when both source pages
   prove the exact same sellable variant.
7. Record a concrete evidence reason for every decision.
8. Reject an unsafe pair rather than weakening thresholds or creating a broad
   alias.

For a non-mutating startup check, add `--check`. The runner refuses non-loopback
hosts and database names outside the dedicated prefix, applies the existing
Alembic head, seeds identity and offers idempotently, and redacts credentials
from startup errors.

The memory-only preview remains available for disposable UI inspection:

`python scripts/run_catalog_review_preview.py --aligned-live-data`

It is not suitable for retaining launch decisions. Durable decisions must use
the PostgreSQL runner or the intended deployed environment under the normal
tenant boundary.

## Verification

- `python scripts/run_catalog_review_preview.py --aligned-live-data --check`:
  passed with `funpay=2`, `ggsel=2`, `playerok=1`, `candidates=0`,
  `proposals=5`.
- `python scripts/verify_aligned_marketplace_categories.py`: passed complete
  three-source evidence with `114,640` deterministic pairs.
- `python scripts/verify_epic20_catalog_onboarding.py`: passed all `4/4`
  offline acceptance gates; all saved real offers remained unreviewed.
- `python scripts/run_catalog_review_preview.py --saved-data --check`: passed
  with `81` proposals and zero candidates.
- `python scripts/run_catalog_review_postgres.py --aligned-live-data --check`:
  passed twice against isolated PostgreSQL 17 at migration `0017`; both runs
  retained exactly five offers and five proposals with zero links or decisions.
- `python scripts/verify_epic23_post_review.py`: passed `45/45` read-only checks
  against the retained isolated PostgreSQL 17 review database at revision
  `0021`. Two canonical products, six immutable decisions, five active links,
  and one retired confirmed link survived a fresh engine. Public products,
  offers, and comparisons used exactly the active reviewed set.

## Status

Launch-batch preparation and one bounded human review are complete in the
isolated local workspace. The retained result contains two canonical products,
six immutable decisions, and five currently active offer links. This is valid
integration evidence for the decision-to-public-read path; it is not a claim
that the same catalog has been deployed to production or that unresolved offers
outside this bounded batch have been approved.

## Local Post-review Link Audit

The isolated local review workspace contained six confirmed links across two
canonical products. A direct availability audit on 2026-10-27 returned HTTP
200 for both GGSEL links, both Playerok links, and FunPay `25007196`. FunPay
`80145738` returned HTTP 404.

The workspace has no persisted marketplace integration records, so the
source-observation migration cannot infer ownership for those manually seeded
legacy rows. On 2026-10-29, an authenticated reviewer retired FunPay
`80145738` through the authorized, versioned, idempotent API command. The replay
returned the same result, immutable action
`04dcb553-f35a-48b6-9310-0a42786de930` was retained, and ordinary repository
and public reads excluded the link without deleting its offer, decision, or
history. Automated repeat checks returned `401` for GGSEL and `403` for
Playerok; these protected responses were not misclassified as missing offers.
The same action must be repeated only if this stale row exists in a future
target deployment; direct SQL and fabricated replacement URLs remain forbidden.
