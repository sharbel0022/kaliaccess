param(
    [int]$Port = 8765,
    [int]$DesktopPort = 8766,
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
$DesktopHelper = Join-Path $InstallRoot "desktop_helper.py"
$TaskName = "KaliAccess Desktop Helper"
$UserSid = $current.User.Value
$CurrentUser = $current.Name

Write-Host "[1/8] Installing files..."
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
& icacls $InstallRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot "agent.py") $Agent
Copy-Item -Force (Join-Path $PSScriptRoot "desktop_helper.py") $DesktopHelper
Copy-Item -Force (Join-Path $RepoRoot "requirements-agent.txt") (Join-Path $InstallRoot "requirements-agent.txt")

Write-Host "[2/8] Python environment..."
if (-not (Test-Path $Venv)) { py -3 -m venv $Venv }
$Python = Join-Path $Venv "Scripts\python.exe"
$Pythonw = Join-Path $Venv "Scripts\pythonw.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $InstallRoot "requirements-agent.txt")
$PostInstall = Join-Path $Venv "Scripts\pywin32_postinstall.py"
if (Test-Path $PostInstall) { & $Python $PostInstall -install 2>$null }

Write-Host "[3/8] Password, TLS and workspace..."
& $Python $Agent setup --username $Username --port $Port --workspace $Workspace

Write-Host "[4/8] Desktop helper pairing..."
[byte[]]$TokenBytes = New-Object byte[] 32
$Rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $Rng.GetBytes($TokenBytes) } finally { $Rng.Dispose() }
$DesktopToken = -join ($TokenBytes | ForEach-Object { $_.ToString("x2") })

$ConfigPath = Join-Path $InstallRoot "config.json"
$Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$Config | Add-Member -NotePropertyName desktop_helper_port -NotePropertyValue $DesktopPort -Force
$Config | Add-Member -NotePropertyName desktop_helper_token -NotePropertyValue $DesktopToken -Force
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($ConfigPath, ($Config | ConvertTo-Json -Depth 10), $Utf8NoBom)

$HelperUserRoot = Join-Path $env:LOCALAPPDATA "KaliAccess"
New-Item -ItemType Directory -Force -Path $HelperUserRoot | Out-Null
$TokenFile = Join-Path $HelperUserRoot "desktop-helper.token"
[IO.File]::WriteAllText($TokenFile, $DesktopToken, $Utf8NoBom)

& icacls $Venv /grant:r "*${UserSid}:(OI)(CI)RX" | Out-Null
& icacls $DesktopHelper /grant:r "*${UserSid}:RX" | Out-Null

Write-Host "[5/8] Windows service..."
if (Get-Service KaliAccessAgent -ErrorAction SilentlyContinue) {
    try { Stop-Service KaliAccessAgent -Force -ErrorAction SilentlyContinue } catch {}
    & $Python $Agent service remove | Out-Null
}
& $Python $Agent service --startup auto install

Write-Host "[6/8] Private-network firewall rule..."
Get-NetFirewallRule -DisplayName "KaliAccess Agent" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "KaliAccess Agent" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private | Out-Null

Write-Host "[7/8] Interactive desktop helper..."
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$HelperArgs = '"' + $DesktopHelper + '" --token-file "' + $TokenFile + '" --port ' + $DesktopPort
$TaskAction = New-ScheduledTaskAction -Execute $Pythonw -Argument $HelperArgs
$TaskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger $TaskTrigger -Principal $TaskPrincipal -Description "Visible KaliAccess desktop helper for screenshots and local key-event testing." | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "[8/8] Starting agent..."
& $Python $Agent service start | Out-Null
Start-Sleep 2
Get-Service KaliAccessAgent | Format-Table Name, Status, StartType
Write-Host "Desktop helper task: $TaskName"
Write-Host "On Kali run: winctl setup <WINDOWS-IP> --username $Username --port $Port"
