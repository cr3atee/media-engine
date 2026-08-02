# Playerok to ParsedOffer Mapping

## Status

Document date: 2026-07-22.

This document defines how Playerok marketplace data should map to the existing MediaEngine `ParsedOffer` contract. It is documentation only and does not modify application code.

## Source Assumptions

Playerok data should be taken from the structured source selected in `docs/PLAYEROK_TECH_SPEC.md`:

- preferred source: Playerok native GraphQL/public JSON data;
- fallback source: public REST/BFF endpoint if browser network research confirms one;
- HTML should not be the primary source for field extraction.

The exact Playerok response shape is not fully confirmed yet. Source field names below are expected names based on current research and must be verified against a captured real response before implementation.

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
| `external_id` | `item.id`, `product.id`; fallback `item.slug` | `str` or `int` | Convert to `str` | Required when available | `None` |
| `title` | `item.name`, `product.name`, `item.title` | `str` | Trim surrounding whitespace; keep original meaning and casing unless normalizer requires otherwise | Required when available | `None` |
| `url` | `item.slug`, `product.slug`, `item.url` | `str` | If slug is present, build `https://playerok.com/products/{slug}`; if absolute URL is present, keep it | Required when available | `None` |
| `price` | `item.price`, `product.price`, current effective price field | `str`, `int`, or decimal-like value | Convert to `Decimal` from string/int; do not use float arithmetic | Required when available | `None` |
| `currency` | `item.currency`, `price.currency` | `str` | Normalize to uppercase currency code if explicit in response | Optional | `None`; use `"RUB"` only after endpoint confirms RUB |
| `seller_id` | `seller.id`, `user.id`, `owner.id` | `str` or `int` | Convert to `str` | Optional | `None` |
| `seller_name` | `seller.username`, `seller.name`, `user.username`, `user.name` | `str` | Trim surrounding whitespace | Optional | `None` |
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

Fallback:

- `None`.

Do not assume `"RUB"` unless the captured endpoint response or product page context confirms that the price is RUB. If confirmed, the Playerok normalizer may default missing currency to `"RUB"` with a documented reason.

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

The following fields cannot currently be guaranteed because no final real Playerok response sample is captured in the project documentation:

- exact current price field name;
- exact currency field name;
- exact seller display field name;
- exact category/game object structure;
- exact availability/status field name;
- whether description is included in listing responses or only detail responses;
- whether image data is included in listing responses.

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

1. Capture one real Playerok listing response before coding the normalizer.
2. Confirm exact field names for id, title, price, currency, URL and seller.
3. Map only universal fields into `ParsedOffer`.
4. Leave missing values as `None`; do not invent values.
5. Keep Playerok-specific fields in a raw adapter model if they are needed later.
6. Do not expand `ParsedOffer` for one marketplace only.
