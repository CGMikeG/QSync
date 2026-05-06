"""
Profile editor dialog – tabbed form for creating / editing a sync profile.
"""

from __future__ import annotations

import os
import time
from tkinter import filedialog, messagebox
from typing import Callable, List, Optional

import customtkinter as ctk

from core.profile import FilterConfig, Profile, PROFILE_COLOURS, ScheduleConfig, get_delete_permission_issue
from ui import theme as T
from ui.components import ColourPicker, GlassCard, LabelledEntry, PrimaryButton, Separator, attach_tooltip


class ProfileEditorDialog(ctk.CTkToplevel):
    """Modal dialog for creating or editing a Profile."""

    def __init__(
        self,
        parent,
        profile: Profile,
        on_save: Callable[[Profile], None],
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._on_save = on_save
        self._working = Profile.from_dict(profile.to_dict())  # working copy

        self.title("Edit Profile" if profile.name != "New Profile" else "New Profile")
        self.geometry("720x580")
        self.minsize(640, 520)
        self.configure(fg_color=T.BG_PANEL)

        # Center over parent before building content
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - 720) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - 580) // 2
        self.geometry(f"720x580+{px}+{py}")

        self._build()

        # grab_set must be called after the window is fully mapped
        self.after(100, self._make_modal)

    # ==================================================================
    # Layout
    # ==================================================================

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Tab view
        tabs = ctk.CTkTabview(
            self,
            fg_color=T.BG_CARD,
            segmented_button_fg_color=T.BG_PANEL,
            segmented_button_selected_color=T.ACCENT,
            segmented_button_selected_hover_color=T.ACCENT_HOVER,
            segmented_button_unselected_color=T.BG_PANEL,
            segmented_button_unselected_hover_color=T.BG_HOVER,
            text_color=T.TEXT,
            border_color=T.BORDER,
            border_width=1,
            corner_radius=T.RADIUS_LG,
        )
        tabs.grid(row=0, column=0, sticky="nsew", padx=T.PAD_LG, pady=(T.PAD_LG, 0))

        for tab_name in ("General", "Source", "Destination", "Options", "Schedule", "Filters"):
            tabs.add(tab_name)
            tabs.tab(tab_name).configure(fg_color="transparent")

        self._build_general(tabs.tab("General"))
        self._build_endpoint(tabs.tab("Source"), is_source=True)
        self._build_endpoint(tabs.tab("Destination"), is_source=False)
        self._build_options(tabs.tab("Options"))
        self._build_schedule(tabs.tab("Schedule"))
        self._build_filters(tabs.tab("Filters"))

        # Bottom buttons
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.grid(row=1, column=0, sticky="ew", padx=T.PAD_LG, pady=T.PAD_MD)

        cancel_btn = ctk.CTkButton(
            btn_bar,
            text="Cancel",
            height=36,
            corner_radius=T.RADIUS_MD,
            fg_color="transparent",
            hover_color=T.BG_HOVER,
            text_color=T.TEXT_MUTED,
            border_color=T.BORDER,
            border_width=1,
            command=self.destroy,
        )
        cancel_btn.pack(side="right", padx=(T.PAD_SM, 0))
        attach_tooltip(
            cancel_btn,
            text="Close this editor without saving changes. Example: use this if you only wanted to review the current profile values."
        )

        save_btn = PrimaryButton(btn_bar, text="  Save Profile  ", command=self._save)
        save_btn.pack(side="right")
        attach_tooltip(
            save_btn,
            text="Save every tab in this profile. Example: after setting the source, destination, and schedule, click here to keep the profile for later runs."
        )

    # ==================================================================
    # Modal helper
    # ==================================================================

    def _make_modal(self) -> None:
        """Called after the window is mapped so grab_set() succeeds."""
        try:
            self.grab_set()
        except Exception:
            pass
        self.focus_set()

    # ==================================================================
    # Tab: General
    # ==================================================================

    def _build_general(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)

        frm = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=T.PAD_SM)
        frm.grid_columnconfigure(0, weight=1)

        # Name
        self._name_entry = LabelledEntry(
            frm,
            "Profile Name",
            placeholder="e.g. Home Backup",
            tooltip_text="Give this sync job a clear name. Example: Home Backup, NAS Mirror, or Client Archive. This name appears in the profile list and dashboard."
        )
        self._name_entry.set(self._working.name)
        self._name_entry.pack(fill="x", pady=(T.PAD_MD, T.PAD_SM))

        # Description
        desc_label = ctk.CTkLabel(
            frm, text="Description", font=ctk.CTkFont(size=12),
            text_color=T.TEXT_MUTED, anchor="w",
        )
        desc_label.pack(fill="x", padx=2, pady=(T.PAD_SM, 3))
        self._desc_box = ctk.CTkTextbox(
            frm, height=60,
            fg_color=T.BG_INPUT, border_color=T.BORDER, border_width=1,
            text_color=T.TEXT, corner_radius=T.RADIUS_SM,
        )
        self._desc_box.pack(fill="x")
        self._desc_box.insert("1.0", self._working.description)
        attach_tooltip(
            desc_label,
            self._desc_box,
            text="Add a short note about what this profile does. Example: Sync laptop photos to the office NAS every night. This helps distinguish similar profiles later."
        )

        # Colour
        colour_label = ctk.CTkLabel(
            frm, text="Accent Colour", font=ctk.CTkFont(size=12),
            text_color=T.TEXT_MUTED, anchor="w",
        )
        colour_label.pack(fill="x", padx=2, pady=(T.PAD_MD, 6))
        self._colour_picker = ColourPicker(frm, on_select=self._on_colour, selected=self._working.color)
        self._colour_picker.pack(anchor="w")
        attach_tooltip(
            colour_label,
            self._colour_picker,
            text="Pick the profile accent shown in the UI. Example: use blue for backups and green for mirrors so profiles are easier to spot at a glance."
        )

        # Enabled toggle
        self._enabled_var = ctk.BooleanVar(value=self._working.enabled)
        enabled_box = ctk.CTkCheckBox(
            frm,
            text="Profile enabled",
            variable=self._enabled_var,
            checkbox_height=18, checkbox_width=18,
            corner_radius=4,
            fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
            text_color=T.TEXT,
        )
        enabled_box.pack(anchor="w", pady=T.PAD_MD)
        attach_tooltip(
            enabled_box,
            text="Turn this profile on or off without deleting it. Example: disable a travel backup profile until the external drive is connected again."
        )

    def _on_colour(self, colour: str) -> None:
        self._working.color = colour

    # ==================================================================
    # Tab: Source / Destination (shared)
    # ==================================================================

    def _build_endpoint(self, parent, is_source: bool) -> None:
        cfg = self._working.source if is_source else self._working.destination

        frm = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=T.PAD_SM)
        frm.grid_columnconfigure((0, 1), weight=1)

        # Type selector
        type_label = ctk.CTkLabel(
            frm, text="Connection Type", font=ctk.CTkFont(size=12),
            text_color=T.TEXT_MUTED, anchor="w",
        )
        type_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=2, pady=(T.PAD_MD, 3))

        type_var = ctk.StringVar(value=cfg.type)

        type_seg = ctk.CTkSegmentedButton(
            frm,
            values=["local", "sftp"],
            variable=type_var,
            fg_color=T.BG_INPUT,
            selected_color=T.ACCENT,
            selected_hover_color=T.ACCENT_HOVER,
            unselected_color=T.BG_INPUT,
            unselected_hover_color=T.BG_HOVER,
            text_color=T.TEXT,
            corner_radius=T.RADIUS_SM,
        )
        type_seg.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, T.PAD_SM))
        endpoint_name = "source" if is_source else "destination"
        attach_tooltip(
            type_label,
            type_seg,
            text=f"Choose where the {endpoint_name} lives. Example: pick local for a folder on this computer, or sftp for a server like backup.example.com over SSH."
        )

        # Local path row
        local_frame = ctk.CTkFrame(frm, fg_color="transparent")
        local_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=T.PAD_XS)
        local_frame.grid_columnconfigure(0, weight=1)

        if is_source:
            path_entry_holder = LabelledEntry(
                local_frame,
                "Local Path",
                placeholder="/path/to/source",
                tooltip_text="Enter the folder path on this computer. Example: /home/mike/Documents or /mnt/backup/photos. This is the local directory QueekSync reads from or writes to."
            )
        else:
            path_entry_holder = LabelledEntry(
                local_frame,
                "Local Path",
                placeholder="/path/to/destination",
                tooltip_text="Enter the folder path on this computer. Example: /home/mike/Backups or /media/usb/Archive. This is the local directory QueekSync reads from or writes to."
            )
        path_entry_holder.set(cfg.path if cfg.type == "local" else "")
        path_entry_holder.grid(row=0, column=0, sticky="ew")
        if not is_source:
            path_entry_holder.entry.bind("<KeyRelease>", self._schedule_delete_notice_refresh, add="+")
            path_entry_holder.entry.bind("<FocusOut>", self._schedule_delete_notice_refresh, add="+")

        browse_btn = ctk.CTkButton(
            local_frame, text="Browse…", width=90, height=30,
            corner_radius=T.RADIUS_SM, fg_color=T.BG_HOVER,
            hover_color=T.BORDER_BRIGHT, text_color=T.TEXT,
            command=lambda: self._browse(path_entry_holder),
        )
        browse_btn.grid(row=0, column=1, sticky="s", padx=(T.PAD_SM, 0))
        attach_tooltip(
            browse_btn,
            text="Open a folder picker for the local path field. Example: use this to avoid mistyping home folders or mounted drive paths."
        )

        local_test_label = ctk.CTkLabel(local_frame, text="", font=ctk.CTkFont(size=11), text_color=T.TEXT_MUTED)
        local_test_label.grid(row=1, column=0, sticky="w", pady=(T.PAD_XS, 0))

        local_test_btn = ctk.CTkButton(
            local_frame, text="Test Folder Access", width=150, height=30,
            corner_radius=T.RADIUS_SM, fg_color="transparent",
            hover_color=T.BG_HOVER, text_color=T.ACCENT,
            border_color=T.ACCENT, border_width=1,
            command=lambda lbl=local_test_label, entry=path_entry_holder, src=is_source: self._test_local_path(entry, lbl, src),
        )
        local_test_btn.grid(row=1, column=1, sticky="e", padx=(T.PAD_SM, 0), pady=(T.PAD_XS, 0))
        attach_tooltip(
            local_test_btn,
            text="Check that this local folder exists and is accessible. Example: for a destination folder, QueekSync also writes and removes a tiny probe file to confirm it can really save files there."
        )

        local_dir_test_label = ctk.CTkLabel(local_frame, text="", font=ctk.CTkFont(size=11), text_color=T.TEXT_MUTED)
        local_dir_test_btn = ctk.CTkButton(
            local_frame, text="Create Test Folder", width=150, height=30,
            corner_radius=T.RADIUS_SM, fg_color="transparent",
            hover_color=T.BG_HOVER, text_color=T.ACCENT,
            border_color=T.ACCENT, border_width=1,
            command=lambda lbl=local_dir_test_label, entry=path_entry_holder: self._create_local_test_folder(entry, lbl),
        )
        if not is_source:
            local_dir_test_label.grid(row=2, column=0, sticky="w", pady=(T.PAD_XS, 0))
            local_dir_test_btn.grid(row=2, column=1, sticky="e", padx=(T.PAD_SM, 0), pady=(T.PAD_XS, 0))
            attach_tooltip(
                local_dir_test_btn,
                text="Create a real testconnection folder inside the destination path. Example: use this to confirm QueekSync can make new folders before running a sync."
            )

        # SFTP fields
        sftp_frame = ctk.CTkFrame(frm, fg_color="transparent")
        sftp_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        sftp_frame.grid_columnconfigure((0, 1), weight=1)

        host_entry = LabelledEntry(
            sftp_frame,
            "Host",
            placeholder="192.168.1.100 or hostname",
            tooltip_text="Enter the server address for this SFTP endpoint. Example: 192.168.1.100, nas.local, or files.example.com. QueekSync connects to this host over SSH. If QueekSync is running inside WSL and the target is on Windows, use the Windows host IP instead of the WSL IP address."
        )
        host_entry.set(cfg.host)
        host_entry.grid(row=0, column=0, sticky="ew", padx=(0, T.PAD_SM), pady=T.PAD_XS)

        port_entry = LabelledEntry(
            sftp_frame,
            "Port",
            placeholder="22",
            tooltip_text="Set the SSH port used by the server. Example: 22 for standard SSH or 2222 if your server uses a custom port."
        )
        port_entry.set(str(cfg.port))
        port_entry.grid(row=0, column=1, sticky="ew", pady=T.PAD_XS)

        user_entry = LabelledEntry(
            sftp_frame,
            "Username",
            tooltip_text="Enter the SSH account name used to sign in. Example: mike, backupbot, or deploy."
        )
        user_entry.set(cfg.username)
        user_entry.grid(row=1, column=0, sticky="ew", padx=(0, T.PAD_SM), pady=T.PAD_XS)

        pass_entry = LabelledEntry(
            sftp_frame,
            "Password",
            show="●",
            tooltip_text="Enter the SSH password if the server allows password login. Leave this blank when you use an SSH key instead."
        )
        pass_entry.set(cfg.password)
        pass_entry.grid(row=1, column=1, sticky="ew", pady=T.PAD_XS)

        key_entry = LabelledEntry(
            sftp_frame,
            "SSH Key File (optional)",
            placeholder="~/.ssh/id_rsa",
            tooltip_text="Optional path to a private SSH key file. Example: ~/.ssh/id_rsa or /home/mike/.ssh/backup_ed25519. Use this when the server authenticates with keys."
        )
        key_entry.set(cfg.key_file)
        key_entry.grid(row=2, column=0, columnspan=2, sticky="ew", pady=T.PAD_XS)

        # Remote path row with Browse button
        sftp_path_row = ctk.CTkFrame(sftp_frame, fg_color="transparent")
        sftp_path_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=T.PAD_XS)
        sftp_path_row.grid_columnconfigure(0, weight=1)

        sftp_path_entry = LabelledEntry(
            sftp_path_row,
            "Remote Path",
            placeholder="/home/user/data",
            tooltip_text="Remote folder path on the server. Example: /home/backup/photos or /srv/archive/client-a. This is the directory QueekSync will sync over SFTP."
        )
        sftp_path_entry.set(cfg.path if cfg.type == "sftp" else "")
        sftp_path_entry.grid(row=0, column=0, sticky="ew")

        remote_browse_btn = ctk.CTkButton(
            sftp_path_row, text="📁  Browse…", width=110, height=30,
            corner_radius=T.RADIUS_SM, fg_color=T.BG_HOVER,
            hover_color=T.BORDER_BRIGHT, text_color=T.TEXT,
            command=lambda: self._browse_remote(
                host_entry, port_entry, user_entry, pass_entry, key_entry, sftp_path_entry
            ),
        )
        remote_browse_btn.grid(row=0, column=1, sticky="s", padx=(T.PAD_SM, 0))
        attach_tooltip(
            remote_browse_btn,
            text="Browse folders on the remote server after you fill in the connection details. Example: connect, inspect /home or /srv, then pick the exact remote folder instead of typing it manually."
        )

        # Test connection button
        test_label = ctk.CTkLabel(sftp_frame, text="", font=ctk.CTkFont(size=11), text_color=T.TEXT_MUTED)
        test_label.grid(row=4, column=1, sticky="w")

        test_btn = ctk.CTkButton(
            sftp_frame, text="⟳  Test Connection", width=160, height=30,
            corner_radius=T.RADIUS_SM, fg_color="transparent",
            hover_color=T.BG_HOVER, text_color=T.ACCENT,
            border_color=T.ACCENT, border_width=1,
            command=lambda lbl=test_label: self._test_sftp(host_entry, port_entry, user_entry, pass_entry, key_entry, lbl),
        )
        test_btn.grid(row=4, column=0, sticky="w", pady=T.PAD_SM)
        attach_tooltip(
            test_btn,
            text="Check that the host, port, username, password, and key settings work. Example: click this before saving to catch a wrong hostname or SSH key path early."
        )

        access_label = ctk.CTkLabel(sftp_frame, text="", font=ctk.CTkFont(size=11), text_color=T.TEXT_MUTED)
        access_label.grid(row=5, column=1, sticky="w")

        access_btn = ctk.CTkButton(
            sftp_frame, text="⟳  Test Folder Access", width=180, height=30,
            corner_radius=T.RADIUS_SM, fg_color="transparent",
            hover_color=T.BG_HOVER, text_color=T.ACCENT,
            border_color=T.ACCENT, border_width=1,
            command=lambda lbl=access_label, src=is_source: self._test_sftp_path_access(
                host_entry, port_entry, user_entry, pass_entry, key_entry, sftp_path_entry, lbl, src
            ),
        )
        access_btn.grid(row=5, column=0, sticky="w", pady=(0, T.PAD_SM))
        attach_tooltip(
            access_btn,
            text="Check that the remote folder exists and is usable. Example: for a destination folder, QueekSync uploads and deletes a tiny test file to confirm write access before you run a full sync."
        )

        create_dir_label = ctk.CTkLabel(sftp_frame, text="", font=ctk.CTkFont(size=11), text_color=T.TEXT_MUTED)
        create_dir_btn = ctk.CTkButton(
            sftp_frame, text="⟳  Create Test Folder", width=180, height=30,
            corner_radius=T.RADIUS_SM, fg_color="transparent",
            hover_color=T.BG_HOVER, text_color=T.ACCENT,
            border_color=T.ACCENT, border_width=1,
            command=lambda lbl=create_dir_label: self._create_sftp_test_folder(
                host_entry, port_entry, user_entry, pass_entry, key_entry, sftp_path_entry, lbl
            ),
        )
        if not is_source:
            create_dir_label.grid(row=6, column=1, sticky="w")
            create_dir_btn.grid(row=6, column=0, sticky="w", pady=(0, T.PAD_SM))
            attach_tooltip(
                create_dir_btn,
                text="Create a real testconnection folder inside the destination path. Example: use this to confirm the server lets QueekSync create nested folders before starting a sync."
            )

        # Show/hide frames based on type
        def _update_type(*_):
            t = type_var.get()
            if t == "local":
                local_frame.grid()
                sftp_frame.grid_remove()
            else:
                local_frame.grid_remove()
                sftp_frame.grid()

        type_var.trace_add("write", _update_type)
        _update_type()

        # Store references for save
        if is_source:
            self._src_type = type_var
            self._src_local_path = path_entry_holder
            self._src_host = host_entry
            self._src_port = port_entry
            self._src_user = user_entry
            self._src_pass = pass_entry
            self._src_key = key_entry
            self._src_sftp_path = sftp_path_entry
        else:
            self._dst_type = type_var
            self._dst_local_path = path_entry_holder
            self._dst_host = host_entry
            self._dst_port = port_entry
            self._dst_user = user_entry
            self._dst_pass = pass_entry
            self._dst_key = key_entry
            self._dst_sftp_path = sftp_path_entry

    def _browse(self, entry: LabelledEntry) -> None:
        path = filedialog.askdirectory(title="Select folder", parent=self)
        if not path:
            return
        if not self.winfo_exists() or not entry.winfo_exists():
            return
        entry.set(path)
        if self.winfo_exists():
            self._schedule_delete_notice_refresh()

    def _browse_remote(
        self,
        host_entry,
        port_entry,
        user_entry,
        pass_entry,
        key_entry,
        path_entry: LabelledEntry,
    ) -> None:
        host = host_entry.get().strip()
        if not host:
            from tkinter import messagebox
            messagebox.showwarning(
                "SFTP Browser",
                "Please fill in the Host field before browsing.",
                parent=self,
            )
            return
        try:
            port = int(port_entry.get() or 22)
        except ValueError:
            port = 22

        from ui.sftp_browser import SFTPBrowserDialog

        def _on_select(selected_path: str) -> None:
            if not self.winfo_exists() or not path_entry.winfo_exists():
                return
            path_entry.set(selected_path)

        SFTPBrowserDialog(
            parent=self,
            host=host,
            port=port,
            username=user_entry.get(),
            password=pass_entry.get(),
            key_file=key_entry.get(),
            initial_path=path_entry.get() or "/",
            on_select=_on_select,
        )

    def _test_sftp(self, host, port, user, pw, key, label) -> None:
        import threading

        # Read all widget values in the UI thread before spawning the worker.
        # Tkinter widgets must never be accessed from a background thread.
        host_val = host.get().strip()
        port_val = int(port.get() or 22)
        user_val = user.get().strip()
        pw_val = pw.get()
        key_val = key.get().strip()

        label.configure(text="Connecting…", text_color=T.TEXT_MUTED)

        def _try():
            try:
                import paramiko  # type: ignore[import]
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(
                    hostname=host_val,
                    port=port_val,
                    username=user_val,
                    password=pw_val or None,
                    key_filename=os.path.expanduser(key_val) if key_val else None,
                    timeout=8,
                )
                c.close()
                self.after(0, lambda: label.configure(text="✔ Connected", text_color=T.SUCCESS))
            except Exception as exc:
                msg = str(exc)[:60]
                self.after(0, lambda: label.configure(text=f"✖ {msg}", text_color=T.ERROR))

        threading.Thread(target=_try, daemon=True).start()

    def _test_local_path(self, entry: LabelledEntry, label, is_source: bool) -> None:
        path = os.path.expanduser(entry.get().strip())
        role = "Source" if is_source else "Destination"
        if not path:
            label.configure(text=f"✖ {role} path is empty", text_color=T.ERROR)
            return
        if not os.path.exists(path):
            label.configure(text=f"✖ {role} folder not found", text_color=T.ERROR)
            return
        if not os.path.isdir(path):
            label.configure(text=f"✖ {role} path is not a folder", text_color=T.ERROR)
            return

        try:
            if is_source:
                if not os.access(path, os.R_OK | os.X_OK):
                    raise PermissionError("folder is not readable")
                os.listdir(path)
                label.configure(text="✔ Source folder exists and is readable", text_color=T.SUCCESS)
                return

            if not os.access(path, os.W_OK | os.X_OK):
                raise PermissionError("folder is not writable")
            stamp = time.strftime("%Y%m%d-%H%M%S")
            probe_name = f"foldertest-{stamp}.txt"
            probe_path = os.path.join(path, probe_name)
            with open(probe_path, "w", encoding="utf-8") as fh:
                fh.write(f"QueekSync folder access test\nCreated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            label.configure(text=f"✔ Destination folder exists and created {probe_name}", text_color=T.SUCCESS)
        except Exception as exc:
            label.configure(text=f"✖ {str(exc)[:80]}", text_color=T.ERROR)

    def _create_local_test_folder(self, entry: LabelledEntry, label) -> None:
        path = os.path.expanduser(entry.get().strip())
        if not path:
            label.configure(text="✖ Destination path is empty", text_color=T.ERROR)
            return
        if not os.path.isdir(path):
            label.configure(text="✖ Destination folder not found", text_color=T.ERROR)
            return
        try:
            test_dir = os.path.join(path, "testconnection")
            os.makedirs(test_dir, exist_ok=True)
            label.configure(text="✔ Created destination folder testconnection", text_color=T.SUCCESS)
        except Exception as exc:
            label.configure(text=f"✖ {str(exc)[:80]}", text_color=T.ERROR)

    def _test_sftp_path_access(self, host, port, user, pw, key, path_entry, label, is_source: bool) -> None:
        import threading

        host_val = host.get().strip()
        try:
            port_val = int(port.get() or 22)
        except ValueError:
            port_val = 22
        user_val = user.get().strip()
        pw_val = pw.get()
        key_val = key.get().strip()
        path_val = path_entry.get().strip()
        role = "source" if is_source else "destination"

        if not host_val or not user_val or not path_val:
            label.configure(text=f"✖ Fill in host, username, and remote path first", text_color=T.ERROR)
            return

        label.configure(text=f"Testing {role} folder…", text_color=T.TEXT_MUTED)

        def _try():
            client = None
            sftp = None
            try:
                import paramiko  # type: ignore[import]

                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    hostname=host_val,
                    port=port_val,
                    username=user_val,
                    password=pw_val or None,
                    key_filename=os.path.expanduser(key_val) if key_val else None,
                    timeout=8,
                )
                sftp = client.open_sftp()
                info = sftp.stat(path_val)
                import stat as stat_mod
                if not stat_mod.S_ISDIR(info.st_mode):
                    raise NotADirectoryError(f"{path_val} is not a folder")

                if is_source:
                    sftp.listdir(path_val)
                    self.after(0, lambda: label.configure(text="✔ Source folder exists and is readable", text_color=T.SUCCESS))
                    return

                stamp = time.strftime("%Y%m%d-%H%M%S")
                probe_name = f"foldertest-{stamp}.txt"
                probe_path = f"{path_val.rstrip('/')}/{probe_name}"
                with sftp.open(probe_path, "w") as fh:
                    fh.write(f"QueekSync folder access test\nCreated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                self.after(0, lambda name=probe_name: label.configure(text=f"✔ Destination folder exists and uploaded {name}", text_color=T.SUCCESS))
            except Exception as exc:
                msg = str(exc).replace("\n", " ")[:90]
                self.after(0, lambda m=msg: label.configure(text=f"✖ {m}", text_color=T.ERROR))
            finally:
                try:
                    if sftp:
                        sftp.close()
                except Exception:
                    pass
                try:
                    if client:
                        client.close()
                except Exception:
                    pass

        threading.Thread(target=_try, daemon=True).start()

    def _create_sftp_test_folder(self, host, port, user, pw, key, path_entry, label) -> None:
        import threading

        host_val = host.get().strip()
        try:
            port_val = int(port.get() or 22)
        except ValueError:
            port_val = 22
        user_val = user.get().strip()
        pw_val = pw.get()
        key_val = key.get().strip()
        path_val = path_entry.get().strip()

        if not host_val or not user_val or not path_val:
            label.configure(text="✖ Fill in host, username, and remote path first", text_color=T.ERROR)
            return

        label.configure(text="Creating destination test folder…", text_color=T.TEXT_MUTED)

        def _try():
            client = None
            sftp = None
            try:
                import paramiko  # type: ignore[import]

                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    hostname=host_val,
                    port=port_val,
                    username=user_val,
                    password=pw_val or None,
                    key_filename=os.path.expanduser(key_val) if key_val else None,
                    timeout=8,
                )
                sftp = client.open_sftp()
                import stat as stat_mod
                info = sftp.stat(path_val)
                if not stat_mod.S_ISDIR(info.st_mode):
                    raise NotADirectoryError(f"{path_val} is not a folder")

                test_dir = f"{path_val.rstrip('/')}/testconnection"
                try:
                    existing = sftp.stat(test_dir)
                    if not stat_mod.S_ISDIR(existing.st_mode):
                        raise NotADirectoryError(f"{test_dir} exists but is not a folder")
                except FileNotFoundError:
                    sftp.mkdir(test_dir)
                self.after(0, lambda: label.configure(text="✔ Created destination folder testconnection", text_color=T.SUCCESS))
            except Exception as exc:
                msg = str(exc).replace("\n", " ")[:90]
                self.after(0, lambda m=msg: label.configure(text=f"✖ {m}", text_color=T.ERROR))
            finally:
                try:
                    if sftp:
                        sftp.close()
                except Exception:
                    pass
                try:
                    if client:
                        client.close()
                except Exception:
                    pass

        threading.Thread(target=_try, daemon=True).start()

    # ==================================================================
    # Tab: Options
    # ==================================================================

    def _build_options(self, parent) -> None:
        frm = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=T.PAD_SM)

        opts = self._working.options

        # Sync mode
        mode_label = ctk.CTkLabel(
            frm, text="Sync Mode", font=ctk.CTkFont(size=12),
            text_color=T.TEXT_MUTED, anchor="w",
        )
        mode_label.pack(fill="x", padx=2, pady=(T.PAD_MD, 4))

        self._mode_var = ctk.StringVar(value=opts.mode)
        mode_frame = ctk.CTkFrame(frm, fg_color="transparent")
        mode_frame.pack(fill="x")

        modes = [
            ("one_way", "→  One-way",  "Copy source → destination only"),
            ("mirror",  "⬡  Mirror",   "One-way + delete files absent from source"),
            ("two_way", "⇄  Two-way",  "Sync in both directions"),
        ]
        for val, lbl, tip in modes:
            row = ctk.CTkFrame(mode_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            mode_btn = ctk.CTkRadioButton(
                row, text=lbl, value=val, variable=self._mode_var,
                fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, text_color=T.TEXT,
            )
            mode_btn.pack(side="left")
            ctk.CTkLabel(
                row, text=tip, font=ctk.CTkFont(size=11), text_color=T.TEXT_DIM,
            ).pack(side="left", padx=T.PAD_SM)
            attach_tooltip(
                mode_btn,
                text=f"{tip}. Example: choose {lbl.replace('  ', ' ').strip()} when that matches how you want files copied and deleted."
            )
        attach_tooltip(
            mode_label,
            text="Choose how file changes should flow between source and destination. Example: use One-way for backups, Mirror for exact replicas, and Two-way when both sides can change."
        )

        Separator(frm).pack(fill="x", pady=T.PAD_MD)

        # Boolean options
        bool_opts = [
            ("_opt_delete",    "Delete extra files in destination",  opts.delete_extra),
            ("_opt_ts",        "Preserve file timestamps",           opts.preserve_timestamps),
            ("_opt_symlinks",  "Follow symbolic links",              opts.follow_symlinks),
            ("_opt_checksum",  "Verify file checksums (slower)",     opts.verify_checksums),
            ("_opt_rsync",     "Use rsync over SSH when available",  opts.use_rsync_ssh),
        ]
        for attr, label, default in bool_opts:
            var = ctk.BooleanVar(value=default)
            setattr(self, attr, var)
            box = ctk.CTkCheckBox(
                frm, text=label, variable=var,
                checkbox_height=18, checkbox_width=18, corner_radius=4,
                fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, text_color=T.TEXT,
            )
            box.pack(anchor="w", pady=3)
            if attr == "_opt_delete":
                self._delete_opt_box = box
            tip_text = {
                "_opt_delete": "Remove files from the destination when they no longer exist in the source. Example: enable this for a true mirror backup, but leave it off for archives where old files must stay. On Linux, the destination folder itself must be writable and executable by your user for deletes to succeed.",
                "_opt_ts": "Keep original modification times after copying. Example: enable this when photo dates or build timestamps matter.",
                "_opt_symlinks": "Follow symbolic links and sync the files they point to. Example: turn this on only if your source folder contains useful linked directories.",
                "_opt_checksum": "Compare file contents using checksums instead of faster metadata checks. Example: use this for critical backups when you want higher confidence and can accept slower runs.",
                "_opt_rsync": "Prefer rsync over SSH for one-way or mirror local-to-remote syncs. Example: enable this for Linux or WSL targets when rsync is installed on both sides and you want faster changed-file transfers.",
            }
            attach_tooltip(box, text=tip_text[attr])

        self._delete_opt_saved_value = self._opt_delete.get()
        self._delete_mode_note = ctk.CTkLabel(
            frm,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=T.TEXT_DIM,
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self._delete_mode_note.pack(fill="x", pady=(0, T.PAD_XS))
        self._delete_mode_note.pack_forget()

        self._linux_delete_notice = ctk.CTkFrame(
            frm,
            fg_color="#2b1f12",
            border_color="#7c5a16",
            border_width=1,
            corner_radius=T.RADIUS_MD,
        )
        self._linux_delete_notice.grid_columnconfigure(0, weight=1)

        self._linux_delete_notice_label = ctk.CTkLabel(
            self._linux_delete_notice,
            text="",
            justify="left",
            anchor="w",
            text_color=T.TEXT,
            font=ctk.CTkFont(size=11),
            wraplength=560,
        )
        self._linux_delete_notice_label.grid(row=0, column=0, sticky="ew", padx=T.PAD_MD, pady=T.PAD_MD)

        self._copy_fix_btn = ctk.CTkButton(
            self._linux_delete_notice,
            text="Copy Linux Fix Commands",
            height=30,
            width=190,
            corner_radius=T.RADIUS_SM,
            fg_color="transparent",
            hover_color=T.BG_HOVER,
            text_color=T.ACCENT,
            border_color=T.ACCENT,
            border_width=1,
            command=self._copy_linux_delete_fix,
        )
        self._copy_fix_btn.grid(row=1, column=0, sticky="w", padx=T.PAD_MD, pady=(0, T.PAD_MD))
        attach_tooltip(
            self._copy_fix_btn,
            text="Copy the recommended Linux permission commands for this destination folder. Example: paste them into a terminal, run them once, then retry the sync."
        )
        self._linux_delete_notice.pack_forget()

        self._mode_var.trace_add("write", self._schedule_delete_notice_refresh)
        self._opt_delete.trace_add("write", self._schedule_delete_notice_refresh)
        self._dst_type.trace_add("write", self._schedule_delete_notice_refresh)
        self._schedule_delete_notice_refresh()

        Separator(frm).pack(fill="x", pady=T.PAD_MD)

        # Bandwidth limit
        bw_frame = ctk.CTkFrame(frm, fg_color="transparent")
        bw_frame.pack(fill="x")
        bw_label = ctk.CTkLabel(
            bw_frame, text="Bandwidth limit (KB/s, 0 = unlimited):",
            font=ctk.CTkFont(size=12), text_color=T.TEXT_MUTED,
        )
        bw_label.pack(side="left")
        self._bw_entry = ctk.CTkEntry(
            bw_frame, width=80,
            fg_color=T.BG_INPUT, border_color=T.BORDER, text_color=T.TEXT,
            corner_radius=T.RADIUS_SM,
        )
        self._bw_entry.insert(0, str(opts.bandwidth_limit_kbps))
        self._bw_entry.pack(side="left", padx=T.PAD_SM)
        attach_tooltip(
            bw_label,
            self._bw_entry,
            text="Limit transfer speed in kilobytes per second. Example: enter 2048 to cap sync traffic at about 2 MB/s, or 0 to let QueekSync use full available bandwidth."
        )

    # ==================================================================
    # Tab: Schedule
    # ==================================================================

    def _build_schedule(self, parent) -> None:
        frm = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=T.PAD_SM, pady=T.PAD_MD)

        sched = self._working.schedule

        self._sched_enabled = ctk.BooleanVar(value=sched.enabled)

        sched_box = ctk.CTkCheckBox(
            frm,
            text="Enable automatic sync on schedule",
            variable=self._sched_enabled,
            checkbox_height=20, checkbox_width=20, corner_radius=4,
            fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, text_color=T.TEXT,
            font=ctk.CTkFont(size=13),
        )
        sched_box.pack(anchor="w", pady=(T.PAD_MD, T.PAD_LG))
        attach_tooltip(
            sched_box,
            text="Run this profile automatically instead of only manual syncs. Example: enable this for hourly document backups or nightly server mirrors."
        )

        Separator(frm).pack(fill="x", pady=T.PAD_SM)

        interval_title = ctk.CTkLabel(
            frm, text="Run every (minutes):",
            font=ctk.CTkFont(size=12), text_color=T.TEXT_MUTED,
        )
        interval_title.pack(anchor="w", pady=(T.PAD_MD, 4))

        self._interval_slider = ctk.CTkSlider(
            frm, from_=1, to=1440, number_of_steps=143,
            fg_color=T.BORDER, button_color=T.ACCENT,
            button_hover_color=T.ACCENT_HOVER, progress_color=T.ACCENT,
            command=self._update_interval_label,
        )
        self._interval_slider.set(sched.interval_minutes)
        self._interval_slider.pack(fill="x", pady=(0, T.PAD_XS))
        attach_tooltip(
            interval_title,
            self._interval_slider,
            text="Set how often the scheduled sync should run. Example: 15 minutes for active work folders, 60 minutes for general backups, or 1440 for once per day."
        )

        self._interval_label = ctk.CTkLabel(
            frm,
            text=self._format_interval(sched.interval_minutes),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=T.ACCENT,
        )
        self._interval_label.pack(anchor="w")

        ctk.CTkLabel(
            frm,
            text="Note: also watches source folder for changes when enabled.",
            font=ctk.CTkFont(size=11), text_color=T.TEXT_DIM,
        ).pack(anchor="w", pady=(T.PAD_LG, 0))

    def _update_interval_label(self, value) -> None:
        self._interval_label.configure(text=self._format_interval(int(value)))

    @staticmethod
    def _format_interval(minutes: int) -> str:
        if minutes < 60:
            return f"{minutes} minute(s)"
        h = minutes // 60
        m = minutes % 60
        return f"{h}h {m}m" if m else f"{h} hour(s)"

    # ==================================================================
    # Tab: Filters
    # ==================================================================

    def _build_filters(self, parent) -> None:
        frm = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=T.PAD_SM, pady=T.PAD_SM)
        frm.grid_columnconfigure((0, 1), weight=1)

        flt = self._working.filters

        def _make_pattern_box(label: str, default: List[str], row: int):
            title = ctk.CTkLabel(
                frm, text=label, font=ctk.CTkFont(size=12, weight="bold"),
                text_color=T.TEXT_MUTED, anchor="w",
            )
            title.grid(row=row * 2, column=row % 2, sticky="w", padx=T.PAD_SM, pady=(T.PAD_MD, 3))
            box = ctk.CTkTextbox(
                frm, height=130,
                fg_color=T.BG_INPUT, border_color=T.BORDER, border_width=1,
                text_color=T.TEXT, corner_radius=T.RADIUS_SM,
                font=ctk.CTkFont(family="Courier New", size=12),
            )
            box.grid(row=row * 2 + 1, column=row % 2, sticky="nsew", padx=T.PAD_SM, pady=(0, T.PAD_SM))
            box.insert("1.0", "\n".join(default))
            return title, box

        include_label, self._include_box = _make_pattern_box("Include Patterns (fnmatch)", flt.include_patterns, 0)
        exclude_label, self._exclude_box = _make_pattern_box("Exclude Patterns (fnmatch)", flt.exclude_patterns, 1)
        attach_tooltip(
            include_label,
            self._include_box,
            text="Only files matching these patterns will be synced. Example: add *.docx and *.xlsx to back up office files only. Leave this empty to include everything unless excluded."
        )
        attach_tooltip(
            exclude_label,
            self._exclude_box,
            text="Files or folders matching these patterns will be skipped. Example: add .venv*, .git, node_modules, or *.tmp to avoid syncing virtual environments, repository metadata, and generated files. On Windows/WSL you can also exclude *:Zone.Identifier to ignore Windows download metadata streams."
        )

        filter_hint = ctk.CTkLabel(
            frm,
            text="One pattern per line. Examples:  *.txt   docs/**   .git",
            font=ctk.CTkFont(size=11), text_color=T.TEXT_DIM,
        )
        filter_hint.grid(row=4, column=0, columnspan=2, sticky="w", padx=T.PAD_SM)
        attach_tooltip(
            filter_hint,
            text="Patterns use fnmatch-style matching. Examples: *.jpg matches image files, docs/** targets everything under docs, and folder names like .venv or .git exclude those directories and their contents."
        )

    # ==================================================================
    # Save
    # ==================================================================

    def _save(self) -> None:
        p = self._working

        # General
        p.name = self._name_entry.get().strip() or "Unnamed Profile"
        p.description = self._desc_box.get("1.0", "end-1c").strip()
        p.enabled = self._enabled_var.get()

        # Source
        src = p.source
        src.type = self._src_type.get()
        if src.type == "local":
            src.path = self._src_local_path.get()
        else:
            src.host = self._src_host.get()
            src.port = int(self._src_port.get() or 22)
            src.username = self._src_user.get()
            src.password = self._src_pass.get()
            src.key_file = self._src_key.get()
            src.path = self._src_sftp_path.get()

        # Destination
        dst = p.destination
        dst.type = self._dst_type.get()
        if dst.type == "local":
            dst.path = self._dst_local_path.get()
        else:
            dst.host = self._dst_host.get()
            dst.port = int(self._dst_port.get() or 22)
            dst.username = self._dst_user.get()
            dst.password = self._dst_pass.get()
            dst.key_file = self._dst_key.get()
            dst.path = self._dst_sftp_path.get()

        # Options
        p.options.mode = self._mode_var.get()
        p.options.delete_extra = self._opt_delete.get()
        p.options.preserve_timestamps = self._opt_ts.get()
        p.options.follow_symlinks = self._opt_symlinks.get()
        p.options.verify_checksums = self._opt_checksum.get()
        p.options.use_rsync_ssh = self._opt_rsync.get()
        try:
            p.options.bandwidth_limit_kbps = max(0, int(self._bw_entry.get() or 0))
        except ValueError:
            p.options.bandwidth_limit_kbps = 0

        # Schedule
        p.schedule.enabled = self._sched_enabled.get()
        p.schedule.interval_minutes = int(self._interval_slider.get())

        # Filters
        def _lines(box) -> List[str]:
            return [l.strip() for l in box.get("1.0", "end-1c").splitlines() if l.strip()]

        p.filters.include_patterns = _lines(self._include_box)
        p.filters.exclude_patterns = _lines(self._exclude_box)

        permission_issue = get_delete_permission_issue(p)
        if permission_issue:
            if not messagebox.askyesno(
                "Linux Permission Warning",
                permission_issue + "\n\nSave this profile anyway?",
                parent=self,
            ):
                return

        # Commit to original
        self._profile.__dict__.update(p.__dict__)

        # Destroy (releases modal grab) before refreshing the panel
        _on_save = self._on_save
        _profile = self._profile
        self.destroy()
        _on_save(_profile)

    def _schedule_delete_notice_refresh(self, *_args) -> None:
        self.after_idle(self._refresh_delete_notice)

    def _refresh_delete_notice(self) -> None:
        self._refresh_delete_option_state()

        if not hasattr(self, "_linux_delete_notice"):
            return

        preview = Profile.from_dict(self._working.to_dict())
        preview.destination.type = self._dst_type.get()
        if preview.destination.type == "local":
            preview.destination.path = self._dst_local_path.get().strip()
        else:
            preview.destination.path = self._dst_sftp_path.get().strip()
        preview.options.mode = self._mode_var.get()
        preview.options.delete_extra = self._opt_delete.get()

        issue = get_delete_permission_issue(preview)
        if issue:
            self._linux_delete_notice_label.configure(
                text=(
                    "Linux delete warning: this profile can remove files, but the current destination folder "
                    "does not have the write and execute permissions your user needs for deletion."
                )
            )
            self._linux_delete_notice.pack(fill="x", pady=(T.PAD_SM, 0))
        else:
            self._linux_delete_notice.pack_forget()

    def _refresh_delete_option_state(self) -> None:
        if not hasattr(self, "_delete_opt_box"):
            return

        is_two_way = self._mode_var.get() == "two_way"
        if is_two_way:
            if self._delete_opt_box.cget("state") != "disabled":
                self._delete_opt_saved_value = self._opt_delete.get()
                self._opt_delete.set(False)
                self._delete_opt_box.configure(state="disabled")
            self._delete_mode_note.configure(
                text="Delete extra files is disabled in Two-way mode because bidirectional sync should not remove files that exist on only one side."
            )
            self._delete_mode_note.pack(fill="x", pady=(0, T.PAD_XS))
        else:
            if self._delete_opt_box.cget("state") == "disabled":
                self._delete_opt_box.configure(state="normal")
                self._opt_delete.set(self._delete_opt_saved_value)
            self._delete_mode_note.pack_forget()

    def _copy_linux_delete_fix(self) -> None:
        path = self._dst_local_path.get().strip()
        if not path:
            messagebox.showwarning(
                "Linux Permission Fix",
                "Set a local destination folder first so QueekSync can build the correct permission commands.",
                parent=self,
            )
            return

        expanded = os.path.expanduser(path)
        commands = (
            f'sudo chown -R $USER:$USER "{expanded}"\n'
            f'chmod -R u+rwX "{expanded}"'
        )
        self.clipboard_clear()
        self.clipboard_append(commands)
        messagebox.showinfo(
            "Linux Permission Fix",
            "Copied the recommended Linux permission commands to the clipboard.",
            parent=self,
        )
