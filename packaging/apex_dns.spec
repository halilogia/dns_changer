# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Apex DNS Changer.

Build with::

    python -m PyInstaller packaging/apex_dns.spec
    pwsh -File packaging/build.ps1

Two executables are produced because they need different execution levels:

* ``ApexDNSChanger.exe``     windowed, ``requireAdministrator`` so the GUI can
                             write DNS settings (UAC prompt from the manifest,
                             so the process is elevated before any code runs).
* ``ApexDNSDiagnostics.exe`` console, ``asInvoker`` so the diagnostics report
                             never triggers an elevation prompt.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

try:
    _SPEC_FILE = SPEC  # noqa: F821 - injected by PyInstaller
except NameError:  # pragma: no cover - direct `python apex_dns.spec`
    raise SystemExit(
        "Bu dosya PyInstaller tarafindan calistirilmalidir:\n"
        "    python -m PyInstaller packaging/apex_dns.spec"
    )

PACKAGING = Path(_SPEC_FILE).resolve().parent
PROJECT = PACKAGING.parent
ICON = PACKAGING / "icon.ico"
MANIFEST = PACKAGING / "apex_dns.manifest"

HIDDEN = [
    "certifi",
    "h2",
    "httpx",
    "httpcore",
    "hpack",
    "hyperframe",
    "psutil",
    "requests",
    "urllib3",
    "charset_normalizer",
    "idna",
] + collect_submodules("core") + collect_submodules("diagnostics") + collect_submodules("i18n")

EXCLUDED = ["tkinter.test", "unittest", "pydoc_data", "doctest"]


def build(name, entry, *, console, uac_admin):
    analysis = Analysis(  # noqa: F821
        [str(PROJECT / entry)],
        pathex=[str(PROJECT)],
        binaries=[],
        datas=[(str(ICON), "packaging")],
        hiddenimports=HIDDEN,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=EXCLUDED,
        noarchive=False,
    )
    pyz = PYZ(analysis.pure)  # noqa: F821
    return EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(ICON),
        manifest=str(MANIFEST),
        uac_admin=uac_admin,
    )


gui_exe = build("ApexDNSChanger", "main.py", console=False, uac_admin=True)
diagnostics_exe = build("ApexDNSDiagnostics", "main.py", console=True, uac_admin=False)
