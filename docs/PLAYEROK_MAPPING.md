# Playerok to ParsedOffer Mapping

## Status

Document date: 2026-07-22.
Last verified update: 2026-09-07.

This document defines how Playerok marketplace data should map to the existing MediaEngine `ParsedOffer` contract. It is documentation only and does not modify application code.

## Source Assumptions

Playerok data should be taken from the structured source selected in `docs/PLAYEROK_TECH_SPEC.md`:

- preferred source: Playerok native GraphQL/public JSON data;
- fallback source: public REST/BFF endpoint if browser network research confirms one;
- HTML should not be the primary source for field extraction.

The public Playerok GraphQL `items` response has been verified. The current
response shape uses `data.items.edges[].node` for item offers and exposes
`pageInfo` for cursor pagination.

Confirmed item fields:

- `id`
- `slug`
- `name`
- `price`
- `rawPrice`
- `status`
- `user.id`
- `user.username`
- `category`
- `game`
- `attachment.url`

The response does not expose an explicit currency field. A direct GraphQL
`currency` field query was rejected by schema validation for both
`MyItemProfile` and `ForeignItemProfile`. The frontend product-page bundle
formats item `price`/`rawPrice` ecommerce events with `currency: "RUB"`, so the
Playerok normalizer applies `RUB` as a documented source-backed fallback.

## ParsedOffer Contract

Current `ParsedOffer` fields:

| Field | Type |
| --- | --- |
| `marketplace` | `str` |
| `external_id` | `str | None` |
| `title` | `str | None` |
| `url` | `str | None` |
| `price` | `Decimal | None` |
| `currency` | `str | None` |
| `seller_id` | `str | None` |
| `seller_name` | `str | None` |
| `canonical_product_id` | `UUID | None` |

## Field Mapping

| ParsedOffer field | Playerok source field | Source data type | Transformation | Required / Optional | Default if missing |
| --- | --- | --- | --- | --- | --- |
| `marketplace` | constant | `str` | Set to `"playerok"` | Required | `"playerok"` |
| `external_id` | `node.id`; fallback `node.slug` | `str` or `int` | Convert to `str` | Required when available | `None` |
| `title` | `node.name`; fallback `node.title` | `str` | Trim surrounding whitespace; keep original meaning and casing unless normalizer requires otherwise | Required when available | `None` |
| `url` | `node.slug`, `node.url` | `str` | If slug is present, build `https://playerok.com/products/{slug}`; if absolute URL is present, keep it | Required when available | `None` |
| `price` | `node.price` | `str`, `int`, or decimal-like value | Convert to `Decimal` from string/int; do not use float arithmetic | Required when available | `None` |
| `currency` | not present in verified `items` response; frontend bundle uses `currency: "RUB"` for item price tracking | `str` | Normalize explicit currency when present; otherwise use documented Playerok `RUB` fallback | Required for snapshot readiness | `"RUB"` |
| `seller_id` | `node.user.id`; fallback `seller.id`, `owner.id` | `str` or `int` | Convert to `str` | Optional | `None` |
| `seller_name` | `node.user.username`; fallback `seller.username`, `seller.name`, `user.name` | `str` | Trim surrounding whitespace | Optional | `None` |
| `canonical_product_id` | no Playerok source | `UUID | None` | Not populated by marketplace extraction; filled later by matching engine | Optional | `None` |

## Domain Field Notes

### Price

Use only the current effective marketplace price for `ParsedOffer.price`.

Do not map marketplace `raw_price`, old price, discount price, crossed-out price, fee multiplier, or UI promotion price into `ParsedOffer.price` unless the response confirms that the value is the current buyer-facing price.

Transformation rules:

- parse from string or integer into `Decimal`;
- strip currency symbols and separators only in the normalizer;
- avoid float arithmetic;
- return `None` if price is absent or ambiguous.

### Title

Map Playerok product name/title to `ParsedOffer.title`.

Transformation rules:

- trim leading and trailing whitespace;
- preserve marketplace wording;
- do not apply matching normalization here;
- do not remove marketplace-specific tokens at this layer.

### Description

Current status: cannot be mapped to `ParsedOffer`.

Reason:

- `ParsedOffer` has no `description` field.

If Playerok response contains `description`, it should remain in a future raw Playerok model or raw metadata structure. It should not be added to `ParsedOffer` unless a universal marketplace need is approved.

### Seller

Map public seller data into:

- `seller_id`;
- `seller_name`.

Do not use seller description, seller rating, review count, registration date, online status, or delivery statistics to determine product identity. Those values are not part of the current `ParsedOffer` contract.

### Product ID

Preferred source:

- stable Playerok item/product `id`.

Fallback:

- stable product `slug`.

Mapping rule:

- `external_id` must uniquely identify the marketplace offer inside Playerok;
- if both `id` and `slug` exist, use `id` as `external_id` and use `slug` for URL construction;
- if only `slug` exists, use `slug` as `external_id`.

### URL

Preferred URL:

- absolute URL from response, if present.

Fallback URL:

- `https://playerok.com/products/{slug}`.

If neither absolute URL nor slug exists, set `ParsedOffer.url` to `None`.

### Category

Current status: cannot be mapped to `ParsedOffer`.

Reason:

- `ParsedOffer` has no `category` field.

Potential Playerok fields:

- `category.id`;
- `category.name`;
- `game.id`;
- `game.name`.

These values may be useful for filtering and diagnostics, but they should stay outside `ParsedOffer` until a universal category contract is introduced.

### Currency

Preferred source:

- explicit currency field from response.

Current verified source:

- the public GraphQL `items` response does not include currency;
- direct `currency` field selection is rejected by the GraphQL schema.
- the Playerok frontend product-page bundle uses `currency: "RUB"` for item
  price/raw-price ecommerce tracking.

Fallback:

- `RUB`.

Keep this fallback at the Playerok adapter boundary. Do not move it into shared
`ParsedOffer`, `SnapshotBuilder`, or repository code.

### Image

Current status: cannot be mapped to `ParsedOffer`.

Reason:

- `ParsedOffer` has no `image` field.

If Playerok returns image/preview data, keep it in raw source data for future content or UI use. Do not add it to `ParsedOffer` during the first integration stage.

### Availability

Current status: cannot be mapped to `ParsedOffer`.

Reason:

- `ParsedOffer` has no `availability` field.

Potential Playerok fields:

- `status`;
- `isAvailable`;
- `availableQuantity`;
- `stock`;
- `isSold`;
- `isActive`.

Initial extraction should include only offers returned by the public listing endpoint. If availability is explicit and indicates an unavailable item, the fetcher/normalizer decision must be documented before filtering.

## Fields Not Currently Obtainable or Not Confirmed

The following fields cannot currently be guaranteed from the verified public
GraphQL item-list response:

- description;
- availability beyond the requested `APPROVED` status filter;
- whether image data is always present.

The following fields are outside the current `ParsedOffer` contract even if Playerok provides them:

- `description`;
- `category`;
- `image`;
- `availability`;
- seller rating;
- review count;
- delivery method;
- marketplace priority;
- product/game metadata;
- raw discount fields.

## Implementation Guidance

1. Continue using the verified public GraphQL `items` response for item lists.
2. Keep the documented `RUB` fallback covered by tests and readiness
   verification.
3. Map only universal fields into `ParsedOffer`.
4. Leave missing values as `None`; do not invent values.
5. Keep Playerok-specific fields in a raw adapter model if they are needed later.
6. Do not expand `ParsedOffer` for one marketplace only.
