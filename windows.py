import ctypes
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time

DISCOVERY_PORT = 45888
DISCOVERY_MAGIC = "KALIACCESS_V1"

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
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        f'"{script}"',
        None,
        1,
    )
    if result <= 32:
        raise RuntimeError("Could not request Administrator permission.")


def run_powershell(command, capture=False):
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


def configure_windows():
    ps = rf"""
$ErrorActionPreference = 'Stop'

Write-Host '[1/5] Checking OpenSSH...'

$sshd = Get-Service sshd -ErrorAction SilentlyContinue
if (-not $sshd) {{
    $server = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*' | Select-Object -First 1
    if (-not $server) {{
        throw 'OpenSSH Server is not available as a Windows capability.'
    }}
    if ($server.State -ne 'Installed') {{
        Write-Host 'Installing OpenSSH Server...'
        Add-WindowsCapability -Online -Name $server.Name | Out-Null
    }}
}}

$client = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Client*' | Select-Object -First 1
if ($client -and $client.State -ne 'Installed') {{
    Write-Host 'Installing OpenSSH Client...'
    Add-WindowsCapability -Online -Name $client.Name | Out-Null
}}

Write-Host '[2/5] Starting SSH background service...'
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

$defaultSsh = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if ($defaultSsh) {{
    Disable-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' | Out-Null
}}

Write-Host '[3/5] Checking Remote Desktop support...'
$productName = (Get-ComputerInfo -Property WindowsProductName).WindowsProductName
$rdpSupported = [bool]($productName -match 'Pro|Professional|Enterprise|Education|Server')
$rdpRunning = $false

if ($rdpSupported) {{
    Write-Host '[4/5] Enabling authenticated Remote Desktop...'
    Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server' -Name 'fDenyTSConnections' -Type DWord -Value 0
    Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp' -Name 'UserAuthentication' -Type DWord -Value 1

    foreach ($item in @(
        @('{RDP_TCP_RULE}', 'TCP'),
        @('{RDP_UDP_RULE}', 'UDP')
    )) {{
        $ruleName = $item[0]
        $protocol = $item[1]
        $rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue

        if ($rule) {{
            Set-NetFirewallRule -Name $ruleName -Enabled True -Direction Inbound -Action Allow -Profile Any | Out-Null
            $rule = Get-NetFirewallRule -Name $ruleName
            Set-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule -RemoteAddress LocalSubnet | Out-Null
        }} else {{
            New-NetFirewallRule -Name $ruleName -DisplayName "KaliAccess RDP $protocol - Local subnet only" -Direction Inbound -Protocol $protocol -LocalPort 3389 -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null
        }}
    }}

    Start-Service TermService -ErrorAction SilentlyContinue
    $rdpRunning = [bool]((Get-Service TermService -ErrorAction SilentlyContinue).Status -eq 'Running')
}} else {{
    Write-Host '[4/5] Windows edition cannot host built-in RDP. Skipping RDP.'
}}

Write-Host '[5/5] Verifying SSH...'
$sshRunning = [bool]((Get-Service sshd).Status -eq 'Running')
$sshListening = [bool](Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue)

Write-Output ('KALIACCESS_PRODUCT=' + $productName)
Write-Output ('KALIACCESS_SSH_RUNNING=' + [int]$sshRunning)
Write-Output ('KALIACCESS_SSH_LISTENING=' + [int]$sshListening)
Write-Output ('KALIACCESS_RDP_SUPPORTED=' + [int]$rdpSupported)
Write-Output ('KALIACCESS_RDP_RUNNING=' + [int]$rdpRunning)
"""

    result = run_powershell(ps, capture=True)
    info = {}

    for line in result.stdout.splitlines():
        if line.startswith("KALIACCESS_") and "=" in line:
            key, value = line.split("=", 1)
            info[key] = value.strip()

    return info


