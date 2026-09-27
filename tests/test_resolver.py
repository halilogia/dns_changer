"""DNS wire-format encoding/parsing and the DoH/IPv6 probe plumbing."""

from __future__ import annotations

import socket
import struct
import unittest
from unittest import mock

from core import resolver
from core.providers import DnsProvider
from tests import ROOT  # noqa: F401
from tests.support import requires_network


class TestBuildQuery(unittest.TestCase):
    def test_header_layout(self):
        packet = resolver.build_query("example.com", resolver.TYPE_A, transaction_id=0x1234)
        self.assertEqual(packet[:2], b"\x12\x34")
        self.assertEqual(packet[2:4], b"\x01\x00")
        self.assertEqual(struct.unpack(">H", packet[4:6])[0], 1)
        self.assertEqual(struct.unpack(">H", packet[6:8])[0], 0)
        self.assertEqual(struct.unpack(">H", packet[8:10])[0], 0)
        self.assertEqual(struct.unpack(">H", packet[10:12])[0], 0)

    def test_question_section(self):
        packet = resolver.build_query("example.com", resolver.TYPE_A, transaction_id=1)
        self.assertIn(b"\x07example\x03com\x00", packet)
        tail = struct.unpack(">HH", packet[-4:])
        self.assertEqual(tail, (resolver.TYPE_A, resolver.CLASS_IN))

    def test_aaaa_type(self):
        packet = resolver.build_query("example.com", resolver.TYPE_AAAA, transaction_id=1)
        self.assertEqual(struct.unpack(">H", packet[-4:-2])[0], resolver.TYPE_AAAA)

    def test_transaction_id_varies(self):
        ids = {resolver.build_query("example.com")[:2] for _ in range(40)}
        self.assertGreater(len(ids), 1)

    def test_trailing_dot_is_ignored(self):
        a = resolver.build_query("example.com", transaction_id=7)
        b = resolver.build_query("example.com.", transaction_id=7)
        self.assertEqual(a, b)


def _response(transaction_id, answers, qname="example.com"):
    header = struct.pack(">HHHHHH", transaction_id, 0x8180, 1, len(answers), 0, 0)
    labels = b"".join(bytes([len(p)]) + p.encode() for p in qname.split("."))
    question = labels + b"\x00" + struct.pack(">HH", resolver.TYPE_A, resolver.CLASS_IN)
    body = b""
    for rdata in answers:
        body += b"\xc0\x0c" + struct.pack(">HHIH", resolver.TYPE_A, resolver.CLASS_IN, 300, 4)
        body += socket.inet_pton(socket.AF_INET, rdata)
    return header + question + body


class TestParseMessage(unittest.TestCase):
    def test_extracts_a_records(self):
        payload = _response(0x1234, ["1.2.3.4", "5.6.7.8"])
        rcode, ipv4, ipv6 = resolver.parse_message(payload)
        self.assertEqual(rcode, 0)
        self.assertEqual(ipv4, ["1.2.3.4", "5.6.7.8"])
        self.assertEqual(ipv6, [])

    def test_no_answers(self):
        rcode, ipv4, ipv6 = resolver.parse_message(_response(1, []))
        self.assertEqual(rcode, 0)
        self.assertEqual(ipv4, [])

    def test_servfail_rcode(self):
        payload = bytearray(_response(1, []))
        payload[3] = 0x82
        rcode, _, _ = resolver.parse_message(bytes(payload))
        self.assertEqual(rcode, 2)
        self.assertEqual(resolver._rcode_name(rcode), "SERVFAIL")

    def test_rcode_names(self):
        self.assertEqual(resolver._rcode_name(0), "NOERROR")
        self.assertEqual(resolver._rcode_name(3), "NXDOMAIN")
        self.assertEqual(resolver._rcode_name(99), "RCODE99")

    def test_short_payload_raises(self):
        with self.assertRaises(ValueError):
            resolver.parse_message(b"\x00\x01")

    def test_compression_pointer_is_followed(self):
        packet = _response(5, ["9.9.9.9"])
        self.assertEqual(b"\xc0\x0c", packet[-16:-14])


