"""
Profiles panel – list view with CRUD operations.
"""

from __future__ import annotations

from datetime import datetime
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Optional

import customtkinter as ctk

from ui import theme as T
from ui.components import (
    DangerButton,
    GlassCard,
    PrimaryButton,
    Separator,
    StatusBadge,
    attach_tooltip,
)

if TYPE_CHECKING:
    from ui.app import QueekSyncApp


class ProfileRow(GlassCard):
    """Single row in the profile list."""

    def __init__(self, master, profile, app: "QueekSyncApp", **kw) -> None:
        kw.setdefault("height", 72)
        super().__init__(master, **kw)
        self.pack_propagate(False)
        self._profile = profile
        self._app = app
        self._build()

    def _build(self) -> None:
        p = self._profile

        # Left accent stripe
        ctk.CTkFrame(self, fg_color=p.color, width=4, corner_radius=0).place(
            x=0, y=0, relheight=1.0
        )

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(x=12, y=0, relwidth=1.0, relheight=1.0)

        # Name + description
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side="left", fill="y", pady=8)

        ctk.CTkLabel(
            left,
            text=p.name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=T.TEXT,
            anchor="w",
        ).pack(anchor="w")

        desc = p.description or f"{p.source.display_label()}  →  {p.destination.display_label()}"
        ctk.CTkLabel(
            left,
            text=desc[:80] + ("…" if len(desc) > 80 else ""),
            font=ctk.CTkFont(size=11),
            text_color=T.TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w")

        # Right side
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right", fill="y", padx=(0, 10), pady=10)

        StatusBadge(right, status=p.last_sync_status).pack(side="right", padx=6, anchor="center")

        # Schedule indicator
        if p.schedule.enabled:
            ctk.CTkLabel(
                right,
                text=f"⏱ every {p.schedule.interval_minutes}m",
                font=ctk.CTkFont(size=11),
                text_color=T.TEXT_DIM,
            ).pack(side="right", padx=4, anchor="center")

        # Action buttons
        btn_frame = ctk.CTkFrame(right, fg_color="transparent")
        btn_frame.pack(side="right", padx=4, anchor="center")

        for label, cmd, fg, hover, tip in [
            ("▶", self._sync,      T.ACCENT,    T.ACCENT_HOVER, "Run this profile immediately. Example: click this after updating source files and wanting a manual sync right now."),
            ("≋", self._compare,   T.BG_CARD,   T.BG_HOVER, "Compare source vs destination and show which side looks more up-to-date. Example: use this when you forgot which machine you edited on last."),
            ("✎", self._edit,      T.BG_CARD,   T.BG_HOVER, "Open the full editor for this profile. Example: use this to change paths, filters, schedule, or sync mode."),
            ("⧉", self._duplicate, T.BG_CARD,   T.BG_HOVER, "Create a copy of this profile. Example: duplicate a working backup profile, then adjust only the destination."),
            ("✕", self._delete,    "#450a0a",   "#7f1d1d", "Delete this profile permanently. Example: use this only when you no longer need the sync definition."),
        ]:
            btn = ctk.CTkButton(
                btn_frame,
                text=label,
                width=32,
                height=32,
                corner_radius=T.RADIUS_SM,
                font=ctk.CTkFont(size=14),
                fg_color=fg,
                hover_color=hover,
                text_color=T.TEXT,
                border_width=1,
                border_color=T.BORDER,
                command=cmd,
            )
            btn.pack(side="left", padx=2)
            attach_tooltip(btn, text=tip)

    # ------------------------------------------------------------------

    def _sync(self) -> None:
        self._app.start_sync(self._profile.id)

    def _compare(self) -> None:
        self._app.start_compare(self._profile.id)

    def _edit(self) -> None:
        from ui.profile_editor import ProfileEditorDialog
        ProfileEditorDialog(
            self._app.root,
            profile=self._profile,
            on_save=self._on_save,
        ).focus()

    def _duplicate(self) -> None:
        """Duplicate the current profile and refresh the UI."""
        try:
            self._app.profile_mgr.duplicate_profile(self._profile.id)
            self._app.refresh_panel("profiles")
            self._app.refresh_panel("dashboard")
        except ValueError as e:
            messagebox.showerror("Error", str(e))

    def _delete(self) -> None:
        from tkinter import messagebox
        if messagebox.askyesno(
            "Delete Profile",
            f"Delete profile  '{self._profile.name}'?\nThis cannot be undone.",
            icon="warning",
        ):
            self._app._scheduler.remove_profile(self._profile.id)
            self._app._watcher_mgr.remove(self._profile.id)
            self._app.profile_mgr.delete(self._profile.id)
            self._app.refresh_panel("profiles")
            self._app.refresh_panel("dashboard")

    def _on_save(self, profile) -> None:
        self._app.profile_mgr.save(profile)
        self._app._scheduler.update_profile(profile)
        self._app._watcher_mgr.update(profile)
        self._app.refresh_panel("profiles")
        self._app.refresh_panel("dashboard")


# ---------------------------------------------------------------------------

class ProfilesPanel(ctk.CTkFrame):
    def __init__(self, master, app: "QueekSyncApp", **kw) -> None:
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._app = app
        self.grid_columnconfigure(0, weight=1)
        self._build()

    def _build(self) -> None:
        profiles = self._app.profile_mgr.all()
        profiles_sorted = sorted(profiles, key=lambda p: p.name)

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=T.PAD_LG, pady=T.PAD_MD)

        ctk.CTkLabel(
            toolbar,
            text=f"{len(profiles)} profile(s)",
            font=ctk.CTkFont(size=12),
            text_color=T.TEXT_MUTED,
        ).pack(side="left")

        new_btn = PrimaryButton(
            toolbar,
            text="＋  New Profile",
            command=self._new_profile,
        )
        new_btn.pack(side="right")
        attach_tooltip(
            new_btn,
            text="Create a new sync profile from scratch. Example: use this to set up a backup between a local folder and an SFTP server or another local drive."
        )

        sync_all_btn = ctk.CTkButton(
            toolbar,
            text="⟳  Sync All",
            height=36,
            corner_radius=T.RADIUS_MD,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=T.BG_HOVER,
            text_color=T.TEXT_MUTED,
            border_color=T.BORDER,
            border_width=1,
            command=self._sync_all,
        )
        sync_all_btn.pack(side="right", padx=(0, T.PAD_SM))
        attach_tooltip(
            sync_all_btn,
            text="Run every enabled profile that is not already syncing. Example: click this before leaving for the day to process all pending backups in one step."
        )

        import_btn = ctk.CTkButton(
            toolbar,
            text="⬆  Import",
            height=36,
            corner_radius=T.RADIUS_MD,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=T.BG_HOVER,
            text_color=T.TEXT_MUTED,
            border_color=T.BORDER,
            border_width=1,
            command=self._import_profiles,
        )
        import_btn.pack(side="right", padx=(0, T.PAD_SM))
        attach_tooltip(
            import_btn,
            text="Load profiles from a previously exported .json file. Profiles with duplicate IDs will be skipped unless you choose to overwrite them.",
        )

        export_btn = ctk.CTkButton(
            toolbar,
            text="⬇  Export",
            height=36,
            corner_radius=T.RADIUS_MD,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=T.BG_HOVER,
            text_color=T.TEXT_MUTED,
            border_color=T.BORDER,
            border_width=1,
            command=self._export_profiles,
        )
        export_btn.pack(side="right", padx=(0, T.PAD_SM))
        attach_tooltip(
            export_btn,
            text="Save all profiles to a single .json file. Use this to back up your configuration or move profiles to another machine.",
        )

        Separator(self).grid(row=1, column=0, sticky="ew", padx=T.PAD_LG)

        # Scrollable list
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
                text="No profiles yet.\nUse  ＋ New Profile  to create your first sync.",
                font=ctk.CTkFont(size=14),
                text_color=T.TEXT_DIM,
                justify="center",
            ).pack(expand=True, pady=80)
            return

        for p in profiles_sorted:
            ProfileRow(scroll, p, self._app).pack(
                fill="x", pady=(0, T.CARD_GAP // 2)
            )

    # ------------------------------------------------------------------

    def _new_profile(self) -> None:
        from core.profile import Profile
        from ui.profile_editor import ProfileEditorDialog

        ProfileEditorDialog(
            self._app.root,
            profile=Profile(),
            on_save=self._on_save,
        ).focus()

    @staticmethod
    def _endpoint_kind(endpoint) -> str:
        return "Remote" if endpoint.type == "sftp" else "Local"

    def _sync_direction_label(self, profile) -> str:
        src_kind = self._endpoint_kind(profile.source)
        dst_kind = self._endpoint_kind(profile.destination)
        if profile.options.mode == "two_way":
            return f"{src_kind} <-> {dst_kind}"
        return f"{src_kind} -> {dst_kind}"

    def _sync_all(self) -> None:
        profiles_to_sync = [
            profile
            for profile in self._app.profile_mgr.all()
            if profile.enabled and not self._app.is_syncing(profile.id)
        ]

        if not profiles_to_sync:
            messagebox.showinfo(
                "Sync All",
                "There are no eligible profiles to sync right now.",
                parent=self._app.root,
            )
            return

        lines = [
            f"- {profile.name}: {self._sync_direction_label(profile)}"
            for profile in sorted(profiles_to_sync, key=lambda profile: profile.name.lower())
        ]
        prompt = (
            "The following profiles will be synced:\n\n"
            + "\n".join(lines)
            + "\n\nContinue with Sync All?"
        )

        if not messagebox.askyesno(
            "Confirm Sync All",
            prompt,
            parent=self._app.root,
            icon="warning",
        ):
            return

        for profile in profiles_to_sync:
            self._app.start_sync(profile.id)

    def _on_save(self, profile) -> None:
        self._app.profile_mgr.save(profile)
        self._app._scheduler.update_profile(profile)
        self._app._watcher_mgr.update(profile)
        self._app.refresh_panel("profiles")
        self._app.refresh_panel("dashboard")

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def _export_profiles(self) -> None:
        profiles = self._app.profile_mgr.all()
        if not profiles:
            messagebox.showinfo(
                "Export Profiles",
                "There are no profiles to export.",
                parent=self._app.root,
            )
            return

        filepath = filedialog.asksaveasfilename(
            parent=self._app.root,
            title="Export profiles to…",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="queeksync_profiles.json",
        )
        if not filepath:
            return

        try:
            count = self._app.profile_mgr.export_profiles(filepath)
            messagebox.showinfo(
                "Export Successful",
                f"Exported {count} profile(s) to:\n{filepath}",
                parent=self._app.root,
            )
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc), parent=self._app.root)

    def _import_profiles(self) -> None:
        filepath = filedialog.askopenfilename(
            parent=self._app.root,
            title="Import profiles from…",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return

        overwrite = messagebox.askyesno(
            "Import Profiles",
            "Overwrite existing profiles that share the same ID?\n\n"
            "• Yes – replace duplicates with the imported version.\n"
            "• No  – keep existing profiles and skip duplicates.",
            parent=self._app.root,
        )

        try:
            imported, skipped = self._app.profile_mgr.import_profiles(
                filepath, overwrite=overwrite
            )
        except Exception as exc:
            messagebox.showerror("Import Failed", str(exc), parent=self._app.root)
            return

        self._app.refresh_panel("profiles")
        self._app.refresh_panel("dashboard")

        messagebox.showinfo(
            "Import Complete",
            f"Imported: {imported} profile(s)\nSkipped:  {skipped} profile(s)",
            parent=self._app.root,
        )
