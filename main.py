#!/usr/bin/env python3
"""
QueekSync - Professional File Synchronization Tool
Cross-platform file sync application with a modern glass UI.
"""

import sys
import os
import hashlib
import subprocess
import venv


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(PROJECT_DIR, ".venv")
REQUIREMENTS_PATH = os.path.join(PROJECT_DIR, "requirements.txt")
REQUIREMENTS_STAMP = os.path.join(VENV_DIR, ".queeksync-requirements.sha256")


def _venv_python_path() -> str:
    if os.name == "nt":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def _running_in_project_venv() -> bool:
    active_prefix = os.path.realpath(sys.prefix)
    project_venv = os.path.realpath(VENV_DIR)
    return active_prefix == project_venv


def _requirements_hash() -> str:
    digest = hashlib.sha256()
    with open(REQUIREMENTS_PATH, "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


def _read_requirements_stamp() -> str:
    try:
        with open(REQUIREMENTS_STAMP, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return ""


def _write_requirements_stamp(requirements_hash: str) -> None:
    with open(REQUIREMENTS_STAMP, "w", encoding="utf-8") as fh:
        fh.write(requirements_hash)


def _ensure_pip(venv_python: str) -> None:
    try:
        subprocess.run(
            [venv_python, "-m", "pip", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    except subprocess.CalledProcessError:
        pass

    print("[QueekSync] pip is missing in the project virtual environment. Installing it...")
    try:
        subprocess.run(
            [venv_python, "-m", "ensurepip", "--upgrade"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        print("[QueekSync] ERROR: Failed to install pip into the project virtual environment.")
        print(
            "[QueekSync] Fix: install the system package that provides venv/ensurepip "
            "(often python3-venv) and re-run."
        )
        raise

    subprocess.run(
        [venv_python, "-m", "pip", "--version"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _install_project_dependencies(venv_python: str) -> None:
    print("[QueekSync] Syncing dependencies in project virtual environment...")
    subprocess.run(
        [venv_python, "-m", "pip", "install", "--quiet", "-r", REQUIREMENTS_PATH],
        check=True,
    )
    _write_requirements_stamp(_requirements_hash())


def _ensure_project_venv() -> None:
    venv_python = _venv_python_path()
    if not os.path.exists(venv_python):
        print("[QueekSync] Creating project virtual environment...")
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(VENV_DIR)
    _ensure_pip(venv_python)


def _ensure_project_dependencies() -> None:
    expected_hash = _requirements_hash()
    if _read_requirements_stamp() == expected_hash:
        return
    venv_python = _venv_python_path()
    _ensure_pip(venv_python)
    _install_project_dependencies(venv_python)


def _reexec_into_project_venv() -> None:
    _ensure_project_venv()

    if _running_in_project_venv():
        _ensure_project_dependencies()
        return

    _ensure_project_dependencies()
    venv_python = _venv_python_path()
    os.execv(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]])

# Ensure the src directory is importable
_reexec_into_project_venv()

sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))

from ui.app import QueekSyncApp


def main():
    if os.environ.get("QUEEKSYNC_BOOTSTRAP_CHECK") == "1":
        print(sys.executable)
        print(sys.prefix)
        return

    app = QueekSyncApp()
    app.run()


if __name__ == "__main__":
    main()
