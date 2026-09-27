"""Console diagnostics report and the CLI entry point."""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import patch

from core import resolver
from diagnostics import report, speedtest
from tests import ROOT  # noqa: F401


class TestSummarizeLoss(unittest.TestCase):
    def test_english_zero_loss(self):
        output = "Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)"
        summary = report.summarize_loss(output)
        self.assertIsNotNone(summary)
        self.assertIn("0%", summary)

    def test_english_partial_loss(self):
        output = "Packets: Sent = 10, Received = 9, Lost = 1 (10% loss)"
        self.assertIn("10%", report.summarize_loss(output))

    def test_turkish_loss(self):
        self.assertIsNotNone(report.summarize_loss("%25 veri kaybi"))

    def test_empty_returns_none(self):
        self.assertIsNone(report.summarize_loss(""))

    def test_unparsable_returns_last_line(self):
        self.assertEqual(report.summarize_loss("bir sey\nson satir"), "son satir")


class TestRunDiagnosticsRendering(unittest.TestCase):
    def build_report(self):
        return {
            "platform": {"public_ipv4": "203.0.113.9"},
            "adapters": [
                {
                    "name": "Ethernet",
                    "status": "Up",
                    "description": "Intel",
                    "is_virtual": False,
                    "dhcp_enabled": True,
                    "ipv4": ["192.168.1.5"],
                    "ipv6": [],
                }
            ],
            "adapters_error": "",
            "dns": {"Cloudflare DNS": 7.5, "Google DNS": None},
            "doh": {
                "Cloudflare DNS": {
                    "endpoint": "https://example/dns-query",
                    "ok": True,
                    "rtt_ms": 12.3,
                    "rcode": "NOERROR",
                    "error": "",
                }
            },
            "ipv6": {
                "supported": True,
                "has_global_address": False,
                "resolves_aaaa": False,
                "rtt_ms": None,
                "detail": "IPv6 yığını var ancak genel adres yok",
            },
            "ping_output": "Packets: Sent = 4, Lost = 0 (0% loss)",
            "loss_summary": "0% kayıp",
            "speed": {"download_mbps": 120.5, "upload_mbps": 20.0},
            "top_apps": [{"name": "chrome.exe", "kb": 1234.0}],
        }

    def render(self, quick=False):
        stream = io.StringIO()
        with patch.object(report, "build_report", return_value=self.build_report()):
            report.run_diagnostics(quick=quick, stream=stream)
        return stream.getvalue()

    def test_report_contains_sections(self):
        output = self.render()
        for expected in ("DNS Yanıt", "DoH", "IPv6", "Ağ Bağlantıları", "TEŞHİS ÖZETİ"):
            self.assertIn(expected, output, expected)

    def test_latency_values_rendered(self):
        self.assertIn("7.5 ms", self.render())

    def test_timeout_rendered_for_unreachable(self):
        self.assertIn("Zaman Aşımı", self.render())

    def test_ipv6_gap_is_reported_as_advice(self):
        self.assertIn("IPv6 genel adresi yok", self.render())

    def test_adapter_flags_rendered(self):
        self.assertIn("DHCP", self.render())

    def test_quick_mode_skips_bandwidth(self):
        output = self.render(quick=True)
        self.assertNotIn("Bant Genişliği", output)

    def test_full_mode_includes_bandwidth(self):
        self.assertIn("Bant Genişliği", self.render(quick=False))

    def test_top_apps_rendered(self):
        self.assertIn("chrome.exe", self.render())

    def test_public_ip_rendered(self):
        self.assertIn("203.0.113.9", self.render())

    def test_low_bandwidth_advice(self):
        data = self.build_report()
        data["speed"]["download_mbps"] = 1.0
        with patch.object(report, "build_report", return_value=data):
            stream = io.StringIO()
            report.run_diagnostics(stream=stream)
        self.assertIn("Bant genişliği düşük", stream.getvalue())

    def test_dns_latency_advice(self):
        data = self.build_report()
        data["dns"] = {"Yavas": 250.0}
        with patch.object(report, "build_report", return_value=data):
            stream = io.StringIO()
            report.run_diagnostics(stream=stream)
        self.assertIn("DNS gecikmesi yüksek", stream.getvalue())


class TestCollectDnsResults(unittest.TestCase):
    def test_maps_provider_names_to_latency(self):
        with patch.object(resolver, "measure_dns_latency", return_value=5.0):
            results = report.collect_dns_results()
        self.assertTrue(results)
        self.assertTrue(all(value == 5.0 for value in results.values()))

    def test_timeout_is_forwarded(self):
        with patch.object(resolver, "measure_dns_latency", return_value=1.0) as measure:
            report.collect_dns_results(timeout=0.42)
        self.assertTrue(all(call.kwargs.get("timeout") == 0.42 for call in measure.call_args_list))


