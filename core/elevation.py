"""Administrator detection and the UAC elevation flow.

When the app runs as a frozen .exe the embedded manifest already requests
``requireAdministrator``, so the OS elevates the process before any of our
code runs. The relaunch path below only matters for ``python main.py``.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from functools import lru_cache

from core import system


@lru_cache(maxsize=1)
def is_admin() -> bool:
    try:
        if system.is_windows():
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return hasattr(os, "geteuid") and os.geteuid() == 0
    except Exception:
        return False


def requires_elevation() -> bool:
    """True when this process still needs to be restarted with admin rights."""
    return not is_admin()


def _argv_for_relaunch() -> str:
    return subprocess.list2cmdline(sys.argv)


def relaunch_as_admin() -> bool:
    """Restart the current process elevated. Returns False when unsupported."""
    exe = sys.executable
    if system.is_frozen():
        target, arguments = exe, ""
    else:
        if not exe:
            return False
        target, arguments = exe, _argv_for_relaunch()

    try:
        if system.is_windows():
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, arguments, None, 1)
            return int(result) > 32
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.execv(exe, [exe, *sys.argv[1:]])
            return True
    except Exception:
        return False
    return False


def ensure_admin_or_exit() -> None:
    """Guarantee admin rights or relaunch elevated, then terminate this process."""
    if is_admin():
        return
    if not relaunch_as_admin():
        sys.stderr.write(
            "Yönetici yetkisi alınamadı. Uygulamayı yönetici olarak çalıştırmak için "
            "sağ tık -> Yönetici olarak çalıştır seçeneğini kullanın.\n"
        )
        raise SystemExit(1)
    raise SystemExit(0)
