param(
    [int]$Port = 8765,
    [string]$Username = $env:USERNAME,
    [string]$Workspace = "C:\KaliAccess"
)
$ErrorActionPreference = "Stop"
$current = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($current)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run PowerShell as Administrator." }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$InstallRoot = "C:\ProgramData\KaliAccess"
$Venv = Join-Path $InstallRoot "venv"
$Agent = Join-Path $InstallRoot "agent.py"

Write-Host "[1/6] Installing files..."
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
# Keep the password hash and automatically generated TLS private key readable only by SYSTEM/Administrators.
& icacls $InstallRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot "agent.py") $Agent
Copy-Item -Force (Join-Path $RepoRoot "requirements-agent.txt") (Join-Path $InstallRoot "requirements-agent.txt")

Write-Host "[2/6] Python environment..."
if (-not (Test-Path $Venv)) { py -3 -m venv $Venv }
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $InstallRoot "requirements-agent.txt")
$PostInstall = Join-Path $Venv "Scripts\pywin32_postinstall.py"
if (Test-Path $PostInstall) { & $Python $PostInstall -install 2>$null }

Write-Host "[3/6] Password, TLS and workspace..."
& $Python $Agent setup --username $Username --port $Port --workspace $Workspace

Write-Host "[4/6] Windows service..."
if (Get-Service KaliAccessAgent -ErrorAction SilentlyContinue) {
    try { Stop-Service KaliAccessAgent -Force -ErrorAction SilentlyContinue } catch {}
    & $Python $Agent service remove | Out-Null
}
& $Python $Agent service --startup auto install

Write-Host "[5/6] Private-network firewall rule..."
Get-NetFirewallRule -DisplayName "KaliAccess Agent" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "KaliAccess Agent" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private | Out-Null

Write-Host "[6/6] Starting..."
& $Python $Agent service start | Out-Null
Start-Sleep 2
Get-Service KaliAccessAgent | Format-Table Name, Status, StartType
Write-Host "On Kali run: winctl setup <WINDOWS-IP> --username $Username --port $Port"
