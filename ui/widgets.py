"""Reusable ttk/tk widgets: DNS cards, provider list, adapter bar, footer."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core.dns_service import is_valid_ip
from core.providers import DnsProvider
from i18n import t
from ui import theme

INDICATOR_SIZE = 12


class DnsCard(tk.Frame):
    """One selectable provider row: name, badge, description, addresses, latency."""

    def __init__(self, master, provider: DnsProvider, index: int, on_select) -> None:
        super().__init__(
            master,
            bg=theme.COLOR_CARD,
            bd=1,
            relief="flat",
            cursor="hand2",
            highlightbackground=theme.COLOR_BORDER,
            highlightthickness=1,
        )
        self.provider = provider
        self.index = index
        self._on_select = on_select
        self._selected = False

        self.indicator = tk.Canvas(
            self, width=INDICATOR_SIZE, height=INDICATOR_SIZE, bg=theme.COLOR_CARD, highlightthickness=0
        )
        self.indicator.pack(side="left", padx=(15, 10))

        self.content = tk.Frame(self, bg=theme.COLOR_CARD)
        self.content.pack(side="left", fill="y", pady=10)

        self.title_row = tk.Frame(self.content, bg=theme.COLOR_CARD)
        self.title_row.pack(anchor="w")

        self.title = tk.Label(
            self.title_row,
            text=provider.name,
            font=theme.FONT_CARD_TITLE,
            fg=theme.COLOR_TEXT_PRIMARY,
            bg=theme.COLOR_CARD,
        )
        self.title.pack(side="left")

        self.badge: tk.Label | None = None
        if provider.badge:
            self.badge = tk.Label(
                self.title_row,
                text=f"  {provider.badge}  ",
                font=theme.FONT_BADGE,
                fg=provider.badge_color,
                bg=theme.COLOR_BORDER,
            )
            self.badge.pack(side="left", padx=10)

        self.description = tk.Label(
            self.content,
            text=provider.desc,
            font=theme.FONT_CARD_TEXT,
            fg=theme.COLOR_TEXT_MUTED,
            bg=theme.COLOR_CARD,
            anchor="w",
        )
        self.description.pack(anchor="w", pady=(2, 0))

        self.addresses = tk.Label(
            self.content,
            text=provider.display_servers(),
            font=theme.FONT_MONO,
            fg=theme.COLOR_CYAN if provider.primary else theme.COLOR_TEXT_MUTED,
            bg=theme.COLOR_CARD,
            anchor="w",
        )
        self.addresses.pack(anchor="w", pady=(2, 0))

        self.right = tk.Frame(self, bg=theme.COLOR_CARD)
        self.right.pack(side="right", padx=(0, 20), fill="y")

        self.latency = tk.Label(
            self.right, text="-- ms", font=theme.FONT_LATENCY, fg=theme.COLOR_TEXT_MUTED, bg=theme.COLOR_CARD
        )
        self.latency.pack(side="top", anchor="e", pady=(10, 0))

        self.badge_star = tk.Label(self.right, text="", font=theme.FONT_STAR, fg=theme.COLOR_AMBER, bg=theme.COLOR_CARD)
        self.badge_star.pack(side="top", anchor="e")

        clickable = [
            self,
            self.content,
            self.title_row,
            self.title,
            self.description,
            self.addresses,
            self.right,
            self.latency,
            self.badge_star,
        ]
        if self.badge is not None:
            clickable.append(self.badge)
        for widget in clickable:
            widget.bind("<Button-1>", self._handle_click)
        self._render_indicator()

    def _handle_click(self, _event) -> None:
        self._on_select(self.index)

    def _render_indicator(self) -> None:
        self.indicator.delete("all")
        if self._selected:
            self.indicator.create_oval(1, 1, 11, 11, outline=theme.COLOR_BORDER_SEL, width=2)
            self.indicator.create_oval(3, 3, 9, 9, fill=theme.COLOR_BORDER_SEL, outline="")
        else:
            self.indicator.create_oval(1, 1, 11, 11, outline=theme.COLOR_BORDER, width=2)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        background = theme.COLOR_CARD_SEL if selected else theme.COLOR_CARD
        self.configure(bg=background, highlightbackground=theme.COLOR_BORDER_SEL if selected else theme.COLOR_BORDER)
        for widget in (
            self.content,
            self.title_row,
            self.title,
            self.description,
            self.addresses,
            self.right,
            self.latency,
            self.badge_star,
            self.indicator,
        ):
            widget.configure(bg=background)
        if self.badge is not None:
            self.badge.configure(bg=theme.COLOR_BORDER)
        self._render_indicator()

    def set_measuring(self) -> None:
        self.badge_star.configure(text="")
        self.latency.configure(text=t("card.measuring"), fg=theme.COLOR_TEXT_MUTED)

    def set_latency(self, latency_ms: float | None, doh_ms: float | None = None) -> None:
        if latency_ms is None:
            self.latency.configure(text=t("card.timeout"), fg=theme.COLOR_RED)
            return
        base = f"{int(latency_ms)} ms"
        if doh_ms is not None:
            base = f"{base}\nDoH {int(doh_ms)} ms"
        self.latency.configure(text=base, fg=theme.latency_color(latency_ms))

    def set_fastest(self, text: str | None = None) -> None:
        self.badge_star.configure(text=text or t("card.fastest"))

    def set_addresses(self, primary: str, secondary: str = "") -> None:
        updated = self.provider.as_custom(primary, secondary)
        self.provider = updated
        self.addresses.configure(
            text=updated.display_servers(),
            fg=theme.COLOR_TEXT_PRIMARY if primary else theme.COLOR_TEXT_MUTED,
        )


class ProviderList(tk.Frame):
    """Scrollable stack of :class:`DnsCard` with single-selection semantics."""

    def __init__(self, master, providers, on_select, on_activate=None) -> None:
        super().__init__(master, bg=theme.COLOR_BG)
        self.providers = list(providers)
        self._on_select = on_select
        self._on_activate = on_activate or (lambda _index: None)
        self._selected_index = 0
        self._cards: list[DnsCard] = []

        self.canvas = tk.Canvas(self, bg=theme.COLOR_BG, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=theme.COLOR_BG)
        self._body_window = self.canvas.create_window(
            (0, 0), window=self.body, anchor="nw", width=theme.CARD_CONTENT_WIDTH
        )
        self.body.bind("<Configure>", self._sync_scrollregion)
        self.canvas.bind("<Configure>", self._sync_body_width)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y", padx=(5, 0))

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.body.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._scroll_step)
        self.canvas.bind("<Button-5>", self._scroll_step)
        self.body.bind("<Button-4>", self._scroll_step)
        self.body.bind("<Button-5>", self._scroll_step)

        for index, provider in enumerate(self.providers):
            card = DnsCard(self.body, provider, index, self.select)
            card.pack(fill="x", pady=4, padx=2)
            self._cards.append(card)

        self.select(0, notify=False)

    def _sync_scrollregion(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_body_width(self, event) -> None:
        self.canvas.itemconfigure(self._body_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        delta = -1 if getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    def _scroll_step(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @property
    def selected_provider(self) -> DnsProvider:
        return self._cards[self._selected_index].provider

    def select(self, index: int, notify: bool = True) -> None:
        if not self._cards:
            return
        index = max(0, min(index, len(self._cards) - 1))
        self._selected_index = index
        for position, card in enumerate(self._cards):
            card.set_selected(position == index)
        if notify:
            self._on_select(index)

    def activate(self, index: int) -> None:
        self.select(index)
        self._on_activate(index)

    def card(self, index: int) -> DnsCard:
        return self._cards[index]

    def cards(self) -> list[DnsCard]:
        return list(self._cards)

    def set_all_measuring(self) -> None:
        for card in self._cards:
            card.set_measuring()

    def add_widget(self, widget: tk.Widget) -> None:
        widget.pack(fill="x", pady=(5, 10), padx=2)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def remove_widget(self, widget: tk.Widget) -> None:
        widget.pack_forget()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


class AdapterBar(tk.Frame):
    """Adapter selector plus the currently configured DNS servers."""

    def __init__(self, master, on_change) -> None:
        super().__init__(master, bg=theme.COLOR_BG, padx=25, pady=12)
        self._on_change = on_change
        self._suppress = False

        tk.Label(
            self, text=t("adapter.label"), font=theme.FONT_CARD_TITLE, fg=theme.COLOR_TEXT_PRIMARY, bg=theme.COLOR_BG
        ).grid(row=0, column=0, sticky="w", pady=5)

        self.selected = tk.StringVar()
        self.menu = ttk.Combobox(self, textvariable=self.selected, state="readonly", width=22)
        self.menu.grid(row=0, column=1, padx=10, sticky="w")
        self.menu.bind("<<ComboboxSelected>>", self._handle_change)

        self.current = tk.Label(
            self,
            text=t("status.scanning_adapters"),
            font=theme.FONT_SUBTITLE,
            fg=theme.COLOR_TEXT_MUTED,
            bg=theme.COLOR_BG,
        )
        self.current.grid(row=0, column=2, padx=10, sticky="e")

    def _handle_change(self, _event=None) -> None:
        if not self._suppress:
            self._on_change(self.selected.get())

    def set_options(self, labels: list[str], active: str) -> None:
        self._suppress = True
        try:
            self.menu["values"] = labels
            if labels:
                self.selected.set(active if active in labels else labels[0])
        finally:
            self._suppress = False

    def show_multiple(self) -> None:
        self.current.configure(text=t("adapter.current.multi"), fg=theme.COLOR_TEXT_MUTED)

    def show_servers(self, servers: list[str], uses_dhcp: bool) -> None:
        if not servers:
            self.current.configure(text=t("adapter.current.auto"), fg=theme.COLOR_TEXT_MUTED)
            return
        key = "adapter.current.dhcp" if uses_dhcp else "adapter.current.servers"
        self.current.configure(text=t(key, servers=", ".join(servers)), fg=theme.COLOR_GREEN)

    def show_error(self, message: str) -> None:
        self.current.configure(text=t("adapter.current.unreadable", reason=message), fg=theme.COLOR_RED)

    def value(self) -> str:
        return self.selected.get()


class CustomDnsForm(tk.Frame):
    """Primary/secondary address inputs with live validation feedback."""

    def __init__(self, master, on_change) -> None:
        super().__init__(
            master,
            bg=theme.COLOR_CARD,
            bd=1,
            relief="flat",
            highlightbackground=theme.COLOR_BORDER,
            highlightthickness=1,
        )
        self._on_change = on_change
        self.primary = tk.StringVar()
        self.secondary = tk.StringVar()

        tk.Label(
            self, text=t("custom.primary"), font=theme.FONT_CARD_TEXT, fg=theme.COLOR_TEXT_PRIMARY, bg=theme.COLOR_CARD
        ).grid(row=0, column=0, padx=15, pady=10, sticky="w")
        self.primary_entry = self._entry(0, 1, self.primary)
        tk.Label(
            self,
            text=t("custom.secondary"),
            font=theme.FONT_CARD_TEXT,
            fg=theme.COLOR_TEXT_PRIMARY,
            bg=theme.COLOR_CARD,
        ).grid(row=0, column=2, padx=15, pady=10, sticky="w")
        self.secondary_entry = self._entry(0, 3, self.secondary)

        self.hint = tk.Label(
            self, text="", font=theme.FONT_CARD_TEXT, fg=theme.COLOR_RED, bg=theme.COLOR_CARD, anchor="w"
        )
        self.hint.grid(row=1, column=0, columnspan=4, padx=15, pady=(0, 10), sticky="w")

        self.primary.trace_add("write", self._handle_change)
        self.secondary.trace_add("write", self._handle_change)

    def _entry(self, row: int, column: int, variable: tk.StringVar) -> tk.Entry:
        entry = tk.Entry(
            self,
            textvariable=variable,
            bg=theme.COLOR_BG,
            fg=theme.COLOR_TEXT_PRIMARY,
            insertbackground=theme.COLOR_TEXT_PRIMARY,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.COLOR_BORDER,
            highlightcolor=theme.COLOR_ACCENT,
            width=16,
        )
        entry.grid(row=row, column=column, padx=5, pady=10)
        return entry

    def _handle_change(self, *_args) -> None:
        primary = self.primary.get().strip()
        secondary = self.secondary.get().strip()
        self._show_hint(primary, secondary)
        self._on_change(primary, secondary)

    def _show_hint(self, primary: str, secondary: str) -> None:
        if primary and not is_valid_ip(primary):
            self.hint.configure(text=t("custom.invalid.primary", value=primary), fg=theme.COLOR_RED)
        elif secondary and not is_valid_ip(secondary):
            self.hint.configure(text=t("custom.invalid.secondary", value=secondary), fg=theme.COLOR_RED)
        elif primary:
            self.hint.configure(text=t("custom.hint.ok"), fg=theme.COLOR_GREEN)
        else:
            self.hint.configure(text="")

    def focus_primary(self) -> None:
        self.primary_entry.focus_set()

    def values(self) -> tuple[str, str]:
        return self.primary.get().strip(), self.secondary.get().strip()


class StatusFooter(tk.Frame):
    """Status line plus the action buttons."""

    def __init__(self, master, *, on_test, on_reset, on_apply, on_doh, on_details=None) -> None:
        super().__init__(master, bg=theme.COLOR_BG, pady=18, padx=25)
        self.status = tk.Label(
            self,
            text=t("status.ready"),
            font=theme.FONT_SUBTITLE,
            fg=theme.COLOR_TEXT_MUTED,
            bg=theme.COLOR_BG,
            anchor="w",
        )
        self.status.pack(anchor="w", fill="x", pady=(0, 10))

        row = tk.Frame(self, bg=theme.COLOR_BG)
        row.pack(fill="x")
        self.buttons: dict[str, tk.Button] = {}

        self.buttons["test"] = self._button(row, t("button.test"), theme.COLOR_CYAN, on_test, 0, (0, 5))
        self.buttons["doh"] = self._button(row, t("button.doh"), theme.COLOR_AMBER, on_doh, 1, (5, 5))
        self.buttons["reset"] = self._button(row, t("button.reset"), theme.COLOR_RED, on_reset, 2, (5, 5))
        if on_details is not None:
            self.buttons["details"] = self._button(
                row, t("button.details"), theme.COLOR_TEXT_MUTED, on_details, 3, (5, 5)
            )
        self.buttons["apply"] = self._button(
            row,
            t("button.apply"),
            theme.COLOR_TEXT_PRIMARY,
            on_apply,
            4,
            (5, 0),
            background=theme.COLOR_ACCENT,
            hover=theme.COLOR_ACCENT_HOVER,
        )
        for column in range(5):
            row.columnconfigure(column, weight=1)

    def _button(self, parent, text, color, command, column, padx, background=None, hover=None) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            font=theme.FONT_BUTTON,
            fg=color,
            bg=background or theme.COLOR_CARD,
            activeforeground=color,
            activebackground=hover or theme.COLOR_CARD_SEL,
            bd=0,
            padx=10,
            pady=10,
            cursor="hand2",
            relief="flat",
            command=command,
        )
        button.grid(row=0, column=column, sticky="ew", padx=padx)
        return button

    def set_status(self, text: str, color: str = theme.COLOR_TEXT_MUTED) -> None:
        self.status.configure(text=text, fg=color)
        self.update_idletasks()

    def set_enabled(self, enabled: bool) -> None:
        for button in self.buttons.values():
            button.configure(state="normal" if enabled else "disabled")
