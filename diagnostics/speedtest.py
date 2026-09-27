"""Console diagnostics: bandwidth, per-process usage, DoH and IPv6 health."""

from __future__ import annotations

import platform
import subprocess
import time

import psutil
import requests

DEFAULT_DOWNLOAD_BYTES = 25_000_000
DEFAULT_UPLOAD_BYTES = 10_000_000
SPEEDTEST_URL = "https://speed.cloudflare.com"


def test_speed(
    down_bytes: int = DEFAULT_DOWNLOAD_BYTES,
    up_bytes: int = DEFAULT_UPLOAD_BYTES,
    timeout: float = 20.0,
) -> tuple[float, float]:
    """Download and upload throughput in Mbit/s, per Cloudflare's test endpoint."""
    down_mbps = 0.0
    up_mbps = 0.0
    try:
        start = time.perf_counter()
        response = requests.get(f"{SPEEDTEST_URL}/__down?bytes={down_bytes}", timeout=timeout)
        duration = time.perf_counter() - start
        if duration > 0:
            down_mbps = round((len(response.content) * 8) / (duration * 1_000_000), 2)
    except requests.RequestException:
        pass

    try:
        start = time.perf_counter()
        requests.post(f"{SPEEDTEST_URL}/__up", data=b"0" * up_bytes, timeout=timeout)
        duration = time.perf_counter() - start
        if duration > 0:
            up_mbps = round((up_bytes * 8) / (duration * 1_000_000), 2)
    except requests.RequestException:
        pass

    return down_mbps, up_mbps


def get_top_network_usage(sample_seconds: int = 2, limit: int = 5) -> list[tuple[str, float]]:
    """Processes that moved the most bytes during the sampling window, in KB."""
    initial: dict[int, object] = {}
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            initial[proc.pid] = proc.io_counters()
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue

    time.sleep(sample_seconds)

    usage: list[tuple[str, float]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            before = initial.get(proc.pid)
            if before is None:
                continue
            after = proc.io_counters()
            delta = (after.write_bytes - before.write_bytes) + (after.read_bytes - before.read_bytes)
            if delta > 0:
                usage.append((proc.info["name"] or "?", round(delta / 1024, 1)))
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue

    usage.sort(key=lambda pair: pair[1], reverse=True)
    return usage[:limit]


def test_latency_and_loss(host: str = "8.8.8.8", count: int = 10) -> str:
    """Raw ping output, or the error text when the probe could not run."""
    parameter = "-n" if platform.system().lower().startswith("win") else "-c"
    command = ["ping", parameter, str(count), host]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system().lower().startswith("win") else 0
    try:
        return subprocess.check_output(command, stderr=subprocess.STDOUT, text=True, creationflags=flags)
    except subprocess.CalledProcessError as exc:
        return exc.output or str(exc)
    except OSError as exc:
        return str(exc)
