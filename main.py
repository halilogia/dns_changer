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

from core import elevation, resolver, system
from core.dns_service import DnsService
from core.providers import DEFAULT_PROVIDERS, doh_providers

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
        description="Apex DNS Changer - DNS yönetimi ve ağ teşhisi",
    )
    parser.add_argument("--version", action="version", version="apex-dns 2.0.0")
    sub = parser.add_subparsers(dest="command")

    diagnostics = sub.add_parser("diagnostics", help="konsol teşhis raporu")
    diagnostics.add_argument("--quick", action="store_true", help="yavaş ölçümleri atla")

    sub.add_parser("diagnostics-json", help="JSON teşhis raporu")

    ping = sub.add_parser("ping", help="ping ve paket kaybı ölçümü")
    ping.add_argument("host", nargs="?", default="8.8.8.8")
    ping.add_argument("-c", "--count", type=int, default=10)

    sub.add_parser("speed", help="bant genişliği ölçümü")
    sub.add_parser("doh", help="DoH ve IPv6 testi")
    sub.add_parser("adapters", help="ağ bağlantılarını listele")
    sub.add_parser("providers", help="DNS sağlayıcı listesini yazdır")

    gui = sub.add_parser("gui", help="grafik arayüzü başlat")
    gui.add_argument(
        "--no-elevation",
        action="store_true",
        help="UAC yeniden başlatmayı atla (yönetici olmadan çalıştırmak için)",
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
        print(f"\nÖzet: {summary}")
    return EXIT_OK


def _cmd_speed(_args) -> int:
    from diagnostics.speedtest import test_speed

    down, up = test_speed()
    print(f"İndirme: {down} Mbps")
    print(f"Yükleme: {up} Mbps")
    return EXIT_OK if down or up else EXIT_ERROR


def _cmd_doh(_args) -> int:
    print("--- DoH ---")
    reachable = 0
    for provider in doh_providers():
        result = resolver.measure_doh_latency(provider)
        if result.ok:
            reachable += 1
            print(f"  {provider.name}: {result.rtt_ms} ms  [{result.rcode}]")
        else:
            print(f"  {provider.name}: başarısız ({result.error or result.rcode})")
    ipv6 = resolver.probe_ipv6()
    print("\n--- IPv6 ---")
    print(f"  {ipv6.detail}")
    return EXIT_OK if reachable or ipv6.has_global_address else EXIT_ERROR


def _cmd_adapters(_args) -> int:
    service = DnsService()
    try:
        adapters = service.adapters(refresh=True)
    except Exception as exc:
        print(f"Bağlantılar okunamadı: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not adapters:
        print("Ağ bağlantısı bulunamadı.")
        return EXIT_ERROR
    print(f"Backend: {service.backend_name}  (yazma: {'var' if service.can_write else 'yok'})")
    for adapter in adapters:
        flags = []
        if adapter.dhcp_enabled:
            flags.append("DHCP")
        if adapter.is_virtual:
            flags.append("sanal")
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
        doh = f"  DoH: {provider.doh_url}" if provider.supports_doh else ""
        print(f"  {provider.name}: {addresses}{doh}")
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


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    command = args.command or "gui"
    if args.command is None:
        args.no_elevation = False
    try:
        return _COMMANDS[command](args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if "--debug" in (argv or sys.argv):
            raise
        print(f"Hata: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    first_arg = sys.argv[1:2][0] if sys.argv[1:2] else ""
    needs_powershell = first_arg in ("gui", "diagnostics", "adapters")
    if needs_powershell and system.is_windows() and not system.powershell_available():
        print("Uyarı: PowerShell bulunamadı, DNS işlemleri çalışmayabilir.", file=sys.stderr)
    raise SystemExit(main())
