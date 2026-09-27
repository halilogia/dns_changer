"""Tkinter application: wires core services to the Apex UI."""

from __future__ import annotations

import contextlib
import queue
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from tkinter import messagebox

from core import resolver, updater
from core import settings as settings_store
from core.dns_service import ApplyResult, DnsService, DnsServiceError, normalize_servers
from core.elevation import is_admin
from core.providers import ALL_ADAPTERS_ID, DEFAULT_PROVIDERS, DnsProvider, all_adapters_label
from core.system import is_frozen
from i18n import t
from ui import theme
from ui.details import collect_details, show_details
from ui.widgets import AdapterBar, CustomDnsForm, ProviderList, StatusFooter

APP_VERSION = "2.0.0"


class App:
    """Main window controller.

    Every call into the core layer runs on a worker thread. Results travel back
    through a queue that the Tk thread drains, because Tk's ``after`` is not
    safe to call from a worker thread and silently never fires.
    """

    INBOX_INTERVAL_MS = 40

    def __init__(self, root: tk.Tk, service: DnsService | None = None) -> None:
        self.root = root
        self.service = service or DnsService()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="apex-dns")
        self.inbox: queue.Queue = queue.Queue()
        self._pump_scheduled = False
        self._busy = False
        self.settings = settings_store.load_settings()
        self.custom_provider = replace(
            DEFAULT_PROVIDERS[-1],
            primary=self.settings.custom_primary,
            secondary=self.settings.custom_secondary,
        )
        self._detail_window = None
        self.last_errors: list[str] = []

        root.title(t("app.title"))
        root.geometry(self.settings.window_geometry or f"{theme.WINDOW_WIDTH}x{theme.WINDOW_HEIGHT}")
        root.configure(bg=theme.COLOR_BG)
        root.resizable(False, False)
        theme.apply_styles(root)

        self._build_ui()
        self._restore_selection()
        self._schedule_pump()
        self.refresh_adapters()
        self.root.after(500, self.start_speed_test)
        if self.settings.check_updates:
            self.root.after(1500, self.check_for_updates)

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=theme.COLOR_BG, pady=15, padx=25)
        header.pack(fill="x")
        tk.Label(header, text=t("app.brand"), font=theme.FONT_TITLE, fg=theme.COLOR_CYAN, bg=theme.COLOR_BG).pack(
            anchor="w"
        )
        tk.Label(
            header,
            text=t("app.tagline"),
            font=theme.FONT_SUBTITLE,
            fg=theme.COLOR_TEXT_MUTED,
            bg=theme.COLOR_BG,
        ).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.root, height=1, bg=theme.COLOR_BORDER).pack(fill="x", padx=25)

        self.adapter_bar = AdapterBar(self.root, self._on_adapter_changed)
        self.adapter_bar.pack(fill="x")

        list_container = tk.Frame(self.root, bg=theme.COLOR_BG, padx=25)
        list_container.pack(fill="both", expand=True)

        self.provider_list = ProviderList(
            list_container,
            DEFAULT_PROVIDERS,
            on_select=self._on_provider_selected,
            on_activate=self._on_provider_activated,
        )
        self.provider_list.pack(fill="both", expand=True)

        self.custom_form = CustomDnsForm(list_container, self._on_custom_dns_changed)
        self.custom_form_visible = False

        self.footer = StatusFooter(
            self.root,
            on_test=self.start_speed_test,
            on_reset=self.reset_dns,
            on_apply=self.apply_dns,
            on_doh=self.start_doh_test,
            on_details=self.show_details,
        )
        self.footer.pack(fill="x", side="bottom")

        if not is_admin():
            self.footer.set_status(t("status.no_admin"), theme.COLOR_AMBER)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _post(self, func, *args) -> None:
        """Queue a call for the Tk thread. Safe to invoke from a worker."""
        self.inbox.put((func, args))

    def _schedule_pump(self) -> None:
        """Arm the inbox drain. Must only be called from the Tk thread."""
        if self._pump_scheduled:
            return
        self._pump_scheduled = True
        self.root.after(self.INBOX_INTERVAL_MS, self._drain_inbox)

    def _drain_inbox(self) -> None:
        self._pump_scheduled = False
        while True:
            try:
                callback, args = self.inbox.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except Exception as exc:  # pragma: no cover - defensive
                self._on_failure("", exc)
        self._schedule_pump()

    def _run_async(self, work, on_success, busy_message: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.footer.set_enabled(False)
        if busy_message:
            self.footer.set_status(busy_message, theme.COLOR_CYAN)

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:
                self._post(self._on_failure, busy_message, exc)
                return
            self._post(on_success, result)

        self.executor.submit(worker)

    def _on_failure(self, _message: str, exc: Exception) -> None:
        self._busy = False
        self.footer.set_enabled(True)
        self.footer.set_status(t("status.failed", error=exc), theme.COLOR_RED)
        messagebox.showerror(t("dialog.error"), str(exc))

    def _finish(self) -> None:
        self._busy = False
        self.footer.set_enabled(True)

    # --- adapters ---

    def refresh_adapters(self) -> None:
        def work() -> list:
            return self.service.adapters(refresh=True)

        self._run_async(work, self._apply_adapter_list, t("status.scanning_adapters"))

    def _apply_adapter_list(self, adapters: list) -> None:
        self._finish()
        if not adapters:
            self.adapter_bar.menu["values"] = ()
            self.adapter_bar.show_error(t("adapter.none"))
            return
        labels = [adapter.name for adapter in adapters]
        if len(labels) > 1:
            labels.append(all_adapters_label())
        current = self.adapter_bar.value()
        active = current if current in labels else labels[0]
        self.adapter_bar.set_options(labels, active)
        self._show_current_dns(active)

    def _adapter_key(self, label: str) -> str:
        return ALL_ADAPTERS_ID if label == all_adapters_label() else label

    def _on_adapter_changed(self, _label: str) -> None:
        self._show_current_dns(self.adapter_bar.value())

    def _show_current_dns(self, label: str) -> None:
        if not label:
            return
        if label == all_adapters_label():
            self.adapter_bar.show_multiple()
            return

        def work() -> tuple[list, bool]:
            return self.service.dns_servers(label, refresh=True), self.service.uses_dhcp(label)

        def runner() -> None:
            try:
                servers, dhcp = work()
            except DnsServiceError as exc:
                self._post(self.adapter_bar.show_error, str(exc)[:40])
                return
            self._post(self.adapter_bar.show_servers, servers, dhcp)

        self.executor.submit(runner)

    # --- provider selection ---

    def _on_provider_selected(self, index: int) -> None:
        provider = self.provider_list.selected_provider
        if provider.has_custom_addresses:
            if not self.custom_form_visible:
                self.provider_list.add_widget(self.custom_form)
                self.custom_form_visible = True
            self.custom_form.focus_primary()
        elif self.custom_form_visible:
            self.provider_list.remove_widget(self.custom_form)
            self.custom_form_visible = False

    def _on_provider_activated(self, index: int) -> None:
        if self.provider_list.selected_provider.has_custom_addresses:
            self.custom_form.focus_primary()
            return
        self.apply_dns()

    def _on_custom_dns_changed(self, primary: str, secondary: str) -> None:
        self.custom_provider = self.custom_provider.as_custom(primary, secondary)
        self.provider_list.card(len(DEFAULT_PROVIDERS) - 1).set_addresses(primary, secondary)

    def _selected_provider(self) -> DnsProvider:
        provider = self.provider_list.selected_provider
        if not provider.has_custom_addresses:
            return provider
        return self.custom_provider

    # --- speed tests ---

    def start_speed_test(self) -> None:
        targets = [(index, provider.primary) for index, provider in enumerate(DEFAULT_PROVIDERS) if provider.primary]
        if not targets:
            return

        self._run_async(
            lambda: self._measure_all(targets),
            self._show_speed_results,
            t("status.measuring"),
        )
        self.provider_list.set_all_measuring()

    def _measure_all(self, targets: list[tuple[int, str]]) -> dict[int, float | None]:
        results: dict[int, float | None] = {}
        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            futures = {pool.submit(resolver.measure_dns_latency, ip): (index, ip) for index, ip in targets}
            for future in as_completed(futures):
                index, _ip = futures[future]
                try:
                    results[index] = future.result()
                except Exception:
                    results[index] = None
        return results

    def _show_speed_results(self, results: dict[int, float | None]) -> None:
        self._finish()
        best_index = None
        best_latency = float("inf")
        for index, latency in results.items():
            card = self.provider_list.card(index)
            card.set_latency(latency)
            if latency is not None and latency < best_latency:
                best_latency = latency
                best_index = index
        if best_index is None:
            self.footer.set_status(t("status.some_failed"), theme.COLOR_RED)
            return
        self.provider_list.card(best_index).set_fastest()
        name = DEFAULT_PROVIDERS[best_index].label
        self.footer.set_status(t("status.fastest", name=name, latency=int(best_latency)), theme.COLOR_GREEN)

    def start_doh_test(self) -> None:
        targets = [(index, provider) for index, provider in enumerate(DEFAULT_PROVIDERS) if provider.supports_doh]

        self._run_async(
            lambda: self._measure_doh_all(targets),
            self._show_doh_results,
            t("status.measuring_doh"),
        )
        self.provider_list.set_all_measuring()

    def _measure_doh_all(self, targets: list[tuple[int, DnsProvider]]) -> dict[int, float | None]:
        results: dict[int, float | None] = {}
        with ThreadPoolExecutor(max_workers=len(targets) or 1) as pool:
            futures = {pool.submit(resolver.measure_doh_latency, provider): index for index, provider in targets}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result().rtt_ms
                except Exception:
                    results[index] = None
        return results

    def _show_doh_results(self, results: dict[int, float | None]) -> None:
        self._finish()
        ipv6 = resolver.probe_ipv6()
        working = [DEFAULT_PROVIDERS[index].label for index, rtt in results.items() if rtt is not None]
        for index, rtt in results.items():
            card = self.provider_list.card(index)
            if rtt is not None:
                card.set_latency(rtt, doh_ms=rtt)
        summary = t("status.doh_summary", providers=", ".join(working) if working else t("status.doh_none"))
        self.footer.set_status(
            f"{summary} | {t('status.ipv6_prefix', detail=ipv6.detail)}",
            theme.COLOR_GREEN if working else theme.COLOR_AMBER,
        )

    # --- mutations ---

    def apply_dns(self) -> None:
        label = self.adapter_bar.value()
        if not label:
            messagebox.showerror(t("dialog.error"), t("dialog.no_adapter"))
            return
        provider = self._selected_provider()
        servers = list(provider.servers)
        if not servers:
            messagebox.showerror(t("dialog.error"), t("dialog.no_address"))
            return
        try:
            servers = list(normalize_servers(servers))
        except DnsServiceError as exc:
            messagebox.showerror(t("dialog.error"), str(exc))
            return

        self._run_async(
            lambda: self.service.apply(self._adapter_key(label), servers),
            self._show_apply_result,
            t("status.applying"),
        )

    def _show_apply_result(self, result: ApplyResult) -> None:
        self._finish()
        self._report_result(result, t("status.applied"))
        self._show_current_dns(self.adapter_bar.value())

    def reset_dns(self) -> None:
        label = self.adapter_bar.value()
        if not label:
            messagebox.showerror(t("dialog.error"), t("dialog.no_adapter"))
            return
        self._run_async(
            lambda: self.service.reset(self._adapter_key(label)),
            self._show_reset_result,
            t("status.resetting"),
        )

    def _show_reset_result(self, result: ApplyResult) -> None:
        self._finish()
        self._report_result(result, t("status.reset_done"))
        self._show_current_dns(self.adapter_bar.value())

    def _report_result(self, result: ApplyResult, success_text: str) -> None:
        if result.ok:
            self.footer.set_status(success_text, theme.COLOR_GREEN)
            messagebox.showinfo(
                t("dialog.success"),
                t("dialog.applied_body", summary=success_text, adapters=", ".join(result.adapters)),
            )
            return
        self.footer.set_status(t("status.incomplete"), theme.COLOR_RED)
        self.last_errors = list(result.errors)
        messagebox.showerror(t("dialog.error"), t("dialog.failed_body", errors="\n".join(result.errors)))

    # --- details ---

    def show_details(self) -> None:
        if self._detail_window is not None and self._detail_window.winfo_exists():
            self._detail_window.lift()
            return
        self._run_async(
            lambda: collect_details(self.service),
            self._open_details,
            t("status.reading_connections"),
        )

    def _open_details(self, report) -> None:
        self._finish()
        self._detail_window = show_details(self.root, report)

    # --- settings ---

    def _restore_selection(self) -> None:
        provider = self.settings.last_provider_id
        if provider:
            for index, candidate in enumerate(DEFAULT_PROVIDERS):
                if candidate.provider_id == provider:
                    self.provider_list.select(index)
                    break
        if self.settings.custom_primary:
            self.custom_form.primary.set(self.settings.custom_primary)
        if self.settings.custom_secondary:
            self.custom_form.secondary.set(self.settings.custom_secondary)

    def _capture_settings(self) -> None:
        label = self.adapter_bar.value()
        if label and label != all_adapters_label():
            self.settings.last_adapter = label
        self.settings.last_provider_id = self.provider_list.selected_provider.provider_id
        primary, secondary = self.custom_form.values()
        self.settings.custom_primary = primary
        self.settings.custom_secondary = secondary
        self.settings.window_geometry = self.root.geometry()
        settings_store.save_settings(self.settings)

    def on_close(self) -> None:
        with contextlib.suppress(Exception):  # never block shutdown
            self._capture_settings()
        self.shutdown()
        self.root.destroy()

    # --- updates ---

    def check_for_updates(self, silent: bool = False) -> None:
        if not is_frozen() and not silent:
            return
        if not self.settings.check_updates and not silent:
            return

        def work():
            return updater.check_for_update(APP_VERSION)

        self._run_async(work, lambda info: self._show_update(info, silent), t("update.checking"))

    def _show_update(self, info, silent: bool) -> None:
        self._finish()
        if info.error:
            if not silent:
                self.footer.set_status(t("status.update_failed", error=info.error), theme.COLOR_AMBER)
            return
        if not info.available:
            if not silent:
                self.footer.set_status(t("status.update_none", version=info.current), theme.COLOR_TEXT_MUTED)
            return

        self.footer.set_status(t("status.update_available", version=info.latest), theme.COLOR_CYAN)
        if silent:
            return
        body = t("dialog.update_found", version=info.latest, current=info.current)
        if info.notes:
            body = f"{body}\n\n{info.notes[:400]}"
        proceed = messagebox.askyesno(
            t("dialog.update_title"),
            f"{body}\n\n{t('status.update_download')}\n\n{t('dialog.update_open')}",
        )
        if proceed and info.url:
            webbrowser.open(info.url)


def launch() -> App:
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    return app
