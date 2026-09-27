"""Adapter discovery and DNS read/write, with one backend per platform.

Public surface is the :class:`DnsService` facade. Platform specifics live in
:class:`DnsBackend` implementations so that the package imports cleanly on
every OS and the read paths are unit-testable without touching the machine.
"""

from __future__ import annotations

import abc
import ipaddress
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from functools import lru_cache

from core import system
from core.providers import ALL_ADAPTERS_ID

_UP_STATE = {
    "up",
    "connected",
    "connected (externally)",
    "connected (full)",
    "bağlı",
    "bagli",
    "etkin",
    "aktif",
}


class DnsServiceError(RuntimeError):
    """Base class for recoverable DNS service failures."""


class UnsupportedPlatformError(DnsServiceError):
    """Raised when the host OS has no writable DNS backend."""


class InvalidAddressError(DnsServiceError, ValueError):
    """Raised when a caller supplies a malformed or unusable DNS server."""


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    name: str
    status: str = "up"
    mac: str = ""
    description: str = ""
    is_virtual: bool = False
    dhcp_enabled: bool = False
    ipv4: tuple[str, ...] = ()
    ipv6: tuple[str, ...] = ()

    @property
    def is_connected(self) -> bool:
        return self.status.strip().lower() in _UP_STATE


@dataclass(frozen=True, slots=True)
class ApplyResult:
    ok: bool
    backend: str
    adapters: tuple[str, ...] = ()
    servers: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default=())


