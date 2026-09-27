"""Introspect a constructed App to verify the widget tree lays out correctly."""

import sys
import tkinter as tk

sys.path.insert(0, ".")

from core.dns_service import AdapterInfo, DnsBackend, DnsService
from ui.app import App


class StubBackend(DnsBackend):
    name = "stub"
    can_write = True

    def list_adapters(self):
        return [
            AdapterInfo(name="Ethernet", status="Up", dhcp_enabled=True),
            AdapterInfo(name="Wi-Fi", status="Up", dhcp_enabled=False),
        ]

    def get_dns_servers(self, adapter):
        return ["1.1.1.1", "1.0.0.1"] if adapter == "Ethernet" else []

    def set_dns_servers(self, adapter, servers):
        pass

    def reset_dns_servers(self, adapter):
        pass


root = tk.Tk()
root.withdraw()
app = App(root, service=DnsService(backend=StubBackend(), cache_ttl=0))


def pump(seconds: float = 2.0) -> None:
    """Spin the Tk event loop so `after` callbacks from worker threads land."""
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


pump()
print(f"window geometry      : {root.winfo_width()}x{root.winfo_height()}")
print(f"provider cards       : {len(app.provider_list.cards())}")
print(f"selected index       : {app.provider_list.selected_index}")
print(f"selected provider    : {app.provider_list.selected_provider.name}")
print(f"card 0 latency text  : {app.provider_list.card(0).latency.cget('text')!r}")
print(f"card 0 selected      : {app.provider_list.card(0)._selected}")
print(f"card 1 selected      : {app.provider_list.card(1)._selected}")
print(f"adapter options      : {app.adapter_bar.menu.cget('values')}")
print(f"current dns label    : {app.adapter_bar.current.cget('text')!r}")
print(f"footer buttons       : {sorted(app.footer.buttons)}")
print(f"custom form hidden   : {not app.custom_form_visible}")
print(f"status line          : {app.footer.status.cget('text')!r}")

pl = app.provider_list

# Selecting the custom provider must reveal the form.
custom_index = len(pl.cards()) - 1
pl.select(custom_index)
root.update()
print(f"after custom select  : form_visible={app.custom_form_visible}")
print(f"custom card text     : {pl.card(custom_index).addresses.cget('text')!r}")

app.custom_form.primary.set("9.9.9.9")
app.custom_form.secondary.set("149.112.112.112")
root.update()
print(f"custom card after typ: {pl.card(custom_index).addresses.cget('text')!r}")
print(f"custom provider      : {app._selected_provider().servers}")
print(f"hint                 : {app.custom_form.hint.cget('text')!r}")

app.custom_form.primary.set("not-an-ip")
root.update()
print(f"invalid hint         : {app.custom_form.hint.cget('text')!r}")

# Selecting a preset again must hide the form.
pl.select(0)
root.update()
print(f"after preset select  : form_visible={app.custom_form_visible}")
print(f"apply target label   : {app.adapter_bar.value()!r}")
print(f"adapter key          : {app._adapter_key(app.adapter_bar.value())!r}")

# Thread marshalling: results must land back on the main loop.
results = {0: 5.0, 1: None, 2: 12.0, 3: 40.0, 4: 70.0, 5: 9.0}
app._show_speed_results(results)
root.update()
print(f"fastest starred      : {[i for i, c in enumerate(pl.cards()) if c.badge_star.cget('text')]}")
print(f"status after test    : {app.footer.status.cget('text')!r}")
print(f"card 0 latency       : {pl.card(0).latency.cget('text')!r}")
print(f"card 1 latency       : {pl.card(1).latency.cget('text')!r}")

app.shutdown()
root.destroy()
print("OK")
