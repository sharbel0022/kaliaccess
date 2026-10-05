# KaliAccess

KaliAccess is an owner-operated remote administration system for controlling **your own Windows 11 PC from Kali Linux** without SSH, SCP or SFTP.

It contains three parts:

- **Windows Agent** - authenticated HTTPS service for terminal, files, processes, status and audit logging.
- **Windows Desktop Helper** - visible per-user helper for screenshots/live view and a safe key-event test window.
- **Kali client (`winctl`)** - CLI used from Kali Linux.

Current protocol/app version: **1.1.0**

## Main features

```text
winctl ping
winctl status
winctl desktop-status

winctl shell
winctl shell cmd
winctl shell wsl
winctl run "Get-Process"

winctl upload ./test.py C:\KaliAccess\uploads\
winctl download C:\KaliAccess\results\result.txt
winctl ls C:\Users\YourUser\Desktop
winctl mkdir C:\KaliAccess\projects\demo

winctl ps
winctl kill 1234
winctl start "notepad.exe"

winctl screenshot
winctl screenshot ./screen.png
winctl screen

winctl keytest
winctl keytest --watch
winctl logs
```

## Architecture

```text
Kali Linux
┌───────────────────────────┐
│ winctl                    │
│                           │
│ shell / files / processes │
│ screenshot / live view    │
│ key-event test / logs     │
└─────────────┬─────────────┘
              │ HTTPS + pinned TLS certificate
              ▼
Windows 11
┌───────────────────────────┐
│ KaliAccessAgent           │
│ Windows service           │
│                           │
│ PowerShell / CMD / WSL    │
│ files / processes / logs  │
└─────────────┬─────────────┘
              │ localhost + random helper token
              ▼
┌───────────────────────────┐
│ Desktop Helper            │
│ signed-in user session    │
│                           │
│ screenshots               │
│ live screen frames        │
│ visible key-event test    │
└───────────────────────────┘
```

The external network only exposes the main HTTPS agent port. The desktop helper listens on **127.0.0.1 only** and uses a random per-install token shared with the Windows service.

## Important key-event limitation

KaliAccess does **not** install a global keylogger.

The key-event feature is deliberately limited to a visible test window called:

```text
KaliAccess - Key-event test
```

Only keys typed inside that window are recorded. This is intended for learning/testing event capture and transport without collecting passwords or keystrokes from other applications.

Open the Windows desktop helper from the taskbar, press **Open key-event test**, then on Kali run:

```bash
winctl keytest --watch
```

## 1. Windows installation

Requirements:

- Windows 11
- Python 3 available through `py -3`
- Administrator PowerShell for the one-time installation
- An interactive Windows user account for desktop screenshots/live view

Clone/download this repository, open **PowerShell as Administrator**, then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd <path-to-kaliaccess>
.\windows_agent\install.ps1
```

The installer:

1. copies the service and desktop helper to `C:\ProgramData\KaliAccess`
2. creates an isolated Python virtual environment
3. installs required packages
4. asks for a KaliAccess username/password
5. generates a TLS certificate automatically
6. creates `C:\KaliAccess` working folders
7. creates a random local desktop-helper token
8. installs `KaliAccessAgent` as an automatic Windows service
9. creates the visible **KaliAccess Desktop Helper** logon task
10. adds a Windows Firewall rule for **Private** networks only
11. starts the service and helper

Default network ports:

```text
8765  Windows HTTPS agent - reachable from Kali on the private network
8766  Desktop helper      - localhost only, never firewall-exposed
```

The KaliAccess password must be at least 12 characters. Windows stores only a bcrypt hash.

### Verify on Windows

```powershell
Get-Service KaliAccessAgent
Get-NetTCPConnection -LocalPort 8765 -State Listen
Get-ScheduledTask -TaskName "KaliAccess Desktop Helper"
```

After a reboot:

- the Windows service starts automatically
- the desktop helper starts when the configured Windows user signs in
- the helper is visible as a minimized taskbar application

## 2. Kali installation

```bash
git clone https://github.com/sharbel0022/kaliaccess.git
cd kaliaccess
chmod +x kali_client/install.sh
./kali_client/install.sh
```

Configure the Windows PC once:

```bash
winctl setup 192.168.1.50 --username sharbel
```

The client shows the Windows TLS certificate SHA-256 fingerprint and asks you to trust it.

The trusted **public certificate** is stored under:

```text
~/.config/kaliaccess/
```

The password is not stored by default.

## 3. Terminal

### PowerShell

```bash
winctl run "Get-Process"
winctl run "Get-Service"
winctl shell
```

### CMD

```bash
winctl run "dir C:\Users" --shell cmd
winctl shell cmd
```

### WSL on Windows

```bash
winctl run "uname -a" --shell wsl
winctl shell wsl
```

## 4. File transfer

### Kali -> Windows

```bash
winctl upload test.py
winctl upload test.py C:\KaliAccess\uploads\test.py
```

### Windows -> Kali

```bash
winctl download C:\KaliAccess\results\result.txt
winctl download C:\KaliAccess\results\result.txt ./result.txt
```

Uploads/downloads are streamed and SHA-256 verified.

## 5. Files and processes

```bash
winctl ls C:\KaliAccess
winctl mkdir C:\KaliAccess\projects\test