def is_valid_ip(value: str) -> bool:
    """Strict IPv4/IPv6 validation.

    ``socket.inet_aton`` accepts sloppy forms such as ``1.2.3`` or ``0x7f.1``
    that Windows then rejects, so use :mod:`ipaddress` instead.
    """
    if not value or not isinstance(value, str):
        return False
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def normalize_servers(servers: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Validate and de-duplicate a list of DNS servers, preserving order."""
    cleaned: list[str] = []
    for server in servers:
        candidate = (server or "").strip()
        if not candidate:
            continue
        if not is_valid_ip(candidate):
            raise InvalidAddressError(f"Geçersiz DNS adresi: {server!r}")
        if candidate not in cleaned:
            cleaned.append(candidate)
    if not cleaned:
        raise InvalidAddressError("En az bir DNS adresi gerekiyor")
    return tuple(cleaned)


def split_by_family(servers: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    v4: list[str] = []
    v6: list[str] = []
    for server in servers:
        (v6 if ipaddress.ip_address(server).version == 6 else v4).append(server)
    return tuple(v4), tuple(v6)


def _ps_json(script: str, timeout: float = 20.0) -> object:
    completed = system.run_powershell(script, timeout=timeout)
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        raise DnsServiceError((completed.stderr or output or "PowerShell hatası").strip())
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise DnsServiceError(f"PowerShell çıktısı çözümlenemedi: {exc}") from exc


def _as_list(data: object) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


class DnsBackend(abc.ABC):
    """Adapter enumeration plus DNS read/write for one platform family."""

    name: str = "generic"
    can_write: bool = False

    @abc.abstractmethod
    def list_adapters(self) -> list[AdapterInfo]: ...

    @abc.abstractmethod
    def get_dns_servers(self, adapter: str) -> list[str]: ...

    def set_dns_servers(self, adapter: str, servers: tuple[str, ...]) -> None:
        raise UnsupportedPlatformError(f"{system.current_platform()} üzerinde DNS yazma desteklenmiyor")

    def reset_dns_servers(self, adapter: str) -> None:
        raise UnsupportedPlatformError(f"{system.current_platform()} üzerinde DNS sıfırlama desteklenmiyor")


class WindowsDnsBackend(DnsBackend):
    """Windows backend driven by the NetTCPIP PowerShell module."""

    name = "windows-powershell"
    can_write = True

    def _list_adapters_netsh(self) -> list[AdapterInfo]:
        """Fallback for hosts where the NetTCPIP module is unavailable."""
        try:
            completed = system.run_hidden(
                ["netsh", "interface", "show", "interface"],
                timeout=15,
            )
        except Exception:
            return []
        if completed.returncode != 0:
            return []
        adapters: list[AdapterInfo] = []
        for line in (completed.stdout or "").splitlines():
            lowered = line.lower()
            if not ("connected" in lowered or "bağlandı" in lowered):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            name = " ".join(parts[3:]).strip()
            if name and not any(a.name == name for a in adapters):
                adapters.append(AdapterInfo(name=name, status="Connected"))
        return adapters

    def _address_state(self, adapter: str) -> tuple[list[str], list[str], bool]:
        alias = system.quote_powershell_literal(adapter)
        script = (
            f"$v4 = @(Get-DnsClientServerAddress -InterfaceAlias {alias} -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty ServerAddresses); "
            f"$v6 = @(Get-DnsClientServerAddress -InterfaceAlias {alias} -AddressFamily IPv6 "
            "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty ServerAddresses); "
            f"$dhcp = (Get-NetIPInterface -InterfaceAlias {alias} -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue).Dhcp; "
            "@{v4=$v4;v6=$v6;dhcp=($dhcp -eq 'Enabled')} | ConvertTo-Json -Compress"
        )
        data = _as_list(_ps_json(script))
        if not data:
            return [], [], True
        entry = data[0]
        v4 = [str(x) for x in (entry.get("v4") or []) if str(x).strip()]
        v6 = [str(x) for x in (entry.get("v6") or []) if str(x).strip()]
        dhcp = bool(entry.get("dhcp"))
        return v4, v6, dhcp

    def list_adapters(self) -> list[AdapterInfo]:
        raw = self._list_adapters_raw()
        enriched: list[AdapterInfo] = []
        for adapter in raw:
            try:
                v4, v6, dhcp = self._address_state(adapter.name)
            except DnsServiceError:
                v4, v6, dhcp = (), (), True
            enriched.append(
                AdapterInfo(
                    name=adapter.name,
                    status=adapter.status,
                    mac=adapter.mac,
                    description=adapter.description,
                    is_virtual=adapter.is_virtual,
                    dhcp_enabled=dhcp,
                    ipv4=tuple(v4),
                    ipv6=tuple(v6),
                )
            )
        return enriched

    def _list_adapters_raw(self) -> list[AdapterInfo]:
        script = (
            "Get-NetAdapter -ErrorAction SilentlyContinue | "
            "Select-Object Name,Status,MacAddress,InterfaceDescription,Virtual | "
            "ConvertTo-Json -Compress -Depth 3"
        )
        adapters: list[AdapterInfo] = []
        for item in _as_list(_ps_json(script)):
            name = str(item.get("Name") or "").strip()
            if not name:
                continue
            adapters.append(
                AdapterInfo(
                    name=name,
                    status=str(item.get("Status") or ""),
                    mac=str(item.get("MacAddress") or ""),
                    description=str(item.get("InterfaceDescription") or ""),
                    is_virtual=bool(item.get("Virtual")),
                )
            )
        return adapters or self._list_adapters_netsh()

    def get_dns_servers(self, adapter: str) -> list[str]:
        v4, v6, _dhcp = self._address_state(adapter)
        return v4 or v6

    def set_dns_servers(self, adapter: str, servers: tuple[str, ...]) -> None:
        alias = system.quote_powershell_literal(adapter)
        v4, v6 = split_by_family(servers)
        scripts: list[str] = []
        if v4:
            literals = ",".join(system.quote_powershell_literal(ip) for ip in v4)
            scripts.append(
                f"Set-DnsClientServerAddress -InterfaceAlias {alias} -ServerAddresses @({literals}) -ErrorAction Stop"
            )
        if v6:
            literals = ",".join(system.quote_powershell_literal(ip) for ip in v6)
            scripts.append(
                f"Set-DnsClientServerAddress -InterfaceAlias {alias} -ServerAddresses @({literals}) "
                f"-AddressFamily IPv6 -ErrorAction Stop"
            )
        if not scripts:
            raise InvalidAddressError("Uygulanabilir DNS adresi yok")
        self._run_set(adapter, "; ".join(scripts))

    def reset_dns_servers(self, adapter: str) -> None:
        alias = system.quote_powershell_literal(adapter)
        self._run_set(
            adapter,
            f"Set-DnsClientServerAddress -InterfaceAlias {alias} -ResetServerAddresses -ErrorAction Stop",
        )

    def _run_set(self, adapter: str, script: str) -> None:
        completed = system.run_powershell(script, timeout=30)
        if completed.returncode != 0:
            raise DnsServiceError((completed.stderr or completed.stdout or "Bilinmeyen hata").strip())


class NetworkManagerDnsBackend(DnsBackend):
    """Linux backend driving NetworkManager through nmcli."""

    name = "networkmanager"
    can_write = True

    def list_adapters(self) -> list[AdapterInfo]:
        completed = system.run_hidden(
            ["nmcli", "-t", "-f", "DEVICE,STATE,TYPE,CONNECTION", "device", "status"],
            timeout=15,
        )
        if completed.returncode != 0:
            raise DnsServiceError((completed.stderr or "nmcli çalıştırılamadı").strip())
        adapters: list[AdapterInfo] = []
        for line in (completed.stdout or "").splitlines():
            fields = line.split(":")
            if len(fields) < 2:
                continue
            name, state = fields[0], fields[1]
            if not name:
                continue
            kind = fields[2] if len(fields) > 2 else ""
            connection = fields[3] if len(fields) > 3 else ""
            adapters.append(
                AdapterInfo(
                    name=name,
                    status=state,
                    description=connection,
                    is_virtual=kind not in ("ethernet", "wifi", "802-3-ethernet", "802-11-wireless"),
                )
            )
        return adapters

    def get_dns_servers(self, adapter: str) -> list[str]:
        completed = system.run_hidden(
            ["nmcli", "-t", "-f", "IP4.DNS,IP6.DNS", "device", "show", adapter],
            timeout=15,
        )
        if completed.returncode != 0:
            raise DnsServiceError((completed.stderr or "nmcli çalıştırılamadı").strip())
        servers: list[str] = []
        for line in (completed.stdout or "").splitlines():
            for token in re.split(r"[,;\s]+", line.strip()):
                token = token.strip()
                if is_valid_ip(token) and token not in servers:
                    servers.append(token)
        return servers

    def _connection_for(self, adapter: str) -> str:
        completed = system.run_hidden(
            ["nmcli", "-t", "-f", "GENERAL.CONNECTION", "device", "show", adapter],
            timeout=15,
        )
        if completed.returncode != 0:
            raise DnsServiceError(f"{adapter}: bağlantı profili bulunamadı")
        return (completed.stdout or "").strip()

    def set_dns_servers(self, adapter: str, servers: tuple[str, ...]) -> None:
        connection = self._connection_for(adapter)
        v4, v6 = split_by_family(servers)
        command = ["nmcli", "connection", "modify", connection, "ipv4.ignore-auto-dns", "yes"]
        command += ["ipv4.dns", ",".join(v4)] if v4 else ["ipv4.dns", ""]
        if v6:
            command += ["ipv6.ignore-auto-dns", "yes", "ipv6.dns", ",".join(v6)]
        completed = system.run_hidden(command, timeout=25)
        if completed.returncode != 0:
            raise DnsServiceError((completed.stderr or completed.stdout or "nmcli hatası").strip())
        self._reapply(adapter)

    def reset_dns_servers(self, adapter: str) -> None:
        connection = self._connection_for(adapter)
        completed = system.run_hidden(
            [
                "nmcli",
                "connection",
                "modify",
                connection,
                "ipv4.dns",
                "",
                "ipv4.ignore-auto-dns",
                "no",
                "ipv6.dns",
                "",
                "ipv6.ignore-auto-dns",
                "no",
            ],
            timeout=25,
        )
        if completed.returncode != 0:
            raise DnsServiceError((completed.stderr or completed.stdout or "nmcli hatası").strip())
        self._reapply(adapter)

    def _reapply(self, adapter: str) -> None:
        completed = system.run_hidden(["nmcli", "device", "reapply", adapter], timeout=25)
        if completed.returncode != 0:
            raise DnsServiceError((completed.stderr or "nmcli device reapply başarısız").strip())


class ReadOnlyDnsBackend(DnsBackend):
    """Best-effort reader for platforms without a supported writer (macOS, BSD).

    Resolver configuration on those systems is a system-wide network
    preference, so this backend reports what ``/etc/resolv.conf`` currently
    provides and refuses to mutate it.
    """

    name = "resolv-conf"
    can_write = False

    @staticmethod
    def _parse_resolv_conf(content: str) -> list[str]:
        servers: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("nameserver"):
                continue
            parts = stripped.split()
            if len(parts) > 1 and is_valid_ip(parts[1]) and parts[1] not in servers:
                servers.append(parts[1])
        return servers

    def list_adapters(self) -> list[AdapterInfo]:
        if not system.is_windows():
            return [AdapterInfo(name="varsayılan", status="up", description="/etc/resolv.conf")]
        return []

    def get_dns_servers(self, adapter: str) -> list[str]:
        try:
            with open("/etc/resolv.conf", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except OSError:
            return []
        return self._parse_resolv_conf(content)


class _TtlCache:
    """Tiny time-to-live cache so repeated UI reads do not re-spawn shells."""

    __slots__ = ("_values", "_ttl", "_clock")

    def __init__(self, ttl: float, clock=time.monotonic) -> None:
        self._values: dict = {}
        self._ttl = ttl
        self._clock = clock

    def get(self, key):
        entry = self._values.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < self._clock():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key, value) -> None:
        self._values[key] = (self._clock() + self._ttl, value)

    def clear(self) -> None:
        self._values.clear()


@lru_cache(maxsize=1)
def default_backend() -> DnsBackend:
    platform = system.current_platform()
    if platform == system.WINDOWS:
        return WindowsDnsBackend()
    if platform == system.LINUX and shutil.which("nmcli"):
        return NetworkManagerDnsBackend()
    return ReadOnlyDnsBackend()


class DnsService:
    """Facade over a :class:`DnsBackend` with a short-lived read cache."""

    def __init__(self, backend: DnsBackend | None = None, cache_ttl: float = 3.0) -> None:
        self.backend = backend or default_backend()
        self._cache = _TtlCache(cache_ttl)
        self.last_error: str = ""

    @property
    def backend_name(self) -> str:
        return self.backend.name

    @property
    def can_write(self) -> bool:
        return self.backend.can_write

    def refresh(self) -> None:
        self.last_error = ""
        self._cache.clear()

    def adapters(self, refresh: bool = False, include_disconnected: bool = True) -> list[AdapterInfo]:
        if refresh:
            self._cache.clear()
        cached = self._cache.get("adapters")
        if cached is None:
            cached = self.backend.list_adapters()
            self._cache.set("adapters", cached)
        if include_disconnected:
            return list(cached)
        return [adapter for adapter in cached if adapter.is_connected]

    def active_adapter_names(self, refresh: bool = False) -> list[str]:
        names = [adapter.name for adapter in self.adapters(refresh=refresh) if adapter.is_connected]
        return names or [adapter.name for adapter in self.adapters()]

    def adapter(self, name: str, refresh: bool = False) -> AdapterInfo | None:
        for candidate in self.adapters(refresh=refresh):
            if candidate.name == name:
                return candidate
        return None

    def dns_servers(self, adapter: str, refresh: bool = False) -> list[str]:
        key = ("dns", adapter)
        if refresh:
            self._cache.clear()
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        servers = self.backend.get_dns_servers(adapter)
        self._cache.set(key, servers)
        return list(servers)

    def uses_dhcp(self, adapter: str) -> bool:
        info = self.adapter(adapter)
        if info is None:
            return False
        return info.dhcp_enabled

    def _targets(self, adapter: str) -> list[str]:
        if adapter != ALL_ADAPTERS_ID:
            return [adapter]
        return self.active_adapter_names(refresh=True)

    def apply(self, adapter: str, servers: list[str] | tuple[str, ...]) -> ApplyResult:
        if not self.can_write:
            raise UnsupportedPlatformError(
                f"{system.current_platform()} üzerinde DNS değişikliği desteklenmiyor "
                f"({self.backend.name} yalnızca okuma yapabilir)"
            )
        normalized = normalize_servers(servers)
        targets = self._targets(adapter)
        errors: list[str] = []
        applied: list[str] = []
        for target in targets:
            try:
                self.backend.set_dns_servers(target, normalized)
                applied.append(target)
            except DnsServiceError as exc:
                errors.append(f"{target}: {exc}")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"{target}: {exc}")
        self.refresh()
        self.last_error = "; ".join(errors)
        return ApplyResult(
            ok=not errors and bool(applied),
            backend=self.backend.name,
            adapters=tuple(applied),
            servers=normalized,
            errors=tuple(errors),
        )

    def reset(self, adapter: str) -> ApplyResult:
        if not self.can_write:
            raise UnsupportedPlatformError(f"{system.current_platform()} üzerinde DNS sıfırlama desteklenmiyor")
        targets = self._targets(adapter)
        errors: list[str] = []
        applied: list[str] = []
        for target in targets:
            try:
                self.backend.reset_dns_servers(target)
                applied.append(target)
            except DnsServiceError as exc:
                errors.append(f"{target}: {exc}")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"{target}: {exc}")
        self.refresh()
        self.last_error = "; ".join(errors)
        return ApplyResult(
            ok=not errors and bool(applied),
            backend=self.backend.name,
            adapters=tuple(applied),
            errors=tuple(errors),
        )
