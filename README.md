# QueekSync

QueekSync is a cross-platform desktop file synchronization app with a modern GUI.
It helps you sync files between:

- Local folder to local folder
- Local folder to SFTP server
- SFTP server to local folder
- SFTP server to SFTP server

## Purpose

Use QueekSync when you want repeatable, profile-based sync jobs without writing shell scripts.
Each sync profile stores source/destination endpoints, sync behavior, filters, and optional scheduling.

## Key Features

- Profile-based sync setup
- Sync modes:
  - one_way: copy source to destination only
  - mirror: one_way plus delete files missing from source
  - two_way: bidirectional sync based on newer timestamps
- Include and exclude patterns
- Optional checksum verification
- Optional bandwidth limit
- Scheduled auto-sync
- File-change triggered sync for local source folders
- Live monitor panel with progress and logs
- SFTP connection testing and remote folder browser

## Tech Stack

- Python 3.10+
- customtkinter (GUI)
- paramiko (SFTP)
- watchdog (filesystem watching)
- schedule (interval scheduling)

## Project Structure

- main.py: app entry point
- src/core/: sync engine, profiles, scheduler, watcher
- src/ui/: desktop UI panels and dialogs
- run.bat: Windows launcher
- run.sh: Linux/WSL launcher

## Requirements

- Python 3.10 or newer
- Network access to any SFTP targets you want to sync
- On Linux/WSL: working GUI display support

## Installation and Launch

### Windows (recommended)

Double-click run.bat

What happens:

1. Creates .venv on first run
2. Installs dependencies from requirements.txt into the local .venv
3. Verifies that the Windows Python installation includes tkinter/Tcl-Tk support
4. Launches the app

Or run manually from terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

Running `main.py` directly also self-bootstraps into the project-local `.venv` if needed, so the app does not continue under the system Python environment.
If `requirements.txt` changes later, QueekSync re-syncs the local `.venv` automatically on the next launch.

### Linux or WSL

Make launcher executable, then run:

```bash
chmod +x run.sh
./run.sh
```

What happens:

1. Creates .venv on first run
2. Installs dependencies from requirements.txt into the local .venv
3. If tkinter is missing, attempts to install the required system Tk package using your distro package manager
4. Launches the app and writes logs to ~/.local/share/QueekSync/queeksync.log

Notes:

- Automatic Tk installation may prompt for sudo/root access
- If auto-install is not available for your distro, the launcher prints the manual package command to run

## How to Use

### 1. Create a Sync Profile

1. Open QueekSync
2. Go to Profiles (or use New Profile from Dashboard)
3. Enter profile name and optional description
4. Configure Source endpoint
5. Configure Destination endpoint
6. Save profile

Endpoint types:

- local: local filesystem path
- sftp: host, port, username, password and/or key file, remote path

### 2. Choose Sync Behavior

In the profile editor:

- Select mode: one_way, mirror, or two_way
- Enable delete extra files only if you are sure
- Configure include and exclude patterns
- Optionally enable checksum verification for safer comparisons

### 3. Run a Sync

- Click Sync on a profile card/row
- App switches to Monitor panel
- Watch progress, copied/deleted files, warnings, and errors

### 4. Enable Automation (Optional)

For each profile, you can enable schedule settings:

- Interval-based sync (every N minutes)
- Auto trigger when local source files change

## Data and Config Storage

QueekSync stores app settings and profiles outside the repository.

Windows:

- Config: %APPDATA%/QueekSync/config.json
- Profiles: %APPDATA%/QueekSync/profiles/*.json

Linux:

- Config: ~/.config/QueekSync/config.json
- Profiles: ~/.config/QueekSync/profiles/*.json

## Security Notes

- Profile SFTP passwords are stored in profile JSON in plaintext.
- Prefer SSH key authentication whenever possible.
- Do not share exported profile files if they contain credentials.

## Common Workflow Example

1. Create profile named Website Backup
2. Source: local folder C:/sites/myapp
3. Destination: SFTP folder /backups/myapp
4. Mode: one_way
5. Exclude: .git, __pycache__, *.log
6. Test SFTP connection
7. Save profile and run Sync
8. Enable schedule to run every 60 minutes

## Troubleshooting

- App does not launch on Windows:
  - Verify Python 3.10+ is installed and available in PATH
- Windows launcher reports missing tkinter:
  - Repair or reinstall Python 3.10+ and ensure the Tcl/Tk and IDLE feature is included
- SFTP connection fails:
  - Check host, port, username, credentials, firewall
- WSL GUI issues:
  - Ensure WSLg or an X server is configured
- Linux launcher exits with missing tkinter:
  - Install the Tk package for your distro, commonly python3-tk or python3-tkinter
- Mirror or delete-extra sync fails on Linux:
  - The destination folder must be writable and executable by your user because Linux delete permissions are controlled by the parent directory
  - Manual sync now offers a one-time admin approval prompt to repair the destination folder and continue automatically when `pkexec` is available
  - Prefer fixing the folder with `chown` or `chmod u+rwX` instead of running the whole app with sudo
- Dependency errors:
  - Reinstall from requirements.txt inside the project virtual environment

## Development

Install dependencies:

```bash
pip install -r requirements.txt
```

Run app:

```bash
python main.py
```

## License

Add your preferred license details here.
