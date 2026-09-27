"""Settings persistence."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import settings as store  # noqa: E402
from tests import ROOT  # noqa: F401


class TempDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APEX_DNS_CONFIG_DIR": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestPaths(TempDirMixin):
    def test_env_override_wins(self):
        self.assertEqual(store.settings_dir(), Path(self._tmp.name))

    def test_path_is_inside_dir(self):
        self.assertEqual(store.settings_path().parent, Path(self._tmp.name))
        self.assertEqual(store.settings_path().name, "settings.json")

    def test_describe_location_is_str(self):
        self.assertIsInstance(store.describe_location(), str)

    def test_app_dir_name(self):
        self.assertEqual(store.APP_DIR_NAME, "ApexDNSChanger")

    @unittest.skipIf(not store.system.is_windows(), "Windows path convention")
    def test_windows_default_uses_appdata(self):
        with (
            mock.patch.object(store.system, "is_windows", return_value=True),
            mock.patch.dict(os.environ, {"APEX_DNS_CONFIG_DIR": "", "APPDATA": r"C:\Users\test\AppData\Roaming"}),
        ):
            self.assertIn("Roaming", str(store.settings_dir()))

    @unittest.skipUnless(
        store.system.current_platform() == store.system.LINUX,
        "XDG_CONFIG_HOME is the Linux convention only",
    )
    def test_posix_default_uses_xdg(self):
        with mock.patch.dict(os.environ, {"APEX_DNS_CONFIG_DIR": "", "XDG_CONFIG_HOME": "/tmp/xdg"}):
            self.assertIn("xdg", str(store.settings_dir()))

    @unittest.skipUnless(
        store.system.current_platform() == store.system.MACOS,
        "macOS uses Application Support, not XDG",
    )
    def test_macos_default_uses_application_support(self):
        with mock.patch.dict(os.environ, {"APEX_DNS_CONFIG_DIR": "", "XDG_CONFIG_HOME": "/tmp/xdg"}):
            path = str(store.settings_dir())
        self.assertIn("Application Support", path)
        self.assertNotIn("xdg", path)


class TestRoundTrip(TempDirMixin):
    def test_defaults_when_missing(self):
        self.assertEqual(store.load_settings().locale, "")

    def test_save_then_load(self):
        original = store.Settings(
            locale="en",
            last_adapter="Ethernet",
            last_provider_id="cloudflare-dns",
            custom_primary="9.9.9.9",
            custom_secondary="149.112.112.112",
            check_updates=False,
            window_geometry="560x730+10+20",
        )
        self.assertTrue(store.save_settings(original))
        loaded = store.load_settings()
        self.assertEqual(loaded.locale, "en")
        self.assertEqual(loaded.last_adapter, "Ethernet")
        self.assertEqual(loaded.last_provider_id, "cloudflare-dns")
        self.assertEqual(loaded.custom_primary, "9.9.9.9")
        self.assertEqual(loaded.custom_secondary, "149.112.112.112")
        self.assertFalse(loaded.check_updates)
        self.assertEqual(loaded.window_geometry, "560x730+10+20")

    def test_file_is_valid_json(self):
        store.save_settings(store.Settings(locale="tr"))
        data = json.loads(store.settings_path().read_text(encoding="utf-8"))
        self.assertEqual(data["locale"], "tr")

    def test_save_creates_directory(self):
        nested = Path(self._tmp.name) / "a" / "b"
        with mock.patch.dict(os.environ, {"APEX_DNS_CONFIG_DIR": str(nested)}):
            self.assertTrue(store.save_settings(store.Settings()))
            self.assertTrue((nested / "settings.json").is_file())

    def test_no_temp_files_left_behind(self):
        store.save_settings(store.Settings())
        leftovers = [p.name for p in store.settings_path().parent.iterdir() if p.name != "settings.json"]
        self.assertEqual(leftovers, [])

    def test_save_failure_returns_false(self):
        with mock.patch.object(store.os, "replace", side_effect=OSError("nope")):
            self.assertFalse(store.save_settings(store.Settings()))


class TestCorruption(TempDirMixin):
    def test_invalid_json_falls_back(self):
        store.settings_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(store.load_settings().locale, "")

    def test_empty_file_falls_back(self):
        store.settings_path().write_text("", encoding="utf-8")
        self.assertEqual(store.load_settings().last_adapter, "")

    def test_json_array_falls_back(self):
        store.settings_path().write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(store.load_settings().locale, "")

    def test_unknown_keys_are_ignored(self):
        store.settings_path().write_text(json.dumps({"locale": "en", "bogus": 1}), encoding="utf-8")
        self.assertEqual(store.load_settings().locale, "en")

    def test_null_values_are_ignored(self):
        store.settings_path().write_text(json.dumps({"locale": None, "last_adapter": "Eth"}), encoding="utf-8")
        settings = store.load_settings()
        self.assertEqual(settings.locale, "")
        self.assertEqual(settings.last_adapter, "Eth")

    def test_wrong_types_are_coerced_or_dropped(self):
        store.settings_path().write_text(
            json.dumps({"locale": 5, "check_updates": "yes", "last_adapter": 12}), encoding="utf-8"
        )
        settings = store.load_settings()
        self.assertIsInstance(settings.check_updates, bool)
        self.assertTrue(settings.check_updates)

    def test_unreadable_file_falls_back(self):
        with mock.patch.object(Path, "read_text", side_effect=OSError("denied")):
            self.assertEqual(store.load_settings().locale, "")


class TestInstallerSeed(TempDirMixin):
    """The installer's opt-in seeds the default, but never overrides a save."""

    def test_seed_true_when_unset(self):
        with mock.patch.object(store, "_installer_wants_updates", return_value=None):
            self.assertTrue(store.defaults().check_updates)

    def test_seed_false_is_honoured(self):
        with mock.patch.object(store, "_installer_wants_updates", return_value=False):
            self.assertFalse(store.defaults().check_updates)

    def test_seed_true_is_honoured(self):
        with mock.patch.object(store, "_installer_wants_updates", return_value=True):
            self.assertTrue(store.defaults().check_updates)

    def test_missing_file_uses_seed(self):
        with mock.patch.object(store, "_installer_wants_updates", return_value=False):
            self.assertFalse(store.load_settings().check_updates)

    def test_saved_value_beats_seed(self):
        store.save_settings(store.Settings(check_updates=True))
        with mock.patch.object(store, "_installer_wants_updates", return_value=False):
            self.assertTrue(store.load_settings().check_updates)

    def test_saved_opt_out_is_preserved(self):
        store.save_settings(store.Settings(check_updates=False))
        with mock.patch.object(store, "_installer_wants_updates", return_value=True):
            self.assertFalse(store.load_settings().check_updates)

    def test_corrupt_file_falls_back_to_seed(self):
        store.settings_path().write_text("{broken", encoding="utf-8")
        with mock.patch.object(store, "_installer_wants_updates", return_value=False):
            self.assertFalse(store.load_settings().check_updates)

    def test_installer_read_returns_none_off_windows(self):
        if store.system.is_windows():
            self.skipTest("windows only")
        self.assertIsNone(store._installer_wants_updates())


if __name__ == "__main__":
    unittest.main()
