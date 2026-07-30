"""Channel-independent outbound delivery contracts."""

from app.delivery.contracts import (
    DeliveryErrorCategory,
    DeliveryMessage,
    DeliveryOutcome,
    DeliveryResult,
    PublicationDeliveryAdapter,
)

__all__ = [
    "DeliveryErrorCategory",
    "DeliveryMessage",
    "DeliveryOutcome",
    "DeliveryResult",
    "PublicationDeliveryAdapter",
]
