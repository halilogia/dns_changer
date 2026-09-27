"""DNS provider catalog: the single source of truth for the whole app."""

from __future__ import annotations

from dataclasses import dataclass, replace

CUSTOM_PROVIDER_ID = "custom"
ALL_ADAPTERS_ID = "*"
ALL_ADAPTERS_LABEL = "Tüm Aktif Bağlantılar"
CUSTOM_PROVIDER_LABEL = "Özel DNS"

DOH_WIRE = "wire"
DOH_JSON = "json"


@dataclass(frozen=True, slots=True)
class DnsProvider:
    name: str
    primary: str = ""
    secondary: str = ""
    desc: str = ""
    badge: str = ""
    badge_color: str = "#9CA3AF"
    doh_url: str = ""
    doh_format: str = DOH_WIRE
    doh_requires_http2: bool = False
    provider_id: str = ""

    @property
    def has_custom_addresses(self) -> bool:
        return self.provider_id == CUSTOM_PROVIDER_ID

    @property
    def supports_doh(self) -> bool:
        return bool(self.doh_url)

    @property
    def servers(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in (self.primary, self.secondary) if s and s.strip())

    def display_servers(self) -> str:
        if not self.primary:
            return "DNS Adreslerini manuel girin"
        if self.secondary:
            return f"{self.primary}  |  {self.secondary}"
        return f"{self.primary}  |  Otomatik"

    def as_custom(self, primary: str, secondary: str = "") -> DnsProvider:
        return replace(self, primary=primary, secondary=secondary)


def _provider(**kwargs) -> DnsProvider:
    kwargs.setdefault("provider_id", kwargs["name"].lower().replace(" ", "-"))
    return DnsProvider(**kwargs)


DEFAULT_PROVIDERS: tuple[DnsProvider, ...] = (
    _provider(
        name="Cloudflare DNS",
        primary="1.1.1.1",
        secondary="1.0.0.1",
        desc="Oyunlar için En İyi Gecikme ve Hız",
        badge="🎮 Oyun Önerisi",
        badge_color="#06B6D4",
        doh_url="https://cloudflare-dns.com/dns-query",
        doh_format=DOH_WIRE,
    ),
    _provider(
        name="Google DNS",
        primary="8.8.8.8",
        secondary="8.8.4.4",
        desc="Güvenilir, Hızlı ve Genel Kullanım",
        badge="⚡ Popüler",
        badge_color="#F59E0B",
        doh_url="https://dns.google/resolve",
        doh_format=DOH_JSON,
    ),
    _provider(
        name="Quad9 Secure",
        primary="9.9.9.9",
        secondary="149.112.112.112",
        desc="Zararlı Yazılım ve Virüs Engelleme",
        badge="🛡️ Güvenli",
        badge_color="#10B981",
        doh_url="https://dns.quad9.net/dns-query",
        doh_format=DOH_WIRE,
        doh_requires_http2=True,
    ),
    _provider(
        name="AdGuard DNS",
        primary="94.140.14.14",
        secondary="94.140.15.15",
        desc="Reklamları ve İzleyicileri Engeller",
        badge="🚫 Reklamsız",
        badge_color="#EF4444",
        doh_url="https://dns.adguard-dns.com/dns-query",
        doh_format=DOH_WIRE,
    ),
    _provider(
        name="OpenDNS Home",
        primary="208.67.222.222",
        secondary="208.67.220.220",
        desc="Aile Koruması ve Web Filtreleme",
        badge="👨‍👩‍👧 Aile",
        badge_color="#3B82F6",
        doh_url="https://doh.opendns.com/dns-query",
        doh_format=DOH_WIRE,
    ),
    _provider(
        name="Level3 DNS",
        primary="4.2.2.1",
        secondary="4.2.2.2",
        desc="Küresel ve Köklü Altyapı",
        badge="🏢 Kurumsal",
        badge_color="#9CA3AF",
    ),
    _provider(
        name=CUSTOM_PROVIDER_LABEL,
        desc="Kendi tercih ettiğiniz DNS adreslerini girin",
        badge="✏️ Özelleştir",
        badge_color="#A855F7",
        provider_id=CUSTOM_PROVIDER_ID,
    ),
)


def get_provider(index: int) -> DnsProvider:
    return DEFAULT_PROVIDERS[index]


def measurable_providers() -> tuple[DnsProvider, ...]:
    """Providers with preset addresses, i.e. latency-testable out of the box."""
    return tuple(p for p in DEFAULT_PROVIDERS if p.primary)


def doh_providers() -> tuple[DnsProvider, ...]:
    return tuple(p for p in DEFAULT_PROVIDERS if p.supports_doh and not p.has_custom_addresses)


def find_by_id(provider_id: str) -> DnsProvider | None:
    for provider in DEFAULT_PROVIDERS:
        if provider.provider_id == provider_id:
            return provider
    return None
