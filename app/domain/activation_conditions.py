from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class DeliveryMethod(StrEnum):
    """Distinct ways to obtain a subscription, not interchangeable products."""

    KEY = "key"
    OWN_ACCOUNT = "own_account"
    NEW_ACCOUNT = "new_account"


class AccountRequirement(StrEnum):
    """Account history permitted by the source's activation terms."""

    NEW_ONLY = "new_only"
    EXISTING_ONLY = "existing_only"
    ANY = "any"


@dataclass(slots=True, frozen=True, kw_only=True)
class ActivationConditions:
    """Explicit complete conditions; an absent object means unknown conditions.

    Countries are source-confirmed two-letter codes, or an explicit ``*`` scope
    with exclusions. A None activation window explicitly means no deadline;
    missing evidence must remain None on ParsedOffer, not create this object.
    Plan and period must be explicit too; title matching does not prove them.
    """

    regions: tuple[str, ...]
    excluded_regions: tuple[str, ...]
    device: str
    plan: str
    period: str
    delivery_method: DeliveryMethod
    account_requirement: AccountRequirement
    vpn_required: bool
    activation_window_seconds: int | None

    def __post_init__(self) -> None:
        regions = tuple(sorted(set(code.strip().upper() for code in self.regions)))
        excluded = tuple(
            sorted(set(code.strip().upper() for code in self.excluded_regions))
        )
        if not regions or any(
            re.fullmatch(r"[A-Z]{2}", code) is None
            for code in regions + excluded
            if code != "*"
        ):
            raise ValueError(
                "Explicit country codes or a worldwide scope are required."
            )
        if {"XX", "ZZ"}.intersection(regions + excluded):
            raise ValueError(
                "Unknown region placeholders are not activation countries."
            )
        if ("*" in regions and regions != ("*",)) or "*" in excluded:
            raise ValueError("Worldwide scope cannot be mixed with country codes.")
        if excluded and regions != ("*",):
            raise ValueError("Exclusions require an explicit worldwide scope.")
        device = self.device.strip().lower()
        unknown_codes = {"unknown", "unconfirmed", "unspecified", "other"}
        if device in unknown_codes or self.plan.strip().lower() in unknown_codes | {
            "any"
        }:
            raise ValueError("Unknown placeholders cannot form comparable conditions.")
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", device) is None:
            raise ValueError("An explicit normalized device code is required.")
        plan = self.plan.strip().lower()
        period = self.period.strip().upper()
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", plan) is None:
            raise ValueError("An explicit plan code is required.")
        if re.fullmatch(r"P[1-9][0-9]{0,4}[DWMY]|PERPETUAL", period) is None:
            raise ValueError(
                "An explicit period is required; do not infer equivalence."
            )
        if not isinstance(self.delivery_method, DeliveryMethod) or not isinstance(
            self.account_requirement, AccountRequirement
        ):
            raise ValueError("Explicit delivery and account requirements are required.")
        if type(self.vpn_required) is not bool:
            raise ValueError("VPN requirements must be explicitly known.")
        window = self.activation_window_seconds
        if window is not None and (type(window) is not int or window <= 0):
            raise ValueError(
                "Activation window must be positive or explicitly unlimited."
            )
        object.__setattr__(self, "regions", regions)
        object.__setattr__(self, "excluded_regions", excluded)
        object.__setattr__(self, "device", device)
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "period", period)

    def to_record(self) -> dict[str, object]:
        """Serialize an explicit, versioned value without guessing missing fields."""
        return {
            "version": 1,
            "regions": list(self.regions),
            "excluded_regions": list(self.excluded_regions),
            "device": self.device,
            "plan": self.plan,
            "period": self.period,
            "delivery_method": self.delivery_method.value,
            "account_requirement": self.account_requirement.value,
            "vpn_required": self.vpn_required,
            "activation_window_seconds": self.activation_window_seconds,
        }

    @classmethod
    def from_record(
        cls, record: Mapping[str, object] | None
    ) -> ActivationConditions | None:
        """Read persisted conditions strictly; unknown versions cannot fail open."""
        if record is None:
            return None
        required = {
            "version",
            "regions",
            "excluded_regions",
            "device",
            "plan",
            "period",
            "delivery_method",
            "account_requirement",
            "vpn_required",
            "activation_window_seconds",
        }
        if (
            set(record) != required
            or type(record["version"]) is not int
            or record["version"] != 1
        ):
            raise ValueError("Unsupported or incomplete activation conditions record.")
        vpn = record["vpn_required"]
        window = record["activation_window_seconds"]
        if type(vpn) is not bool or (window is not None and type(window) is not int):
            raise ValueError("Invalid activation condition value types.")
        return cls(
            regions=_codes(record["regions"]),
            excluded_regions=_codes(record["excluded_regions"]),
            device=_text(record["device"]),
            plan=_text(record["plan"]),
            period=_text(record["period"]),
            delivery_method=DeliveryMethod(_text(record["delivery_method"])),
            account_requirement=AccountRequirement(
                _text(record["account_requirement"])
            ),
            vpn_required=vpn,
            activation_window_seconds=window,
        )


def _codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(code, str) for code in value):
        raise ValueError("Region codes must be an explicit list of strings.")
    return tuple(_text(code) for code in value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Activation condition must be a string.")
    return value
