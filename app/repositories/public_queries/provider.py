from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from app.repositories.public_queries.contracts import (
    PublicCategoryQueryRepository,
    PublicComparisonQueryRepository,
    PublicOfferQueryRepository,
    PublicPriceChangeQueryRepository,
    PublicPriceHistoryQueryRepository,
    PublicProductQueryRepository,
)


@dataclass(slots=True, frozen=True)
class PublicReadRepositoryProvider:
    """Container for public consumer read repository implementations."""

    products: PublicProductQueryRepository
    offers: PublicOfferQueryRepository
    comparisons: PublicComparisonQueryRepository
    price_history: PublicPriceHistoryQueryRepository
    price_changes: PublicPriceChangeQueryRepository
    categories: PublicCategoryQueryRepository


class PublicReadRepositoryScopeFactory(Protocol):
    """Callable async-context-manager contract for one public read scope."""

    def __call__(self) -> AbstractAsyncContextManager[PublicReadRepositoryProvider]:
        """Return an async context manager yielding a public read provider."""
        ...
