from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import SecretStr


class PlayerokCredentialError(ValueError):
    """Safe validation failure for Playerok session credential material."""


@dataclass(slots=True, frozen=True)
class PlayerokSessionCredentials:
    """Browser-bound Playerok session values kept out of repr and persistence."""

    user_agent: str
    _cookies: tuple[tuple[str, SecretStr], ...] = field(repr=False)

    _COOKIE_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")

    @classmethod
    def from_secret(cls, secret: SecretStr) -> PlayerokSessionCredentials:
        """Parse a JSON deployment secret into validated session credentials."""
        try:
            payload = json.loads(secret.get_secret_value())
        except json.JSONDecodeError as exc:
            raise PlayerokCredentialError(
                "Playerok credential secret must contain valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise PlayerokCredentialError(
                "Playerok credential secret must contain a JSON object."
            )

        user_agent = payload.get("user_agent")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise PlayerokCredentialError(
                "Playerok credential secret requires a browser user agent."
            )
        normalized_user_agent = user_agent.strip()
        if len(normalized_user_agent) > 512 or _contains_control_characters(
            normalized_user_agent
        ):
            raise PlayerokCredentialError("Playerok credential user agent is invalid.")

        raw_cookies = payload.get("cookies")
        if not isinstance(raw_cookies, dict) or not raw_cookies:
            raise PlayerokCredentialError(
                "Playerok credential secret requires browser cookies."
            )

        cookies: list[tuple[str, SecretStr]] = []
        has_token = False
        for name, value in raw_cookies.items():
            if not isinstance(name, str) or cls._COOKIE_NAME.fullmatch(name) is None:
                raise PlayerokCredentialError(
                    "Playerok credential contains an invalid cookie name."
                )
            if not isinstance(value, str) or not value:
                raise PlayerokCredentialError(
                    "Playerok credential contains an invalid cookie value."
                )
            if ";" in value or _contains_control_characters(value):
                raise PlayerokCredentialError(
                    "Playerok credential contains an unsafe cookie value."
                )
            has_token = has_token or name == "token"
            cookies.append((name, SecretStr(value)))

        if not has_token:
            raise PlayerokCredentialError(
                "Playerok credential secret requires the token cookie."
            )

        return cls(
            user_agent=normalized_user_agent,
            _cookies=tuple(cookies),
        )

    def cookie_header(self) -> str:
        """Return the Cookie header only at the transport boundary."""
        return "; ".join(
            f"{name}={value.get_secret_value()}" for name, value in self._cookies
        )


def _contains_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)
