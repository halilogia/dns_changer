"""Colours, fonts and ttk styling for the Apex look."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import system

WINDOW_WIDTH = 560
WINDOW_HEIGHT = 730
CARD_CONTENT_WIDTH = WINDOW_WIDTH - 66

FONT_FAMILY = "Segoe UI"
FONT_TITLE = (FONT_FAMILY, 16, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 9)
FONT_CARD_TITLE = (FONT_FAMILY, 10, "bold")
FONT_CARD_TEXT = (FONT_FAMILY, 9)
FONT_BADGE = (FONT_FAMILY, 8, "bold")
FONT_LATENCY = (FONT_FAMILY, 10, "bold")
FONT_STAR = (FONT_FAMILY, 12, "bold")
FONT_BUTTON = (FONT_FAMILY, 10, "bold")
FONT_MONO = ("Consolas", 9)

COLOR_BG = "#0B0F19"
COLOR_CARD = "#161D30"
COLOR_CARD_SEL = "#232E4C"
COLOR_ACCENT = "#6366F1"
COLOR_ACCENT_HOVER = "#4F46E5"
COLOR_CYAN = "#06B6D4"
COLOR_GREEN = "#10B981"
COLOR_RED = "#EF4444"
COLOR_AMBER = "#F59E0B"
COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_MUTED = "#9CA3AF"
COLOR_BORDER = "#1E293B"
COLOR_BORDER_SEL = "#8B5CF6"

LATENCY_FAST_MS = 30
LATENCY_MEDIUM_MS = 60

ACCENT = COLOR_ACCENT
CARD = COLOR_CARD


def latency_color(latency_ms: float) -> str:
    if latency_ms < LATENCY_FAST_MS:
        return COLOR_GREEN
    if latency_ms < LATENCY_MEDIUM_MS:
        return COLOR_CYAN
    return COLOR_TEXT_MUTED


def apply_styles(root: tk.Misc) -> ttk.Style:
    """Install the dark theme overrides for the built-in ttk widgets."""
    style = ttk.Style(root)
    if system.is_windows() and "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure(
        "TCombobox",
        fieldbackground=COLOR_CARD,
        background=COLOR_CARD,
        foreground=COLOR_TEXT_PRIMARY,
        arrowcolor=COLOR_TEXT_PRIMARY,
        bordercolor=COLOR_BORDER,
        lightcolor=COLOR_CARD,
        darkcolor=COLOR_CARD,
        bd=0,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLOR_CARD)],
        foreground=[("readonly", COLOR_TEXT_PRIMARY)],
        selectbackground=[("readonly", COLOR_CARD)],
        selectforeground=[("readonly", COLOR_TEXT_PRIMARY)],
    )
    root.option_add("*TCombobox*Listbox.background", COLOR_CARD)
    root.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT_PRIMARY)
    root.option_add("*TCombobox*Listbox.selectBackground", COLOR_CARD_SEL)
    root.option_add("*TCombobox*Listbox.selectForeground", COLOR_TEXT_PRIMARY)

    style.configure(
        "TScrollbar",
        background=COLOR_CARD,
        troughcolor=COLOR_BG,
        bordercolor=COLOR_BORDER,
        arrowcolor=COLOR_TEXT_MUTED,
        darkcolor=COLOR_CARD,
        lightcolor=COLOR_CARD,
    )
    style.configure("Dark.Horizontal.TProgressbar", troughcolor=COLOR_BORDER, background=COLOR_CYAN)
    return style
