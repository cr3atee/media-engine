# Catalog Review Evidence

## Purpose

This document records source-backed evidence for human canonical-product
review. It is not an approval manifest and must not be used to create automatic
links.

## Latest Live Observation

Observed on 2026-10-05 through the existing public GGSEL, Playerok, and FunPay
adapter boundaries:

| Marketplace | Source count | Parsed | Snapshot-ready |
| --- | ---: | ---: | ---: |
| GGSEL | 60 | 60 | 60 |
| Playerok | 173 | 20 | 20 |
| FunPay | 1,346 | 1,346 | 1,346 |

The aligned Minecraft key batches produced `1,426` offers and `108,880`
cross-marketplace title pairs. Existing deterministic matching classified all
pairs as `NO_MATCH`; the highest similarity was `0.714`. No threshold was
changed and no record was persisted.

## Candidate Evidence

### FunPay / GGSEL Base Edition

Status: `NEEDS HUMAN CONFIRMATION`.

- FunPay `25007196`: `Minecraft: Java & Bedrock Edition PC`, `21.64 EUR`,
  seller `NWKeKsIKNW`, with `KEY+VPN` wording.
- GGSEL `102169338`: `Minecraft: Java & Bedrock Edition | PC | GLOBAL`,
  `1699 RUB`, seller `BaronAutomaton`.
- Similarity: `0.714`.
- Risk: VPN and GLOBAL wording may represent different activation or region
  constraints. Currencies also differ, so the current comparator must mark the
  price comparison unavailable.

### FunPay / Playerok Account-Key Variant

Status: `NEEDS HUMAN CONFIRMATION`.

- FunPay `65294767`: `Minecraft: Java + Bedrock PC Key to your account`,
  `19.89 EUR`, seller `thousis13`.
- Playerok `1f18fda8-28e1-6c70-d6fa-23b1b5d0b29c`: `Minecraft Java +
  Bedrock key to your account`, `1999 RUB`, seller `NightWalker9`.
- Similarity: `0.357`.
- Risk: the listing response does not expose enough description or activation
  detail to prove equivalent delivery terms. Currencies differ.

### GGSEL / Playerok Same-Currency Inspection

Status: `NEEDS HUMAN CONFIRMATION`.

- GGSEL `103219667`: `Minecraft: Java + Bedrock for PC Key GLOBAL`,
  `1855.54 RUB`, seller `geiwoaichide`.
- Playerok `1f18fda8-28e1-6c70-d6fa-23b1b5d0b29c`: `Minecraft Java +
  Bedrock key to your account`, `1999 RUB`, seller `NightWalker9`.
- Similarity: `0.182`.
- Benefit: both prices use RUB, so an approved canonical link would exercise
  the existing comparator without currency conversion.
- Risk: GLOBAL and account-bound wording must be checked on both source pages
  before approval.

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
