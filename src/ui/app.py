"""
Main application window and top-level wiring.
"""

from __future__ import annotations

import getpass
import queue
import shutil
import subprocess
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import customtkinter as ctk

from core.config import ConfigManager
from core.profile import ProfileManager, get_delete_permission_issue
from core.scheduler import SyncScheduler
from core.syncer import SyncEngine, SyncEvent
from core.watcher import WatcherManager
from ui import theme as T
from ui.sidebar import Sidebar


class QueekSyncApp:
    """Application entry-point; owns the main CTk window and all shared state."""

    def __init__(self) -> None:
        # ---- configuration & data ---------------------------------
        self.config_mgr = ConfigManager()
        self.profile_mgr = ProfileManager()
        cfg = self.config_mgr.config

        # ---- customtkinter global setup ---------------------------
        appearance = cfg.theme if cfg.theme in ("dark", "light") else "dark"
        ctk.set_appearance_mode(appearance)
        ctk.set_default_color_theme("blue")

        # ---- main window ------------------------------------------
        self.root = ctk.CTk()
        self.root.title("QueekSync")
        self.root.geometry(f"{cfg.window_width}x{cfg.window_height}")
        self.root.minsize(900, 600)
        self.root.configure(fg_color=T.BG_ROOT)

        # Subtle window transparency (works on Windows & most Linux compositors)
        try:
            self.root.attributes("-alpha", 0.97)
        except Exception:
            pass

        # DWM Acrylic blur on Windows 10/11
        if sys.platform == "win32":
            self._enable_win_blur()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- shared runtime state ---------------------------------
        self._engines: Dict[str, SyncEngine] = {}   # profile_id → engine
        self._event_queue: queue.Queue[SyncEvent] = queue.Queue()
        self._log_file_path: str = ""
        self._log_fh = None
        self.refresh_file_logging()

        # ---- background services ----------------------------------
        self._scheduler = SyncScheduler(on_trigger=self._schedule_trigger)
        self._watcher_mgr = WatcherManager(on_change=self._watch_trigger)

        # Initialise scheduler for existing profiles
        for p in self.profile_mgr.all():
            self._scheduler.update_profile(p)
            self._watcher_mgr.update(p)
        self._scheduler.start()

        # ---- build UI ---------------------------------------------
        self._panels: Dict[str, ctk.CTkFrame] = {}
        self._active_panel: str = ""
        self._build_ui()

        # ---- start event pump -------------------------------------
        self._pump_events()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = Sidebar(self.root, on_navigate=self.navigate)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Content container
        self._content = ctk.CTkFrame(self.root, fg_color=T.BG_PANEL, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(1, weight=1)

        # Header bar
        self._header = ctk.CTkFrame(
            self._content,
            fg_color=T.BG_PANEL,
            corner_radius=0,
            height=T.HEADER_H,
            border_color=T.BORDER,
            border_width=0,
        )
        self._header.grid(row=0, column=0, sticky="ew")
        self._header.grid_propagate(False)

        self._header_title = ctk.CTkLabel(
            self._header,
            text="Dashboard",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=T.TEXT,
        )
        self._header_title.pack(side="left", padx=T.PAD_LG, pady=T.PAD_SM)

        # Panel host frame
        self._panel_host = ctk.CTkFrame(self._content, fg_color="transparent", corner_radius=0)
        self._panel_host.grid(row=1, column=0, sticky="nsew")
        self._panel_host.grid_columnconfigure(0, weight=1)
        self._panel_host.grid_rowconfigure(0, weight=1)

        # Lazy-load panels on first navigation
        self.navigate("dashboard")

    # ==================================================================
    # Navigation
    # ==================================================================

    _PAGE_TITLES = {
        "dashboard": "Dashboard",
        "profiles":  "Profiles",
        "monitor":   "Monitor",
        "settings":  "Settings",
    }

    def navigate(self, page_id: str) -> None:
        if page_id == self._active_panel:
            return

        # Hide current panel
        if self._active_panel and self._active_panel in self._panels:
            self._panels[self._active_panel].grid_remove()

        # Lazy-create panel
        if page_id not in self._panels:
            self._panels[page_id] = self._create_panel(page_id)

        self._panels[page_id].grid(row=0, column=0, sticky="nsew")
        self._active_panel = page_id
        self.sidebar.set_active(page_id)
        self._header_title.configure(text=self._PAGE_TITLES.get(page_id, page_id.title()))

    def _create_panel(self, page_id: str) -> ctk.CTkFrame:
        from ui.dashboard import DashboardPanel
        from ui.monitor_panel import MonitorPanel
        from ui.profiles_panel import ProfilesPanel
        from ui.settings_panel import SettingsPanel

        host = self._panel_host
        if page_id == "dashboard":
            return DashboardPanel(host, app=self)
        if page_id == "profiles":
            return ProfilesPanel(host, app=self)
        if page_id == "monitor":
            return MonitorPanel(host, app=self)
        if page_id == "settings":
            return SettingsPanel(host, app=self)
        return ctk.CTkFrame(host, fg_color="transparent")

    def refresh_panel(self, page_id: str) -> None:
        """Destroy and recreate a panel so it picks up data changes."""
        if page_id in self._panels:
            self._panels[page_id].destroy()
            del self._panels[page_id]
        if self._active_panel == page_id:
            self._active_panel = ""
            self.navigate(page_id)

    # ==================================================================
    # Sync operations (called from UI)
    # ==================================================================

    def start_sync(self, profile_id: str, interactive: bool = True) -> None:
        profile = self.profile_mgr.get(profile_id)
        if profile is None:
            return
        if profile_id in self._engines and self._engines[profile_id].is_running():
            return  # already running

        validation_error = self._validate_sync_permissions(profile)
        if validation_error:
            if interactive and self._attempt_elevated_permission_fix(profile, validation_error):
                validation_error = self._validate_sync_permissions(profile)
            self._report_blocked_sync(profile_id, profile.name, validation_error, interactive)
            if validation_error:
                profile.last_sync_status = "error"
                self.profile_mgr.save(profile)
                return

        def _cb(event: SyncEvent) -> None:
            event._profile_id = profile_id  # type: ignore[attr-defined]
            self._log_event_to_file(event)
            self._event_queue.put(event)

        profile.last_sync_status = "running"
        self.profile_mgr.save(profile)

        engine = SyncEngine(profile, event_cb=_cb)
        self._engines[profile_id] = engine
        engine.start(blocking=False)

        # Navigate to monitor
        self.navigate("monitor")

    def start_compare(self, profile_id: str) -> None:
        profile = self.profile_mgr.get(profile_id)
        if profile is None:
            return
        if profile_id in self._engines and self._engines[profile_id].is_running():
            return

        def _cb(event: SyncEvent) -> None:
            event._profile_id = profile_id  # type: ignore[attr-defined]
            self._log_event_to_file(event)
            self._event_queue.put(event)

        engine = SyncEngine(profile, event_cb=_cb, compare_only=True)
        self._engines[profile_id] = engine
        engine.start(blocking=False)
        self.navigate("monitor")

    def cancel_sync(self, profile_id: str) -> None:
        engine = self._engines.get(profile_id)
        if engine:
            engine.cancel()

    def toggle_pause_sync(self, profile_id: str) -> None:
        engine = self._engines.get(profile_id)
        if engine:
            engine.toggle_pause()

    def get_engine(self, profile_id: str) -> Optional[SyncEngine]:
        return self._engines.get(profile_id)

    def is_syncing(self, profile_id: str) -> bool:
        engine = self._engines.get(profile_id)
        return engine is not None and engine.is_running()

    # ==================================================================
    # Background triggers
    # ==================================================================

    def _schedule_trigger(self, profile_id: str) -> None:
        self.start_sync(profile_id, interactive=False)

    def _watch_trigger(self, profile_id: str) -> None:
        if not self.is_syncing(profile_id):
            self.start_sync(profile_id, interactive=False)

    def _validate_sync_permissions(self, profile) -> Optional[str]:
        return get_delete_permission_issue(profile)

    def _attempt_elevated_permission_fix(self, profile, message: str) -> bool:
        if sys.platform != "linux" or profile.destination.type != "local":
            return False

        from tkinter import messagebox

        dst_path = profile.destination.path.strip()
        if not dst_path:
            return False

        proceed = messagebox.askyesno(
            f"Admin Access Needed: {profile.name}",
            message
            + "\n\n"
            + "QueekSync can ask for administrator approval now, repair this destination folder, and then continue the sync automatically.\n\n"
            + "Proceed?",
            parent=self.root,
        )
        if not proceed:
            return False

        success, error = self._run_elevated_permission_fix(dst_path)
        if success:
            return True

        messagebox.showerror(
            "Permission Repair Failed",
            "QueekSync could not get administrator approval to repair the destination folder.\n\n"
            + error,
            parent=self.root,
        )
        return False

    def _run_elevated_permission_fix(self, path: str) -> tuple[bool, str]:
        username = getpass.getuser()
        fix_script = (
            "import subprocess, sys; "
            "username, target = sys.argv[1], sys.argv[2]; "
            "subprocess.run(['chown', '-R', f'{username}:{username}', target], check=True); "
            "subprocess.run(['chmod', '-R', 'u+rwX', target], check=True)"
        )

        cached_sudo = ["sudo", "-n", sys.executable, "-c", fix_script, username, path]
        try:
            subprocess.run(cached_sudo, check=True, capture_output=True, text=True)
            return True, ""
        except FileNotFoundError:
            pass
        except subprocess.CalledProcessError:
            pass

        if not shutil.which("pkexec"):
            return (
                False,
                "No graphical privilege helper is available on this system. Install polkit/pkexec or run the suggested chown/chmod commands manually.",
            )

        try:
            subprocess.run(
                ["pkexec", sys.executable, "-c", fix_script, username, path],
                check=True,
                capture_output=True,
                text=True,
            )
            return True, ""
        except FileNotFoundError:
            return False, "The pkexec command is not available on this system."
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            if not details:
                details = "Administrator approval was denied or the permission repair command failed."
            return False, details

    def _report_blocked_sync(self, profile_id: str, profile_name: str, message: str, interactive: bool) -> None:
        if not message:
            return
        event = SyncEvent("error", message)
        event._profile_id = profile_id  # type: ignore[attr-defined]
        self._log_event_to_file(event)
        self._event_queue.put(event)

        if interactive:
            from tkinter import messagebox

            messagebox.showerror(f"Cannot Start Sync: {profile_name}", message)

    # ==================================================================
    # Event pump (queue → UI thread)
    # ==================================================================

    def _pump_events(self) -> None:
        """Poll the event queue and forward to the Monitor panel."""
        try:
            while True:
                event = self._event_queue.get_nowait()
                self._dispatch_event(event)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._pump_events)

    def _dispatch_event(self, event: SyncEvent) -> None:
        # Forward to monitor panel if it exists
        if "monitor" in self._panels:
            self._panels["monitor"].on_sync_event(event)  # type: ignore[attr-defined]
        # Refresh dashboard card when sync finishes
        if event.kind in ("success", "error", "warning") and "dashboard" in self._panels:
            self._panels["dashboard"].refresh()  # type: ignore[attr-defined]

    # ==================================================================
    # Window close
    # ==================================================================

    def _on_close(self) -> None:
        # Persist window size
        self.config_mgr.config.window_width = self.root.winfo_width()
        self.config_mgr.config.window_height = self.root.winfo_height()
        self.config_mgr.save()

        self._scheduler.stop()
        self._watcher_mgr.stop_all()
        try:
            if self._log_fh:
                self._log_fh.close()
        except Exception:
            pass
        self.root.destroy()

    def get_log_file_path(self) -> str:
        return self._log_file_path

    def refresh_file_logging(self) -> None:
        self._log_file_path = self._compute_log_file_path()

        try:
            if self._log_fh:
                self._log_fh.close()
        except Exception:
            pass
        self._log_fh = None

        try:
            log_dir = Path(self._log_file_path).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self._log_file_path, "a", encoding="utf-8")
            if os.path.getsize(self._log_file_path) == 0:
                started = Path(sys.argv[0]).name or "QueekSync"
                self._log_fh.write(f"[{Path(self._log_file_path).name}] Logging started for {started}\n")
            self._log_fh.flush()
        except Exception:
            self._log_fh = None

    @staticmethod
    def _compute_log_file_path() -> str:
        if os.name == "nt":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
            log_dir = Path(base) / "QueekSync"
        else:
            base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            log_dir = Path(base) / "QueekSync"
        return str(log_dir / "log.txt")

    def _log_event_to_file(self, event: SyncEvent) -> None:
        cfg = self.config_mgr.config
        if not self._log_fh:
            return

        level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        min_level = level_map.get(str(cfg.log_level).upper(), 20)
        kind_level = 20
        if event.kind == "warning":
            kind_level = 30
        elif event.kind == "error":
            kind_level = 40

        if kind_level < min_level:
            return

        pid = getattr(event, "_profile_id", "unknown")
        profile = self.profile_mgr.get(pid)
        pname = profile.name if profile else pid[:8]
        ts = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        msg = event.message.replace("\n", " ").strip()
        rel = event.rel_path.strip()
        suffix = f" | {rel}" if rel else ""
        line = f"[{ts}] [{pname}] [{event.kind.upper()}] {msg}{suffix}\n"
        try:
            self._log_fh.write(line)
            self._log_fh.flush()
        except Exception:
            pass

    # ==================================================================
    # Windows DWM glass
    # ==================================================================

    def _enable_win_blur(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes  # noqa: F401

            HWND = ctypes.windll.user32.GetParent(self.root.winfo_id())

            class _MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth",    ctypes.c_int),
                    ("cxRightWidth",   ctypes.c_int),
                    ("cyTopHeight",    ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            margins = _MARGINS(-1, -1, -1, -1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(HWND, ctypes.byref(margins))
        except Exception:
            pass  # Graceful degradation on unsupported platforms

    # ==================================================================
    # Main loop
    # ==================================================================

    def run(self) -> None:
        self.root.mainloop()
