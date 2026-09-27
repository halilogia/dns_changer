"""DNS provider catalog: the single source of truth for the whole app."""

from __future__ import annotations

from dataclasses import dataclass, replace

from i18n import t

CUSTOM_PROVIDER_ID = "custom"
ALL_ADAPTERS_ID = "*"

DOH_WIRE = "wire"
DOH_JSON = "json"


def all_adapters_label() -> str:
    """Display label for the multi-adapter option.

    The label is localized, so it must never be used as a key: compare
    against :data:`ALL_ADAPTERS_ID` instead.
    """
    return t("adapter.all")


def custom_provider_label() -> str:
    return t("provider.custom")


@dataclass(frozen=True, slots=True)
class DnsProvider:
    """A DNS endpoint on offer.

    Localized text is stored as catalog *keys* and resolved on access, so
    switching locale takes effect immediately instead of only at import time.
    """

    name: str = ""
    primary: str = ""
    secondary: str = ""
    name_key: str = ""
    desc_key: str = ""
    badge_key: str = ""
    badge_color: str = "#9CA3AF"
    doh_url: str = ""
    doh_format: str = DOH_WIRE
    doh_requires_http2: bool = False
    provider_id: str = ""

    @property
    def label(self) -> str:
        return t(self.name_key) if self.name_key else self.name

    @property
    def desc(self) -> str:
        return t(self.desc_key) if self.desc_key else ""

    @property
    def badge(self) -> str:
        return t(self.badge_key) if self.badge_key else ""

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
            return t("card.placeholder")
        if self.secondary:
            return f"{self.primary}  |  {self.secondary}"
        return f"{self.primary}  |  {t('card.auto')}"

    def as_custom(self, primary: str, secondary: str = "") -> DnsProvider:
        return replace(self, primary=primary, secondary=secondary)


def _provider(**kwargs) -> DnsProvider:
    if "provider_id" not in kwargs:
        source = kwargs.get("name") or kwargs.get("name_key", "")
        kwargs["provider_id"] = source.lower().replace(" ", "-")
    return DnsProvider(**kwargs)


DEFAULT_PROVIDERS: tuple[DnsProvider, ...] = (
    _provider(
        name="Cloudflare DNS",
        primary="1.1.1.1",
        secondary="1.0.0.1",
        desc_key="provider.cloudflare.desc",
        badge_key="badge.cloudflare",
        badge_color="#06B6D4",
        doh_url="https://cloudflare-dns.com/dns-query",
        doh_format=DOH_WIRE,
    ),
    _provider(
        name="Google DNS",
        primary="8.8.8.8",
        secondary="8.8.4.4",
        desc_key="provider.google.desc",
        badge_key="badge.google",
        badge_color="#F59E0B",
        doh_url="https://dns.google/resolve",
        doh_format=DOH_JSON,
    ),
    _provider(
        name="Quad9 Secure",
        primary="9.9.9.9",
        secondary="149.112.112.112",
        desc_key="provider.quad9.desc",
        badge_key="badge.quad9",
        badge_color="#10B981",
        doh_url="https://dns.quad9.net/dns-query",
        doh_format=DOH_WIRE,
        doh_requires_http2=True,
    ),
    _provider(
        name="AdGuard DNS",
        primary="94.140.14.14",
        secondary="94.140.15.15",
        desc_key="provider.adguard.desc",
        badge_key="badge.adguard",
        badge_color="#EF4444",
        doh_url="https://dns.adguard-dns.com/dns-query",
        doh_format=DOH_WIRE,
    ),
    _provider(
        name="OpenDNS Home",
        primary="208.67.222.222",
        secondary="208.67.220.220",
        desc_key="provider.opendns.desc",
        badge_key="badge.opendns",
        badge_color="#3B82F6",
        doh_url="https://doh.opendns.com/dns-query",
        doh_format=DOH_WIRE,
    ),
    _provider(
        name="Level3 DNS",
        primary="4.2.2.1",
        secondary="4.2.2.2",
        desc_key="provider.level3.desc",
        badge_key="badge.level3",
        badge_color="#9CA3AF",
    ),
    _provider(
        name_key="provider.custom",
        desc_key="provider.custom.desc",
        badge_key="badge.custom",
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
