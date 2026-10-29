from __future__ import annotations

from dataclasses import dataclass

from app.parsers.models import ParsedOffer
from app.parsers.source_snapshot import SourceSnapshotEvidence


@dataclass(slots=True, frozen=True)
class MarketplaceIngestionResult:
    """Return normalized offers with per-run source completeness evidence."""

    offers: tuple[ParsedOffer, ...]
    evidence: SourceSnapshotEvidence

    def __post_init__(self) -> None:
        """Reject evidence that cannot safely describe these offers."""
        if len(self.offers) != self.evidence.parsed_items:
            raise ValueError("Normalized offer count does not match source evidence.")
        if not self.evidence.complete:
            return

        identities = tuple(offer.external_id for offer in self.offers)
        if any(identity is None for identity in identities):
            raise ValueError(
                "A complete source snapshot requires stable offer identities."
            )
        if len(set(identities)) != len(identities):
            raise ValueError(
                "A complete source snapshot requires unique offer identities."
            )
