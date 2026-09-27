"""Provider catalog invariants."""

from __future__ import annotations

import unittest

from core.dns_service import is_valid_ip
from core.providers import (
    ALL_ADAPTERS_ID,
    CUSTOM_PROVIDER_ID,
    DEFAULT_PROVIDERS,
    DnsProvider,
    all_adapters_label,
    custom_provider_label,
    doh_providers,
    find_by_id,
    get_provider,
    measurable_providers,
)
from tests import ROOT  # noqa: F401


class TestCatalog(unittest.TestCase):
    def test_catalog_is_not_empty(self):
        self.assertGreaterEqual(len(DEFAULT_PROVIDERS), 6)

    def test_provider_ids_are_unique(self):
        ids = [provider.provider_id for provider in DEFAULT_PROVIDERS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_names_are_unique(self):
        names = [provider.name for provider in DEFAULT_PROVIDERS]
        self.assertEqual(len(names), len(set(names)))

    def test_preset_addresses_are_valid(self):
        for provider in DEFAULT_PROVIDERS:
            with self.subTest(provider.name):
                if provider.has_custom_addresses:
                    continue
                self.assertTrue(is_valid_ip(provider.primary), provider.primary)
                if provider.secondary:
                    self.assertTrue(is_valid_ip(provider.secondary), provider.secondary)

    def test_doh_urls_are_https(self):
        for provider in DEFAULT_PROVIDERS:
            with self.subTest(provider.name):
                if provider.supports_doh:
                    self.assertTrue(provider.doh_url.startswith("https://"), provider.doh_url)

    def test_measurable_excludes_custom(self):
        measured = measurable_providers()
        self.assertTrue(measured)
        for provider in measured:
            self.assertFalse(provider.has_custom_addresses)
            self.assertTrue(provider.primary)

    def test_doh_providers_excludes_custom_and_unknown(self):
        for provider in doh_providers():
            self.assertTrue(provider.supports_doh)
            self.assertFalse(provider.has_custom_addresses)

    def test_custom_provider_is_last_and_addressless(self):
        last = DEFAULT_PROVIDERS[-1]
        self.assertEqual(last.provider_id, CUSTOM_PROVIDER_ID)
        self.assertEqual(last.primary, "")
        self.assertFalse(last.supports_doh)

    def test_get_provider_by_index(self):
        self.assertEqual(get_provider(0).name, "Cloudflare DNS")

    def test_find_by_id(self):
        self.assertIsNotNone(find_by_id("cloudflare-dns"))
        self.assertIsNone(find_by_id("yok-boyle-bir-sayi"))

    def test_cloudflare_endpoint_is_the_doh_one(self):
        cloudflare = find_by_id("cloudflare-dns")
        self.assertEqual(cloudflare.doh_url, "https://cloudflare-dns.com/dns-query")

    def test_quad9_declares_http2_requirement(self):
        quad9 = find_by_id("quad9-secure")
        self.assertTrue(quad9.doh_requires_http2)

    def test_all_adapters_sentinel(self):
        self.assertNotEqual(ALL_ADAPTERS_ID, all_adapters_label())

    def test_all_adapters_label_is_localized(self):
        from i18n import set_locale

        try:
            set_locale("en")
            english = all_adapters_label()
            set_locale("tr")
            turkish = all_adapters_label()
        finally:
            set_locale("tr")
        self.assertNotEqual(english, turkish)

    def test_custom_provider_label_is_localized(self):
        from i18n import set_locale

        try:
            set_locale("en")
            english = custom_provider_label()
        finally:
            set_locale("tr")
        self.assertEqual(english, "Custom DNS")
        self.assertEqual(custom_provider_label(), "Özel DNS")


class TestDnsProvider(unittest.TestCase):
    def make(self, **kwargs):
        base = {"name": "Test", "provider_id": "test"}
        base.update(kwargs)
        return DnsProvider(**base)

    def test_servers_skips_blanks(self):
        provider = self.make(primary="1.1.1.1", secondary="")
        self.assertEqual(provider.servers, ("1.1.1.1",))

    def test_servers_drops_whitespace_only(self):
        provider = self.make(primary="1.1.1.1", secondary="   ")
        self.assertEqual(provider.servers, ("1.1.1.1",))

    def test_display_servers_without_secondary(self):
        provider = self.make(primary="1.1.1.1")
        self.assertIn("Otomatik", provider.display_servers())

    def test_display_servers_with_secondary(self):
        provider = self.make(primary="1.1.1.1", secondary="1.0.0.1")
        self.assertIn("1.0.0.1", provider.display_servers())

    def test_display_servers_placeholder_when_empty(self):
        self.assertIn("manuel", self.make().display_servers())

    def test_label_desc_badge_resolve_from_keys(self):
        provider = self.make(name_key="provider.custom", desc_key="provider.cloudflare.desc")
        self.assertIn("DNS", provider.label)
        self.assertTrue(provider.desc)
        self.assertEqual(provider.badge, "")

    def test_literal_label_falls_back_to_name(self):
        self.assertEqual(self.make(name="Plain").label, "Plain")

    def test_as_custom_returns_new_instance(self):
        original = self.make()
        updated = original.as_custom("9.9.9.9", "149.112.112.112")
        self.assertEqual(original.primary, "")
        self.assertEqual(updated.primary, "9.9.9.9")
        self.assertEqual(updated.secondary, "149.112.112.112")
        self.assertIsNot(original, updated)

    def test_provider_is_immutable(self):
        provider = self.make()
        with self.assertRaises(AttributeError):
            provider.primary = "8.8.8.8"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
