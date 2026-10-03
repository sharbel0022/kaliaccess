# KaliAccess

KaliAccess is a small owner-operated remote administration system for controlling **your own Windows 11 PC from Kali Linux** without SSH, SCP or SFTP.

It contains two parts:

- **Windows Agent**  a FastAPI service installed as `KaliAccessAgent` and started automatically by Windows.
- **Kali client (`winctl`)**  a CLI that sends commands, transfers files, checks status and manages processes.

## What it can do

```text
winctl ping
winctl status
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
```

There are **no SSH keys and no SSH server**. KaliAccess uses its own HTTPS API. During Windows installation it automatically generates a TLS certificate. The Kali client stores only the **public certificate** after first trust; it never stores your KaliAccess password.

## Architecture

```text
Kali Linux                         Windows 11
-----------                        ----------
winctl  HTTPS/TLS > KaliAccessAgent service
                                      
    commands                          PowerShell
    upload/download                   CMD
    status                            WSL
    process list                      files
    start/stop                        processes
```

## 1. Windows installation

Requirements:

- Windows 11
- Python 3 installed and available through `py -3`
- Administrator PowerShell for the one-time service installation

Clone/download this repository, open **PowerShell as Administrator**, then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd <path-to-kaliaccess>
.\windows_agent\install.ps1
```

The installer will:

1. copy the agent to `C:\ProgramData\KaliAccess`
2. create an isolated Python virtual environment
3. install required packages
4. ask for a KaliAccess username/password
5. generate the TLS certificate automatically
6. create `C:\KaliAccess` with working folders
7. install `KaliAccessAgent` as an automatic Windows service
8. add a Windows Firewall rule for **Private** networks only
9. start the service

Default port: `8765`.

The password must be at least 12 characters. Only a bcrypt hash is stored on Windows.

### Verify on Windows

```powershell
Get-Service KaliAccessAgent
Get-NetTCPConnection -LocalPort 8765 -State Listen
```

After a reboot, `KaliAccessAgent` should start automatically without opening a terminal or logging in interactively.

## 2. Kali installation

On Kali:

```bash
git clone https://github.com/sharbel0022/kaliaccess.git
cd kaliaccess
chmod +x kali_client/install.sh
./kali_client/install.sh
```

Then configure the Windows PC once:

```bash
winctl setup 192.168.1.50 --username sharbel
```

The client displays the Windows TLS certificate SHA-256 fingerprint and asks you to trust it. The trusted **public** certificate is stored under:

```text
~/.config/kaliaccess/
```

No password is saved there.

## 3. Normal use

### Check connectivity

```bash
winctl ping
```

### System status

```bash
winctl status
```

### Run PowerShell

```bash
winctl run "Get-Process"
winctl run "Get-Service"
```

### Run CMD

```bash
winctl run "dir C:\Users" --shell cmd
```

### Run Linux commands through WSL

```bash
winctl run "uname -a" --shell wsl
winctl run "ls -la /mnt/c/Users" --shell wsl
```

### Interactive command loop

```bash
winctl shell
winctl shell cmd
winctl shell wsl
```

The client keeps track of the remote working directory between commands.

## 4. File transfer

### Kali -> Windows

```bash
winctl upload test.py
```

Default destination is `C:\KaliAccess\uploads\test.py`.

Or choose a path:

```bash
winctl upload test.py C:\KaliAccess\uploads\test.py
```

### Windows -> Kali

```bash
winctl download C:\KaliAccess\results\result.txt
```

Or choose a local destination:

```bash
winctl download C:\KaliAccess\results\result.txt ./result.txt
```

Uploads/downloads are streamed and verified with SHA-256.

## 5. Files and processes

```bash
winctl ls C:\KaliAccess
winctl mkdir C:\KaliAccess\projects\test
winctl ps
winctl kill 1234
winctl start "notepad.exe"
```

## Security model

KaliAccess intentionally has powerful capabilities because it is meant for the owner to administer their own PC. Treat the agent password like an administrator credential.

Important defaults:

- HTTPS is always used.
- A TLS certificate is generated automatically by the Windows setup code.
- The password is never stored by the Kali client.
- Windows stores only a bcrypt password hash.
- `C:\ProgramData\KaliAccess` is ACL-restricted to SYSTEM and Administrators.
- The firewall rule is limited to Windows **Private** network profiles.
- Do **not** port-forward TCP/8765 directly to the public internet.
- For access across the internet, place both machines on a private VPN and keep the KaliAccess port private.

The service is installed in the normal Windows service context (LocalSystem by default). That is intentionally powerful: an authenticated KaliAccess session can perform actions with that service account's Windows permissions. Keep the port private and use a strong password.

## Working folders

The Windows setup creates:

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

Relative remote paths are resolved under `C:\KaliAccess`. Absolute Windows paths are also supported when the service account has permission.

## Uninstall Windows service

Run PowerShell as Administrator:

```powershell
.\windows_agent\uninstall.ps1
```

Keep data by default, or remove `C:\ProgramData\KaliAccess` too:

```powershell
.\windows_agent\uninstall.ps1 -RemoveProgramData
```

`C:\KaliAccess` is intentionally not removed automatically so your transferred files are not deleted by accident.

## Development check

A portable syntax check can be run on either Linux or Windows:

```bash
python3 -m compileall windows_agent kali_client
```
