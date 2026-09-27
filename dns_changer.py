"""Backward-compatible launcher.

The application moved to the ``core`` / ``ui`` / ``diagnostics`` packages and
``main.py``; this shim keeps the old ``python dns_changer.py`` invocation and
the existing Desktop shortcut working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
