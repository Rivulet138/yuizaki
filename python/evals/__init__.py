"""Opt-in local product metrics support."""

from .product_metrics import JsonlProductEventStore, compute_product_metrics, normalize_product_event

__all__ = [
    "compute_product_metrics",
    "JsonlProductEventStore",
    "normalize_product_event",
]
