from __future__ import annotations

from app.catalog.taxonomy import MVP_CATALOG_HUBS


def test_mvp_taxonomy_exposes_three_subscription_service_hubs() -> None:
    hubs = {hub.code: hub for hub in MVP_CATALOG_HUBS}

    assert tuple(hubs)[:3] == ("exitlag", "duolingo", "spotify")
    assert hubs["exitlag"].name == "ExitLag"
    assert hubs["duolingo"].name == "Duolingo"
    assert hubs["spotify"].name == "Spotify"
    for code in ("exitlag", "duolingo", "spotify"):
        assert len(hubs[code].sections) == 1
        assert hubs[code].sections[0].code == "subscriptions"
        assert hubs[code].sections[0].offer_type == "subscriptions"


def test_existing_minecraft_hub_remains_available_for_saved_rules() -> None:
    hubs = {hub.code: hub for hub in MVP_CATALOG_HUBS}

    assert "minecraft" in hubs
