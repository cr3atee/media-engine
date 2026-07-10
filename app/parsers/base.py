from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(slots=True, kw_only=True)
class RawItem:
    """Represents a normalized raw item produced by a parser."""

    external_id: str
    title: str
    price: Decimal | None
    currency: str | None
    seller: str | None
    url: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class BaseParser(ABC, Generic[T]):
    """Defines the abstract contract for asynchronous parsers."""

    @abstractmethod
    async def fetch(self) -> Any:
        """Fetches raw source data required for further parsing."""

    @abstractmethod
    async def parse(self, payload: Any) -> Sequence[T]:
        """Transforms fetched raw data into normalized parser items."""

    @abstractmethod
    async def run(self) -> Sequence[T]:
        """Executes the full parser flow and returns parsed items."""
