from __future__ import annotations

from enum import Enum


class Marketplace(str, Enum):
    """Supported marketplace identifiers."""

    GGSEL = "ggsel"
    PLAYEROK = "playerok"
    FUNPAY = "funpay"
