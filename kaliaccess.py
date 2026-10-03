import ctypes
import os
import socket
import subprocess
import sys


SSH_RULE = "KaliAccess-SSH-LocalSubnet"
RDP_TCP_RULE = "KaliAccess-RDP-TCP-LocalSubnet"
RDP_UDP_RULE = "KaliAccess-RDP-UDP-LocalSubnet"


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
        raise RuntimeError("Could not restart as Administrator.")


def powershell(command, capture=False):
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        text=True,
        capture_output=capture,
    )


def get_local_ip():
    # UDP connect chooses the active interface without sending application data.
    for target in ("1.1.1.1", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            ip = sock.getsockname()[0]
            if not ip.startswith(("127.", "169.254.")):
                return ip
        except OSError:
            pass
        finally:
            sock.close()

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith(("127.", "169.254.")):
                return ip
    except OSError:
        pass

    return "<run ipconfig to find the Windows IPv4 address>"


def setup():
    ps = rf"""
$ErrorActionPreference = 'Stop'

Write-Host '[1/4] Configuring OpenSSH Server...'

$ssh = Get-WindowsCapability -Online |
    Where-Object Name -like 'OpenSSH.Server*' |
    Select-Object -First 1

if (-not $ssh) {{
    throw 'OpenSSH Server is not available as a Windows capability.'
}}

if ($ssh.State -ne 'Installed') {{
    Add-WindowsCapability -Online -Name $ssh.Name | Out-Null
}}

Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

$sshRule = Get-NetFirewallRule -Name '{SSH_RULE}' -ErrorAction SilentlyContinue
if ($sshRule) {{
    Set-NetFirewallRule -Name '{SSH_RULE}' -Enabled True -Direction Inbound -Action Allow -Profile Any | Out-Null
    $sshRule = Get-NetFirewallRule -Name '{SSH_RULE}'
    Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $sshRule -RemoteAddress LocalSubnet | Out-Null
}} else {{
    New-NetFirewallRule -Name '{SSH_RULE}' -DisplayName 'KaliAccess SSH - Local subnet only' -Direction Inbound -Protocol TCP -LocalPort 22 -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
}}

# Windows can create this broader rule when OpenSSH is installed.
# KaliAccess uses its own LocalSubnet-only rule instead.
$defaultSshRule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if ($defaultSshRule) {{
    Disable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' | Out-Null
}}

Write-Host '[2/4] Detecting Windows edition...'

$productName = (Get-ComputerInfo -Property WindowsProductName).WindowsProductName
$rdpSupported = $false

if ($productName -match 'Pro|Professional|Enterprise|Education|Server') {{
    $rdpSupported = $true
}}

Write-Host '[3/4] Configuring Remote Desktop when supported...'

if ($rdpSupported) {{
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -Type DWord -Value 0
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name 'UserAuthentication' -Type DWord -Value 1

    foreach ($ruleSpec in @(
        @('{RDP_TCP_RULE}', 'TCP'),
        @('{RDP_UDP_RULE}', 'UDP')
    )) {{
        $name = $ruleSpec[0]
        $protocol = $ruleSpec[1]
        $rule = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue

        if ($rule) {{
            Set-NetFirewallRule -Name $name -Enabled True -Direction Inbound -Action Allow -Profile Any | Out-Null
            $rule = Get-NetFirewallRule -Name $name
            Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule -RemoteAddress LocalSubnet | Out-Null
        }} else {{
            New-NetFirewallRule -Name $name -DisplayName "KaliAccess RDP $protocol - Local subnet only" -Direction Inbound -Protocol $protocol -LocalPort 3389 -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
        }}
    }}

    Start-Service TermService -ErrorAction SilentlyContinue
}}

Write-Host '[4/4] Verifying services...'

$sshRunning = ((Get-Service sshd).Status -eq 'Running')
$rdpRunning = $false

if ($rdpSupported) {{
    $rdpRunning = ((Get-Service TermService).Status -eq 'Running')
}}

Write-Output ('KALIACCESS_PRODUCT=' + $productName)
Write-Output ('KALIACCESS_SSH=' + [int]$sshRunning)
Write-Output ('KALIACCESS_RDP_SUPPORTED=' + [int]$rdpSupported)
Write-Output ('KALIACCESS_RDP_RUNNING=' + [int]$rdpRunning)
"""

    result = powershell(ps, capture=True)

    info = {}
    for line in result.stdout.splitlines():
        if line.startswith("KALIACCESS_") and "=" in line:
            key, value = line.split("=", 1)
            info[key] = value.strip()

    return info


def main():
    if os.name != "nt":
        print("Run kaliaccess.py on the Windows computer you want to access.")
        return 1

    if not is_admin():
        print("Requesting Administrator permission...")
        restart_as_admin()
        return 0

    print()
    print("KaliAccess")
    print("Configuring secure background access on this Windows PC...")
    print()

    try:
        info = setup()
    except subprocess.CalledProcessError as exc:
        print("Setup failed.")
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr)
        input("Press Enter to close...")
        return 1
    except Exception as exc:
        print(f"Setup failed: {exc}")
        input("Press Enter to close...")
        return 1

    ip = get_local_ip()
    username = os.environ.get("USERNAME", "<WINDOWS_USER>")
    product = info.get("KALIACCESS_PRODUCT", "Windows")
    ssh_ok = info.get("KALIACCESS_SSH") == "1"
    rdp_supported = info.get("KALIACCESS_RDP_SUPPORTED") == "1"
    rdp_running = info.get("KALIACCESS_RDP_RUNNING") == "1"

    print()
    print("=" * 62)
    print("KALIACCESS READY")
    print("=" * 62)
    print(f"Windows edition : {product}")
    print(f"Windows user    : {username}")
    print(f"Windows IP      : {ip}")
    print(f"SSH background  : {'READY' if ssh_ok else 'CHECK FAILED'}")

    if rdp_supported:
        print(f"Remote Desktop  : {'READY' if rdp_running else 'ENABLED / CHECK SERVICE'}")
    else:
        print("Remote Desktop  : NOT AVAILABLE on this Windows edition")
        print("                  Windows Home cannot act as an RDP host.")

    print()
    print("From Kali - terminal:")
    print(f"  ssh {username}@{ip}")

    print()
    print("Kali -> Windows file:")
    print(f"  scp bild.jpg {username}@{ip}:Desktop/")

    print()
    print("Windows -> Kali file:")
    print(f"  scp {username}@{ip}:Desktop/test.txt .")

    print()
    print("Interactive file transfer:")
    print(f"  sftp {username}@{ip}")

    if rdp_supported:
        print()
        print("Windows screen from Kali:")
        print(f"  xfreerdp3 /v:{ip} /u:{username} /dynamic-resolution")
        print("  If your Kali package uses the older command name, use xfreerdp instead.")

    print()
    print("Important:")
    print("- SSH and RDP firewall access created by KaliAccess is limited to LocalSubnet.")
    print("- Use a real Windows account password; Windows Hello PIN is not an SSH password.")
    print("- The SSH service keeps running in the background after this setup window closes.")
    print("- Remote Desktop is normal authenticated Windows access, not hidden screen capture.")
    print()
    input("Press Enter to close...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
