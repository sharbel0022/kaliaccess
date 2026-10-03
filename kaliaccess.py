import ctypes
import os
import socket
import subprocess
import sys


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def restart_as_admin():
    script = os.path.abspath(sys.argv[0])
    params = f'"{script}"'
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        None,
        1,
    )
    if result <= 32:
        raise RuntimeError("Kunde inte starta scriptet som administrator.")


def run_powershell(command):
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
    )


def get_local_ip():
    for target in ("1.1.1.1", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            return sock.getsockname()[0]
        except OSError:
            pass
        finally:
            sock.close()

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except OSError:
        pass

    return "<kor ipconfig for att hitta IP>"


if os.name != "nt":
    print("Detta script ska koras pa Windows.")
    sys.exit(1)


if not is_admin():
    print("Begär administratorrattigheter...")
    restart_as_admin()
    sys.exit(0)


print("KaliAccess: installerar och aktiverar Windows SSH...")

powershell = r"""
$ErrorActionPreference = 'Stop'

$ssh = Get-WindowsCapability -Online |
    Where-Object Name -like 'OpenSSH.Server*' |
    Select-Object -First 1

if (-not $ssh) {
    throw 'OpenSSH Server finns inte som Windows Capability.'
}

if ($ssh.State -ne 'Installed') {
    Write-Host 'Installerar OpenSSH Server...'
    Add-WindowsCapability -Online -Name $ssh.Name | Out-Null
}

Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

$ruleName = 'KaliAccess-SSH-LocalSubnet'

if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Any
    $rule = Get-NetFirewallRule -Name $ruleName
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule -RemoteAddress LocalSubnet
} else {
    New-NetFirewallRule         -Name $ruleName         -DisplayName 'KaliAccess SSH - Local subnet only'         -Direction Inbound         -Protocol TCP         -LocalPort 22         -RemoteAddress LocalSubnet         -Action Allow         -Profile Any | Out-Null
}

# Windows OpenSSH kan skapa en bredare standardregel.
# KaliAccess använder i stället regeln ovan, som bara tillåter lokala nätverket.
$defaultRule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if ($defaultRule) {
    Disable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP'
}

$service = Get-Service sshd
if ($service.Status -ne 'Running') {
    throw 'sshd startade inte korrekt.'
}
"""

try:
    run_powershell(powershell)
except subprocess.CalledProcessError:
    print()
    print("Nagot gick fel nar Windows SSH skulle aktiveras.")
    input("Tryck Enter for att stanga...")
    sys.exit(1)

ip = get_local_ip()
username = os.environ.get("USERNAME", "<WINDOWS_USER>")

print()
print("=" * 54)
print("KALIACCESS AR KLAR")
print("=" * 54)
print(f"Windows user: {username}")
print(f"Windows IP:   {ip}")
print()
print("Fran Kali:")
print(f"  ssh {username}@{ip}")
print()
print("Skicka en fil Kali -> Windows Desktop:")
print(f"  scp bild.jpg {username}@{ip}:Desktop/")
print()
print("Hamta en fil Windows -> Kali:")
print(f"  scp {username}@{ip}:Desktop/test.txt .")
print()
print("Interaktiv filoverforing:")
print(f"  sftp {username}@{ip}")
print()
print("Anvand ditt riktiga Windows-kontolosennord, inte Windows Hello-PIN.")
print("Brandvaggen tillater SSH endast fran det lokala natverket.")
print()
input("Tryck Enter for att stanga...")
