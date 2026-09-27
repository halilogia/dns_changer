"""Persistent user settings.

Stored as JSON under the per-user application data directory. Reads never
raise: a missing, unreadable or corrupt file falls back to defaults so a bad
write can never lock the user out of the app.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from core import system

APP_DIR_NAME = "ApexDNSChanger"
SETTINGS_FILE = "settings.json"
REGISTRY_KEY = r"Software\Apex DNS Changer"
REGISTRY_VALUE = "CheckForUpdates"


def settings_dir() -> Path:
    """Per-user config directory, following each platform's convention."""
    override = os.environ.get("APEX_DNS_CONFIG_DIR")
    if override:
        return Path(override)
    if system.is_windows():
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif system.current_platform() == system.MACOS:
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME


def settings_path() -> Path:
    return settings_dir() / SETTINGS_FILE


def _installer_wants_updates() -> bool | None:
    """Seed the update preference from the value the installer writes.

    The installer stores the choice in ``HKCU\\Software\\Apex DNS Changer`` so
    the opt-in survives before the app has ever written its settings file.
    """
    if not system.is_windows():
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, REGISTRY_VALUE)
    except (OSError, ImportError, ValueError):
        return None
    return bool(value)


@dataclass
class Settings:
    locale: str = ""
    last_adapter: str = ""
    last_provider_id: str = ""
    custom_primary: str = ""
    custom_secondary: str = ""
    check_updates: bool = True
    window_geometry: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce(raw: dict) -> Settings:
    """Build settings from untrusted JSON, ignoring wrong-typed keys."""
    known = {f.name: f for f in fields(Settings)}
    clean: dict = {}
    for key, value in raw.items():
        spec = known.get(key)
        if spec is None or value is None:
            continue
        expected = spec.type
        try:
            if expected in ("bool", bool):
                clean[key] = bool(value)
            elif expected in ("int", int):
                clean[key] = int(value)
            elif expected in ("str", str):
                clean[key] = value if isinstance(value, str) else str(value)
            else:
                clean[key] = value
        except (TypeError, ValueError):
            continue
    return Settings(**clean)


def defaults() -> Settings:
    """Fresh settings, seeded from the installer's opt-in when present.

    Only used before the user has ever saved a settings file; once they have,
    their stored value wins so a later reinstall cannot override it.
    """
    seed = _installer_wants_updates()
    return Settings(check_updates=True if seed is None else seed)


def load_settings() -> Settings:
    path = settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults()
    if not isinstance(raw, dict):
        return defaults()
    return _coerce(raw)


def save_settings(settings: Settings) -> bool:
    """Write settings atomically. Returns False if the write failed."""
    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".settings-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(settings.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise
    except (OSError, TypeError, ValueError):
        return False
    return True


def describe_location() -> str:
    return str(settings_path())


__all__ = [
    "APP_DIR_NAME",
    "Settings",
    "defaults",
    "describe_location",
    "load_settings",
    "save_settings",
    "settings_dir",
    "settings_path",
]