winctl ps
winctl kill 1234
winctl start "notepad.exe"
```

## 6. Screenshot and live screen

Check that the signed-in desktop helper is available:

```bash
winctl desktop-status
```

Take one screenshot:

```bash
winctl screenshot
winctl screenshot ./windows-screen.png
```

Open a read-only live viewer in the Kali browser:

```bash
winctl screen
```

Change refresh rate:

```bash
winctl screen --interval 0.5
```

The viewer binds only to `127.0.0.1` on Kali. Press **Ctrl+C** in the Kali terminal to stop it.

If Windows is at the sign-in screen, locked, or no interactive user session is available, desktop capture may be unavailable.

## 7. Safe key-event test

On Windows:

1. open **KaliAccess Desktop Helper**
2. press **Open key-event test**
3. click inside its text box
4. type test text

On Kali:

```bash
winctl keytest
```

Or watch new test events:

```bash
winctl keytest --watch
```

No system-wide keyboard hook is installed.

## 8. Audit logs

State-changing API calls are written to:

```text
C:\KaliAccess\logs\audit.jsonl
```

View recent entries from Kali:

```bash
winctl logs
winctl logs --limit 250
```

The log records timestamp, API path, status code, client IP and duration. Authorization headers and passwords are not written to the audit file.

## Security model

KaliAccess intentionally has powerful administration capabilities because it is designed for the owner to administer their own Windows PC.

Important defaults:

- HTTPS is mandatory.
- Kali pins the Windows TLS certificate.
- The KaliAccess password is not saved by `winctl` by default.
- Windows stores only a bcrypt password hash.
- `C:\ProgramData\KaliAccess` keeps service secrets protected from ordinary users.
- The desktop helper listens on localhost only.
- A separate random token authenticates service -> desktop-helper requests.
- The inbound firewall rule is limited to Windows **Private** network profiles.
- Audit logging records administrative API actions.
- There is no global keylogger, credential recovery, browser-password extraction, anti-analysis or AV bypass.
- Do **not** port-forward TCP/8765 directly to the public internet.

For access away from home/lab, put Kali and Windows on a private VPN and keep TCP/8765 private.

## Working folders

```text
C:\KaliAccess\
  uploads\
  downloads\
  scripts\
  projects\
  results\
  logs\
  temp\
```

Relative remote paths resolve under `C:\KaliAccess`. Absolute Windows paths are supported when the Windows service account has permission.

## Uninstall

Run PowerShell as Administrator:

```powershell
.\windows_agent\uninstall.ps1
```

Remove the service program files too:

```powershell
.\windows_agent\uninstall.ps1 -RemoveProgramData
```

`C:\KaliAccess` is intentionally not deleted automatically.

## Development checks

Python syntax:

```bash
python3 -m compileall windows_agent kali_client
```

Useful Kali check after installation:

```bash
winctl --version
winctl ping
winctl status
winctl desktop-status
```
