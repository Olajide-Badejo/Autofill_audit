"""Precision, recall, F1 per label, per locale, per tier, and latency percentiles.

Filled at P5 (spec section 13.2), including the insufficient-data rule that
keeps a metric computed over too few examples from being reported as a metric.
"""
