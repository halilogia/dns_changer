"""Per-adapter diagnostic detail window.

The status bar can only say "some servers did not respond". This window is the
detail view: one row per connection with its live state, plus any error the
backend reported, so a failure is diagnosable without reading logs.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

from i18n import t
from ui import theme

COLUMNS = ("adapter", "status", "dns", "dhcp", "addresses", "error")


@dataclass(frozen=True, slots=True)
class AdapterDetail:
    """Flattened view of one connection for display."""

    name: str
    status: str = ""
    servers: tuple[str, ...] = ()
    dhcp: bool = False
    addresses: tuple[str, ...] = ()
    error: str = ""

    @property
    def is_up(self) -> bool:
        return self.status.strip().lower() in {"up", "connected", "bağlı"}


@dataclass
class DetailReport:
    rows: list[AdapterDetail] = field(default_factory=list)
    error: str = ""


def collect_details(service, probe_servers: bool = True) -> DetailReport:
    """Read every adapter plus its configured DNS from a :class:`DnsService`."""
    rows: list[AdapterDetail] = []
    try:
        adapters = service.adapters(refresh=True)
    except Exception as exc:
        return DetailReport(rows=[], error=str(exc))

    for adapter in adapters:
        servers: tuple[str, ...] = ()
        error = ""
        if probe_servers:
            try:
                servers = tuple(service.dns_servers(adapter.name, refresh=True))
            except Exception as exc:
                error = str(exc)
        rows.append(
            AdapterDetail(
                name=adapter.name,
                status=adapter.status,
                servers=servers,
                dhcp=adapter.dhcp_enabled,
                addresses=adapter.ipv4 + adapter.ipv6,
                error=error,
            )
        )
    return DetailReport(rows=rows)


class DetailsWindow(tk.Toplevel):
    """Modal-ish read-only view of :class:`DetailReport`."""

    def __init__(self, master: tk.Misc, report: DetailReport) -> None:
        super().__init__(master)
        self.title(t("details.title"))
        self.configure(bg=theme.COLOR_BG)
        self.resizable(True, True)
        self.transient(master)

        self.report = report
        self._build()
        self._center_on(master)

    def _center_on(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width = max(720, len(self.report.rows) * 4 + 240)
        height = min(560, 180 + len(self.report.rows) * 26)
        try:
            x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
            y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 2)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:  # pragma: no cover - window manager edge cases
            self.geometry(f"{width}x{height}")

    def _build(self) -> None:
        header = tk.Frame(self, bg=theme.COLOR_BG, padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text=t("details.title"),
            font=theme.FONT_TITLE,
            fg=theme.COLOR_CYAN,
            bg=theme.COLOR_BG,
        ).pack(anchor="w")
        tk.Label(
            header,
            text=self._summary_text(),
            font=theme.FONT_SUBTITLE,
            fg=theme.COLOR_TEXT_MUTED,
            bg=theme.COLOR_BG,
        ).pack(anchor="w", pady=(2, 0))

        if self.report.error:
            tk.Label(
                self,
                text=t("details.error", reason=self.report.error),
                font=theme.FONT_CARD_TEXT,
                fg=theme.COLOR_RED,
                bg=theme.COLOR_BG,
                wraplength=700,
                justify="left",
            ).pack(anchor="w", padx=18, pady=6)

        body = tk.Frame(self, bg=theme.COLOR_BG, padx=18)
        body.pack(fill="both", expand=True)

        if not self.report.rows:
            tk.Label(
                body,
                text=t("details.empty"),
                font=theme.FONT_CARD_TEXT,
                fg=theme.COLOR_TEXT_MUTED,
                bg=theme.COLOR_BG,
            ).pack(anchor="w", pady=20)
        else:
            self._build_table(body)

        footer = tk.Frame(self, bg=theme.COLOR_BG, padx=18, pady=12)
        footer.pack(fill="x")
        tk.Button(
            footer,
            text=t("details.close"),
            font=theme.FONT_BUTTON,
            fg=theme.COLOR_TEXT_PRIMARY,
            bg=theme.COLOR_CARD,
            activebackground=theme.COLOR_CARD_SEL,
            activeforeground=theme.COLOR_TEXT_PRIMARY,
            bd=0,
            padx=18,
            pady=8,
            cursor="hand2",
            command=self.destroy,
        ).pack(anchor="e")

    def _summary_text(self) -> str:
        if not self.report.rows:
            return t("details.empty")
        up = sum(1 for row in self.report.rows if row.is_up)
        return t(
            "details.summary",
            count=len(self.report.rows),
            up=up,
            down=len(self.report.rows) - up,
        )

    def _build_table(self, parent: tk.Frame) -> None:
        headers = {
            "adapter": t("details.column.adapter"),
            "status": t("details.column.status"),
            "dns": t("details.column.dns"),
            "dhcp": t("details.column.dhcp"),
            "addresses": t("details.column.addresses"),
            "error": t("details.column.error"),
        }
        widths = {"adapter": 150, "status": 80, "dns": 190, "dhcp": 60, "addresses": 190, "error": 210}

        head = tk.Frame(parent, bg=theme.COLOR_CARD)
        head.pack(fill="x")
        for column in COLUMNS:
            tk.Label(
                head,
                text=headers[column],
                font=theme.FONT_BADGE,
                fg=theme.COLOR_CYAN,
                bg=theme.COLOR_CARD,
                width=max(8, widths[column] // 8),
                anchor="w",
            ).pack(side="left", padx=6, pady=6)

        canvas = tk.Canvas(parent, bg=theme.COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=theme.COLOR_BG)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for index, row in enumerate(self.report.rows):
            self._build_row(inner, row, index)

    def _build_row(self, parent: tk.Frame, row: AdapterDetail, index: int) -> None:
        background = theme.COLOR_CARD if index % 2 == 0 else theme.COLOR_BG
        frame = tk.Frame(parent, bg=background)
        frame.pack(fill="x", pady=1)

        status_color = theme.COLOR_GREEN if row.is_up else theme.COLOR_TEXT_MUTED
        error_color = theme.COLOR_RED if row.error else theme.COLOR_TEXT_MUTED
        cells = {
            "adapter": (row.name or t("details.none"), theme.COLOR_TEXT_PRIMARY),
            "status": (t("details.up") if row.is_up else t("details.down"), status_color),
            "dns": (", ".join(row.servers) if row.servers else t("details.none"), theme.COLOR_CYAN),
            "dhcp": (t("details.yes") if row.dhcp else t("details.no"), theme.COLOR_TEXT_MUTED),
            "addresses": (", ".join(row.addresses) if row.addresses else t("details.none"), theme.COLOR_TEXT_MUTED),
            "error": (row.error or t("details.none"), error_color),
        }
        widths = {"adapter": 150, "status": 80, "dns": 190, "dhcp": 60, "addresses": 190, "error": 210}
        for column in COLUMNS:
            text, color = cells[column]
            tk.Label(
                frame,
                text=text,
                font=theme.FONT_CARD_TEXT,
                fg=color,
                bg=background,
                width=max(8, widths[column] // 8),
                anchor="w",
            ).pack(side="left", padx=6, pady=3)


def show_details(master: tk.Misc, report: DetailReport) -> DetailsWindow:
    window = DetailsWindow(master, report)
    window.focus_set()
    return window
