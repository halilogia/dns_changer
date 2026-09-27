"""Core domain logic for Apex DNS Changer.

Free of any GUI imports so it can be exercised head-less in CI.
"""

from __future__ import annotations

__all__ = [
    "dns_service",
    "elevation",
    "providers",
    "resolver",
    "system",
]

__version__ = "2.0.0"