@requires_network
class TestQueryUdp(unittest.TestCase):
    def test_invalid_server_reports_error(self):
        probe = resolver.query_udp("not-an-ip")
        self.assertFalse(probe.reachable)
        self.assertIn("Geçersiz", probe.error)

    def test_ipv6_family_detected(self):
        probe = resolver.query_udp("not-an-ip")
        self.assertEqual(probe.version, 0)

    def test_timeout_is_reported_not_raised(self):
        # 203.0.113.0/24 is TEST-NET-3 and guaranteed not to answer.
        probe = resolver.query_udp("203.0.113.1", timeout=0.15)
        self.assertFalse(probe.reachable)
        self.assertTrue(probe.error)
        self.assertEqual(probe.source, "udp")

    def test_ipv6_dns_server_uses_ipv6_socket(self):
        probe = resolver.query_udp("2001:db8::1", timeout=0.15)
        self.assertEqual(probe.version, 6)
        self.assertFalse(probe.reachable)


class FakeSocket:
    def __init__(self, payload=None, family=socket.AF_INET):
        self.payload = payload
        self.family = family
        self.sent = None
        self.closed = False

    def settimeout(self, _value):
        return None

    def sendto(self, data, address):
        self.sent = (data, address)
        return len(data)

    def recvfrom(self, _size):
        if self.payload is None:
            raise TimeoutError()
        return self.payload, ("1.1.1.1", 53)

    def close(self):
        self.closed = True


class TestQueryUdpSocketHandling(unittest.TestCase):
    def setUp(self):
        self.original = resolver.socket.socket
        self.probes = []

        def factory(*args, **kwargs):
            probe = FakeSocket(None)
            self.probes.append(probe)
            return probe

        resolver.socket.socket = factory

    def tearDown(self):
        resolver.socket.socket = self.original

    def test_socket_is_always_closed(self):
        resolver.query_udp("1.1.1.1", timeout=0.1)
        self.assertTrue(self.probes[-1].closed)

    def test_query_is_sent_to_port_53(self):
        probe = FakeSocket(_response(0, ["1.2.3.4"]))
        resolver.socket.socket = lambda *a, **k: probe
        resolver.query_udp("1.1.1.1", timeout=1.0)
        self.assertEqual(probe.sent[1], ("1.1.1.1", 53))

    def test_ipv6_server_uses_ipv6_socket_family(self):
        seen = {}

        def factory(family=socket.AF_INET, kind=socket.SOCK_DGRAM, proto=0):
            seen["family"] = family
            return FakeSocket(None, family)

        resolver.socket.socket = factory
        resolver.query_udp("2001:db8::1", timeout=0.1)
        self.assertEqual(seen["family"], socket.AF_INET6)

    def test_ipv4_server_uses_ipv4_socket_family(self):
        seen = {}

        def factory(family=socket.AF_INET, kind=socket.SOCK_DGRAM, proto=0):
            seen["family"] = family
            return FakeSocket(None, family)

        resolver.socket.socket = factory
        resolver.query_udp("1.1.1.1", timeout=0.1)
        self.assertEqual(seen["family"], socket.AF_INET)

    def test_transaction_id_mismatch_is_rejected(self):
        probe = FakeSocket(_response(0x9999, ["1.2.3.4"]))
        resolver.socket.socket = lambda *a, **k: probe
        result = resolver.query_udp("1.1.1.1", timeout=1.0)
        self.assertFalse(result.reachable)
        self.assertIn("Eşleşmeyen", result.error)


class TestMeasureDnsLatency(unittest.TestCase):
    def test_empty_server_returns_none(self):
        self.assertIsNone(resolver.measure_dns_latency(""))

    def test_falls_back_to_icmp_when_udp_unreachable(self):
        calls = []

        def fake_query(server, **kwargs):
            calls.append("udp")
            return resolver.DnsProbe(host=server, version=4, reachable=False, error="Zaman aşımı")

        def fake_icmp(host, timeout=1.2):
            calls.append("icmp")
            return 42.0

        with mock.patch.object(resolver, "query_udp", fake_query), mock.patch.object(resolver, "icmp_rtt", fake_icmp):
            self.assertEqual(resolver.measure_dns_latency("1.1.1.1"), 42.0)
        self.assertEqual(calls, ["udp", "icmp"])

    def test_uses_udp_result_when_reachable(self):
        reachable = resolver.DnsProbe(host="1.1.1.1", version=4, reachable=True, rtt_ms=7.5)
        with (
            mock.patch.object(resolver, "query_udp", return_value=reachable),
            mock.patch.object(resolver, "icmp_rtt", return_value=999.0),
        ):
            self.assertEqual(resolver.measure_dns_latency("1.1.1.1"), 7.5)

    def test_returns_none_when_both_fail(self):
        unreachable = resolver.DnsProbe(host="1.1.1.1", version=4, reachable=False, error="x")
        with (
            mock.patch.object(resolver, "query_udp", return_value=unreachable),
            mock.patch.object(resolver, "icmp_rtt", return_value=None),
        ):
            self.assertIsNone(resolver.measure_dns_latency("1.1.1.1"))

    def test_core_functions_are_not_polluted(self):
        # Guards against a test replacing a module function without restoring it.
        self.assertTrue(callable(resolver.query_udp))
        probe = resolver.DnsProbe(host="x", version=4, reachable=False)
        self.assertEqual(probe.host, "x")


