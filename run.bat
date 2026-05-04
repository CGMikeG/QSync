@echo off
setlocal EnableDelayedExpansion
title QueekSync

:: ── Detect where the project lives ──────────────────────────────────────────
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: Check if the script is being run from a WSL UNC path (\\wsl.localhost\...)
echo %SCRIPT_DIR% | findstr /i "wsl.localhost" >nul 2>&1
if %errorlevel%==0 (
    goto :run_via_wsl
)

:: ── Native Windows path: use (or create) the project venv ───────────────────
set "VENV=%SCRIPT_DIR%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [QueekSync] Creating Windows virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [QueekSync] ERROR: Python not found. Please install Python 3.10+ from https://python.org
        pause
        exit /b 1
    )
    echo [QueekSync] Ready.
)

"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [QueekSync] Installing pip in virtual environment...
    "%PYTHON%" -m ensurepip --upgrade >nul 2>&1
)

"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [QueekSync] ERROR: pip is not available in the virtual environment.
    echo [QueekSync] Fix: reinstall/repair Python and ensure the venv components are installed, then re-run.
    pause
    exit /b 1
)

"%PYTHON%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [QueekSync] ERROR: tkinter is not available in this Python installation.
    echo [QueekSync] QueekSync uses customtkinter, which depends on the Tcl/Tk components bundled with Python on Windows.
    echo [QueekSync] Fix: modify or reinstall Python 3.10+ from https://python.org and make sure Tcl/Tk and IDLE is selected.
    pause
    exit /b 1
)

echo [QueekSync] Starting (Windows native)...
"%PYTHON%" "%SCRIPT_DIR%\main.py"
goto :eof

:: ── WSL path: delegate to WSL ────────────────────────────────────────────────
:run_via_wsl
echo [QueekSync] Detected WSL project path. Launching via WSL...

:: Convert UNC path  \\wsl.localhost\<distro>\<user>\QueekSync
:: to WSL path       /<user>/QueekSync
for /f "tokens=*" %%P in ('wsl wslpath -u "%SCRIPT_DIR:\=/%"') do set "WSL_DIR=%%P"

wsl bash -c "cd '%WSL_DIR%' && bash run.sh"
if errorlevel 1 (
    echo.
    echo [QueekSync] ERROR: Could not launch via WSL.
    echo   Make sure WSL 2 with Ubuntu is installed and WSLg (or an X server) is available.
    pause
)
