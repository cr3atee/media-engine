from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.catalog.hierarchy import (
    CatalogClassifier,
    CatalogHub,
    CatalogSection,
    CatalogSourceRule,
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


def test_integration_mapping_overrides_generic_marketplace_mapping() -> None:
    hub = _fortnite()
    integration_id = UUID(int=500)
    classifier = CatalogClassifier(
        hubs=(hub,),
        mappings=(
            SourceCategoryMapping(
                "playerok",
                "products",
                "fortnite",
                "accounts",
            ),
            SourceCategoryMapping(
                "playerok",
                "products",
                "fortnite",
                "v-bucks",
                integration_id=integration_id,
            ),
        ),
    )

    generic = classifier.classify("playerok", "products")
    scoped = classifier.classify(
        "playerok",
        "products",
        integration_id=integration_id,
    )

    assert generic is not None
    assert generic.section.code == "accounts"
    assert scoped is not None
    assert scoped.section.code == "v-bucks"


def test_catalog_source_rule_normalizes_evidence_and_builds_scoped_mapping() -> None:
    created_at = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
    rule = CatalogSourceRule(
        id=UUID(int=1),
        tenant_id=UUID(int=2),
        integration_id=UUID(int=3),
        marketplace=" Playerok ",
        source_category_id=" fortnite-vbucks ",
        source_category_name="  Fortnite   V-Bucks ",
        hub_code="FORTNITE",
        section_code="V-BUCKS",
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=1),
    )

    assert rule.marketplace == "playerok"
    assert rule.source_category_id == "fortnite-vbucks"
    assert rule.source_category_name == "Fortnite V-Bucks"
    assert rule.hub_code == "fortnite"
    assert rule.section_code == "v-bucks"
    assert rule.mapping().integration_id == rule.integration_id


def test_catalog_source_rule_rejects_invalid_lifecycle_state() -> None:
    now = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)

    def source_rule(*, updated_at: datetime, version: int = 1) -> CatalogSourceRule:
        return CatalogSourceRule(
            id=UUID(int=1),
            tenant_id=UUID(int=2),
            integration_id=UUID(int=3),
            marketplace="playerok",
            source_category_id="fortnite-vbucks",
            hub_code="fortnite",
            section_code="v-bucks",
            created_at=now,
            updated_at=updated_at,
            version=version,
        )

    with pytest.raises(ValueError, match="must not predate"):
        source_rule(updated_at=now - timedelta(seconds=1))

    with pytest.raises(ValueError, match="version must be positive"):
        source_rule(updated_at=now, version=0)


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
