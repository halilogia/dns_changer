"""Localization layer and catalog integrity."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from core import system
from i18n import (
    DEFAULT_LOCALE,
    available_locales,
    catalog,
    detect_locale,
    get_locale,
    locale_name,
    normalize,
    set_locale,
    t,
    translate,
)
from tests import ROOT  # noqa: F401

ALL_KEYS = sorted(set(catalog.TRANSLATIONS[DEFAULT_LOCALE]) | set(catalog.TRANSLATIONS["en"]))


class TestCatalogIntegrity(unittest.TestCase):
    def tearDown(self):
        set_locale(DEFAULT_LOCALE)

    def test_every_locale_is_registered(self):
        for code in catalog.TRANSLATIONS:
            self.assertIn(code, catalog.LOCALE_NAMES)

    def test_locale_names_are_distinct(self):
        names = list(catalog.LOCALE_NAMES.values())
        self.assertEqual(len(names), len(set(names)))

    def test_key_sets_match_across_locales(self):
        for code, table in catalog.TRANSLATIONS.items():
            with self.subTest(locale=code):
                self.assertEqual(set(table), set(catalog.TRANSLATIONS[DEFAULT_LOCALE]))

    def test_no_empty_translations(self):
        for code, table in catalog.TRANSLATIONS.items():
            for key, value in table.items():
                with self.subTest(locale=code, key=key):
                    self.assertTrue(value.strip(), f"{code}:{key} is empty")

    def test_no_translation_equals_its_key(self):
        for code, table in catalog.TRANSLATIONS.items():
            for key, value in table.items():
                with self.subTest(locale=code, key=key):
                    self.assertNotEqual(value, key, f"{code}:{key} was never translated")

    def test_placeholders_are_consistent(self):
        """A translation may not drop or invent a {placeholder}."""
        import re

        pattern = re.compile(r"\{(\w+)\}")
        for key in ALL_KEYS:
            expected = set(pattern.findall(catalog.TRANSLATIONS[DEFAULT_LOCALE][key]))
            for code, table in catalog.TRANSLATIONS.items():
                with self.subTest(locale=code, key=key):
                    self.assertEqual(set(pattern.findall(table[key])), expected, f"{code}:{key}")

    def test_tr_is_the_default_locale(self):
        self.assertIn(DEFAULT_LOCALE, catalog.TRANSLATIONS)

    def test_available_locales_matches_catalog(self):
        self.assertEqual(set(available_locales()), set(catalog.TRANSLATIONS))


class TestNormalize(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(normalize("en"), "en")
        self.assertEqual(normalize("tr"), "tr")

    def test_region_variant(self):
        self.assertEqual(normalize("en-US"), "en")
        self.assertEqual(normalize("tr_TR"), "tr")

    def test_case_insensitive(self):
        self.assertEqual(normalize("EN"), "en")

    def test_unknown_falls_back(self):
        self.assertEqual(normalize("de"), DEFAULT_LOCALE)
        self.assertEqual(normalize(""), DEFAULT_LOCALE)

    def test_underscore_and_dash_equivalent(self):
        self.assertEqual(normalize("en_US"), normalize("en-US"))


class TestTranslate(unittest.TestCase):
    def tearDown(self):
        set_locale(DEFAULT_LOCALE)

    def test_uses_active_locale(self):
        set_locale("en")
        self.assertEqual(t("app.brand"), catalog.TRANSLATIONS["en"]["app.brand"])
        set_locale("tr")
        self.assertEqual(t("app.brand"), catalog.TRANSLATIONS["tr"]["app.brand"])

    def test_get_locale_reflects_change(self):
        set_locale("en")
        self.assertEqual(get_locale(), "en")

    def test_unknown_key_returns_key(self):
        self.assertEqual(t("totally.missing.key"), "totally.missing.key")

    def test_placeholders_are_filled(self):
        set_locale("en")
        self.assertIn("Cloudflare", t("status.fastest", name="Cloudflare", latency=7))

    def test_missing_placeholder_is_survivable(self):
        result = t("status.fastest", name="X")
        self.assertIn("{latency}", result)

    def test_explicit_locale_overrides_active(self):
        set_locale("tr")
        self.assertEqual(translate("app.brand", "en"), catalog.TRANSLATIONS["en"]["app.brand"])

    def test_locale_switch_takes_effect_immediately(self):
        before = t("button.apply")
        set_locale("en")
        self.assertNotEqual(before, t("button.apply"))

    def test_locale_name(self):
        self.assertEqual(locale_name("tr"), "Türkçe")
        self.assertEqual(locale_name("zz"), "zz")


class TestDetect(unittest.TestCase):
    LOCALE_VARS = ("APEX_DNS_LOCALE", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")

    def _detect_with(self, **values):
        # Every locale variable must be overridden: LC_ALL outranks LANG, so a
        # stale value in the ambient environment would win.
        environment = dict.fromkeys(self.LOCALE_VARS, "")
        environment.update(values)
        with mock.patch.dict(os.environ, environment):
            return detect_locale()

    def test_explicit_override_wins(self):
        self.assertEqual(self._detect_with(APEX_DNS_LOCALE="en"), "en")

    def test_lang_variable(self):
        self.assertEqual(self._detect_with(LANG="en_US.UTF-8"), "en")

    def test_lc_all_outranks_lang(self):
        self.assertEqual(self._detect_with(LC_ALL="en_US.UTF-8", LANG="tr_TR.UTF-8"), "en")

    def test_stripped_modifier(self):
        self.assertEqual(self._detect_with(LANG="tr_TR.UTF-8"), "tr")

    def test_colon_separated_list(self):
        self.assertEqual(self._detect_with(LANG="tr_TR:en_US"), "tr")

    def test_unknown_locale_falls_back(self):
        self.assertEqual(self._detect_with(APEX_DNS_LOCALE="de_DE"), DEFAULT_LOCALE)

    def test_empty_environment_falls_back(self):
        # With no locale variables there is nothing to read, so the result is
        # the app default. On Windows the OS language is consulted next, which
        # is a separate path.
        with mock.patch("core.system.is_windows", return_value=False):
            self.assertEqual(self._detect_with(), DEFAULT_LOCALE)

    def test_windows_consults_the_system_language(self):
        if not system.is_windows():
            self.skipTest("windows only")
        # A runner or desktop with an English UI language yields English; the
        # important part is that the result is always a supported locale.
        self.assertIn(self._detect_with(), available_locales())


class TestUserVisibleStringsAreTranslated(unittest.TestCase):
    """Guards against a hardcoded Turkish string creeping back into the UI."""

    SOURCES = [
        ROOT / "ui" / "app.py",
        ROOT / "ui" / "widgets.py",
        ROOT / "ui" / "details.py",
        ROOT / "diagnostics" / "report.py",
        ROOT / "main.py",
    ]

    # Status values and adapter names legitimately come from the OS.
    ALLOWED = {"bağlı", "bagli", "etkin", "aktif", "sanal", "DHCP", "Değer"}

    def test_no_hardcoded_turkish_literals(self):
        import ast

        turkish = set("ÇĞİÖŞÜçğıöşü")
        offenders = []
        for path in self.SOURCES:
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                text = node.value
                if not (turkish & set(text)):
                    continue
                if text in self.ALLOWED:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {text[:60]!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
