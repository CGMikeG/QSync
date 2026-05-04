#!/usr/bin/env bash
# QueekSync launcher for Linux / WSL
set -e

LOG="$HOME/.local/share/QueekSync/queeksync.log"
mkdir -p "$(dirname "$LOG")"

_die() {
    echo ""
    echo "══════════════════════════════════════════"
    echo "  QueekSync failed to start. Error log:"
    echo "  $LOG"
    echo "══════════════════════════════════════════"
    echo ""
    tail -30 "$LOG" 2>/dev/null || true
    # Keep terminal open when launched by double-click
    if [ -t 1 ]; then
        read -rp "Press Enter to close..." _
    fi
    exit 1
}
trap _die ERR

_tk_hint() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "Install it with: sudo apt-get update && sudo apt-get install -y python3-tk"
    elif command -v dnf >/dev/null 2>&1; then
        echo "Install it with: sudo dnf install -y python3-tkinter"
    elif command -v pacman >/dev/null 2>&1; then
        echo "Install it with: sudo pacman -S tk"
    elif command -v zypper >/dev/null 2>&1; then
        echo "Install it with: sudo zypper install python3-tk"
    else
        echo "Install the Tk bindings for your system Python (package often named python3-tk or python3-tkinter)."
    fi
}

_run_privileged() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        return 1
    fi
}

_install_tk() {
    echo "[QueekSync] tkinter is missing. Attempting to install the required system package..." >&2

    if command -v apt-get >/dev/null 2>&1; then
        _run_privileged apt-get update && _run_privileged apt-get install -y python3-tk
        return
    fi

    if command -v dnf >/dev/null 2>&1; then
        _run_privileged dnf install -y python3-tkinter
        return
    fi

    if command -v pacman >/dev/null 2>&1; then
        _run_privileged pacman -S --noconfirm tk
        return
    fi

    if command -v zypper >/dev/null 2>&1; then
        _run_privileged zypper install -y python3-tk
        return
    fi

    return 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── WSLg display setup ───────────────────────────────────────────────────────
if grep -qi microsoft /proc/version 2>/dev/null; then
    export DISPLAY="${DISPLAY:-:0}"
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/mnt/wslg/runtime-dir}"
fi

VENV="$SCRIPT_DIR/.venv"

# ── Create venv if it doesn't exist ─────────────────────────────────────────
if [ ! -f "$VENV/bin/python" ]; then
    echo "[QueekSync] Creating virtual environment..."
    python3 -m venv "$VENV"
fi

if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "[QueekSync] Installing pip in virtual environment..."
    "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi

if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "[QueekSync] ERROR: pip is not available in the virtual environment." >&2
    echo "[QueekSync] Fix: install the system package that provides venv/ensurepip (often python3-venv) and re-run." >&2
    exit 1
fi

if ! "$VENV/bin/python" -c "import tkinter" >/dev/null 2>&1; then
    echo "[QueekSync] Missing tkinter support in the selected Python installation." >&2
    echo "[QueekSync] QueekSync uses customtkinter, which depends on the system Tk libraries." >&2

    if ! _install_tk; then
        echo "[QueekSync] Automatic installation is not available on this machine." >&2
        echo "[QueekSync] $(_tk_hint)" >&2
        exit 1
    fi

    if ! "$VENV/bin/python" -c "import tkinter" >/dev/null 2>&1; then
        echo "[QueekSync] Tk package installation completed, but tkinter is still unavailable." >&2
        echo "[QueekSync] $(_tk_hint)" >&2
        exit 1
    fi
fi

# ── Launch ───────────────────────────────────────────────────────────────────
echo "[QueekSync] Starting... (log: $LOG)"
"$VENV/bin/python" main.py "$@" 2>&1 | tee "$LOG"
