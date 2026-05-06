"""
Dashboard panel – overview of all profiles with quick-sync cards.
"""

from __future__ import annotations

from datetime import datetime
from tkinter import messagebox
from typing import TYPE_CHECKING, Dict, List

import customtkinter as ctk

from ui import theme as T
from ui.components import GlassCard, PrimaryButton, Separator, StatTile, StatusBadge, attach_tooltip

if TYPE_CHECKING:
    from ui.app import QueekSyncApp


class ProfileCard(GlassCard):
    """Card widget showing a single profile's summary."""

    def __init__(self, master, profile, app: "QueekSyncApp", **kw) -> None:
        kw.setdefault("width", 300)
        super().__init__(master, **kw)

        self._profile = profile
        self._app = app
        self._build()

    def _build(self) -> None:
        p = self._profile
        pad = 18
        vertical_pad = 14

        # ── Colour accent bar (left edge, fixed 4 px wide) ─────────────
        ctk.CTkFrame(
            self,
            fg_color=p.color,
            corner_radius=0,
            width=4,
        ).place(x=0, y=0, relheight=1.0)

        # ── Main content frame (sits to the right of accent bar) ───────
        content = ctk.CTkFrame(
            self,
            fg_color="transparent",
        )
        content.grid(row=0, column=0, sticky="nsew", padx=pad, pady=vertical_pad)
        self.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        # Name + status row
        top = ctk.CTkFrame(content, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text=p.name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=T.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        StatusBadge(top, status=p.last_sync_status).grid(row=0, column=1, sticky="e", padx=4)

        # Paths
        src_label = p.source.display_label() or "(source not set)"
        dst_label = p.destination.display_label() or "(destination not set)"

        paths = ctk.CTkFrame(content, fg_color="transparent")
        paths.grid(row=1, column=0, sticky="ew")

        ctk.CTkLabel(
            paths,
            text=f"▲  {src_label}",
            font=ctk.CTkFont(size=11),
            text_color=T.TEXT_MUTED,
            anchor="w",
            wraplength=240,
        ).pack(anchor="w")

        ctk.CTkLabel(
            paths,
            text=f"▼  {dst_label}",
            font=ctk.CTkFont(size=11),
            text_color=T.TEXT_MUTED,
            anchor="w",
            wraplength=240,
        ).pack(anchor="w")

        # Last sync + mode
        meta = ctk.CTkFrame(content, fg_color="transparent")
        meta.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        # Last sync
        last_sync_txt = "Never"
        if p.last_sync:
            try:
                dt = datetime.fromisoformat(p.last_sync)
                last_sync_txt = dt.strftime("%Y-%m-%d  %H:%M")
            except Exception:
                last_sync_txt = p.last_sync

        ctk.CTkLabel(
            meta,
            text=f"Last sync:  {last_sync_txt}",
            font=ctk.CTkFont(size=11),
            text_color=T.TEXT_DIM,
            anchor="w",
        ).pack(anchor="w")

        # Mode badge
        mode_map = {"one_way": "→ One-way", "mirror": "↔ Mirror", "two_way": "⇄ Two-way"}
        ctk.CTkLabel(
            meta,
            text=mode_map.get(p.options.mode, p.options.mode),
            font=ctk.CTkFont(size=11),
            text_color=T.ACCENT,
            anchor="w",
        ).pack(anchor="w")

        # Buttons
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        btn_frame.grid_columnconfigure(0, weight=1)

        sync_btn = PrimaryButton(
            btn_frame,
            text="▶  Sync Now",
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._sync,
        )
        sync_btn.grid(row=0, column=0, sticky="ew")
        attach_tooltip(
            sync_btn,
            text="Start this profile immediately. Example: use this after dropping new files into the source folder and wanting the destination updated now."
        )

        actions = ctk.CTkFrame(btn_frame, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        compare_btn = ctk.CTkButton(
            actions,
            text="≋  Compare",
            height=28,
            width=110,
            corner_radius=T.RADIUS_MD,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover_color=T.BG_HOVER,
            text_color=T.TEXT_MUTED,
            border_color=T.BORDER,
            border_width=1,
            command=self._compare,
        )
        compare_btn.pack(side="left", padx=(0, 6))
        attach_tooltip(
            compare_btn,
            text="Compare source vs destination and report which side looks more up-to-date. Example: use this when you forgot which computer you edited on last."
        )

        for label, cmd, tip in [
            ("✎", self._edit, "Open this profile in the editor. Example: use this to change folders, credentials, filters, or schedule settings."),
            ("⧉", self._duplicate, "Create a copy of this profile. Example: duplicate a working profile, then adjust only the destination."),
            ("✕", self._delete, "Delete this profile permanently. Example: use this only when you no longer need the sync definition."),
        ]:
            btn = ctk.CTkButton(
                actions,
                text=label,
                width=32,
                height=28,
                corner_radius=T.RADIUS_SM,
                font=ctk.CTkFont(size=13),
                fg_color="transparent" if label != "✕" else "#450a0a",
                hover_color=T.BG_HOVER if label != "✕" else "#7f1d1d",
                text_color=T.TEXT_MUTED if label != "✕" else T.ERROR,
                border_color=T.BORDER if label != "✕" else T.ERROR,
                border_width=1,
                command=cmd,
            )
            btn.pack(side="left", padx=(0, 6))
            attach_tooltip(btn, text=tip)

    def _sync(self) -> None:
        self._app.start_sync(self._profile.id)

    def _compare(self) -> None:
        self._app.start_compare(self._profile.id)

    def _edit(self) -> None:
        from ui.profile_editor import ProfileEditorDialog
        dlg = ProfileEditorDialog(
            self._app.root,
            profile=self._profile,
            on_save=self._on_save,
        )
        dlg.focus()

    def _duplicate(self) -> None:
        try:
            self._app.profile_mgr.duplicate_profile(self._profile.id)
            self._app.refresh_panel("dashboard")
            self._app.refresh_panel("profiles")
        except ValueError as exc:
            messagebox.showerror("Error", str(exc), parent=self._app.root)

    def _delete(self) -> None:
        if not messagebox.askyesno(
            "Delete Profile",
            f"Delete profile  '{self._profile.name}'?\nThis cannot be undone.",
            icon="warning",
            parent=self._app.root,
        ):
            return
        self._app._scheduler.remove_profile(self._profile.id)
        self._app._watcher_mgr.remove(self._profile.id)
        self._app.profile_mgr.delete(self._profile.id)
        self._app.refresh_panel("dashboard")
        self._app.refresh_panel("profiles")

    def _on_save(self, profile) -> None:
        self._app.profile_mgr.save(profile)
        self._app._scheduler.update_profile(profile)
        self._app._watcher_mgr.update(profile)
        self._app.refresh_panel("dashboard")
        self._app.refresh_panel("profiles")


class DashboardPanel(ctk.CTkFrame):
    def __init__(self, master, app: "QueekSyncApp", **kw) -> None:
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build()

    def _build(self) -> None:
        profiles = self._app.profile_mgr.all()
        total = len(profiles)
        active = sum(1 for p in profiles if p.last_sync_status == "running")
        ok = sum(1 for p in profiles if p.last_sync_status == "success")

        # ---- Stats row -----------------------------------------------
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.grid(row=0, column=0, sticky="ew", padx=T.PAD_LG, pady=(T.PAD_LG, 0))

        StatTile(stats_frame, "Total Profiles", str(total), T.ACCENT).pack(side="left", padx=(0, T.CARD_GAP))
        StatTile(stats_frame, "Running",        str(active), T.WARNING).pack(side="left", padx=(0, T.CARD_GAP))
        StatTile(stats_frame, "Last OK",        str(ok),    T.SUCCESS).pack(side="left")

        # Quick-add button
        new_btn = ctk.CTkButton(
            stats_frame,
            text="＋  New Profile",
            corner_radius=T.RADIUS_MD,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#ffffff",
            height=38,
            width=150,
            command=self._new_profile,
        )
        new_btn.pack(side="right")
        attach_tooltip(
            new_btn,
            text="Create a new profile from the dashboard. Example: use this when you want to add another backup job without switching to the Profiles page first."
        )

        Separator(self, "horizontal").grid(
            row=1, column=0, sticky="ew", padx=T.PAD_LG, pady=T.PAD_SM
        )

        # ---- Scrollable profile cards --------------------------------
        scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=T.BORDER,
            scrollbar_button_hover_color=T.BORDER_BRIGHT,
        )
        scroll.grid(row=2, column=0, sticky="nsew", padx=T.PAD_LG, pady=T.PAD_SM)
        self.grid_rowconfigure(2, weight=1)

        if not profiles:
            ctk.CTkLabel(
                scroll,
                text="No profiles yet.\nClick  ＋ New Profile  to get started.",
                font=ctk.CTkFont(size=14),
                text_color=T.TEXT_DIM,
                justify="center",
            ).pack(expand=True, pady=80)
            return

        # 3-column responsive grid of cards
        col_count = 3
        card_width = 300
        column_width = card_width + T.CARD_GAP

        for col_ in range(col_count):
            scroll.grid_columnconfigure(col_, weight=0, minsize=column_width, pad=T.CARD_GAP)
        scroll.grid_columnconfigure(col_count, weight=1)

        for idx, profile in enumerate(sorted(profiles, key=lambda p: p.name)):
            row_ = idx // col_count
            col_ = idx % col_count
            card = ProfileCard(scroll, profile, self._app)
            card.grid(row=row_, column=col_, padx=(0, T.CARD_GAP), pady=T.CARD_GAP // 2, sticky="nw")

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild card grid after data changes."""
        for child in self.winfo_children():
            child.destroy()
        self._build()

    def _new_profile(self) -> None:
        from core.profile import Profile
        from ui.profile_editor import ProfileEditorDialog

        new_p = Profile()
        dlg = ProfileEditorDialog(
            self._app.root,
            profile=new_p,
            on_save=self._on_new_save,
        )
        dlg.focus()

    def _on_new_save(self, profile) -> None:
        self._app.profile_mgr.save(profile)
        self._app._scheduler.update_profile(profile)
        self._app._watcher_mgr.update(profile)
        self.refresh()
        self._app.refresh_panel("profiles")
