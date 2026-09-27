"""Command line entry point for Apex DNS Changer.

python main.py                      launch the GUI (elevates when needed)
python main.py diagnostics          full console report
python main.py diagnostics --quick  skip bandwidth and process sampling
python main.py diagnostics-json     machine-readable report
python main.py adapters              list detected network adapters
python main.py ping 1.1.1.1         ping/loss probe
python main.py speed                 bandwidth only
python main.py doh                   DoH + IPv6 checks
python main.py providers             print the provider catalog
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from core import elevation, resolver, system, updater
from core import settings as settings_store
from core.dns_service import DnsService
from core.providers import DEFAULT_PROVIDERS, doh_providers
from i18n import detect_locale, set_locale, t

APP_VERSION = "2.0.0"

EXIT_OK = 0
EXIT_ERROR = 1


def _configure_console() -> None:
    """Make Turkish output survive the default Windows console code page."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apex-dns",
        description=t("cli.description"),
    )
    parser.add_argument("--version", action="version", version=f"apex-dns {APP_VERSION}")
    parser.add_argument("--locale", help=t("cli.locale"))
    parser.add_argument("--check-update", action="store_true", help=t("cli.check_update"))
    parser.add_argument("--no-update-check", action="store_true", help=t("cli.no_update_check"))
    sub = parser.add_subparsers(dest="command")

    diagnostics = sub.add_parser("diagnostics", help=t("cli.report_description"))
    diagnostics.add_argument("--quick", action="store_true", help=t("cli.quick"))

    diagnostics_json = sub.add_parser("diagnostics-json", help=t("cli.report_description"))
    diagnostics_json.add_argument("--quick", action="store_true", help=t("cli.quick"))

    ping = sub.add_parser("ping", help=t("cli.ping"))
    ping.add_argument("host", nargs="?", default="8.8.8.8")
    ping.add_argument("-c", "--count", type=int, default=10, help=t("cli.count"))

    sub.add_parser("speed", help=t("cli.speed_test"))
    sub.add_parser("doh", help=t("cli.dohtest"))
    sub.add_parser("adapters", help=t("cli.adapters"))
    sub.add_parser("providers", help=t("cli.providers"))

    gui = sub.add_parser("gui", help=t("cli.gui"))
    gui.add_argument(
        "--no-elevation",
        action="store_true",
        help=t("cli.no_elevation"),
    )
    return parser


def _cmd_diagnostics(args) -> int:
    from diagnostics.report import run_diagnostics

    run_diagnostics(quick=getattr(args, "quick", False))
    return EXIT_OK


def _cmd_diagnostics_json(args) -> int:
    from diagnostics.report import run_diagnostics_json

    print(json.dumps(run_diagnostics_json(quick=getattr(args, "quick", False)), ensure_ascii=False, indent=2))
    return EXIT_OK


def _cmd_ping(args) -> int:
    from diagnostics.report import summarize_loss
    from diagnostics.speedtest import test_latency_and_loss

    output = test_latency_and_loss(args.host, args.count)
    print(output)
    summary = summarize_loss(output)
    if summary:
        print("")
    print(t("cli.summary", value=summary))
    return EXIT_OK


def _cmd_speed(_args) -> int:
    from diagnostics.speedtest import test_speed

    down, up = test_speed()
    print(t("report.download_short", value=down))
    print(t("report.upload_short", value=up))
    return EXIT_OK if down or up else EXIT_ERROR


def _cmd_doh(_args) -> int:
    print(f"--- {t('report.doh_section')} ---")
    reachable = 0
    for provider in doh_providers():
        result = resolver.measure_doh_latency(provider)
        if result.ok:
            reachable += 1
            print(f"  {provider.label}: {result.rtt_ms} ms  [{result.rcode}]")
        else:
            print(f"  {provider.label}: {t('report.doh_failed', reason=result.error or result.rcode)}")
    ipv6 = resolver.probe_ipv6()
    print(f"\n--- {t('report.ipv6_section')} ---")
    print(f"  {ipv6.detail}")
    return EXIT_OK if reachable or ipv6.has_global_address else EXIT_ERROR


