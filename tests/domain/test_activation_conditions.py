from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.activation_conditions import (
    AccountRequirement,
    ActivationConditions,
    DeliveryMethod,
)


def conditions() -> ActivationConditions:
    """Explicit synthetic terms, not verified marketplace data."""
    return ActivationConditions(
        regions=("RU",),
        excluded_regions=(),
        device="pc",
        plan="individual",
        period="P1M",
        delivery_method=DeliveryMethod.KEY,
        account_requirement=AccountRequirement.ANY,
        vpn_required=False,
        activation_window_seconds=None,
    )


def test_explicit_conditions_roundtrip_and_normalize_country_order() -> None:
    original = replace(conditions(), regions=(" kz ", "ru", "KZ"), device=" PC ")
    assert original.regions == ("KZ", "RU")
    assert original.device == "pc"
    assert ActivationConditions.from_record(original.to_record()) == original
    assert ActivationConditions.from_record(None) is None


def test_worldwide_and_exclusions_are_distinct_from_unknown() -> None:
    worldwide = replace(conditions(), regions=("*",))
    except_ru = replace(worldwide, excluded_regions=("ru",))
    assert worldwide != except_ru
    assert worldwide != conditions()


@pytest.mark.parametrize("regions", [(), ("Russia",), ("*", "RU")])
def test_invalid_region_scopes_are_not_guessed(regions: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        replace(conditions(), regions=regions)


def test_invalid_exclusions_and_activation_windows_are_rejected() -> None:
    with pytest.raises(ValueError):
        replace(conditions(), excluded_regions=("RU",))
    with pytest.raises(ValueError):
        replace(conditions(), regions=("*",), excluded_regions=("*",))
    with pytest.raises(ValueError):
        replace(conditions(), activation_window_seconds=0)
    assert replace(conditions(), activation_window_seconds=3600) != conditions()


def test_unknown_or_partial_storage_does_not_become_worldwide() -> None:
    for invalid in ({}, {"version": 2}, {**conditions().to_record(), "extra": True}):
        with pytest.raises(ValueError):
            ActivationConditions.from_record(invalid)


@pytest.mark.parametrize("field", ["vpn_required", "activation_window_seconds"])
def test_ambiguous_json_scalar_types_are_rejected(field: str) -> None:
    record = conditions().to_record()
    record[field] = "unknown"
    with pytest.raises(ValueError):
        ActivationConditions.from_record(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("device", "unknown"),
        ("plan", "unknown"),
        ("plan", "other"),
        ("regions", ("ZZ",)),
    ],
)
def test_unknown_placeholders_cannot_be_confirmed(field: str, value: object) -> None:
    record = conditions().to_record()
    record[field] = list(value) if isinstance(value, tuple) else value
    with pytest.raises(ValueError):
        ActivationConditions.from_record(record)
