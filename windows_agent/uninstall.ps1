param([switch]$RemoveProgramData)
$ErrorActionPreference = "Stop"
$Root = "C:\ProgramData\KaliAccess"
$Python = Join-Path $Root "venv\Scripts\python.exe"
$Agent = Join-Path $Root "agent.py"
if (Get-Service KaliAccessAgent -ErrorAction SilentlyContinue) {
    try { Stop-Service KaliAccessAgent -Force -ErrorAction SilentlyContinue } catch {}
    if ((Test-Path $Python) -and (Test-Path $Agent)) { & $Python $Agent service remove | Out-Null }
}
Get-NetFirewallRule -DisplayName "KaliAccess Agent" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
if ($RemoveProgramData) { Remove-Item -Recurse -Force $Root -ErrorAction SilentlyContinue }
Write-Host "KaliAccess service removed. C:\KaliAccess user files were not deleted."
