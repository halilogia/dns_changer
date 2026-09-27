"""Name resolution probes: plain DNS over UDP, DNS-over-HTTPS and IPv6 health.

The module intentionally depends on the standard library only so that ``core``
stays importable everywhere and the DoH checks do not drag in a HTTP client.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import random
import socket
import ssl
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

from core import system
from core.providers import DnsProvider

DEFAULT_QUERY_NAME = "example.com"
QUERY_PORT = 53

TYPE_A = 1
TYPE_AAAA = 28
CLASS_IN = 1

RCODE_NAMES = {
    0: "NOERROR",
    1: "FORMERR",
    2: "SERVFAIL",
    3: "NXDOMAIN",
    4: "NOTIMP",
    5: "REFUSED",
}

_DOH_RETRY_STATUS = frozenset({400, 404, 405, 415, 500, 501, 505})


@dataclass(frozen=True, slots=True)
class DohResult:
    provider_id: str
    endpoint: str
    ok: bool
    rtt_ms: float | None = None
    addresses: tuple[str, ...] = ()
    rcode: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class Ipv6Status:
    supported: bool = False
    has_global_address: bool = False
    resolves_aaaa: bool = False
    rtt_ms: float | None = None
    addresses: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DnsProbe:
    """Plain-UDP reachability of a DNS server."""

    host: str
    version: int
    reachable: bool
    rtt_ms: float | None = None
    rcode: str = ""
    addresses: tuple[str, ...] = ()
    source: str = "udp"
    error: str = ""


def build_query(name: str, qtype: int = TYPE_A, transaction_id: int | None = None) -> bytes:
    """Build a minimal DNS query packet."""
    if transaction_id is None:
        transaction_id = random.randint(0, 0xFFFF)
    header = struct.pack(">HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    labels = b"".join(bytes([len(label)]) + label.encode("idna") for label in name.rstrip(".").split("."))
    return header + labels + b"\x00" + struct.pack(">HH", qtype, CLASS_IN)


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    end = offset
    guard = 0
    while offset < len(data) and guard < 128:
        guard += 1
        length = data[offset]
        if length == 0:
            offset += 1
            if not jumped:
                end = offset
            break
        if length & 0xC0 == 0xC0:
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                end = offset + 2
            jumped = True
            offset = pointer
            continue
        offset += 1
        labels.append(data[offset : offset + length].decode("ascii", "replace"))
        offset += length
        if not jumped:
            end = offset
    return ".".join(labels), end


def parse_message(data: bytes) -> tuple[int, list[str], list[str]]:
    """Return ``(rcode, a_records, aaaa_records)`` from a DNS response."""
    if len(data) < 12:
        raise ValueError("DNS yanıtı çok kısa")
    _, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    rcode = flags & 0x0F
    offset = 12
    for _ in range(qdcount):
        _, offset = _read_name(data, offset)
        offset += 4
    ipv4: list[str] = []
    ipv6: list[str] = []
    for _ in range(ancount):
        if offset >= len(data):
            break
        _, offset = _read_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + rdlength]
        offset += rdlength
        if rtype == TYPE_A and rdlength == 4:
            ipv4.append(socket.inet_ntop(socket.AF_INET, rdata))
        elif rtype == TYPE_AAAA and rdlength == 16:
            ipv6.append(socket.inet_ntop(socket.AF_INET6, rdata))
    return rcode, ipv4, ipv6


def _rcode_name(rcode: int) -> str:
    return RCODE_NAMES.get(rcode, f"RCODE{rcode}")


def query_udp(server: str, name: str = DEFAULT_QUERY_NAME, qtype: int = TYPE_A, timeout: float = 1.2) -> DnsProbe:
    """Send a single UDP DNS query and time the round trip."""
    try:
        parsed = ipaddress.ip_address(server)
        version = parsed.version
    except ValueError:
        return DnsProbe(host=server, version=0, reachable=False, error="Geçersiz DNS adresi")

    family = socket.AF_INET6 if version == 6 else socket.AF_INET
    transaction_id = random.randint(0, 0xFFFF)
    packet = build_query(name, qtype, transaction_id)
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        start = time.perf_counter()
        sock.sendto(packet, (server, QUERY_PORT))
        data, _addr = sock.recvfrom(2048)
        elapsed = (time.perf_counter() - start) * 1000
        if len(data) < 2 or struct.unpack(">H", data[:2])[0] != transaction_id:
            return DnsProbe(host=server, version=version, reachable=False, error="Eşleşmeyen DNS yanıtı")
        rcode, ipv4, ipv6 = parse_message(data)
        addresses = tuple(ipv6 if qtype == TYPE_AAAA else ipv4)
        return DnsProbe(
            host=server,
            version=version,
            reachable=rcode == 0,
            rtt_ms=round(elapsed, 2),
            rcode=_rcode_name(rcode),
            addresses=addresses,
        )
    except TimeoutError:
        return DnsProbe(host=server, version=version, reachable=False, source="udp", error="Zaman aşımı")
    except OSError as exc:
        return DnsProbe(host=server, version=version, reachable=False, error=str(exc))
    finally:
        sock.close()


def icmp_rtt(host: str, timeout: float = 1.2) -> float | None:
    """ICMP round-trip time via the system ping, or None when unavailable."""
    try:
        completed = system.run_hidden(
            system.ping_command(host, count=1, timeout_ms=int(timeout * 1000)),
            timeout=timeout + 3,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return system.parse_ping_rtt(completed.stdout or "")


def measure_dns_latency(server: str, timeout: float = 1.2, name: str = DEFAULT_QUERY_NAME) -> float | None:
    """Round-trip time of a DNS query, falling back to ICMP when port 53 is blocked.

    Campuses, corporate networks and some ISPs drop outbound port 53, which
    makes a pure UDP probe report every server as unreachable. Falling back to
    ICMP keeps the ranking meaningful there.
    """
    if not server:
        return None
    probe = query_udp(server, name=name, timeout=timeout)
    if probe.reachable and probe.rtt_ms is not None:
        return probe.rtt_ms
    return icmp_rtt(server, timeout=timeout)


class DohTransportError(Exception):
    """Raised when a DoH query cannot be delivered by any available transport."""


class _HttpxTransport:
    """httpx-based transport; negotiates HTTP/2 only when 'h2' is installed."""

    name = "httpx"
    supports_http2 = False

    def __init__(self, http2: bool) -> None:
        self._http2 = http2
        self.supports_http2 = http2

    def request(self, method: str, url: str, data: bytes | None, headers: dict, timeout: float):
        import httpx

        with httpx.Client(http2=self._http2, timeout=timeout, follow_redirects=True) as client:
            start = time.perf_counter()
            response = client.request(method, url, content=data, headers=headers)
            elapsed = (time.perf_counter() - start) * 1000
        if response.status_code >= 400:
            raise urllib.error.HTTPError(url, response.status_code, response.reason_phrase, response.headers, None)
        return response.content, elapsed


class _UrllibTransport:
    """Standard-library fallback. HTTP/1.1 only."""

    name = "urllib"
    supports_http2 = False

    def request(self, method: str, url: str, data: bytes | None, headers: dict, timeout: float):
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return response.read(), (time.perf_counter() - start) * 1000


@lru_cache(maxsize=1)
def _httpx_module():
    try:
        import httpx

        return httpx
    except Exception:
        return None


@lru_cache(maxsize=1)
def _h2_available() -> bool:
    try:
        import h2  # noqa: F401

        return True
    except Exception:
        return False


def transport(prefer_http2: bool = False) -> _HttpxTransport | _UrllibTransport:
    """Return the HTTP transport to use.

    urllib is the default because it starts faster and reuses the cached TLS
    context. httpx is only worth its setup cost when the endpoint genuinely
    requires HTTP/2: Quad9 answers HTTP/1.1 with 505 per RFC 8484 section 5.2.
    """
    if prefer_http2 and _httpx_module() is not None and _h2_available():
        return _HttpxTransport(http2=True)
    return _UrllibTransport()


def http2_supported() -> bool:
    return _httpx_module() is not None and _h2_available()


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """TLS context for HTTPS probes.

    The Windows certificate store that :func:`ssl.create_default_context`
    consults is missing intermediates for some DoH providers (Cloudflare chains
    through SSL.com, for example), so certifi's bundle is layered on top when
    it is importable. ``APEX_DNS_CA_BUNDLE`` / ``SSL_CERT_FILE`` win over both.
    """
    context = ssl.create_default_context()
    override = os.environ.get("APEX_DNS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if override and os.path.isfile(override):
        try:
            context.load_verify_locations(cafile=override)
            return context
        except (OSError, ssl.SSLError):
            pass
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return context


def _candidate_transports() -> list:
    """HTTP/2-capable transport first, plain urllib second."""
    candidates: list = []
    if _httpx_module() is not None and _h2_available():
        candidates.append(_HttpxTransport(http2=True))
    candidates.append(_UrllibTransport())
    return candidates


def _doh_wire_query(url: str, name: str, qtype: int, timeout: float) -> tuple[bytes, float]:
    """RFC 8484 DoH query: POST first, GET as the fallback servers must support."""
    query = build_query(name, qtype)
    encoded = base64.urlsafe_b64encode(query).decode("ascii").rstrip("=")
    separator = "&" if "?" in url else "?"
    get_url = f"{url}{separator}{urlencode({'dns': encoded})}"
    post_headers = {"Content-Type": "application/dns-message", "Accept": "application/dns-message"}
    get_headers = {"Accept": "application/dns-message"}
    candidates = _candidate_transports()

    first_error: Exception | None = None
    for client in candidates:
        try:
            return client.request("POST", url, query, post_headers, timeout)
        except urllib.error.HTTPError as exc:
            first_error = first_error or exc
            if exc.code not in _DOH_RETRY_STATUS:
                raise
        except Exception as exc:
            first_error = first_error or exc

    for client in candidates:
        try:
            return client.request("GET", get_url, None, get_headers, timeout)
        except Exception as exc:
            first_error = first_error or exc

    raise first_error or DohTransportError("DoH isteği başarısız")


def _doh_json_query(url: str, name: str, qtype: int, timeout: float) -> tuple[list[str], str, float]:
    record_type = "AAAA" if qtype == TYPE_AAAA else "A"
    separator = "&" if "?" in url else "?"
    target = f"{url}{separator}{urlencode({'name': name, 'type': record_type})}"
    payload, elapsed = transport().request("GET", target, None, {"Accept": "application/dns-json"}, timeout)
    data = json.loads(payload.decode("utf-8", "replace"))
    addresses: list[str] = []
    for answer in data.get("Answer") or []:
        if answer.get("type") in (TYPE_A, TYPE_AAAA):
            addresses.append(str(answer.get("data", "")).strip())
    return addresses, _rcode_name(int(data.get("Status", 0))), elapsed


def measure_doh_latency(
    provider: DnsProvider,
    name: str = DEFAULT_QUERY_NAME,
    timeout: float = 6.0,
) -> DohResult:
    """Time a DNS-over-HTTPS query against a provider endpoint."""
    if not provider.supports_doh:
        return DohResult(provider.provider_id, "", False, error="DoH uç noktası tanımlı değil")

    try:
        if provider.doh_format == "json":
            addresses, rcode, elapsed = _doh_json_query(provider.doh_url, name, TYPE_A, timeout)
        else:
            payload, elapsed = _doh_wire_query(provider.doh_url, name, TYPE_A, timeout)
            rcode_code, ipv4, _ipv6 = parse_message(payload)
            rcode = _rcode_name(rcode_code)
            addresses = ipv4
        return DohResult(
            provider_id=provider.provider_id,
            endpoint=provider.doh_url,
            ok=rcode == "NOERROR",
            rtt_ms=round(elapsed, 2),
            addresses=tuple(addresses),
            rcode=rcode,
        )
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}"
        if provider.doh_requires_http2 and not http2_supported():
            detail += " (endpoint HTTP/2 istiyor; 'pip install httpx[http2]' ile etkinleştirin)"
        return DohResult(provider.provider_id, provider.doh_url, False, error=detail)
    except urllib.error.URLError as exc:
        return DohResult(provider.provider_id, provider.doh_url, False, error=str(exc.reason))
    except (ValueError, KeyError, OSError, ssl.SSLError) as exc:
        return DohResult(provider.provider_id, provider.doh_url, False, error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return DohResult(provider.provider_id, provider.doh_url, False, error=str(exc))


def has_global_ipv6() -> tuple[bool, tuple[str, ...]]:
    """Detect a non-link-local IPv6 address without sending any packet.

    ``connect()`` on a UDP socket only performs address selection locally.
    """
    if not socket.has_ipv6:
        return False, ()
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    except OSError:
        return False, ()
    try:
        sock.settimeout(0.5)
        sock.connect(("2001:4860:4860::8888", 53))
        address = sock.getsockname()[0]
    except OSError:
        return False, ()
    finally:
        sock.close()
    if not address or address.lower().startswith("fe80") or address == "::":
        return False, ()
    return True, (address,)


def resolves_aaaa(name: str = DEFAULT_QUERY_NAME) -> tuple[bool, tuple[str, ...]]:
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET6)
    except socket.gaierror:
        return False, ()
    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    return bool(addresses), addresses


def probe_ipv6(name: str = DEFAULT_QUERY_NAME) -> Ipv6Status:
    """Full IPv6 health check: stack, global address, AAAA resolution, RTT."""
    supported = socket.has_ipv6
    global_ok, global_addresses = has_global_ipv6()
    resolves, resolved = resolves_aaaa(name)
    rtt = icmp_rtt(resolved[0], timeout=1.2) if (global_ok and resolved) else None

    if not supported:
        detail = "IPv6 yığını desteklenmiyor"
    elif not global_ok:
        detail = "IPv6 yığını var ancak genel adres yok (yalnızca link-local)"
    elif not resolves:
        detail = "Genel IPv6 adresi var ancak AAAA kaydı çözülemiyor"
    elif rtt is None:
        detail = "IPv6 bağlantısı çalışıyor, ICMP yanıtı yok (ICMP engellenmiş olabilir)"
    else:
        detail = "IPv6 bağlantısı sorunsuz"

    return Ipv6Status(
        supported=supported,
        has_global_address=global_ok,
        resolves_aaaa=resolves,
        rtt_ms=rtt,
        addresses=global_addresses,
        detail=detail,
    )


def ipv4_public_address(timeout: float = 4.0) -> str | None:
    """Best-effort public IPv4 lookup used by the diagnostics report."""
    try:
        payload, _ = transport().request("GET", "https://api.ipify.org", None, {}, timeout)
        candidate = payload.decode("ascii", "replace").strip()
        ipaddress.ip_address(candidate)
        return candidate
    except Exception:
        return None
