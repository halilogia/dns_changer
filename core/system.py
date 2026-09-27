"""Platform plumbing shared by every layer.

Nothing in this module may import a Windows-only symbol at import time, so the
package stays importable (and testable) on Linux and macOS as well.
"""

from __future__ import annotations

import base64
import platform
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"
BSD = "bsd"
UNKNOWN = "unknown"

_RTT_PATTERNS = (
    re.compile(r"(?:time|süre|tiempo|temps|zeit)\s*[=<]\s*([\d.,]+)", re.IGNORECASE),
    # POSIX summary line: "min/avg/max/mdev = 10.1/15.2/20.3/1.2 ms"
    re.compile(r"min/avg/max[^=\n]*=\s*[\d.]+/([\d.,]+)", re.IGNORECASE),
    re.compile(r"(?:average|avg|ortalama|media|moyenne|mittelwert)\s*[=<]\s*([\d.,]+)", re.IGNORECASE),
)

_LOSS_WORDS = r"loss|verlust|perte|p[eé]rdid[oa]|kay[ıi]p|kayb[ıi]|perdita|perdido"
_LOSS_PERCENT = re.compile(
    r"(\d+)\s*%\s*(?:packet\s+|veri\s+|paket\s+|datos\s+)?(?:data\s+)?(?:" + _LOSS_WORDS + r")",
    re.IGNORECASE,
)
_LOSS_PERCENT_PREFIX = re.compile(r"%\s*(\d+)\s*(?:paket\s+|veri\s+)?(?:" + _LOSS_WORDS + r")", re.IGNORECASE)
_LOSS_PERCENT_WORD = re.compile(r"(\d+)\s*(?:percent|yuzde|yüzde)\b", re.IGNORECASE)
_LOSS_COUNT = re.compile(r"(?:Lost|Kay[ıi]p|kayb[ıi]|Verlust|Perd[ei]d[oa]?|Perdido)\s*[=:]?\s*(\d+)", re.IGNORECASE)


@lru_cache(maxsize=1)
def current_platform() -> str:
    system = platform.system().lower()
    if system.startswith("win"):
        return WINDOWS
    if system == "darwin":
        return MACOS
    if system == "linux":
        return LINUX
    if "bsd" in system:
        return BSD
    return UNKNOWN


def is_windows() -> bool:
    return current_platform() == WINDOWS


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def resource_path(*parts: str) -> Path:
    """Absolute path of a bundled resource (onefile mode extracts to _MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def app_dir() -> Path:
    """Directory the executable or the source tree lives in."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def powershell_executable() -> str:
    if is_windows():
        for candidate in ("pwsh", "powershell"):
            if shutil.which(candidate):
                return candidate
        return "powershell"
    for candidate in ("pwsh", "powershell"):
        if shutil.which(candidate):
            return candidate
    return ""


def powershell_available() -> bool:
    return bool(powershell_executable())


def run_hidden(
    command: list[str],
    *,
    timeout: float | None = None,
    check: bool = False,
    stdin: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a console command without flashing a window on Windows."""
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if is_windows():
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    if stdin is not None:
        kwargs["input"] = stdin
    return subprocess.run(command, timeout=timeout, check=check, **kwargs)


def run_powershell(script: str, *, timeout: float = 20.0) -> subprocess.CompletedProcess:
    """Execute a PowerShell script through -EncodedCommand.

    Encoding the script as UTF-16LE base64 sidesteps quoting, escaping and
    code-page problems that ``-Command`` runs into with non-ASCII adapter
    names on Turkish Windows installs.
    """
    exe = powershell_executable()
    if not exe:
        raise FileNotFoundError("No PowerShell interpreter found on PATH")
    preamble = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    payload = base64.b64encode((preamble + script).encode("utf-16-le")).decode("ascii")
    return run_hidden(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", payload],
        timeout=timeout,
    )


def quote_powershell_literal(value: str) -> str:
    """Quote a value as a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def ping_command(host: str, count: int = 1, timeout_ms: int = 1200) -> list[str]:
    """Platform-appropriate ping invocation."""
    if is_windows():
        return ["ping", "-n", str(count), "-w", str(int(timeout_ms)), host]
    if current_platform() == MACOS:
        return ["ping", "-c", str(count), "-W", str(int(timeout_ms)), host]
    return ["ping", "-c", str(count), "-W", str(max(1, int(timeout_ms / 1000))), host]


def parse_ping_rtt(output: str) -> float | None:
    """Extract a round-trip time in ms from localized ping output."""
    if not output:
        return None
    for pattern in _RTT_PATTERNS:
        match = pattern.search(output)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                return None
    return None


def parse_ping_loss(output: str) -> int | None:
    """Extract the packet loss percentage from localized ping output.

    Falls back to the ``Lost = N`` counter when no percentage is present.
    """
    if not output:
        return None
    for pattern in (_LOSS_PERCENT, _LOSS_PERCENT_PREFIX, _LOSS_PERCENT_WORD):
        match = pattern.search(output)
        if match:
            return int(match.group(1))
    match = _LOSS_COUNT.search(output)
    if match:
        return int(match.group(1))
    return None
