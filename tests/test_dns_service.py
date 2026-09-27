"""Address validation and DNS service behaviour."""

from __future__ import annotations

import unittest

from core import dns_service as ds
from core.providers import ALL_ADAPTERS_ID
from tests import ROOT  # noqa: F401


class TestIsValidIp(unittest.TestCase):
    def test_accepts_ipv4(self):
        for address in ("1.1.1.1", "8.8.8.8", "4.2.2.1", "127.0.0.1"):
            self.assertTrue(ds.is_valid_ip(address), address)

    def test_accepts_ipv6(self):
        for address in ("2001:4860:4860::8888", "::1", "fe80::1", "2606:4700:4700::1111"):
            self.assertTrue(ds.is_valid_ip(address), address)

    def test_rejects_sloppy_ipv4_that_inet_aton_would_accept(self):
        # socket.inet_aton used to accept these, Windows then rejected them.
        for address in ("1.2.3", "1.2.3.4.5", "0x7f.0.0.1", "010.1.1.1", " 1.1.1.1 extra"):
            self.assertFalse(ds.is_valid_ip(address), address)

    def test_rejects_garbage(self):
        for address in ("", "   ", "not-an-ip", "example.com", "1.1.1.1/24", None, "999.1.1.1"):
            self.assertFalse(ds.is_valid_ip(address), address)

    def test_strips_surrounding_whitespace(self):
        self.assertTrue(ds.is_valid_ip("  1.1.1.1  "))


class TestNormalizeServers(unittest.TestCase):
    def test_trims_and_preserves_order(self):
        self.assertEqual(ds.normalize_servers([" 1.1.1.1 ", "1.0.0.1"]), ("1.1.1.1", "1.0.0.1"))

    def test_drops_duplicates(self):
        self.assertEqual(ds.normalize_servers(["1.1.1.1", "1.1.1.1", "1.0.0.1"]), ("1.1.1.1", "1.0.0.1"))

    def test_drops_empty_entries(self):
        self.assertEqual(ds.normalize_servers(["1.1.1.1", "", "   "]), ("1.1.1.1",))

    def test_mixed_families_are_allowed(self):
        self.assertEqual(
            ds.normalize_servers(["1.1.1.1", "2606:4700:4700::1111"]),
            ("1.1.1.1", "2606:4700:4700::1111"),
        )

    def test_rejects_invalid_address(self):
        with self.assertRaises(ds.InvalidAddressError):
            ds.normalize_servers(["1.1.1.1", "nope"])

    def test_rejects_empty_list(self):
        with self.assertRaises(ds.InvalidAddressError):
            ds.normalize_servers([])

    def test_invalid_address_error_is_also_value_error(self):
        self.assertTrue(issubclass(ds.InvalidAddressError, ValueError))


class TestSplitByFamily(unittest.TestCase):
    def test_splits_v4_and_v6(self):
        servers = ds.normalize_servers(["1.1.1.1", "1.0.0.1", "2606:4700:4700::1111"])
        v4, v6 = ds.split_by_family(servers)
        self.assertEqual(v4, ("1.1.1.1", "1.0.0.1"))
        self.assertEqual(v6, ("2606:4700:4700::1111",))

    def test_only_v6(self):
        v4, v6 = ds.split_by_family(ds.normalize_servers(["2606:4700:4700::1111"]))
        self.assertEqual(v4, ())
        self.assertEqual(len(v6), 1)


class FakeBackend(ds.DnsBackend):
    name = "fake"
    can_write = True

    def __init__(self, servers=None, adapters=None, failures=None):
        self._servers = servers or {"Ethernet": ["1.1.1.1"]}
        self._adapters = adapters or [
            ds.AdapterInfo(name="Ethernet", status="Up", dhcp_enabled=False),
            ds.AdapterInfo(name="Wi-Fi", status="Disconnected", dhcp_enabled=True),
        ]
        self._failures = failures or {}
        self.set_calls: list[tuple[str, tuple[str, ...]]] = []
        self.reset_calls: list[str] = []
        self.serve_calls = 0

    def list_adapters(self):
        return list(self._adapters)

    def get_dns_servers(self, adapter):
        self.serve_calls += 1
        if adapter in self._failures:
            raise self._failures[adapter]
        return list(self._servers.get(adapter, []))

    def set_dns_servers(self, adapter, servers):
        if adapter in self._failures:
            raise self._failures[adapter]
        self.set_calls.append((adapter, servers))
        self._servers[adapter] = list(servers)

    def reset_dns_servers(self, adapter):
        if adapter in self._failures:
            raise self._failures[adapter]
        self.reset_calls.append(adapter)
        self._servers[adapter] = []


