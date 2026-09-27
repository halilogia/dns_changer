"""Network diagnostics report (console and JSON) built on the core layer."""

from __future__ import annotations

import os
import platform
import sys

from core import elevation, resolver, system
from core import settings as settings_store
from core.dns_service import DnsService
from core.providers import measurable_providers
from diagnostics.netusage import get_top_network_usage
from diagnostics.speedtest import test_latency_and_loss, test_speed
from i18n import t

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
    return f"{loss}% {t('report.lost')} — {tail}".strip(" —")


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
        "settings_path": str(settings_store.settings_path()),
        "ping_output": ping_output,
        "loss_summary": summarize_loss(ping_output),
        "speed": {"download_mbps": down_mbps, "upload_mbps": up_mbps},
        "top_apps": [{"name": name, "kb": kb} for name, kb in top_apps],
    }


def _print_dns(report: dict, out) -> None:
    print(f"--- {t('report.dns_section')} ---", file=out)
    for name, latency in report["dns"].items():
        value = f"{latency} ms" if latency is not None else t("report.dns_timeout")
        print(f"  {name}: {value}", file=out)


def _print_doh(report: dict, out) -> None:
    if not report["doh"]:
        return
    print(f"\n--- {t('report.doh_section')} ---", file=out)
    for name, entry in report["doh"].items():
        if entry["ok"]:
            print(f"  {name}: {entry['rtt_ms']} ms  [{entry['rcode']}]", file=out)
        else:
            print(f"  {name}: {t('report.doh_failed', reason=entry['error'] or entry['rcode'])}", file=out)


def _print_ipv6(report: dict, out) -> None:
    ipv6 = report["ipv6"]
    yes, no = t("report.yes"), t("report.no")
    print(f"\n--- {t('report.ipv6_section')} ---", file=out)
    print(f"  {t('report.status')}: {ipv6['detail']}", file=out)
    print(
        "  "
        + t(
            "report.ipv6_stack",
            stack=yes if ipv6["supported"] else no,
            global_addr=yes if ipv6["has_global_address"] else no,
            aaaa=yes if ipv6["resolves_aaaa"] else no,
        ),
        file=out,
    )


def _print_adapters(report: dict, out) -> None:
    if not report["adapters"]:
        if report["adapters_error"]:
            print(f"\n--- {t('report.adapters_unreadable', reason=report['adapters_error'])} ---", file=out)
        return
    print(f"\n--- {t('report.adapters_section')} ---", file=out)
    for adapter in report["adapters"]:
        flags = []
        if adapter["dhcp_enabled"]:
            flags.append(t("report.dhcp"))
        if adapter["is_virtual"]:
            flags.append(t("report.virtual"))
        suffix = f"  ({', '.join(flags)})" if flags else ""
        print(f"  {adapter['name']}  [{adapter['status']}]{suffix}", file=out)


def _print_summary(report: dict, out) -> None:
    down_mbps = report["speed"]["download_mbps"]
    if down_mbps and down_mbps < 5:
        print(t("report.low_bandwidth", value=down_mbps), file=out)
    if any(latency is None or latency >= 100 for latency in report["dns"].values()):
        print(t("report.high_dns_latency"), file=out)
    loss_summary = report["loss_summary"]
    if loss_summary and t("report.no_loss") not in loss_summary:
        print(t("report.packet_loss", summary=loss_summary), file=out)
    if not report["ipv6"]["has_global_address"]:
        print(t("report.no_ipv6"), file=out)


def run_diagnostics(quick: bool = False, stream=None) -> dict:
    """Print the human-readable report and return the same data as a dict."""
    report = build_report(quick=quick)
    out = stream if stream is not None else sys.stdout

    print(RULE, file=out)
    print(f"      {t('report.title')}", file=out)
    print(RULE, file=out)

    _print_dns(report, out)
    _print_doh(report, out)
    _print_ipv6(report, out)
    _print_adapters(report, out)

    print(f"\n--- {t('report.ping_section')} ---", file=out)
    for line in (report["ping_output"] or "").splitlines()[-4:]:
        print(f"  {line}", file=out)

    if not quick:
        print(f"\n--- {t('report.speed_section')} ---", file=out)
        print("  " + t("report.download", value=report["speed"]["download_mbps"]), file=out)
        print("  " + t("report.upload", value=report["speed"]["upload_mbps"]), file=out)
        public_ip = report["platform"].get("public_ipv4")
        if public_ip:
            print("  " + t("report.public_ip", value=public_ip), file=out)

        print(f"\n--- {t('report.apps_section')} ---", file=out)
        if report["top_apps"]:
            for app in report["top_apps"]:
                print(f"  {app['name']}: ~{app['kb']} KB", file=out)
        else:
            print("  " + t("report.no_usage"), file=out)

    print("\n" + RULE, file=out)
    print(f"                {t('report.summary_title')}", file=out)
    print(RULE, file=out)
    _print_summary(report, out)
    return report


def run_diagnostics_json(quick: bool = False) -> dict:
    return build_report(quick=quick)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="apex-dns-diagnostics", description=t("cli.report_description"))
    parser.add_argument("--quick", action="store_true", help=t("cli.quick"))
    args = parser.parse_args(argv)

    if os.environ.get("APEX_DNS_JSON"):
        print(json.dumps(run_diagnostics_json(quick=args.quick), ensure_ascii=False, indent=2))
    else:
        run_diagnostics(quick=args.quick)
    return 0
