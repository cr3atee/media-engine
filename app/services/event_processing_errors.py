class PermanentEventProcessingError(ValueError):
    """Raised when a durable event cannot be scored without data correction."""
