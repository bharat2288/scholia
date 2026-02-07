"""
Rem Models (DEPRECATED)
======================
This module is deprecated. Use models/gluon.py instead.

These are backward compatibility re-exports.
"""

# Re-export everything from gluon with Rem names
from .gluon import (
    GluonType as RemType,
    GluonBase as RemBase,
    GluonCreate as RemCreate,
    GluonUpdate as RemUpdate,
    Gluon as Rem,
    GluonWithLinks as RemWithLinks,
    Link,
    LinkCreate,
)

__all__ = [
    "RemType",
    "RemBase",
    "RemCreate",
    "RemUpdate",
    "Rem",
    "RemWithLinks",
    "Link",
    "LinkCreate",
]
