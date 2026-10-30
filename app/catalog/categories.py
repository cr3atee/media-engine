from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

type CatalogCategoryCode = Literal[
    "games",
    "keys",
    "accounts",
    "subscriptions",
    "topups",
]


@dataclass(slots=True, frozen=True)
class CatalogCategory:
    """One stable buyer-facing category in the MVP catalog taxonomy."""

    code: CatalogCategoryCode
    name: str
    aliases: tuple[str, ...]

    def matches(self, value: str) -> bool:
        """Return whether a code, name, or configured alias matches value."""
        normalized = _normalize(value)
        return normalized in {
            _normalize(self.code),
            _normalize(self.name),
            *(_normalize(alias) for alias in self.aliases),
        }

    def contains(self, value: str) -> bool:
        """Return whether value is a partial search for this category."""
        normalized = _normalize(value)
        return any(
            normalized in candidate
            for candidate in (
                _normalize(self.code),
                _normalize(self.name),
                *(_normalize(alias) for alias in self.aliases),
            )
        )


MVP_CATALOG_CATEGORIES: Final[tuple[CatalogCategory, ...]] = (
    CatalogCategory(
        code="games",
        name="Игры и предметы",
        aliases=("game", "games", "игра", "игры", "items", "предметы"),
    ),
    CatalogCategory(
        code="keys",
        name="Ключи и подарки",
        aliases=("key", "keys", "ключ", "ключи", "gift", "gifts", "подарки"),
    ),
    CatalogCategory(
        code="accounts",
        name="Аккаунты",
        aliases=("account", "accounts", "аккаунт", "аккаунты"),
    ),
    CatalogCategory(
        code="subscriptions",
        name="Подписки",
        aliases=("subscription", "subscriptions", "подписка", "подписки"),
    ),
    CatalogCategory(
        code="topups",
        name="Пополнение баланса",
        aliases=("topup", "topups", "top up", "balance", "баланс", "пополнение"),
    ),
)

_INFERENCE_MARKERS: Final[tuple[tuple[CatalogCategoryCode, tuple[str, ...]], ...]] = (
    (
        "accounts",
        (
            "account",
            "accounts",
            "аккаунт",
            "аккаунты",
            "учетная запись",
            "учётная запись",
        ),
    ),
    (
        "subscriptions",
        (
            "subscription",
            "подписк",
            "game pass",
            "playstation plus",
            "ps plus",
            "discord nitro",
            "spotify premium",
            "telegram premium",
        ),
    ),
    (
        "topups",
        (
            "top up",
            "topup",
            "пополн",
            "balance",
            "баланс",
            "wallet",
            "кошел",
            "донат",
            "robux",
            "v bucks",
        ),
    ),
    (
        "keys",
        (
            "key",
            "keys",
            "ключ",
            "gift",
            "гифт",
            "activation",
            "активац",
            "license",
            "лиценз",
        ),
    ),
    (
        "games",
        ("skin", "skins", "скин", "предмет", "item", "items", "dlc"),
    ),
)


def resolve_catalog_category(value: str | None) -> CatalogCategory | None:
    """Resolve a persisted legacy value or public code to the MVP category."""
    if value is None or not value.strip():
        return None
    return next(
        (category for category in MVP_CATALOG_CATEGORIES if category.matches(value)),
        None,
    )


def infer_catalog_category(title: str | None) -> CatalogCategory | None:
    """Infer a category only when a marketplace title contains explicit evidence."""
    if title is None or not title.strip():
        return None
    normalized = _normalize_title(title)
    for code, markers in _INFERENCE_MARKERS:
        if any(_contains_marker(normalized, marker) for marker in markers):
            return category_by_code(code)

    tokens = set(normalized.split())
    currencies = tokens.intersection({"rub", "kzt", "uah", "usd", "eur"})
    if "steam" in tokens and len(currencies) >= 2:
        return category_by_code("topups")
    return None


def category_by_code(code: CatalogCategoryCode) -> CatalogCategory:
    """Return one configured category by its stable public code."""
    return next(
        category for category in MVP_CATALOG_CATEGORIES if category.code == code
    )


def _normalize(value: str) -> str:
    return " ".join(
        value.strip().casefold().replace("_", " ").replace("-", " ").split()
    )


def _normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _contains_marker(normalized_title: str, marker: str) -> bool:
    words = normalized_title.split()
    if marker in {"подписк", "пополн", "кошел", "активац", "лиценз"}:
        return any(word.startswith(marker) for word in words)
    if " " in marker:
        return f" {marker} " in f" {normalized_title} "
    return marker in words
