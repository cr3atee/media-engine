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

1. Start the bounded workspace with
   `python scripts/run_catalog_review_preview.py --aligned-live-data`.
2. Sign in with the preview credentials printed by the command.
3. Open every source URL and verify edition, included content, platform,
   region, delivery model, availability, and currency.
4. Confirm a new canonical product only when the source offer itself is clear.
5. Resolve a later proposal to an existing product only when both source pages
   prove the exact same sellable variant.
6. Record a concrete evidence reason for every decision.
7. Reject an unsafe pair rather than weakening thresholds or creating a broad
   alias.

The preview is loopback-only and memory-only. It is suitable for reviewing the
batch shape, not for retaining production decisions. Durable launch decisions
must use the authenticated workspace backed by the intended non-production or
production PostgreSQL environment under the normal tenant boundary.

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

## Status

Launch-batch preparation is complete. Product identity approval is deliberately
not complete: it requires a human operator to inspect current source pages and
record durable decisions. Until then, the public catalog must not claim these
offers are the same product.
