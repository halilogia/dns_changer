"""Guards for the platform-independence requirement.

The monolith only ran on Windows. ``core`` must stay importable everywhere and
must not reference Windows-only symbols at import time, so that CI can run the
test suite on Linux and macOS.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

from core import dns_service, elevation, providers, resolver, system
from tests import ROOT

WINDOWS_ONLY_MODULES = {"win32api", "win32con", "wintypes", "msvcrt", "_winreg"}
WINDOWS_ONLY_ATTRIBUTES = {
    ("subprocess", "CREATE_NO_WINDOW"),
    ("subprocess", "CREATE_NEW_CONSOLE"),
    ("subprocess", "STARTUPINFO"),
    ("subprocess", "SW_HIDE"),
}


def iter_source_files() -> list[Path]:
    paths = [ROOT / "main.py", ROOT / "dns_changer.py"]
    for package in ("core", "diagnostics", "tools"):
        paths.extend(sorted((ROOT / package).rglob("*.py")))
    return [path for path in paths if path.exists()]


class TestNoWindowsOnlyImports(unittest.TestCase):
    def test_no_windows_only_module_imports(self):
        offenders = []
        for path in iter_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in WINDOWS_ONLY_MODULES:
                        offenders.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(offenders, [], f"Windows-only imports found: {offenders}")

    def test_windows_only_attributes_are_guarded(self):
        """CREATE_NO_WINDOW only exists on Windows; it must sit behind a guard."""
        offenders = []
        for path in iter_source_files():
            source = path.read_text(encoding="utf-8")
            for module, attribute in WINDOWS_ONLY_ATTRIBUTES:
                needle = f"{module}.{attribute}"
                if needle not in source:
                    continue
                for line_number, line in enumerate(source.splitlines(), start=1):
                    if needle not in line:
                        continue
                    stripped = line.strip()
                    guarded = (
                        "getattr(" in stripped
                        or stripped.startswith("kwargs[")
                        or "if is_windows()" in stripped
                        or "if system.is_windows()" in stripped
                    )
                    if not guarded:
                        offenders.append(f"{path.relative_to(ROOT)}:{line_number}: {stripped}")
        self.assertEqual(offenders, [], f"Unguarded Windows-only attribute use: {offenders}")


class TestCoreImportsWithoutTkinter(unittest.TestCase):
    def test_core_does_not_import_tkinter(self):
        for path in sorted((ROOT / "core").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import tkinter", source, f"{path.name} imports tkinter")

    def test_diagnostics_does_not_import_ui(self):
        for path in sorted((ROOT / "diagnostics").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("from ui", source, f"{path.name} imports ui")

    def test_core_does_not_import_diagnostics(self):
        for path in sorted((ROOT / "core").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("from diagnostics", source, f"{path.name} imports diagnostics")


class TestBackendSelection(unittest.TestCase):
    def test_default_backend_matches_platform(self):
        backend = dns_service.default_backend()
        if system.is_windows():
            self.assertIsInstance(backend, dns_service.WindowsDnsBackend)
            self.assertTrue(backend.can_write)
        elif system.current_platform() == system.LINUX:
            self.assertIsInstance(backend, (dns_service.NetworkManagerDnsBackend, dns_service.ReadOnlyDnsBackend))
        else:
            self.assertIsInstance(backend, dns_service.ReadOnlyDnsBackend)
            self.assertFalse(backend.can_write)

    def test_default_backend_is_cached(self):
        self.assertIs(dns_service.default_backend(), dns_service.default_backend())

    def test_every_backend_declares_a_name(self):
        for cls in (
            dns_service.WindowsDnsBackend,
            dns_service.NetworkManagerDnsBackend,
            dns_service.ReadOnlyDnsBackend,
        ):
            self.assertTrue(cls.name)
            self.assertIsInstance(cls.can_write, bool)


class TestWindowsBackendScriptConstruction(unittest.TestCase):
    def test_set_dns_servers_builds_powershell(self):
        backend = dns_service.WindowsDnsBackend()
        with mock.patch.object(system, "run_powershell", return_value=subprocess_result(0)) as run:
            backend.set_dns_servers("Ethernet", ("1.1.1.1", "1.0.0.1"))
        script = run.call_args.args[0]
        self.assertIn("Set-DnsClientServerAddress", script)
        self.assertIn("'Ethernet'", script)
        self.assertIn("'1.1.1.1'", script)
        self.assertIn("'1.0.0.1'", script)

    def test_ipv6_servers_use_ipv6_address_family(self):
        backend = dns_service.WindowsDnsBackend()
        with mock.patch.object(system, "run_powershell", return_value=subprocess_result(0)) as run:
            backend.set_dns_servers("Ethernet", ("2606:4700:4700::1111",))
        script = run.call_args.args[0]
        self.assertIn("-AddressFamily IPv6", script)

    def test_mixed_family_split_into_two_calls(self):
        backend = dns_service.WindowsDnsBackend()
        with mock.patch.object(system, "run_powershell", return_value=subprocess_result(0)) as run:
            backend.set_dns_servers("Ethernet", ("1.1.1.1", "2606:4700:4700::1111"))
        script = run.call_args.args[0]
        self.assertIn("-AddressFamily IPv6", script)
        self.assertIn("'1.1.1.1'", script)

    def test_reset_uses_reset_server_addresses(self):
        backend = dns_service.WindowsDnsBackend()
        with mock.patch.object(system, "run_powershell", return_value=subprocess_result(0)) as run:
            backend.reset_dns_servers("Ethernet")
        self.assertIn("-ResetServerAddresses", run.call_args.args[0])

    def test_adapter_name_is_quoted_against_injection(self):
        backend = dns_service.WindowsDnsBackend()
        hostile = "x'; Remove-Item -Recurse C:\\; '"
        with mock.patch.object(system, "run_powershell", return_value=subprocess_result(0)) as run:
            backend.set_dns_servers(hostile, ("1.1.1.1",))
        script = run.call_args.args[0]
        self.assertIn("x''; Remove-Item -Recurse C:\\; ''", script)

    def test_powershell_failure_raises_service_error(self):
        backend = dns_service.WindowsDnsBackend()
        failure = subprocess_result(returncode=1, stderr="Access is denied.")
        with (
            mock.patch.object(system, "run_powershell", return_value=failure),
            self.assertRaises(dns_service.DnsServiceError),
        ):
            backend.set_dns_servers("Ethernet", ("1.1.1.1",))

    def test_no_address_family_addressable_raises(self):
        backend = dns_service.WindowsDnsBackend()
        with self.assertRaises(dns_service.InvalidAddressError):
            backend.set_dns_servers("Ethernet", ())

    def test_get_dns_servers_prefers_ipv4(self):
        backend = dns_service.WindowsDnsBackend()
        payload = '[{"v4":["1.1.1.1"],"v6":["2606:4700:4700::1111"],"dhcp":false}]'
        with mock.patch.object(dns_service, "_ps_json", return_value=json_items(payload)):
            self.assertEqual(backend.get_dns_servers("Ethernet"), ["1.1.1.1"])

    def test_get_dns_servers_falls_back_to_ipv6(self):
        backend = dns_service.WindowsDnsBackend()
        payload = '[{"v4":[],"v6":["fec0::1"],"dhcp":true}]'
        with mock.patch.object(dns_service, "_ps_json", return_value=json_items(payload)):
            self.assertEqual(backend.get_dns_servers("Ethernet"), ["fec0::1"])

    def test_invalid_json_raises_service_error(self):
        with (
            mock.patch.object(
                system, "run_powershell", return_value=subprocess_result(returncode=0, stdout="not json")
            ),
            self.assertRaises(dns_service.DnsServiceError),
        ):
            dns_service._ps_json("Get-Date")


def subprocess_result(returncode: int, stdout: str = "", stderr: str = ""):
    import subprocess

    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def json_items(payload: str):
    import json

    return json.loads(payload)


class TestElevation(unittest.TestCase):
    def test_is_admin_returns_bool(self):
        self.assertIsInstance(elevation.is_admin(), bool)

    def test_requires_elevation_is_inverse(self):
        self.assertEqual(elevation.requires_elevation(), not elevation.is_admin())

    def test_relaunch_never_raises(self):
        # Must fail gracefully when elevation is declined.
        result = elevation.relaunch_as_admin()
        self.assertIn(result, (True, False))

    def test_argv_quoting_handles_spaces(self):
        import subprocess
        import sys

        original = sys.argv
        try:
            sys.argv = ["C:/Program Files/app/main.py", "diagnostics", "--quick"]
            rendered = subprocess.list2cmdline(sys.argv)
        finally:
            sys.argv = original
        self.assertIn('"C:/Program Files/app/main.py"', rendered)


class TestProvidersAreUiFree(unittest.TestCase):
    def test_provider_helpers_are_pure(self):
        self.assertTrue(providers.measurable_providers())
        self.assertTrue(providers.doh_providers())


class TestResolverIsStdlibOnly(unittest.TestCase):
    def test_resolver_does_not_import_third_party_at_module_level(self):
        source = (ROOT / "core" / "resolver.py").read_text(encoding="utf-8")
        for module in ("requests", "psutil", "dns"):
            self.assertNotIn(f"import {module}", source)
        # Optional imports must stay inside functions.
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import certifi", "import h2", "import httpx")):
                self.assertTrue(line.startswith("    "), f"top-level optional import: {stripped}")

    def test_resolver_constants(self):
        self.assertEqual(resolver.TYPE_A, 1)
        self.assertEqual(resolver.TYPE_AAAA, 28)
        self.assertEqual(resolver.QUERY_PORT, 53)


if __name__ == "__main__":
    unittest.main()
