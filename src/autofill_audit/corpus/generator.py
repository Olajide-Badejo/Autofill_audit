"""Seeded composition of forms across family, locale, tier, and variant.

Filled at P1 (spec section 8.1). Per-form seeding uses a stable digest, never
Python's built-in ``hash()``, which is randomised per process for strings.
"""
