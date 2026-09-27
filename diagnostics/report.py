"""Network diagnostics report (console and JSON) built on the core layer."""

from __future__ import annotations

import os
import platform
import sys

from core import elevation, resolver, system
from core.dns_service import DnsService
from core.providers import measurable_providers
from diagnostics.netusage import get_top_network_usage
from diagnostics.speedtest import test_latency_and_loss, test_speed

RULE = "=" * 52


def summarize_loss(ping_output: str) -> str | None:
    """Human-readable packet-loss summary from localized ping output."""
    if not ping_output:
        return None
    lines = [line for line in ping_output.splitlines() if line.strip()]
    tail = lines[-1].strip() if lines else ""
    loss = system.parse_ping_loss(ping_output)
    if loss is None:
        return tail or None
    return f"{loss}% kayıp — {tail}".strip(" —")


def collect_dns_results(timeout: float = 1.2) -> dict[str, float | None]:
    results: dict[str, float | None] = {}
    for provider in measurable_providers():
        results[provider.name] = resolver.measure_dns_latency(provider.primary, timeout=timeout)
    return results


def collect_doh_results() -> dict[str, dict]:
    from core.providers import doh_providers

    payload: dict[str, dict] = {}
    for provider in doh_providers():
        result = resolver.measure_doh_latency(provider)
        payload[provider.name] = {
            "endpoint": result.endpoint,
            "ok": result.ok,
            "rtt_ms": result.rtt_ms,
            "rcode": result.rcode,
            "error": result.error,
        }
    return payload


def build_report(quick: bool = False) -> dict:
    """Run every probe once and return a machine-readable snapshot."""
    service = DnsService()
    adapters: list[dict] = []
    dns_error = ""
    try:
        for adapter in service.adapters(refresh=True):
            adapters.append(
                {
                    "name": adapter.name,
                    "status": adapter.status,
                    "description": adapter.description,
                    "is_virtual": adapter.is_virtual,
                    "dhcp_enabled": adapter.dhcp_enabled,
                    "ipv4": list(adapter.ipv4),
                    "ipv6": list(adapter.ipv6),
                }
            )
    except Exception as exc:
        dns_error = str(exc)

    ping_output = test_latency_and_loss("8.8.8.8", 4 if quick else 10)
    down_mbps, up_mbps = (0.0, 0.0) if quick else test_speed(timeout=8.0 if quick else 20.0)
    top_apps = [] if quick else get_top_network_usage(sample_seconds=1)
    ipv6 = resolver.probe_ipv6()
    public_ip = None if quick else resolver.ipv4_public_address()

    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": sys.version.split()[0],
            "frozen": system.is_frozen(),
            "is_admin": elevation.is_admin(),
            "dns_backend": service.backend_name,
            "public_ipv4": public_ip,
        },
        "adapters": adapters,
        "adapters_error": dns_error,
        "dns": collect_dns_results(timeout=0.8 if quick else 1.2),
        "doh": {} if quick else collect_doh_results(),
        "ipv6": {
            "supported": ipv6.supported,
            "has_global_address": ipv6.has_global_address,
            "resolves_aaaa": ipv6.resolves_aaaa,
            "rtt_ms": ipv6.rtt_ms,
            "detail": ipv6.detail,
        },
        "ping_output": ping_output,
        "loss_summary": summarize_loss(ping_output),
        "speed": {"download_mbps": down_mbps, "upload_mbps": up_mbps},
        "top_apps": [{"name": name, "kb": kb} for name, kb in top_apps],
    }


def _print_dns(report: dict, out) -> None:
    print("--- DNS Yanıt Süreleri (UDP/53) ---", file=out)
    for name, latency in report["dns"].items():
        value = f"{latency} ms" if latency is not None else "Zaman Aşımı"
        print(f"  {name}: {value}", file=out)


def _print_doh(report: dict, out) -> None:
    if not report["doh"]:
        return
    print("\n--- DNS over HTTPS (DoH) ---", file=out)
    for name, entry in report["doh"].items():
        if entry["ok"]:
            print(f"  {name}: {entry['rtt_ms']} ms  [{entry['rcode']}]", file=out)
        else:
            print(f"  {name}: başarısız ({entry['error'] or entry['rcode']})", file=out)


