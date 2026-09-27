"""Platform helper behaviour that must hold on every operating system."""

from __future__ import annotations

import subprocess
import sys
import unittest

from core import system
from tests import ROOT  # noqa: F401


class TestPlatformDetection(unittest.TestCase):
    def test_current_platform_is_known(self):
        self.assertIn(
            system.current_platform(),
            {system.WINDOWS, system.MACOS, system.LINUX, system.BSD, system.UNKNOWN},
        )

    def test_is_windows_is_consistent(self):
        self.assertEqual(system.is_windows(), system.current_platform() == system.WINDOWS)

    def test_cached(self):
        self.assertIs(system.current_platform(), system.current_platform())


class TestRunHidden(unittest.TestCase):
    def test_captures_stdout(self):
        completed = system.run_hidden(
            [sys.executable, "-c", "print('merhaba')"],
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("merhaba", completed.stdout)

    def test_nonzero_exit_is_returned_not_raised(self):
        completed = system.run_hidden([sys.executable, "-c", "raise SystemExit(3)"], timeout=30)
        self.assertEqual(completed.returncode, 3)

    def test_creationflags_only_on_windows(self):
        # The old code referenced subprocess.CREATE_NO_WINDOW unconditionally,
        # which raised AttributeError on Linux and macOS.
        completed = system.run_hidden(
            [sys.executable, "-c", "import sys; print('ok')"],
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0)

    def test_missing_executable_raises_oserror(self):
        with self.assertRaises((OSError, FileNotFoundError)):
            system.run_hidden(["apex-does-not-exist-binary-xyz"], timeout=10)

    def test_timeout_is_enforced(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            system.run_hidden([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3)


class TestPingParsing(unittest.TestCase):
    def test_windows_english(self):
        output = "Pinging 8.8.8.8 with 32 bytes of data:\nReply from 8.8.8.8: bytes=32 time=24ms TTL=115\n"
        self.assertEqual(system.parse_ping_rtt(output), 24.0)

    def test_windows_turkish(self):
        output = "8.8.8.8 yanıtı: bayt=32 süre=17ms TTL=115\n"
        self.assertEqual(system.parse_ping_rtt(output), 17.0)

    def test_windows_sub_millisecond(self):
        self.assertEqual(system.parse_ping_rtt("time<1ms"), 1.0)

    def test_posix_english(self):
        output = "--- ping statistics ---\n64 bytes from 8.8.8.8: icmp_seq=1 ttl=115 time=12.3 ms\n"
        self.assertEqual(system.parse_ping_rtt(output), 12.3)

    def test_posix_average_fallback(self):
        output = "rtt min/avg/max/mdev = 10.1/15.2/20.3/1.2 ms\n"
        self.assertEqual(system.parse_ping_rtt(output), 15.2)

    def test_comma_decimal_separator(self):
        self.assertEqual(system.parse_ping_rtt("time=12,5 ms"), 12.5)

    def test_empty_output(self):
        self.assertIsNone(system.parse_ping_rtt(""))
        self.assertIsNone(system.parse_ping_rtt("no numbers here"))

    def test_loss_english(self):
        self.assertEqual(system.parse_ping_loss("10% packet loss"), 10)
        self.assertEqual(system.parse_ping_loss("0% loss"), 0)

    def test_loss_turkish(self):
        self.assertEqual(system.parse_ping_loss("%10 veri kaybi"), 10)

    def test_loss_from_lost_counter(self):
        # A percentage is present, so it wins over the raw counter.
        self.assertEqual(system.parse_ping_loss("Packets: Sent = 10, Lost = 1 (10% loss)"), 10)

    def test_loss_counter_only(self):
        self.assertEqual(system.parse_ping_loss("Packets: Sent = 10, Lost = 3"), 3)

    def test_loss_absent(self):
        self.assertIsNone(system.parse_ping_loss(""))


class TestPingCommand(unittest.TestCase):
    def test_count_appears_in_command(self):
        for _ in range(1):
            self.assertIn("4", system.ping_command("1.1.1.1", count=4, timeout_ms=1000))

    def test_timeout_is_included(self):
        command = " ".join(system.ping_command("1.1.1.1", count=1, timeout_ms=750))
        self.assertIn("750", command)
        self.assertIn("1.1.1.1", command)


class TestPowerShellQuoting(unittest.TestCase):
    def test_plain_value(self):
        self.assertEqual(system.quote_powershell_literal("Ethernet"), "'Ethernet'")

    def test_embedded_single_quote_is_doubled(self):
        self.assertEqual(system.quote_powershell_literal("Bob's Adapter"), "'Bob''s Adapter'")

    def test_injection_attempt_is_neutralised(self):
        hostile = "x'; Remove-Item -Recurse C:\\; '"
        quoted = system.quote_powershell_literal(hostile)
        self.assertTrue(quoted.startswith("'") and quoted.endswith("'"))
        # Undoing PowerShell's '' escape must return exactly the original value,
        # which proves it stays a single string literal.
        self.assertEqual(quoted[1:-1].replace("''", "'"), hostile)

    def test_turkish_characters_preserved(self):
        self.assertIn("Ağ", system.quote_powershell_literal("Ağ"))


class TestResourcePaths(unittest.TestCase):
    def test_resource_path_is_absolute(self):
        self.assertTrue(system.resource_path("icon.ico").is_absolute())

    def test_app_dir_points_at_project(self):
        self.assertEqual(system.app_dir(), ROOT)


if __name__ == "__main__":
    unittest.main()