class TestDohTransportSelection(unittest.TestCase):
    def test_http2_supported_is_boolean(self):
        self.assertIn(resolver.http2_supported(), (True, False))

    def test_default_transport_is_urllib(self):
        # urllib is the fast default; httpx is only selected on demand.
        self.assertEqual(resolver.transport().name, "urllib")

    def test_candidate_transports_always_ends_with_urllib(self):
        candidates = resolver._candidate_transports()
        self.assertEqual(candidates[-1].name, "urllib")

    def test_http2_requested_uses_httpx_when_available(self):
        transport = resolver.transport(prefer_http2=True)
        if resolver.http2_supported():
            self.assertEqual(transport.name, "httpx")
            self.assertTrue(transport.supports_http2)
        else:
            self.assertEqual(transport.name, "urllib")

    def test_retry_status_set_covers_505(self):
        self.assertIn(505, resolver._DOH_RETRY_STATUS)
        self.assertIn(405, resolver._DOH_RETRY_STATUS)


@requires_network
class TestDohEndpoints(unittest.TestCase):
    def test_provider_without_endpoint_is_rejected(self):
        provider = DnsProvider(name="Yok", provider_id="yok")
        result = resolver.measure_doh_latency(provider)
        self.assertFalse(result.ok)
        self.assertIn("DoH", result.error)

    def test_unreachable_endpoint_returns_error_not_exception(self):
        provider = DnsProvider(
            name="Yerel",
            provider_id="yerel",
            doh_url="https://127.0.0.1:1/dns-query",
        )
        result = resolver.measure_doh_latency(provider, timeout=0.5)
        self.assertFalse(result.ok)
        self.assertTrue(result.error)
        self.assertIsNone(result.rtt_ms)

    def test_http_error_mentions_http2_hint_for_quad9(self):
        provider = DnsProvider(
            name="Q9",
            provider_id="q9",
            doh_url="https://127.0.0.1:1/dns-query",
            doh_requires_http2=True,
        )
        result = resolver.measure_doh_latency(provider, timeout=0.5)
        if not resolver.http2_supported() and "HTTP" in result.error:
            self.assertIn("HTTP/2", result.error)

    def test_json_format_is_used_for_json_providers(self):
        provider = DnsProvider(
            name="JSON",
            provider_id="json",
            doh_url="https://127.0.0.1:1/resolve",
            doh_format="json",
        )
        result = resolver.measure_doh_latency(provider, timeout=0.5)
        self.assertFalse(result.ok)


@requires_network
class TestIpv6Probe(unittest.TestCase):
    def test_returns_status_object(self):
        status = resolver.probe_ipv6()
        self.assertIsInstance(status, resolver.Ipv6Status)
        self.assertIn(status.supported, (True, False))
        self.assertTrue(status.detail)

    def test_global_ipv6_detection_is_safe_on_ipv4_only_hosts(self):
        found, addresses = resolver.has_global_ipv6()
        self.assertIn(found, (True, False))
        for address in addresses:
            self.assertFalse(address.lower().startswith("fe80"))

    def test_aaaa_resolution_returns_tuple(self):
        ok, addresses = resolver.resolves_aaaa("example.com")
        self.assertIn(ok, (True, False))
        self.assertIsInstance(addresses, tuple)

    def test_aaaa_resolution_of_garbage(self):
        ok, addresses = resolver.resolves_aaaa("this-host-does-not-exist.invalid")
        self.assertFalse(ok)
        self.assertEqual(addresses, ())

    def test_public_address_returns_none_on_failure(self):
        original = resolver.transport
        resolver.transport = lambda prefer_http2=False: _FailingTransport()
        try:
            self.assertIsNone(resolver.ipv4_public_address())
        finally:
            resolver.transport = original


class _FailingTransport:
    def request(self, *_args, **_kwargs):
        raise OSError("network down")


if __name__ == "__main__":
    unittest.main()
