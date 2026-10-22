# Catalog Review Evidence

## Purpose

This document records source-backed evidence for human canonical-product
review. It is not an approval manifest and must not be used to create automatic
links.

## Latest Live Observation

Observed on 2026-10-22 through the existing public GGSEL, Playerok, and FunPay
adapter boundaries:

| Marketplace | Source count | Parsed | Snapshot-ready |
| --- | ---: | ---: | ---: |
| GGSEL | 60 | 60 | 60 |
| Playerok | 201 | 20 | 20 |
| FunPay | 1,418 | 1,418 | 1,418 |

The aligned Minecraft key batches produced `1,498` offers and `114,640`
cross-marketplace title pairs. Existing deterministic matching classified all
pairs as `NO_MATCH`; the highest similarity was `0.714`. No threshold was
changed and no record was persisted. The complete three-source verifier passed.

The same live input was reduced to a bounded memory-only operator preview. It
selected two FunPay, two GGSEL, and one Playerok offer, producing five
`NO_MATCH` proposals and zero review candidates. The exact batch and operator
procedure are recorded in `docs/EPIC_23_CATALOG_LAUNCH_BATCH.md`.

## Previous Availability Incident

On 2026-10-12, GGSEL and FunPay remained available while Playerok returned
`HTTP 502`. Failure isolation retained successful source evidence, returned a
non-zero status for the incomplete three-source run, and persisted no catalog
decision. The successful 2026-10-22 refresh supersedes that availability result
without changing the safety boundary.

## Candidate Evidence

### FunPay / GGSEL Base Edition

Status: `NEEDS HUMAN CONFIRMATION`.

- FunPay `25007196`: `Minecraft: Java & Bedrock Edition PC`, `22.60 EUR`,
  seller `NWKeKsIKNW`, with `KEY+VPN` wording.
- GGSEL `102169338`: `Minecraft: Java & Bedrock Edition | PC | GLOBAL`,
  `1899.0 RUB`, seller `BaronAutomaton`.
- Similarity: `0.714`.
- Risk: VPN and GLOBAL wording may represent different activation or region
  constraints. Currencies also differ, so the current comparator must mark the
  price comparison unavailable.

### FunPay / Playerok Current Highest Pair

Status: `DO NOT LINK FROM CURRENT EVIDENCE`.

- FunPay `75886527`: `Minecraft: Java & Bedrock Edition`, PC digital key,
  `35.12 EUR`, seller `terusu`.
- Playerok `1f1cdf3f-373d-6e00-b2b0-a0e7e51b90e5`: a Minecraft Java &
  Bedrock mega cape bundle, `1190 RUB`, seller `phoenikz`.
- Similarity: `0.462`.
- Risk: the Playerok title describes a cape bundle rather than the base game.
  The listings must remain separate unless current source detail proves exact
  product equivalence. Currencies also differ.

### GGSEL / Playerok Current Highest Pair

Status: `DO NOT LINK FROM CURRENT EVIDENCE`.

- GGSEL `102083633`: `Minecraft Java & Bedrock Edition (PC) GLOBAL KEY`,
  `1745.0 RUB`, seller `Hann`.
- Playerok `1f1cdf3f-373d-6e00-b2b0-a0e7e51b90e5`: a Minecraft Java &
  Bedrock mega cape bundle, `1190 RUB`, seller `phoenikz`.
- Similarity: `0.455`.
- Risk: both prices use RUB, but the source titles describe different sellable
  content. Currency compatibility is not product-identity evidence.

### False Strongest GGSEL / Playerok Pair

Status: `DO NOT LINK`.

- GGSEL `102842153` is a Java & Bedrock bundle mentioning Deluxe and Ultimate.
- Playerok `1f163312-d72e-6d90-0aba-a06b1c56fa04` is Minecraft Dungeons
  Ultimate.
- Despite being the strongest title score for this source pair (`0.200`), these
  are different products. This confirms that human evidence must remain
  authoritative below the existing review threshold.

## Operator Checklist

Before confirming any pair, verify on both current source pages:

- edition and included content;
- platform;
- activation region;
- key, gift, account, or account-login delivery model;
- availability and current listing status;
- currency compatibility for comparison.

Use the authenticated `/terminal/review` commands only after this evidence is
confirmed. Record a non-empty reason. Do not infer aliases or approve a pair
from category alignment, seller identity, or title similarity alone.

## Current Decision State

No candidate in this document is approved. No canonical product, offer link,
alias, or immutable review decision was created from this report.
