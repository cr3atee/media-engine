# Catalog

## Purpose
Описание подхода к каталогу товаров.

## CatalogItem
Назначение единой карточки товара в каталоге.

## Matching
Принципы сопоставления предложений маркетплейсов с каталогом.

## Administration
Роль администратора в подтверждении решений системы.

## MVP Category Taxonomy

The buyer-facing catalog uses five stable categories:

- `games` - Игры и предметы;
- `keys` - Ключи и подарки;
- `accounts` - Аккаунты;
- `subscriptions` - Подписки;
- `topups` - Пополнение баланса.

The public category API always returns the complete taxonomy, including
categories whose current product count is zero. Existing persisted category
names and legacy aliases are normalized to these stable codes at the read
boundary. Unknown values remain unclassified instead of being forced into an
unrelated category.

Creating a canonical product from the seller review workspace requires an
explicit category selection. The selected public code is included in the
idempotency fingerprint and the canonical Russian category name is stored in
the existing `CanonicalProduct.category` field. No schema migration is needed.

Saved-data preview classification is deliberately conservative: it uses only
explicit title evidence. A title without sufficient evidence remains visible
under the complete catalog view and receives no invented category.

Marketplace source category evidence is separate from this public taxonomy.
`ParsedOffer.source_category_id` and `source_category_name` retain exact adapter
data through memory and PostgreSQL persistence. GGSEL currently supplies the
section identifier, Playerok supplies category ID and name, and the supported
FunPay offer-preview contract supplies neither. The review workspace displays
this evidence, but only the reviewer selects the canonical public category.