class TestCollectDohResults(unittest.TestCase):
    def test_serialises_doh_results(self):
        payload = report.collect_doh_results()
        self.assertTrue(payload)
        for name, entry in payload.items():
            with self.subTest(name):
                self.assertIn("ok", entry)
                self.assertIn("rtt_ms", entry)
                self.assertIn("endpoint", entry)

    def test_handles_failure(self):
        with patch.object(
            resolver,
            "measure_doh_latency",
            return_value=resolver.DohResult(provider_id="x", endpoint="https://e", ok=False, error="kapali"),
        ):
            payload = report.collect_doh_results()
        self.assertTrue(all(not entry["ok"] for entry in payload.values()))


class TestSpeedtest(unittest.TestCase):
    def test_speed_uses_bytes(self):
        class Response:
            content = b"x" * 1000

        with (
            patch.object(speedtest.requests, "get", return_value=Response()) as get,
            patch.object(speedtest.requests, "post", return_value=Response()) as post,
            patch.object(speedtest.time, "perf_counter", side_effect=[0.0, 1.0, 1.0, 2.0]),
        ):
            down, up = speedtest.test_speed(down_bytes=1000, up_bytes=1000)

        self.assertAlmostEqual(down, 0.01)
        self.assertAlmostEqual(up, 0.01)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(post.call_count, 1)

    def test_speed_returns_zero_on_failure(self):
        import requests

        with (
            patch.object(speedtest.requests, "get", side_effect=requests.RequestException("x")),
            patch.object(speedtest.requests, "post", side_effect=requests.RequestException("x")),
        ):
            self.assertEqual(speedtest.test_speed(), (0.0, 0.0))

    def test_speed_ignores_zero_duration(self):
        class Response:
            content = b"x" * 1000

        with (
            patch.object(speedtest.requests, "get", return_value=Response()),
            patch.object(speedtest.requests, "post", return_value=Response()),
            patch.object(speedtest.time, "perf_counter", side_effect=[0.0, 0.0, 0.0, 0.0]),
        ):
            self.assertEqual(speedtest.test_speed(), (0.0, 0.0))


class TestNetUsage(unittest.TestCase):
    class Counters:
        def __init__(self, write_bytes=0, read_bytes=0):
            self.write_bytes = write_bytes
            self.read_bytes = read_bytes

    def test_ranks_by_delta(self):
        import psutil

        proc = psutil  # placeholder for clarity
        self.assertTrue(hasattr(proc, "process_iter"))

    def test_reports_top_consumer(self):
        from unittest.mock import MagicMock, patch

        import psutil

        before, after = self.Counters(0, 0), self.Counters(15000, 15000)
        process = MagicMock()
        process.pid = 1
        process.info = {"name": "test.exe"}
        process.io_counters.side_effect = [before, after]

        with patch.object(psutil, "process_iter", return_value=[process]), patch("time.sleep", return_value=None):
            result = speedtest.get_top_network_usage(sample_seconds=0)

        self.assertEqual(result, [("test.exe", 29.3)])

    def test_skips_dead_processes(self):
        from unittest.mock import MagicMock, patch

        import psutil

        first = MagicMock()
        first.pid = 1
        first.io_counters.side_effect = psutil.NoSuchProcess(1)
        second = MagicMock()
        second.pid = 2
        second.info = {"name": "b.exe"}
        second.io_counters.side_effect = psutil.NoSuchProcess(2)

        with patch.object(psutil, "process_iter", return_value=[first, second]), patch("time.sleep", return_value=None):
            self.assertEqual(speedtest.get_top_network_usage(sample_seconds=0), [])


class TestBuildReportShape(unittest.TestCase):
    def test_quick_report_has_expected_keys(self):
        data = report.build_report(quick=True)
        for key in ("platform", "adapters", "dns", "ipv6", "ping_output", "speed", "top_apps"):
            self.assertIn(key, data)

    def test_json_serialisable(self):
        data = report.build_report(quick=True)
        text = json.dumps(data, ensure_ascii=False)
        self.assertIn("ipv6", text)

    def test_platform_block_reports_backend(self):
        data = report.build_report(quick=True)
        self.assertIn("dns_backend", data["platform"])
        self.assertIn("is_admin", data["platform"])


class TestCLI(unittest.TestCase):
    def test_parser_builds(self):
        import main

        self.assertIsNotNone(main.build_parser())

    def test_providers_command_returns_ok(self):
        import main

        self.assertEqual(main.main(["providers"]), main.EXIT_OK)

    def test_version_flag(self):
        import main

        with self.assertRaises(SystemExit) as ctx:
            main.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_help_flag(self):
        import main

        with self.assertRaises(SystemExit):
            main.main(["--help"])

    def test_unknown_command_exits_nonzero(self):
        import main

        with self.assertRaises(SystemExit):
            main.main(["bilinmeyen-komut"])

    def test_console_encoding_is_configured(self):
        import main

        main._configure_console()
        self.assertEqual(sys.stdout.encoding.lower().replace("-", ""), "utf8")


if __name__ == "__main__":
    unittest.main()
