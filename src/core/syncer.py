"""
Core synchronisation engine.

Supports:
  - Local ↔ Local
  - Local ↔ SFTP (upload)
  - SFTP ↔ Local (download)
  - SFTP ↔ SFTP  (via temp file)

Sync modes:
  one_way  – copy source → destination (never delete)
  mirror   – one_way + delete files in destination that are absent from source
  two_way  – bidirectional: copy newer file to the other side
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shlex
import signal
import stat
import subprocess
import shutil
import time
import tempfile
import threading
from datetime import datetime
from enum import Enum, auto
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Status & event types
# ---------------------------------------------------------------------------

class SyncStatus(Enum):
    IDLE = auto()
    SCANNING = auto()
    SYNCING = auto()
    COMPLETED = auto()
    ERROR = auto()
    CANCELLED = auto()


class SyncEvent:
    """A single progress / log event emitted by the engine."""

    def __init__(
        self,
        kind: str,           # "info" | "compare" | "copy" | "delete" | "skip" | "error" | "success" | "warning"
        message: str,
        rel_path: str = "",
        progress: float = 0.0,
        bytes_done: int = 0,
        bytes_total: int = 0,
    ) -> None:
        self.kind = kind
        self.message = message
        self.rel_path = rel_path
        self.progress = progress          # 0.0 – 1.0
        self.bytes_done = bytes_done
        self.bytes_total = bytes_total
        self.timestamp = datetime.now()

    def __repr__(self) -> str:  # noqa: D105
        return f"[{self.kind.upper()}] {self.message}"


class SyncCancelled(Exception):
    """Raised to abort a running sync immediately."""


def _apply_bandwidth_limit(started_at: float, bytes_done: int, limit_kbps: int) -> None:
    if limit_kbps <= 0:
        return
    expected_elapsed = bytes_done / float(limit_kbps * 1024)
    actual_elapsed = time.monotonic() - started_at
    if expected_elapsed > actual_elapsed:
        time.sleep(expected_elapsed - actual_elapsed)


# ---------------------------------------------------------------------------
# File info
# ---------------------------------------------------------------------------

class FileInfo:
    __slots__ = ("abs_path", "rel_path", "size", "mtime", "is_dir", "_checksum")

    def __init__(
        self,
        abs_path: str,
        rel_path: str,
        size: int,
        mtime: float,
        is_dir: bool = False,
    ) -> None:
        self.abs_path = abs_path
        self.rel_path = rel_path
        self.size = size
        self.mtime = mtime
        self.is_dir = is_dir
        self._checksum: Optional[str] = None

    def checksum(self) -> str:
        if self._checksum is None:
            h = hashlib.md5()
            with open(self.abs_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            self._checksum = h.hexdigest()
        return self._checksum


# ---------------------------------------------------------------------------
# Local filesystem
# ---------------------------------------------------------------------------

class LocalFS:
    """Operations on the local file system."""

    @staticmethod
    def scan(
        root: str,
        include_patterns: List[str],
        exclude_patterns: List[str],
        follow_symlinks: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        pause_cb: Optional[Callable[[], None]] = None,
    ) -> List[FileInfo]:
        root_path = os.path.abspath(root)
        if not os.path.exists(root_path):
            raise FileNotFoundError(f"Source path does not exist: {root_path}")

        files: List[FileInfo] = []
        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=follow_symlinks):
            if pause_cb:
                pause_cb()
            if cancel_cb and cancel_cb():
                raise SyncCancelled()
            # Filter out excluded directories in-place
            dirnames[:] = [
                d for d in dirnames
                if not LocalFS._excluded(
                    d,
                    exclude_patterns,
                    include_patterns,
                    os.path.relpath(os.path.join(dirpath, d), root_path).replace("\\", "/"),
                    is_dir=True,
                )
                and (follow_symlinks or not os.path.islink(os.path.join(dirpath, d)))
            ]
            for name in filenames:
                if pause_cb:
                    pause_cb()
                if cancel_cb and cancel_cb():
                    raise SyncCancelled()
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root_path).replace("\\", "/")
                if LocalFS._excluded(name, exclude_patterns, include_patterns, rel, is_dir=False):
                    continue
                if not follow_symlinks and os.path.islink(full):
                    continue
                try:
                    st = os.stat(full)
                    files.append(FileInfo(full, rel, st.st_size, st.st_mtime))
                    if progress_cb:
                        progress_cb(rel)
                except OSError:
                    continue

            # Also record directories
            for name in dirnames:
                if pause_cb:
                    pause_cb()
                if cancel_cb and cancel_cb():
                    raise SyncCancelled()
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root_path).replace("\\", "/")
                try:
                    st = os.stat(full)
                    files.append(FileInfo(full, rel, 0, st.st_mtime, is_dir=True))
                except OSError:
                    continue

        return files

    @staticmethod
    def _excluded(
        name: str,
        exclude: List[str],
        include: List[str],
        rel: str = "",
        is_dir: bool = False,
    ) -> bool:
        for pat in exclude:
            if LocalFS._matches_pattern(name, rel, pat, is_dir):
                return True
        # Always traverse directories unless they are explicitly excluded.
        # This lets file include patterns like *.txt still match deeper files.
        if is_dir:
            return False
        if include:
            for pat in include:
                if LocalFS._matches_pattern(name, rel, pat, is_dir):
                    return False
            return True
        return False

    @staticmethod
    def _matches_pattern(name: str, rel: str, pattern: str, is_dir: bool) -> bool:
        pat = pattern.replace("\\", "/").strip()
        if not pat:
            return False

        variants = {name}
        if is_dir:
            variants.add(f"{name}/")
        if rel:
            rel_parts = rel.split("/")
            for idx in range(len(rel_parts)):
                suffix = "/".join(rel_parts[idx:])
                variants.add(suffix)
                if is_dir:
                    variants.add(f"{suffix}/")

        if any(fnmatch.fnmatch(variant, pat) for variant in variants):
            return True

        if pat.endswith("/**"):
            base = pat[:-3].rstrip("/")
            if base and any(variant == base or variant.startswith(f"{base}/") for variant in variants):
                return True

        return False

    @staticmethod
    def checksum(file_info: FileInfo) -> str:
        return file_info.checksum()

    @staticmethod
    def exists(path: str) -> bool:
        return os.path.exists(path)

    @staticmethod
    def copy_file(
        src: str,
        dst: str,
        preserve_timestamps: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        pause_cb: Optional[Callable[[], None]] = None,
        bandwidth_limit_kbps: int = 0,
    ) -> None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        total = os.path.getsize(src)
        done = 0
        started_at = time.monotonic()
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                if pause_cb:
                    pause_cb()
                if cancel_cb and cancel_cb():
                    raise SyncCancelled()
                chunk = fsrc.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                fdst.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
                _apply_bandwidth_limit(started_at, done, bandwidth_limit_kbps)
        if preserve_timestamps:
            st = os.stat(src)
            os.utime(dst, (st.st_atime, st.st_mtime))

    @staticmethod
    def _force_remove(func, path, exc_info) -> None:
        """onerror handler for shutil.rmtree.

        When a delete fails, try clearing the read-only bit on the offending
        path and retry the operation. This handles files left read-only by
        Windows NTFS/Samba shares, Git objects, or other tools — no sudo
        required as long as the current user owns the file.
        """
        try:
            LocalFS._grant_delete_access(path)
            func(path)
        except Exception:
            pass  # still can't delete; surface nothing here, caller tracks the error

    @staticmethod
    def _grant_delete_access(path: str) -> None:
        """Best-effort permission fix-up for delete retries.

        On POSIX systems, deleting an entry depends on the parent directory's
        write/execute bits, not only the file's mode. On Windows and SMB shares,
        clearing a read-only bit on the entry itself is often enough. Adjust both
        so a retry can succeed when the current user already owns the paths.
        """
        try:
            target_mode = os.stat(path).st_mode
            extra_bits = stat.S_IWUSR | stat.S_IREAD
            if stat.S_ISDIR(target_mode):
                extra_bits |= stat.S_IXUSR
            os.chmod(path, stat.S_IMODE(target_mode) | extra_bits)
        except Exception:
            pass

        parent = os.path.dirname(path) or "."
        try:
            parent_mode = os.stat(parent).st_mode
            os.chmod(
                parent,
                stat.S_IMODE(parent_mode) | stat.S_IWUSR | stat.S_IREAD | stat.S_IXUSR,
            )
        except Exception:
            pass

    @staticmethod
    def delete(path: str, is_dir: bool = False) -> None:
        if is_dir or os.path.isdir(path):
            shutil.rmtree(path, onerror=LocalFS._force_remove)
            # rmtree with onerror swallows individual failures; verify the dir is gone
            if os.path.exists(path):
                raise PermissionError(
                    f"Could not fully remove directory '{path}'. "
                    "Some files may be locked by another process or owned by a different user."
                )
        else:
            try:
                LocalFS._grant_delete_access(path)
                os.remove(path)
            except PermissionError:
                # Try clearing read-only bit and retry once
                try:
                    LocalFS._grant_delete_access(path)
                    os.remove(path)
                except Exception as inner:
                    raise PermissionError(
                        f"Cannot delete '{path}': {inner}. "
                        "The file may be locked by another process or owned by a different user."
                    ) from inner

    @staticmethod
    def makedirs(path: str) -> None:
        os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# SFTP filesystem
# ---------------------------------------------------------------------------

class SFTPFS:
    """Operations on a remote host via SSH/SFTP (requires paramiko)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str = "",
        key_file: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_file = key_file
        self._ssh = None
        self._sftp = None

    # ------------------------------------------------------------------
    def connect(self) -> None:
        import paramiko  # type: ignore[import]

        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": 15,
        }
        if self.key_file:
            kwargs["key_filename"] = os.path.expanduser(self.key_file)
        elif self.password:
            kwargs["password"] = self.password
        self._ssh.connect(**kwargs)
        self._sftp = self._ssh.open_sftp()

    def disconnect(self) -> None:
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
        self._sftp = None
        self._ssh = None

    # ------------------------------------------------------------------
    def scan(
        self,
        root: str,
        include_patterns: List[str],
        exclude_patterns: List[str],
        follow_symlinks: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        pause_cb: Optional[Callable[[], None]] = None,
    ) -> List[FileInfo]:
        import stat as stat_mod  # noqa: PLC0415

        files: List[FileInfo] = []

        def _walk(remote_dir: str, rel_base: str) -> None:
            if pause_cb:
                pause_cb()
            if cancel_cb and cancel_cb():
                raise SyncCancelled()
            try:
                entries = self._sftp.listdir_attr(remote_dir)
            except Exception:
                return
            for entry in entries:
                if pause_cb:
                    pause_cb()
                if cancel_cb and cancel_cb():
                    raise SyncCancelled()
                rel = f"{rel_base}/{entry.filename}".lstrip("/")
                abs_path = f"{remote_dir}/{entry.filename}"
                is_dir = stat_mod.S_ISDIR(entry.st_mode)
                if LocalFS._excluded(
                    entry.filename,
                    exclude_patterns,
                    include_patterns,
                    rel,
                    is_dir=is_dir,
                ):
                    continue
                files.append(
                    FileInfo(abs_path, rel, entry.st_size or 0, entry.st_mtime or 0, is_dir)
                )
                if progress_cb and not is_dir:
                    progress_cb(rel)
                if is_dir:
                    _walk(abs_path, rel)

        _walk(root.rstrip("/"), "")
        return files

    def checksum(self, file_info: FileInfo) -> str:
        h = hashlib.md5()
        with self._sftp.open(file_info.abs_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def exists(self, path: str) -> bool:
        try:
            self._sftp.stat(path)
            return True
        except Exception:
            return False

    def upload(
        self,
        local: str,
        remote: str,
        preserve_timestamps: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        pause_cb: Optional[Callable[[], None]] = None,
        bandwidth_limit_kbps: int = 0,
    ) -> None:
        remote_dir = remote.rsplit("/", 1)[0]
        if remote_dir and remote_dir != ".":
            self._mkdir_p(remote_dir)
            if not remote_dir.endswith(":") and not self.exists(remote_dir):
                raise FileNotFoundError(f"Remote directory does not exist: {remote_dir}")
        total = os.path.getsize(local)
        done = 0
        started_at = time.monotonic()
        with open(local, "rb") as src_fh, self._sftp.open(remote, "wb") as dst_fh:
            while True:
                if pause_cb:
                    pause_cb()
                if cancel_cb and cancel_cb():
                    raise SyncCancelled()
                chunk = src_fh.read(1 << 20)
                if not chunk:
                    break
                dst_fh.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
                _apply_bandwidth_limit(started_at, done, bandwidth_limit_kbps)
        if preserve_timestamps:
            st = os.stat(local)
            self._sftp.utime(remote, (st.st_atime, st.st_mtime))

    def download(
        self,
        remote: str,
        local: str,
        preserve_timestamps: bool = True,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        pause_cb: Optional[Callable[[], None]] = None,
        bandwidth_limit_kbps: int = 0,
    ) -> None:
        local_dir = os.path.dirname(local)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        attr = self._sftp.stat(remote)
        total = attr.st_size or 0
        done = 0
        started_at = time.monotonic()
        with self._sftp.open(remote, "rb") as src_fh, open(local, "wb") as dst_fh:
            while True:
                if pause_cb:
                    pause_cb()
                if cancel_cb and cancel_cb():
                    raise SyncCancelled()
                chunk = src_fh.read(1 << 20)
                if not chunk:
                    break
                dst_fh.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
                _apply_bandwidth_limit(started_at, done, bandwidth_limit_kbps)
        if preserve_timestamps:
            try:
                if attr.st_mtime:
                    os.utime(local, (attr.st_atime or attr.st_mtime, attr.st_mtime))
            except Exception:
                pass  # non-fatal: timestamp preservation is best-effort

    def delete(self, path: str, is_dir: bool = False) -> None:
        if is_dir:
            try:
                self._sftp.rmdir(path)
            except Exception:
                pass
        else:
            self._sftp.remove(path)

    def _mkdir_p(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        current = "/" if path.startswith("/") else "."
        if parts and len(parts[0]) == 2 and parts[0][1] == ":" and parts[0][0].isalpha():
            current = parts[0]
            parts = parts[1:]

        for part in parts:
            if current in ("", "."):
                current = f"{current}/{part}" if current == "." else part
            elif current == "/":
                current = f"/{part}"
            else:
                current = f"{current}/{part}"
            try:
                self._sftp.mkdir(current)
            except Exception:
                pass

    def makedirs(self, path: str) -> None:
        self._mkdir_p(path)


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------

class SyncEngine:
    """Drives a single sync run for one Profile."""

    def __init__(
        self,
        profile,
        event_cb: Optional[Callable[[SyncEvent], None]] = None,
        compare_only: bool = False,
    ) -> None:
        self.profile = profile
        self.event_cb = event_cb
        self._compare_only = compare_only
        self.status = SyncStatus.IDLE
        self._cancel = False
        self._pause_gate = threading.Event()
        self._pause_gate.set()
        self._thread: Optional[threading.Thread] = None
        self._active_process: Optional[subprocess.Popen] = None
        self._process_paused = False

    # ------------------------------------------------------------------
    def start(self, blocking: bool = False) -> None:
        if self.status in (SyncStatus.SCANNING, SyncStatus.SYNCING):
            return
        self._cancel = False
        self._pause_gate.set()
        if blocking:
            self._run()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True, name="queeksync-worker")
            self._thread.start()

    def cancel(self) -> None:
        self._cancel = True
        self._pause_gate.set()
        self._terminate_active_process()

    def pause(self) -> None:
        if self._active_process and self._active_process.poll() is None:
            if os.name != "posix":
                self._emit("warning", "Pause is not supported for rsync jobs on this platform.")
                return
            try:
                os.killpg(self._active_process.pid, signal.SIGSTOP)
                self._process_paused = True
                self._emit("warning", f"{'Compare' if self._compare_only else 'Sync'} paused by user.")
            except Exception as exc:
                self._emit("warning", f"Could not pause rsync job: {exc}")
            return
        if self.is_running() and self._pause_gate.is_set():
            self._pause_gate.clear()
            self._emit("warning", f"{'Compare' if self._compare_only else 'Sync'} paused by user.")

    def resume(self) -> None:
        if self._active_process and self._active_process.poll() is None and self._process_paused:
            if os.name != "posix":
                return
            try:
                os.killpg(self._active_process.pid, signal.SIGCONT)
                self._process_paused = False
                self._emit("info", f"Resuming {'compare' if self._compare_only else 'sync'} …")
            except Exception as exc:
                self._emit("warning", f"Could not resume rsync job: {exc}")
            return
        if self.is_running() and not self._pause_gate.is_set():
            self._pause_gate.set()
            self._emit("info", f"Resuming {'compare' if self._compare_only else 'sync'} …")

    def toggle_pause(self) -> None:
        if self.is_paused():
            self.resume()
        else:
            self.pause()

    def is_running(self) -> bool:
        return self.status in (SyncStatus.SCANNING, SyncStatus.SYNCING)

    def is_paused(self) -> bool:
        return self.is_running() and (not self._pause_gate.is_set() or self._process_paused)

    # ------------------------------------------------------------------
    def _emit(
        self,
        kind: str,
        message: str,
        rel_path: str = "",
        progress: float = 0.0,
        bytes_done: int = 0,
        bytes_total: int = 0,
    ) -> None:
        if self.event_cb:
            self.event_cb(
                SyncEvent(kind, message, rel_path, progress, bytes_done, bytes_total)
            )

    def _safe_transfer(self, src_fs, src_abs: str, dst_fs, dst_abs: str, preserve_ts: bool, rel: str) -> None:
        try:
            self._transfer(src_fs, src_abs, dst_fs, dst_abs, preserve_ts)
        except SyncCancelled:
            try:
                dst_fs.delete(dst_abs, False)
            except Exception:
                pass
            raise
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            if errno is None and getattr(exc, "args", None):
                try:
                    errno = int(exc.args[0])
                except Exception:
                    errno = None

            missing = errno == 2
            if missing:
                src_exists = True
                try:
                    src_exists = src_fs.exists(src_abs)
                except Exception:
                    src_exists = True

                if not src_exists:
                    self._emit("skip", f"Skipping {rel} (source missing)", rel)
                    return

                dst_dir = ""
                if isinstance(dst_abs, str) and "/" in dst_abs:
                    dst_dir = dst_abs.rsplit("/", 1)[0]
                if dst_dir and hasattr(dst_fs, "exists"):
                    try:
                        if not dst_dir.endswith(":") and not dst_fs.exists(dst_dir):
                            self._emit("error", f"Copy failed [{rel}]: destination folder missing or not accessible: {dst_dir}", rel)
                            return
                    except Exception:
                        pass

                self._emit("error", f"Copy failed [{rel}]: {exc}", rel)
                return

            self._emit("error", f"Copy failed [{rel}]: {exc}", rel)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        self.status = SyncStatus.SCANNING
        try:
            run_label = "Compare" if self._compare_only else "Sync"
            self._emit("info", f"Starting: {self.profile.name} ({run_label})")
            src_cfg = self.profile.source
            dst_cfg = self.profile.destination

            src_fs = self._make_fs(src_cfg)
            dst_fs = self._make_fs(dst_cfg)

            if isinstance(src_fs, SFTPFS):
                self._emit("info", f"Connecting to source {src_cfg.host} …")
                src_fs.connect()
                self._emit("info", f"Connected to source {src_cfg.host}:{src_cfg.path}")
            if isinstance(dst_fs, SFTPFS):
                self._emit("info", f"Connecting to destination {dst_cfg.host} …")
                dst_fs.connect()
                self._emit("info", f"Connected to destination {dst_cfg.host}:{dst_cfg.path}")

            try:
                self._sync(src_fs, src_cfg, dst_fs, dst_cfg)
            finally:
                if isinstance(src_fs, SFTPFS):
                    src_fs.disconnect()
                if isinstance(dst_fs, SFTPFS):
                    dst_fs.disconnect()

            if self._cancel:
                self.status = SyncStatus.CANCELLED
                self._emit("warning", f"{run_label} cancelled by user.")
                if not self._compare_only:
                    self.profile.last_sync_status = "cancelled"
            else:
                self.status = SyncStatus.COMPLETED
                self._emit("success", f"{run_label} completed successfully.")
                if not self._compare_only:
                    self.profile.last_sync = datetime.now().isoformat()
                    self.profile.last_sync_status = "success"

        except SyncCancelled:
            self.status = SyncStatus.CANCELLED
            self._emit("warning", f"{'Compare' if self._compare_only else 'Sync'} cancelled by user.")
            if not self._compare_only:
                self.profile.last_sync_status = "cancelled"
        except Exception as exc:
            self.status = SyncStatus.ERROR
            self._emit("error", f"{run_label} failed: {exc}")
            if not self._compare_only:
                self.profile.last_sync_status = "error"

    # ------------------------------------------------------------------
    def _make_fs(self, cfg):
        if cfg.type == "local":
            return LocalFS()
        if cfg.type == "sftp":
            return SFTPFS(cfg.host, cfg.port, cfg.username, cfg.password, cfg.key_file)
        raise ValueError(f"Unknown endpoint type: {cfg.type!r}")

    # ------------------------------------------------------------------
    def _sync(self, src_fs, src_cfg, dst_fs, dst_cfg) -> None:
        opts = self.profile.options
        flt = self.profile.filters

        include_patterns = list(flt.include_patterns)
        exclude_patterns = list(flt.exclude_patterns)
        for pat in (".venv*", "*:Zone.Identifier"):
            if pat not in exclude_patterns:
                exclude_patterns.append(pat)

        if self._should_use_rsync(src_cfg, dst_cfg, opts):
            self.status = SyncStatus.SYNCING
            if self._run_rsync_transport(src_cfg, dst_cfg, include_patterns, exclude_patterns, opts):
                return

        if self._compare_only:
            self._compare_only_run(src_fs, src_cfg, dst_fs, dst_cfg, include_patterns, exclude_patterns, opts)
            return

        self._emit("info", "Scanning source …")
        src_files = src_fs.scan(
            src_cfg.path,
            include_patterns,
            exclude_patterns,
            opts.follow_symlinks,
            progress_cb=lambda rel: self._emit("info", f"Scanning source: {rel}", rel),
            cancel_cb=lambda: self._cancel,
            pause_cb=self._wait_if_paused,
        )
        if self._cancel:
            return

        self._emit("info", "Scanning destination …")
        try:
            dst_files = dst_fs.scan(
                dst_cfg.path,
                include_patterns,
                exclude_patterns,
                opts.follow_symlinks,
                progress_cb=lambda rel: self._emit("info", f"Scanning destination: {rel}", rel),
                cancel_cb=lambda: self._cancel,
                pause_cb=self._wait_if_paused,
            )
        except FileNotFoundError:
            dst_files = []
        if self._cancel:
            return

        src_map: Dict[str, FileInfo] = {f.rel_path: f for f in src_files}
        dst_map: Dict[str, FileInfo] = {f.rel_path: f for f in dst_files}
        self.status = SyncStatus.SYNCING
        if opts.mode == "two_way":
            self._sync_two_way(src_fs, src_cfg, src_map, dst_fs, dst_cfg, dst_map, opts)
        else:
            self._sync_one_way(src_fs, src_map, dst_fs, dst_cfg, dst_map, opts)

        # ---- delete extras (mirror mode) -------------------------
        if opts.mode != "two_way" and (opts.mode == "mirror" or opts.delete_extra):
            delete_entries = [
                (rel, dst_f) for rel, dst_f in dst_map.items() if rel not in src_map
            ]
            delete_entries.sort(
                key=lambda item: (item[0].count("/"), 1 if item[1].is_dir else 0),
                reverse=True,
            )
            for rel, dst_f in delete_entries:
                if self._cancel:
                    return
                dst_abs = self._join(dst_cfg, rel)
                self._emit("delete", f"Deleting {rel}", rel)
                try:
                    dst_fs.delete(dst_abs, dst_f.is_dir)
                except Exception as exc:
                    self._emit("error", f"Delete failed [{rel}]: {exc}", rel)

    def _compare_only_run(self, src_fs, src_cfg, dst_fs, dst_cfg, include_patterns, exclude_patterns, opts) -> None:
        self._emit("info", "Scanning source …")
        src_files = src_fs.scan(
            src_cfg.path,
            include_patterns,
            exclude_patterns,
            opts.follow_symlinks,
            progress_cb=lambda rel: self._emit("info", f"Scanning source: {rel}", rel),
            cancel_cb=lambda: self._cancel,
            pause_cb=self._wait_if_paused,
        )
        if self._cancel:
            return

        self._emit("info", "Scanning destination …")
        try:
            dst_files = dst_fs.scan(
                dst_cfg.path,
                include_patterns,
                exclude_patterns,
                opts.follow_symlinks,
                progress_cb=lambda rel: self._emit("info", f"Scanning destination: {rel}", rel),
                cancel_cb=lambda: self._cancel,
                pause_cb=self._wait_if_paused,
            )
        except FileNotFoundError:
            dst_files = []
        if self._cancel:
            return

        src_map: Dict[str, FileInfo] = {f.rel_path: f for f in src_files if not f.is_dir}
        dst_map: Dict[str, FileInfo] = {f.rel_path: f for f in dst_files if not f.is_dir}
        paths = sorted(set(src_map.keys()) | set(dst_map.keys()))

        self.status = SyncStatus.SYNCING
        self._emit("info", f"Found {len(src_map)} file(s) in source, {len(dst_map)} file(s) in destination.")

        counts = {
            "same": 0,
            "src_only": 0,
            "dst_only": 0,
            "src_newer": 0,
            "dst_newer": 0,
            "conflict": 0,
        }
        newest_src = max((f.mtime for f in src_map.values()), default=0.0)
        newest_dst = max((f.mtime for f in dst_map.values()), default=0.0)

        total = len(paths)
        for idx, rel in enumerate(paths, start=1):
            if self._cancel:
                return
            self._emit("compare", f"Comparing {rel}", rel, (idx - 1) / max(total, 1))

            src_f = src_map.get(rel)
            dst_f = dst_map.get(rel)
            status = self._compare_pair_status(src_fs, src_f, dst_fs, dst_f, opts)
            counts[status] += 1

        self._emit("info", f"Same: {counts['same']}")
        self._emit("info", f"Source newer: {counts['src_newer']}  |  Destination newer: {counts['dst_newer']}")
        self._emit("info", f"Only in source: {counts['src_only']}  |  Only in destination: {counts['dst_only']}")
        if counts["conflict"]:
            self._emit("warning", f"Conflicts (same timestamp but different content/size): {counts['conflict']}")

        newest_src_txt = datetime.fromtimestamp(newest_src).strftime("%Y-%m-%d %H:%M:%S") if newest_src else "n/a"
        newest_dst_txt = datetime.fromtimestamp(newest_dst).strftime("%Y-%m-%d %H:%M:%S") if newest_dst else "n/a"
        self._emit("info", f"Latest file change seen — source: {newest_src_txt} | destination: {newest_dst_txt}")

        src_score = counts["src_newer"] + counts["src_only"]
        dst_score = counts["dst_newer"] + counts["dst_only"]
        if src_score > dst_score:
            self._emit("info", "Recommendation: source appears more up-to-date overall.")
        elif dst_score > src_score:
            self._emit("info", "Recommendation: destination appears more up-to-date overall.")
        else:
            self._emit("info", "Recommendation: both sides look equally up-to-date overall (or mixed).")

        self._emit("info", f"Progress: {total}/{total}", progress=1.0)

    @staticmethod
    def _compare_pair_status(src_fs, src: Optional[FileInfo], dst_fs, dst: Optional[FileInfo], opts) -> str:
        if src is None and dst is None:
            return "same"
        if src is None:
            return "dst_only"
        if dst is None:
            return "src_only"

        if src.size == dst.size and abs(src.mtime - dst.mtime) <= 2:
            return "same"
        if src.mtime > dst.mtime + 2:
            return "src_newer"
        if dst.mtime > src.mtime + 2:
            return "dst_newer"

        if opts.verify_checksums:
            try:
                if src_fs.checksum(src) == dst_fs.checksum(dst):
                    return "same"
            except Exception:
                pass
        return "conflict"

    def _sync_one_way(self, src_fs, src_map, dst_fs, dst_cfg, dst_map, opts) -> None:
        file_entries = [(rel, src_f) for rel, src_f in src_map.items() if not src_f.is_dir]
        total = len(file_entries)
        done = 0

        self._emit("info", f"Found {total} file(s) in source.")
        self._ensure_destination_dirs(src_map, dst_fs, dst_cfg)

        for rel, src_f in file_entries:
            if self._cancel:
                return

            dst_f = dst_map.get(rel)
            reason = self._compare_reason(src_fs, src_f, dst_fs, dst_f, opts)
            self._emit("compare", f"Comparing {rel}", rel, done / max(total, 1))

            if reason:
                src_abs = src_f.abs_path
                dst_abs = self._join(dst_cfg, rel)
                self._emit("copy", f"Copying {rel} ({reason})", rel, done / max(total, 1))
                self._safe_transfer(src_fs, src_abs, dst_fs, dst_abs, opts.preserve_timestamps, rel)
            else:
                self._emit("skip", f"Skipping {rel} (up-to-date)", rel, done / max(total, 1))

            done += 1
            self._emit("info", f"Progress: {done}/{total}", progress=done / max(total, 1))

    def _sync_two_way(self, src_fs, src_cfg, src_map, dst_fs, dst_cfg, dst_map, opts) -> None:
        file_paths = sorted(
            {
                rel
                for rel, file_info in src_map.items()
                if not file_info.is_dir
            }
            | {
                rel
                for rel, file_info in dst_map.items()
                if not file_info.is_dir
            }
        )
        total = len(file_paths)
        done = 0

        self._emit("info", f"Found {total} file(s) across both sides.")
        if opts.delete_extra:
            self._emit("warning", "Ignoring delete-extra option in two-way mode.")
        self._ensure_destination_dirs(src_map, dst_fs, dst_cfg)

        for rel in file_paths:
            if self._cancel:
                return

            src_f = src_map.get(rel)
            dst_f = dst_map.get(rel)
            self._emit("compare", f"Comparing {rel}", rel, done / max(total, 1))

            direction, reason = self._resolve_two_way_action(src_fs, src_f, dst_fs, dst_f, opts)
            if direction == "src_to_dst" and src_f is not None:
                dst_abs = self._join(dst_cfg, rel)
                self._emit("copy", f"Copying {rel} to destination ({reason})", rel, done / max(total, 1))
                self._safe_transfer(src_fs, src_f.abs_path, dst_fs, dst_abs, opts.preserve_timestamps, rel)
            elif direction == "dst_to_src" and dst_f is not None:
                src_abs = self._join(src_cfg, rel)
                self._emit("copy", f"Copying {rel} to source ({reason})", rel, done / max(total, 1))
                self._safe_transfer(dst_fs, dst_f.abs_path, src_fs, src_abs, opts.preserve_timestamps, rel)
            else:
                self._emit("skip", f"Skipping {rel} (already matched)", rel, done / max(total, 1))

            done += 1
            self._emit("info", f"Progress: {done}/{total}", progress=done / max(total, 1))

    # ------------------------------------------------------------------
    @staticmethod
    def _compare_reason(src_fs, src: FileInfo, dst_fs, dst: Optional[FileInfo], opts) -> str:
        if dst is None:
            return "new file"
        if opts.verify_checksums:
            try:
                if src_fs.checksum(src) != dst_fs.checksum(dst):
                    return "checksum changed"
                return ""
            except Exception:
                pass
        if src.size != dst.size:
            return "size changed"
        if abs(src.mtime - dst.mtime) > 2:
            return "modified time changed"
        return ""

    @staticmethod
    def _resolve_two_way_action(src_fs, src: Optional[FileInfo], dst_fs, dst: Optional[FileInfo], opts) -> tuple[str, str]:
        if src is None and dst is None:
            return "", ""
        if src is None:
            return "dst_to_src", "new file on destination"
        if dst is None:
            return "src_to_dst", "new file on source"

        compare_reason = SyncEngine._compare_reason(src_fs, src, dst_fs, dst, opts)
        if not compare_reason:
            return "", ""

        if src.mtime > dst.mtime + 2:
            return "src_to_dst", "source is newer"
        if dst.mtime > src.mtime + 2:
            return "dst_to_src", "destination is newer"

        if compare_reason == "checksum changed":
            return "src_to_dst", "content changed with matching timestamps"

        if src.size != dst.size:
            if src.size > dst.size:
                return "src_to_dst", "source size is larger at same timestamp"
            if dst.size > src.size:
                return "dst_to_src", "destination size is larger at same timestamp"

        return "src_to_dst", compare_reason

    def _wait_if_paused(self) -> None:
        while not self._pause_gate.is_set():
            if self._cancel:
                raise SyncCancelled()
            time.sleep(0.1)

    def _ensure_destination_dirs(self, src_map, dst_fs, dst_cfg) -> None:
        dir_entries = sorted(
            (rel for rel, file_info in src_map.items() if file_info.is_dir),
            key=lambda rel: rel.count("/"),
        )
        for rel in dir_entries:
            if self._cancel:
                raise SyncCancelled()
            dst_dir = self._join(dst_cfg, rel)
            try:
                if hasattr(dst_fs, "makedirs"):
                    dst_fs.makedirs(dst_dir)
                elif isinstance(dst_fs, LocalFS):
                    LocalFS.makedirs(dst_dir)
            except Exception as exc:
                self._emit("error", f"Could not create destination folder [{rel}]: {exc}", rel)

    def _terminate_active_process(self) -> None:
        proc = self._active_process
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
        except Exception:
            pass

    def _should_use_rsync(self, src_cfg, dst_cfg, opts) -> bool:
        return (
            opts.use_rsync_ssh
            and opts.mode in ("one_way", "mirror")
            and not self._compare_only
            and ((src_cfg.type == "local" and dst_cfg.type == "sftp") or (src_cfg.type == "sftp" and dst_cfg.type == "local"))
        )

    def _run_rsync_transport(self, src_cfg, dst_cfg, include_patterns, exclude_patterns, opts) -> bool:
        if not shutil.which("rsync") or not shutil.which("ssh"):
            self._emit("warning", "rsync over SSH is enabled, but rsync or ssh is not installed locally. Falling back to built-in transfer.")
            return False

        remote_cfg = dst_cfg if dst_cfg.type == "sftp" else src_cfg
        if remote_cfg.password and not remote_cfg.key_file and not shutil.which("sshpass"):
            self._emit("warning", "rsync over SSH needs sshpass for password-only profiles. Falling back to built-in transfer.")
            return False

        cmd = self._build_rsync_command(src_cfg, dst_cfg, include_patterns, exclude_patterns, opts)
        self._emit("info", "Using rsync over SSH for this sync.")
        self._emit("info", f"rsync destination: {dst_cfg.path if dst_cfg.type == 'sftp' else src_cfg.path}")

        creationflags = 0
        start_new_session = os.name == "posix"
        self._process_paused = False
        try:
            self._active_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=start_new_session,
                creationflags=creationflags,
            )

            assert self._active_process.stdout is not None
            for raw_line in self._active_process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("*deleting "):
                    rel = line[len("*deleting "):].strip()
                    self._emit("delete", f"Deleting {rel}", rel)
                elif line[:2] in {">f", "cd", "cL", "hL"}:
                    parts = line.split(maxsplit=1)
                    rel = parts[1].strip() if len(parts) > 1 else ""
                    self._emit("copy", f"Copying {rel} via rsync", rel)
                else:
                    self._emit("info", f"rsync: {line}")

            exit_code = self._active_process.wait()
            if self._cancel:
                raise SyncCancelled()
            if exit_code != 0:
                raise RuntimeError(f"rsync exited with code {exit_code}")
            return True
        finally:
            self._active_process = None
            self._process_paused = False

    def _build_rsync_command(self, src_cfg, dst_cfg, include_patterns, exclude_patterns, opts) -> List[str]:
        remote_cfg = dst_cfg if dst_cfg.type == "sftp" else src_cfg
        local_cfg = src_cfg if src_cfg.type == "local" else dst_cfg

        ssh_cmd = ["ssh", "-p", str(remote_cfg.port), "-o", "StrictHostKeyChecking=accept-new"]
        if remote_cfg.key_file:
            ssh_cmd.extend(["-i", os.path.expanduser(remote_cfg.key_file)])
        elif not remote_cfg.password:
            ssh_cmd.extend(["-o", "BatchMode=yes"])

        cmd: List[str] = []
        if remote_cfg.password and not remote_cfg.key_file:
            cmd.extend(["sshpass", "-p", remote_cfg.password])

        cmd.extend(["rsync", "-r", "--itemize-changes", "--human-readable"])
        if opts.preserve_timestamps:
            cmd.append("-t")
        if opts.follow_symlinks:
            cmd.append("-L")
        else:
            cmd.append("--no-links")
        if opts.verify_checksums:
            cmd.append("-c")
        if opts.mode == "mirror" or opts.delete_extra:
            cmd.append("--delete")
        if opts.bandwidth_limit_kbps > 0:
            cmd.extend(["--bwlimit", str(opts.bandwidth_limit_kbps)])

        for pat in exclude_patterns:
            cmd.extend(["--exclude", pat])
        if include_patterns:
            cmd.extend(["--include", "*/"])
            for pat in include_patterns:
                cmd.extend(["--include", pat])
            cmd.extend(["--exclude", "*"])

        cmd.extend(["-e", shlex.join(ssh_cmd)])

        remote_path = remote_cfg.path.rstrip("/") + "/"
        remote_spec = f"{remote_cfg.username}@{remote_cfg.host}:{shlex.quote(remote_path)}"
        local_path = os.path.abspath(local_cfg.path).rstrip(os.sep) + os.sep

        if src_cfg.type == "local":
            cmd.extend([local_path, remote_spec])
        else:
            os.makedirs(local_cfg.path, exist_ok=True)
            cmd.extend([remote_spec, local_path])
        return cmd

    @staticmethod
    def _join(cfg, rel: str) -> str:
        if cfg.type == "sftp":
            return f"{cfg.path.rstrip('/')}/{rel}"
        return os.path.join(cfg.path, rel.replace("/", os.sep))

    def _transfer(
        self,
        src_fs,
        src_abs: str,
        dst_fs,
        dst_abs: str,
        preserve_ts: bool,
    ) -> None:
        if isinstance(src_fs, LocalFS) and isinstance(dst_fs, LocalFS):
            LocalFS.copy_file(
                src_abs,
                dst_abs,
                preserve_ts,
                cancel_cb=lambda: self._cancel,
                pause_cb=self._wait_if_paused,
                bandwidth_limit_kbps=self.profile.options.bandwidth_limit_kbps,
            )

        elif isinstance(src_fs, LocalFS) and isinstance(dst_fs, SFTPFS):
            dst_fs.upload(
                src_abs,
                dst_abs,
                preserve_ts,
                cancel_cb=lambda: self._cancel,
                pause_cb=self._wait_if_paused,
                bandwidth_limit_kbps=self.profile.options.bandwidth_limit_kbps,
            )

        elif isinstance(src_fs, SFTPFS) and isinstance(dst_fs, LocalFS):
            src_fs.download(
                src_abs,
                dst_abs,
                preserve_ts,
                cancel_cb=lambda: self._cancel,
                pause_cb=self._wait_if_paused,
                bandwidth_limit_kbps=self.profile.options.bandwidth_limit_kbps,
            )

        elif isinstance(src_fs, SFTPFS) and isinstance(dst_fs, SFTPFS):
            # SFTP → SFTP via temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".queeksync_tmp") as tf:
                tmp = tf.name
            try:
                src_fs.download(
                    src_abs,
                    tmp,
                    cancel_cb=lambda: self._cancel,
                    pause_cb=self._wait_if_paused,
                    bandwidth_limit_kbps=self.profile.options.bandwidth_limit_kbps,
                )
                dst_fs.upload(
                    tmp,
                    dst_abs,
                    preserve_ts,
                    cancel_cb=lambda: self._cancel,
                    pause_cb=self._wait_if_paused,
                    bandwidth_limit_kbps=self.profile.options.bandwidth_limit_kbps,
                )
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