class TestDnsService(unittest.TestCase):
    def test_adapters_are_listed(self):
        service = ds.DnsService(backend=FakeBackend(), cache_ttl=0)
        names = [adapter.name for adapter in service.adapters()]
        self.assertEqual(names, ["Ethernet", "Wi-Fi"])

    def test_connected_adapters_only(self):
        service = ds.DnsService(backend=FakeBackend(), cache_ttl=0)
        self.assertEqual(service.active_adapter_names(), ["Ethernet"])

    def test_active_names_falls_back_when_none_connected(self):
        backend = FakeBackend(adapters=[ds.AdapterInfo(name="Wi-Fi", status="Disconnected")])
        service = ds.DnsService(backend=backend, cache_ttl=0)
        self.assertEqual(service.active_adapter_names(), ["Wi-Fi"])

    def test_apply_normalizes_and_records(self):
        backend = FakeBackend()
        service = ds.DnsService(backend=backend, cache_ttl=0)
        result = service.apply("Ethernet", [" 1.1.1.1 ", "1.0.0.1", "1.1.1.1"])
        self.assertTrue(result.ok)
        self.assertEqual(backend.set_calls, [("Ethernet", ("1.1.1.1", "1.0.0.1"))])
        self.assertEqual(result.servers, ("1.1.1.1", "1.0.0.1"))

    def test_apply_to_all_connected_adapters(self):
        backend = FakeBackend()
        service = ds.DnsService(backend=backend, cache_ttl=0)
        result = service.apply(ALL_ADAPTERS_ID, ["9.9.9.9"])
        self.assertTrue(result.ok)
        self.assertEqual([name for name, _ in backend.set_calls], ["Ethernet"])

    def test_apply_reports_partial_failure(self):
        backend = FakeBackend(failures={"Ethernet": ds.DnsServiceError("erisim reddedildi")})
        service = ds.DnsService(backend=backend, cache_ttl=0)
        result = service.apply("Ethernet", ["1.1.1.1"])
        self.assertFalse(result.ok)
        self.assertIn("Ethernet", result.errors[0])
        self.assertIn("erisim reddedildi", result.errors[0])

    def test_apply_rejects_invalid_address_before_touching_backend(self):
        backend = FakeBackend()
        service = ds.DnsService(backend=backend, cache_ttl=0)
        with self.assertRaises(ds.InvalidAddressError):
            service.apply("Ethernet", ["1.2.3"])
        self.assertEqual(backend.set_calls, [])

    def test_reset_calls_backend(self):
        backend = FakeBackend()
        service = ds.DnsService(backend=backend, cache_ttl=0)
        result = service.reset("Ethernet")
        self.assertTrue(result.ok)
        self.assertEqual(backend.reset_calls, ["Ethernet"])
        self.assertEqual(service.dns_servers("Ethernet", refresh=True), [])

    def test_read_cache_avoids_repeat_backend_calls(self):
        backend = FakeBackend()
        service = ds.DnsService(backend=backend, cache_ttl=60)
        service.dns_servers("Ethernet")
        service.dns_servers("Ethernet")
        self.assertEqual(backend.serve_calls, 1)
        service.dns_servers("Ethernet", refresh=True)
        self.assertEqual(backend.serve_calls, 2)

    def test_uses_dhcp_flag(self):
        service = ds.DnsService(backend=FakeBackend(), cache_ttl=0)
        self.assertFalse(service.uses_dhcp("Ethernet"))
        self.assertTrue(service.uses_dhcp("Wi-Fi"))

    def test_adapter_lookup(self):
        service = ds.DnsService(backend=FakeBackend(), cache_ttl=0)
        self.assertIsNotNone(service.adapter("Ethernet"))
        self.assertIsNone(service.adapter("Yok"))


class TestReadOnlyBackend(unittest.TestCase):
    def test_write_raises_unsupported(self):
        backend = ds.ReadOnlyDnsBackend()
        self.assertFalse(backend.can_write)
        with self.assertRaises(ds.UnsupportedPlatformError):
            backend.set_dns_servers("any", ("1.1.1.1",))
        with self.assertRaises(ds.UnsupportedPlatformError):
            backend.reset_dns_servers("any")

    def test_service_refuses_apply_on_read_only_backend(self):
        service = ds.DnsService(backend=ds.ReadOnlyDnsBackend(), cache_ttl=0)
        with self.assertRaises(ds.UnsupportedPlatformError):
            service.apply("Ethernet", ["1.1.1.1"])

    def test_resolv_conf_parsing_filters_invalid_entries(self):
        backend = ds.ReadOnlyDnsBackend()
        parsed = backend._parse_resolv_conf("nameserver 1.1.1.1\nnameserver nope\n# nameserver 8.8.8.8\n")
        self.assertEqual(parsed, ["1.1.1.1"])


if __name__ == "__main__":
    unittest.main()
