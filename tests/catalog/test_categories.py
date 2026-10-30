from __future__ import annotations

import pytest

from app.catalog.categories import (
    MVP_CATALOG_CATEGORIES,
    category_by_code,
    infer_catalog_category,
    resolve_catalog_category,
)


def test_mvp_taxonomy_has_five_stable_categories() -> None:
    assert tuple(category.code for category in MVP_CATALOG_CATEGORIES) == (
        "games",
        "keys",
        "accounts",
        "subscriptions",
        "topups",
    )
    assert resolve_catalog_category("Games") == category_by_code("games")
    assert resolve_catalog_category("Пополнение баланса") == category_by_code("topups")
    assert resolve_catalog_category("unknown") is None


@pytest.mark.parametrize(
    ("title", "expected_code"),
    (
        ("Battlefield 6 Steam gift РФ", "keys"),
        ("Minecraft account full access", "accounts"),
        ("Xbox Game Pass subscription", "subscriptions"),
        ("Пополнение баланса Steam RUB", "topups"),
        ("STEAM РФ-СНГ RUB-KZT-UAH 24/7", "topups"),
        ("CS2 skins and items", "games"),
    ),
)
def test_title_inference_requires_explicit_category_evidence(
    title: str,
    expected_code: str,
) -> None:
    category = infer_catalog_category(title)
    assert category is not None
    assert category.code == expected_code


def test_title_inference_does_not_guess_unknown_product() -> None:
    assert infer_catalog_category("Stardew Valley Complete") is None
