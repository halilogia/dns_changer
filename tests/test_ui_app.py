"""UI controller tests.

Tk needs a display, so the whole module is skipped when one is unavailable
(headless Linux CI). The regression these guard against is important: results
posted from worker threads never reach the UI if they are handed to Tk's
``after`` from a non-main thread, which silently leaves the app empty.
"""

from __future__ import annotations

import time
import unittest

from core.dns_service import AdapterInfo, DnsBackend, DnsService
from tests import ROOT  # noqa: F401

try:
    import tkinter as tk

    _probe = tk.Tk()
    _probe.withdraw()
    _probe.destroy()
    TK_AVAILABLE = True
except Exception:  # pragma: no cover - headless environments
    TK_AVAILABLE = False


class StubBackend(DnsBackend):
    name = "stub"
    can_write = True

    def __init__(self):
        self.applied = []
        self.reset_calls = []

    def list_adapters(self):
        return [
            AdapterInfo(name="Ethernet", status="Up", dhcp_enabled=True),
            AdapterInfo(name="Wi-Fi", status="Up", dhcp_enabled=False),
        ]

    def get_dns_servers(self, adapter):
        return ["1.1.1.1", "1.0.0.1"] if adapter == "Ethernet" else []

    def set_dns_servers(self, adapter, servers):
        self.applied.append((adapter, servers))

    def reset_dns_servers(self, adapter):
        self.reset_calls.append(adapter)


@unittest.skipUnless(TK_AVAILABLE, "Tk display not available")
class TestAppController(unittest.TestCase):
    def setUp(self):
        from unittest import mock

        from ui import app as app_module

        self.backend = StubBackend()
        self.root = tk.Tk()
        self.root.withdraw()
        # Modal dialogs would block the event loop forever.
        self.messagebox = mock.patch.object(app_module, "messagebox").start()
        self.addCleanup(mock.patch.stopall)
        self.app = app_module.App(self.root, service=DnsService(backend=self.backend, cache_ttl=0))
        self.pump()

    def tearDown(self):
        self.app.shutdown()
        self.root.destroy()

    def pump(self, seconds: float = 1.5) -> None:
        """Run the Tk event loop so queued worker results are delivered."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)

    def test_window_uses_expected_geometry(self):
        self.assertEqual(self.root.winfo_width(), 560)
        self.assertEqual(self.root.winfo_height(), 730)

    def test_all_provider_cards_are_built(self):
        self.assertEqual(len(self.app.provider_list.cards()), 7)

    def test_first_card_is_selected(self):
        self.assertTrue(self.app.provider_list.card(0)._selected)
        self.assertFalse(self.app.provider_list.card(1)._selected)

    def test_adapters_are_listed_from_the_backend(self):
        options = self.app.adapter_bar.menu.cget("values")
        self.assertEqual(list(options), ["Ethernet", "Wi-Fi", "Tüm Aktif Bağlantılar"])

    def test_current_dns_is_displayed_with_dhcp_hint(self):
        text = self.app.adapter_bar.current.cget("text")
        self.assertIn("1.1.1.1", text)
        self.assertIn("DHCP", text)

    def test_all_action_buttons_exist(self):
        self.assertEqual(sorted(self.app.footer.buttons), ["apply", "details", "doh", "reset", "test"])

    def test_worker_results_reach_the_ui(self):
        # The regression: adapters were never populated because worker results
        # were handed to Tk's after() from a background thread.
        self.assertTrue(self.app.adapter_bar.menu.cget("values"))
        self.assertNotEqual(self.app.adapter_bar.current.cget("text"), "Mevcut DNS: tespit ediliyor...")

    def test_busy_flag_is_released(self):
        self.assertFalse(self.app._busy)

    def test_selecting_custom_provider_reveals_form(self):
        self.app.provider_list.select(6)
        self.pump(0.2)
        self.assertTrue(self.app.custom_form_visible)

    def test_selecting_preset_hides_form(self):
        self.app.provider_list.select(6)
        self.pump(0.2)
        self.app.provider_list.select(0)
        self.pump(0.2)
        self.assertFalse(self.app.custom_form_visible)

    def test_custom_input_updates_card_and_provider(self):
        self.app.provider_list.select(6)
        self.pump(0.2)
        self.app.custom_form.primary.set("9.9.9.9")
        self.app.custom_form.secondary.set("149.112.112.112")
        self.pump(0.2)
        self.assertEqual(self.app._selected_provider().servers, ("9.9.9.9", "149.112.112.112"))
        self.assertIn("9.9.9.9", self.app.provider_list.card(6).addresses.cget("text"))

    def test_invalid_custom_input_is_flagged(self):
        self.app.provider_list.select(6)
        self.pump(0.2)
        self.app.custom_form.primary.set("not-an-ip")
        self.pump(0.2)
        self.assertIn("geçersiz", self.app.custom_form.hint.cget("text"))

    def test_latency_results_render_and_pick_winner(self):
        results = {0: 5.0, 1: None, 2: 12.0, 3: 40.0, 4: 70.0, 5: 9.0}
        self.app._show_speed_results(results)
        self.pump(0.2)
        self.assertEqual(self.app.provider_list.card(0).latency.cget("text"), "5 ms")
        self.assertEqual(self.app.provider_list.card(1).latency.cget("text"), "Zaman Aşımı")
        self.assertIn("En Hızlı", self.app.provider_list.card(0).badge_star.cget("text"))
        self.assertEqual(self.app.provider_list.card(0).badge_star.cget("text"), "⭐ En Hızlı")

    def test_all_timeouts_reports_failure(self):
        self.app._show_speed_results(dict.fromkeys(range(6)))
        self.pump(0.2)
        self.assertIn("yanıt vermedi", self.app.footer.status.cget("text"))

    def test_adapter_key_maps_multi_select_to_sentinel(self):
        from core.providers import ALL_ADAPTERS_ID, all_adapters_label

        self.assertEqual(self.app._adapter_key(all_adapters_label()), ALL_ADAPTERS_ID)
        self.assertEqual(self.app._adapter_key("Ethernet"), "Ethernet")

    def test_details_button_opens_a_window(self):
        from i18n import set_locale
        from ui.details import AdapterDetail, DetailReport, DetailsWindow

        report = DetailReport(
            rows=[
                AdapterDetail(name="Ethernet", status="Up", servers=("1.1.1.1",), dhcp=True),
                AdapterDetail(name="Wi-Fi", status="Disconnected"),
            ]
        )
        window = DetailsWindow(self.root, report)
        self.pump(0.2)
        self.assertEqual(len(window.report.rows), 2)
        try:
            set_locale("en")
            self.assertEqual(window._summary_text(), "2 connection(s) | 1 up, 1 down")
        finally:
            set_locale("tr")
        window.destroy()

    def test_apply_reaches_the_backend(self):
        self.app.provider_list.select(0)
        self.pump(0.2)
        self.app.apply_dns()
        self.pump(0.5)
        self.assertEqual(self.backend.applied[0][0], "Ethernet")
        self.assertEqual(self.backend.applied[0][1], ("1.1.1.1", "1.0.0.1"))

    def test_reset_reaches_the_backend(self):
        self.app.reset_dns()
        self.pump(0.5)
        self.assertEqual(self.backend.reset_calls, ["Ethernet"])

    def test_queue_delivers_results_in_order(self):
        seen = []
        self.app._post(seen.append, 1)
        self.app._post(seen.append, 2)
        self.pump(0.3)
        self.assertEqual(seen, [1, 2])


if __name__ == "__main__":
    unittest.main()