def _print_ipv6(report: dict, out) -> None:
    ipv6 = report["ipv6"]
    print("\n--- IPv6 ---", file=out)
    print(f"  Durum: {ipv6['detail']}", file=out)
    print(
        f"  Yığın: {'var' if ipv6['supported'] else 'yok'} | "
        f"Genel adres: {'var' if ipv6['has_global_address'] else 'yok'} | "
        f"AAAA çözümü: {'var' if ipv6['resolves_aaaa'] else 'yok'}",
        file=out,
    )


def _print_adapters(report: dict, out) -> None:
    if not report["adapters"]:
        if report["adapters_error"]:
            print(f"\n--- Ağ Bağlantıları okunamadı: {report['adapters_error']} ---", file=out)
        return
    print("\n--- Ağ Bağlantıları ---", file=out)
    for adapter in report["adapters"]:
        flags = []
        if adapter["dhcp_enabled"]:
            flags.append("DHCP")
        if adapter["is_virtual"]:
            flags.append("sanal")
        suffix = f"  ({', '.join(flags)})" if flags else ""
        print(f"  {adapter['name']}  [{adapter['status']}]{suffix}", file=out)


def _print_summary(report: dict, out) -> None:
    down_mbps = report["speed"]["download_mbps"]
    if down_mbps and down_mbps < 5:
        print(f"Bant genişliği düşük görünüyor: {down_mbps} Mbps", file=out)
    if any(latency is None or latency >= 100 for latency in report["dns"].values()):
        print("DNS gecikmesi yüksek. 1.1.1.1 veya 8.8.8.8 deneyin.", file=out)
    loss_summary = report["loss_summary"]
    if loss_summary and "0% kayıp" not in loss_summary:
        print(f"Paket kaybı tespit edildi: {loss_summary}", file=out)
    if not report["ipv6"]["has_global_address"]:
        print("IPv6 genel adresi yok. Bazı servisler IPv6'yı tercih ettiği için yavaşlık olabilir.", file=out)


def run_diagnostics(quick: bool = False, stream=None) -> dict:
    """Print the human-readable report and return the same data as a dict."""
    report = build_report(quick=quick)
    out = stream if stream is not None else sys.stdout

    print(RULE, file=out)
    print("      GELİŞMİŞ İNTERNET TEŞHİS RAPORU", file=out)
    print(RULE, file=out)

    _print_dns(report, out)
    _print_doh(report, out)
    _print_ipv6(report, out)
    _print_adapters(report, out)

    print("\n--- Ping & Paket Kaybı ---", file=out)
    for line in (report["ping_output"] or "").splitlines()[-4:]:
        print(f"  {line}", file=out)

    if not quick:
        print("\n--- Bant Genişliği ---", file=out)
        print(f"  İndirme Hızı: {report['speed']['download_mbps']} Mbps", file=out)
        print(f"  Yükleme Hızı: {report['speed']['upload_mbps']} Mbps", file=out)
        public_ip = report["platform"].get("public_ipv4")
        if public_ip:
            print(f"  Açık IP: {public_ip}", file=out)

        print("\n--- En Çok Ağ Kullanan İşlemler ---", file=out)
        if report["top_apps"]:
            for app in report["top_apps"]:
                print(f"  {app['name']}: ~{app['kb']} KB", file=out)
        else:
            print("  Belirgin ağ kullanımı tespit edilmedi.", file=out)

    print("\n" + RULE, file=out)
    print("                TEŞHİS ÖZETİ", file=out)
    print(RULE, file=out)
    _print_summary(report, out)
    return report


def run_diagnostics_json(quick: bool = False) -> dict:
    return build_report(quick=quick)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="apex-dns-diagnostics", description="Apex DNS teşhis raporu")
    parser.add_argument("--quick", action="store_true", help="Hız testi ve süreç taramasını atla")
    args = parser.parse_args(argv)

    if os.environ.get("APEX_DNS_JSON"):
        print(json.dumps(run_diagnostics_json(quick=args.quick), ensure_ascii=False, indent=2))
    else:
        run_diagnostics(quick=args.quick)
    return 0
