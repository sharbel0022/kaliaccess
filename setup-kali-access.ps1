#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== KaliAccess - Windows SSH setup ===" -ForegroundColor Cyan
Write-Host ""

# 1) Install OpenSSH Server if needed
$capability = Get-WindowsCapability -Online |
    Where-Object { $_.Name -like "OpenSSH.Server*" } |
    Select-Object -First 1

if (-not $capability) {
    throw "OpenSSH Server capability could not be found on this Windows installation."
}

if ($capability.State -ne "Installed") {
    Write-Host "[1/5] Installing OpenSSH Server..."
    Add-WindowsCapability -Online -Name $capability.Name | Out-Null
} else {
    Write-Host "[1/5] OpenSSH Server is already installed."
}

# 2) Start SSH service and enable automatic startup
Write-Host "[2/5] Starting sshd..."
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

# 3) Firewall: allow TCP/22 only from the local subnet
Write-Host "[3/5] Configuring Windows Firewall..."
$ruleName = "KaliAccess-SSH-LocalSubnet"

$existingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue

if ($existingRule) {
    Set-NetFirewallRule `
        -Name $ruleName `
        -Enabled True `
        -Direction Inbound `
        -Action Allow `
        -Profile Any | Out-Null

    Set-NetFirewallAddressFilter `
        -AssociatedNetFirewallRule $existingRule `
        -RemoteAddress LocalSubnet | Out-Null
} else {
    New-NetFirewallRule `
        -Name $ruleName `
        -DisplayName "KaliAccess SSH (Local Subnet Only)" `
        -Description "Allows SSH/SCP/SFTP to this Windows PC from devices on the local subnet." `
        -Enabled True `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 22 `
        -RemoteAddress LocalSubnet `
        -Action Allow `
        -Profile Any | Out-Null
}

# Disable Microsoft's broader default OpenSSH firewall rule if it exists.
# KaliAccess keeps its own LocalSubnet-only rule above.
$defaultRules = Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -eq "OpenSSH-Server-In-TCP" -or
        $_.DisplayName -eq "OpenSSH SSH Server (sshd)"
    }

foreach ($rule in $defaultRules) {
    if ($rule.Name -ne $ruleName) {
        Disable-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue
    }
}

# 4) Detect a usable IPv4 address
Write-Host "[4/5] Detecting local IPv4 address..."

$ip = Get-NetIPConfiguration |
    Where-Object {
        $_.IPv4Address -and
        $_.NetAdapter.Status -eq "Up"
    } |
    ForEach-Object { $_.IPv4Address.IPAddress } |
    Where-Object {
        $_ -notlike "127.*" -and
        $_ -notlike "169.254.*"
    } |
    Select-Object -First 1

if (-not $ip) {
    $ip = "<WINDOWS-IP>"
}

$username = $env:USERNAME

# 5) Verify service / listener
Write-Host "[5/5] Verifying SSH..."
$service = Get-Service sshd
$listener = Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green

if ($service.Status -eq "Running" -and $listener) {
    Write-Host "KaliAccess is READY." -ForegroundColor Green
} else {
    Write-Host "Setup completed, but port 22 could not be verified." -ForegroundColor Yellow
}

Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Windows user : $username"
Write-Host "Windows IP   : $ip"
Write-Host ""
Write-Host "From Kali:" -ForegroundColor Cyan
Write-Host "  ssh $username@$ip" -ForegroundColor Yellow
Write-Host ""
Write-Host "Send a file Kali -> Windows Desktop:" -ForegroundColor Cyan
Write-Host "  scp image.jpg ${username}@${ip}:Desktop/" -ForegroundColor Yellow
Write-Host ""
Write-Host "Download a file Windows -> Kali:" -ForegroundColor Cyan
Write-Host "  scp ${username}@${ip}:Desktop/file.txt ." -ForegroundColor Yellow
Write-Host ""
Write-Host "Interactive file transfer:" -ForegroundColor Cyan
Write-Host "  sftp $username@$ip" -ForegroundColor Yellow
Write-Host ""
Write-Host "IMPORTANT: Use your real Windows account password, not the Windows Hello PIN." -ForegroundColor Magenta
Write-Host "SSH access is restricted to your local subnet by Windows Firewall." -ForegroundColor Magenta
Write-Host ""
Read-Host "Press Enter to close"
