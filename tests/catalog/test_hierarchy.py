from __future__ import annotations

import pytest

from app.catalog.hierarchy import (
    CatalogClassifier,
    CatalogHub,
    CatalogSection,
    SourceCategoryMapping,
)


def _fortnite() -> CatalogHub:
    return CatalogHub(
        code="fortnite",
        name="Fortnite",
        sections=(
            CatalogSection(code="v-bucks", name="В-баксы", offer_type="topups"),
            CatalogSection(
                code="accounts",
                name="Аккаунты",
                offer_type="accounts",
            ),
            CatalogSection(code="rental", name="Аренда"),
        ),
    )


def test_classifier_uses_exact_verified_source_category_mapping() -> None:
    classifier = CatalogClassifier(
        hubs=(_fortnite(),),
        mappings=(
            SourceCategoryMapping(
                marketplace=" Playerok ",
                source_category_id=" fortnite-vbucks ",
                hub_code="fortnite",
                section_code="v-bucks",
            ),
        ),
    )

    result = classifier.classify("PLAYEROK", "fortnite-vbucks")

    assert result is not None
    assert result.hub.name == "Fortnite"
    assert result.section.name == "В-баксы"
    assert result.section.offer_type == "topups"


def test_classifier_does_not_guess_unknown_or_missing_categories() -> None:
    classifier = CatalogClassifier(hubs=(_fortnite(),), mappings=())

    assert classifier.classify("playerok", "unknown") is None
    assert classifier.classify("playerok", None) is None
    assert classifier.classify("playerok", "  ") is None
    assert classifier.classify("  ", "fortnite-vbucks") is None


def test_classifier_keeps_same_source_id_scoped_to_marketplace() -> None:
    hub = _fortnite()
    classifier = CatalogClassifier(
        hubs=(hub,),
        mappings=(
            SourceCategoryMapping("playerok", "accounts", "fortnite", "accounts"),
            SourceCategoryMapping("ggsel", "accounts", "fortnite", "rental"),
        ),
    )

    assert classifier.classify("playerok", "accounts") == classifier.classify(
        "PLAYEROK", "accounts"
    )
    assert classifier.classify("playerok", "accounts") != classifier.classify(
        "ggsel", "accounts"
    )


def test_classifier_rejects_unknown_mapping_targets() -> None:
    with pytest.raises(ValueError, match="Unknown catalog hub"):
        CatalogClassifier(
            hubs=(_fortnite(),),
            mappings=(
                SourceCategoryMapping(
                    "playerok",
                    "accounts",
                    "missing",
                    "accounts",
                ),
            ),
        )

    with pytest.raises(ValueError, match="Unknown section"):
        CatalogClassifier(
            hubs=(_fortnite(),),
            mappings=(
                SourceCategoryMapping(
                    "playerok",
                    "accounts",
                    "fortnite",
                    "missing",
                ),
            ),
        )


def test_classifier_rejects_ambiguous_configuration() -> None:
    hub = _fortnite()
    duplicate = SourceCategoryMapping(
        "playerok",
        "accounts",
        "fortnite",
        "accounts",
    )

    with pytest.raises(ValueError, match="Duplicate catalog hub code"):
        CatalogClassifier(hubs=(hub, hub), mappings=())

    with pytest.raises(ValueError, match="Duplicate marketplace source-category"):
        CatalogClassifier(hubs=(hub,), mappings=(duplicate, duplicate))

    with pytest.raises(ValueError, match="duplicate section codes"):
        CatalogHub(
            code="fortnite",
            name="Fortnite",
            sections=(hub.sections[0], hub.sections[0]),
        )


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("Fort nite", "lowercase slug"),
        ("", "lowercase slug"),
        ("fortnite_2", "lowercase slug"),
    ],
)
def test_hierarchy_rejects_unstable_codes(code: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CatalogHub(code=code, name="Fortnite", sections=())
