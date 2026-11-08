"""Opt-in local product metrics support."""

from .product_metrics import (
    JsonlProductEventStore,
    compute_product_metrics,
    normalize_product_event,
)

__all__ = [
    "JsonlProductEventStore",
    "compute_product_metrics",
    "normalize_product_event",
]