def get_interfaces():
    ps = r"""
$items = Get-NetIPConfiguration |
    Where-Object {
        $_.NetAdapter.Status -eq 'Up' -and $_.IPv4Address
    } |
    ForEach-Object {
        foreach ($addr in $_.IPv4Address) {
            if ($addr.IPAddress -notlike '127.*' -and $addr.IPAddress -notlike '169.254.*') {
                [PSCustomObject]@{
                    InterfaceAlias = $_.InterfaceAlias
                    IPAddress = $addr.IPAddress
                    PrefixLength = $addr.PrefixLength
                }
            }
        }
    }

$items | ConvertTo-Json -Compress
"""

    result = run_powershell(ps, capture=True)
    raw = result.stdout.strip()

    if not raw:
        return []

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    interfaces = []
    for item in data:
        try:
            ip = str(item["IPAddress"])
            prefix = int(item["PrefixLength"])
            network = ipaddress.IPv4Interface(f"{ip}/{prefix}").network
            interfaces.append(
                {
                    "name": str(item.get("InterfaceAlias", "")),
                    "ip": ip,
                    "prefix": prefix,
                    "broadcast": str(network.broadcast_address),
                }
            )
        except Exception:
            continue

    return interfaces


def send_discovery(info, interfaces, seconds=30):
    username = os.environ.get("USERNAME", "")
    hostname = socket.gethostname()

    packet = {
        "magic": DISCOVERY_MAGIC,
        "hostname": hostname,
        "username": username,
        "ips": [item["ip"] for item in interfaces],
        "ssh_port": 22,
        "ssh_ready": (
            info.get("KALIACCESS_SSH_RUNNING") == "1"
            and info.get("KALIACCESS_SSH_LISTENING") == "1"
        ),
        "rdp_supported": info.get("KALIACCESS_RDP_SUPPORTED") == "1",
        "rdp_ready": info.get("KALIACCESS_RDP_RUNNING") == "1",
        "windows_product": info.get("KALIACCESS_PRODUCT", "Windows"),
    }

    payload = json.dumps(packet).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    targets = sorted({item["broadcast"] for item in interfaces})
    if "255.255.255.255" not in targets:
        targets.append("255.255.255.255")

    print()
    print(f"Sending connection information to Kali for {seconds} seconds...")
    print("Run kali.py on Kali now if it is not already waiting.")
    print()

    end = time.time() + seconds

    while time.time() < end:
        for target in targets:
            try:
                sock.sendto(payload, (target, DISCOVERY_PORT))
            except OSError:
                pass
        time.sleep(1)

    sock.close()


def main():
    if os.name != "nt":
        print("Run windows.py on the Windows computer.")
        return 1

    if not is_admin():
        print("Requesting Administrator permission...")
        restart_as_admin()
        return 0

    print()
    print("KaliAccess - Windows setup")
    print("=" * 40)

    try:
        info = configure_windows()
        interfaces = get_interfaces()
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

    username = os.environ.get("USERNAME", "<WINDOWS_USER>")

    print()
    print("Windows setup complete.")
    print(f"User: {username}")
    print(f"Windows: {info.get('KALIACCESS_PRODUCT', 'Windows')}")

    if interfaces:
        print("Detected IPv4 addresses:")
        for item in interfaces:
            print(f"  {item['name']}: {item['ip']}/{item['prefix']}")
    else:
        print("No usable IPv4 address was detected.")

    ssh_ready = (
        info.get("KALIACCESS_SSH_RUNNING") == "1"
        and info.get("KALIACCESS_SSH_LISTENING") == "1"
    )
    print(f"SSH: {'READY' if ssh_ready else 'NOT READY'}")

    if info.get("KALIACCESS_RDP_SUPPORTED") == "1":
        print(
            "Remote Desktop: "
            + ("READY" if info.get("KALIACCESS_RDP_RUNNING") == "1" else "CHECK FAILED")
        )
    else:
        print("Remote Desktop: unavailable as a built-in host on this Windows edition")

    if ssh_ready and interfaces:
        send_discovery(info, interfaces, seconds=30)

    print()
    print("SSH keeps running as a Windows background service.")
    print("The discovery broadcast stops when this program exits.")
    input("Press Enter to close...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
