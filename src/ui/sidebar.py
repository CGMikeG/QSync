"""
Sidebar navigation panel.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

import customtkinter as ctk

from ui import theme as T
from ui.components import Separator, attach_tooltip


NAV_ITEMS: List[Tuple[str, str, str]] = [
    ("dashboard",  "⬡  Dashboard",  "Overview of all profiles and activity"),
    ("profiles",   "☰  Profiles",   "Manage sync profiles"),
    ("monitor",    "◉  Monitor",    "Live sync progress and logs"),
    ("settings",   "⚙  Settings",   "Application preferences"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_navigate: Callable[[str], None],
        **kw,
    ) -> None:
        kw.setdefault("fg_color", T.BG_SIDEBAR)
        kw.setdefault("corner_radius", 0)
        kw.setdefault("width", T.SIDEBAR_W)
        super().__init__(master, **kw)
        self.grid_propagate(False)

        self._on_navigate = on_navigate
        self._active_page: str = ""
        self._nav_btns: Dict[str, ctk.CTkButton] = {}

        self._build()

    # ------------------------------------------------------------------

    def _build(self) -> None:
        # Logo / branding
        logo_frame = ctk.CTkFrame(self, fg_color="transparent", height=64)
        logo_frame.pack(fill="x", padx=T.PAD_MD, pady=(T.PAD_LG, T.PAD_SM))
        logo_frame.pack_propagate(False)

        ctk.CTkLabel(
            logo_frame,
            text="Queek",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=T.ACCENT,
        ).pack(side="left")
        ctk.CTkLabel(
            logo_frame,
            text="Sync",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=T.TEXT,
        ).pack(side="left", padx=(6, 0))

        Separator(self).pack(fill="x", padx=T.PAD_MD, pady=(0, T.PAD_SM))

        # Navigation buttons
        nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        nav_frame.pack(fill="x", padx=T.PAD_SM, pady=T.PAD_SM)

        for page_id, label, _tip in NAV_ITEMS:
            btn = ctk.CTkButton(
                nav_frame,
                text=label,
                anchor="w",
                height=42,
                corner_radius=T.RADIUS_MD,
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                hover_color=T.BG_HOVER,
                text_color=T.TEXT_MUTED,
                border_width=0,
                command=lambda p=page_id: self._click(p),
            )
            btn.pack(fill="x", pady=2)
            attach_tooltip(
                btn,
                text=f"Open {label.replace('⬡', '').replace('☰', '').replace('◉', '').replace('⚙', '').strip()}. Example: {_tip}."
            )
            self._nav_btns[page_id] = btn

        # Bottom section
        self._bottom = ctk.CTkFrame(self, fg_color="transparent")
        self._bottom.pack(side="bottom", fill="x", padx=T.PAD_SM, pady=T.PAD_MD)

        Separator(self._bottom).pack(fill="x", padx=T.PAD_SM, pady=(0, T.PAD_SM))

        ctk.CTkLabel(
            self._bottom,
            text="Cross-platform file sync",
            font=ctk.CTkFont(size=10),
            text_color=T.TEXT_DIM,
        ).pack()

    # ------------------------------------------------------------------

    def _click(self, page_id: str) -> None:
        self.set_active(page_id)
        self._on_navigate(page_id)

    def set_active(self, page_id: str) -> None:
        self._active_page = page_id
        for pid, btn in self._nav_btns.items():
            if pid == page_id:
                btn.configure(
                    fg_color=T.BG_HOVER,
                    text_color=T.TEXT,
                    border_width=1,
                    border_color=T.ACCENT,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=T.TEXT_MUTED,
                    border_width=0,
                )
