from __future__ import annotations

from datetime import UTC, datetime

from app.domain.price_snapshot import PriceSnapshot
from app.parsers.models import ParsedOffer


class SnapshotBuilder:
    """Builds price snapshots from parsed marketplace offers."""

    def build(self, offer: ParsedOffer) -> PriceSnapshot:
        """Convert a parsed offer into a database-independent price snapshot."""
        if offer.external_id is None or offer.price is None or offer.currency is None:
            msg = "ParsedOffer does not contain required PriceSnapshot fields."
            raise ValueError(msg)

        return PriceSnapshot(
            marketplace=offer.marketplace,
            external_id=offer.external_id,
            price=offer.price,
            currency=offer.currency,
            collected_at=datetime.now(UTC),
        )
