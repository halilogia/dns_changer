"""Import-surface tests.

A wrong import inside a UI module is invisible to unit tests that never touch
that module, so every public module is imported here and the CLI is exercised
end to end in a subprocess.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import unittest

from tests import ROOT

MODULES = [
    "core",
    "core.system",
    "core.providers",
    "core.resolver",
    "core.dns_service",
    "core.elevation",
    "diagnostics",
    "diagnostics.report",
    "diagnostics.speedtest",
    "diagnostics.netusage",
    "ui",
    "ui.theme",
    "ui.widgets",
    "ui.app",
    "main",
]

CLI_MODULES = ["ui.theme", "ui.widgets", "ui.app"]


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "main.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(ROOT),
    )


class TestModuleImports(unittest.TestCase):
    def test_every_module_imports(self):
        for name in MODULES:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))

    def test_importing_core_does_not_pull_in_tkinter(self):
        code = "import sys; import core.resolver, core.dns_service; assert 'tkinter' not in sys.modules"
        completed = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(ROOT)
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_importing_diagnostics_does_not_pull_in_ui(self):
        code = "import sys; import diagnostics.report; assert 'ui' not in sys.modules"
        completed = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(ROOT)
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_core_imports_on_a_clean_interpreter(self):
        for name in ("core.system", "core.providers", "core.dns_service", "core.resolver"):
            with self.subTest(module=name):
                completed = subprocess.run(
                    [sys.executable, "-c", f"import {name}"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(ROOT),
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)


class TestLegacyShim(unittest.TestCase):
    def test_dns_changer_module_still_works(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "dns_changer.py"), "providers"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            cwd=str(ROOT),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Cloudflare", completed.stdout)


class TestCommandLine(unittest.TestCase):
    def test_providers(self):
        completed = run_cli("providers")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("1.1.1.1", completed.stdout)
        self.assertIn("DoH", completed.stdout)

    def test_providers_output_is_utf8_clean(self):
        completed = run_cli("providers")
        self.assertIn("\u00d6zel DNS", completed.stdout)

    def test_version(self):
        completed = run_cli("--version")
        self.assertEqual(completed.returncode, 0)

    def test_adapters(self):
        completed = run_cli("adapters")
        self.assertIn(completed.returncode, (0, 1))
        self.assertIn("Backend:", completed.stdout)

    def test_help_lists_commands(self):
        completed = run_cli("--help")
        for command in ("diagnostics", "doh", "adapters", "providers", "ping"):
            self.assertIn(command, completed.stdout)

    def test_diagnostics_json_is_parseable(self):
        completed = run_cli("diagnostics-json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        import json

        payload = json.loads(completed.stdout)
        self.assertIn("dns", payload)
        self.assertIn("ipv6", payload)
        self.assertIn("platform", payload)


if __name__ == "__main__":
    unittest.main()