def _cmd_adapters(_args) -> int:
    service = DnsService()
    try:
        adapters = service.adapters(refresh=True)
    except Exception as exc:
        print(t("cli.adapters_unreadable", reason=exc), file=sys.stderr)
        return EXIT_ERROR
    if not adapters:
        print(t("cli.no_adapter_found"))
        return EXIT_ERROR
    write_label = t("report.yes") if service.can_write else t("report.no")
    print(t("report.backend", name=service.backend_name, write=write_label))
    for adapter in adapters:
        flags = []
        if adapter.dhcp_enabled:
            flags.append(t("report.dhcp"))
        if adapter.is_virtual:
            flags.append(t("report.virtual"))
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {adapter.name}  ({adapter.status}){suffix}")
        try:
            servers = service.dns_servers(adapter.name, refresh=True)
        except Exception:
            servers = []
        if servers:
            print(f"      DNS: {', '.join(servers)}")
    return EXIT_OK


def _cmd_providers(_args) -> int:
    for provider in DEFAULT_PROVIDERS:
        addresses = provider.display_servers()
        name = provider.label
        doh = f"  DoH: {provider.doh_url}" if provider.supports_doh else ""
        print(f"  {name}: {addresses}{doh}")
    return EXIT_OK


def _cmd_gui(args) -> int:
    if not args.no_elevation and elevation.requires_elevation():
        elevation.ensure_admin_or_exit()
    from ui.app import launch

    app = launch()
    app.root.mainloop()
    return EXIT_OK


_COMMANDS = {
    "gui": _cmd_gui,
    "diagnostics": _cmd_diagnostics,
    "diagnostics-json": _cmd_diagnostics_json,
    "ping": _cmd_ping,
    "speed": _cmd_speed,
    "doh": _cmd_doh,
    "adapters": _cmd_adapters,
    "providers": _cmd_providers,
}


def _apply_locale(requested: str | None) -> str:
    """Settings win, then the flag, then the environment."""
    if requested:
        return set_locale(requested)
    stored = settings_store.load_settings().locale
    return set_locale(stored or detect_locale())


def _default_command() -> str:
    """The diagnostics build must not fall through to the GUI.

    Both executables are built from this entry point, so the console build
    would otherwise open a window instead of printing a report.
    """
    if system.is_frozen() and Path(sys.executable).stem.lower().startswith("apexdnsdiagnostics"):
        return "diagnostics"
    return "gui"


def _cmd_check_update(_args) -> int:
    info = updater.check_for_update(APP_VERSION)
    if info.error:
        print(t("status.update_failed", error=info.error), file=sys.stderr)
        return EXIT_ERROR
    if not info.available:
        print(t("status.update_none", version=info.current))
        return EXIT_OK
    print(t("status.update_available", version=info.latest))
    if info.url:
        print(info.url)
    return EXIT_OK


def _prescan_locale(argv: list[str]) -> str:
    """Find --locale before the parser exists, so --help is localized too."""
    for index, token in enumerate(argv):
        if token == "--locale" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--locale="):
            return token.split("=", 1)[1]
    return ""


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    arguments = list(argv) if argv is not None else sys.argv[1:]
    settings = settings_store.load_settings()

    # Resolve the locale before building the parser, otherwise help text and
    # subcommand descriptions are rendered in the default language.
    _apply_locale(_prescan_locale(arguments) or settings.locale or None)

    parser = build_parser()
    args = parser.parse_args(arguments)
    if getattr(args, "locale", None):
        _apply_locale(args.locale)

    if getattr(args, "no_update_check", False):
        settings.check_updates = False
        settings_store.save_settings(settings)

    if getattr(args, "check_update", False):
        return _cmd_check_update(args)

    command = args.command or _default_command()
    if args.command is None:
        args.no_elevation = command != "gui"
    try:
        return _COMMANDS[command](args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if "--debug" in arguments:
            raise
        print(t("cli.error", error=exc), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    first_arg = sys.argv[1:2][0] if sys.argv[1:2] else ""
    needs_powershell = first_arg in ("gui", "diagnostics", "adapters")
    if needs_powershell and system.is_windows() and not system.powershell_available():
        print(t("report.no_powershell"), file=sys.stderr)
    raise SystemExit(main())
