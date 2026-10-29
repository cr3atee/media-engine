from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class SourceSnapshotEvidence:
    """Describe whether one source response is safe for reconciliation."""

    source_items: int
    parsed_items: int
    complete: bool
    reason: str
    expected_items: int | None = None

    def __post_init__(self) -> None:
        """Reject internally inconsistent completeness evidence."""
        if self.source_items < 0 or self.parsed_items < 0:
            raise ValueError("Source snapshot item counts cannot be negative.")
        if self.expected_items is not None and self.expected_items < 0:
            raise ValueError("Expected source item count cannot be negative.")
        if not self.reason.strip():
            raise ValueError("Source snapshot evidence requires a reason.")
        if self.complete and self.source_items != self.parsed_items:
            raise ValueError(
                "A complete source snapshot requires full parser coverage."
            )
        if (
            self.complete
            and self.expected_items is not None
            and self.expected_items != self.parsed_items
        ):
            raise ValueError(
                "A complete source snapshot must match its declared total."
            )


@dataclass(slots=True, frozen=True)
class SourceExtraction[T]:
    """Pair extracted source items with reconciliation safety evidence."""

    items: tuple[T, ...]
    evidence: SourceSnapshotEvidence

    def __post_init__(self) -> None:
        """Keep the evidence parser count aligned with returned items."""
        if len(self.items) != self.evidence.parsed_items:
            raise ValueError(
                "Source extraction item count does not match its evidence."
            )
