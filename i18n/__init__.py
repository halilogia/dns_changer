"""Minimal localization layer.

``t("key", name="x")`` looks the key up in the active locale and falls back to
the key itself, so a missing translation degrades to a visible marker rather
than an exception.
"""

from __future__ import annotations

import os
from functools import cache

from i18n.catalog import DEFAULT_LOCALE, FALLBACK_LOCALE, LOCALE_NAMES, TRANSLATIONS

SUPPORTED = tuple(sorted(TRANSLATIONS))
_current = DEFAULT_LOCALE


def available_locales() -> tuple[str, ...]:
    return SUPPORTED


def locale_name(code: str) -> str:
    return LOCALE_NAMES.get(code, code)


def normalize(code: str) -> str:
    """Map a locale tag onto a supported one, or return the default."""
    if not code:
        return DEFAULT_LOCALE
    tag = code.replace("_", "-").strip().lower()
    if tag in TRANSLATIONS:
        return tag
    primary = tag.split("-")[0]
    if primary in TRANSLATIONS:
        return primary
    return DEFAULT_LOCALE


def detect_locale() -> str:
    """Best guess at the user's language from the environment."""
    for variable in ("APEX_DNS_LOCALE", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            return normalize(value.split(":")[0])
    from core import system

    if system.is_windows():
        try:
            import ctypes

            windll = ctypes.windll
            windll.kernel32.GetUserDefaultUILanguage.restype = ctypes.c_ulong
            language_id = int(windll.kernel32.GetUserDefaultUILanguage())
        except Exception:
            return DEFAULT_LOCALE
        return normalize({0x041F: "tr"}.get(language_id, ""))
    return DEFAULT_LOCALE


def get_locale() -> str:
    return _current


def set_locale(code: str) -> str:
    """Activate a locale. Returns the locale actually in effect."""
    global _current
    _current = normalize(code)
    return _current


@cache
def _lookup(locale: str, key: str) -> str:
    table = TRANSLATIONS.get(locale, {})
    if key in table:
        return table[key]
    fallback = TRANSLATIONS.get(FALLBACK_LOCALE, {})
    if key in fallback:
        return fallback[key]
    return key


def translate(key: str, locale: str | None = None, /, **values) -> str:
    """Translate ``key``; unknown keys return the key itself."""
    text = _lookup(locale or _current, key)
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def t(key: str, /, **values) -> str:
    return translate(key, None, **values)


__all__ = [
    "DEFAULT_LOCALE",
    "LOCALE_NAMES",
    "available_locales",
    "detect_locale",
    "get_locale",
    "locale_name",
    "normalize",
    "set_locale",
    "t",
    "translate",
]
