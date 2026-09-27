"""Shared test helpers.

``requires_network`` marks the handful of tests that touch the real network.
They are skipped by default so the suite is fast and deterministic, and are
enabled with ``APEX_DNS_NETWORK_TESTS=1`` (CI runs a dedicated job for them).
"""

from __future__ import annotations

import os
import unittest

NETWORK_TESTS = os.environ.get("APEX_DNS_NETWORK_TESTS") == "1"

requires_network = unittest.skipUnless(
    NETWORK_TESTS,
    "real network test; set APEX_DNS_NETWORK_TESTS=1 to enable",
)

__all__ = ["NETWORK_TESTS", "requires_network"]
