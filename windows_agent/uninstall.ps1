param([switch]$RemoveProgramData)
$ErrorActionPreference = "Stop"
$Root = "C:\ProgramData\KaliAccess"
$Python = Join-Path $Root "venv\Scripts\python.exe"
$Agent = Join-Path $Root "agent.py"
$TaskName = "KaliAccess Desktop Helper"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*KaliAccess*desktop_helper.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (Get-Service KaliAccessAgent -ErrorAction SilentlyContinue) {
    try { Stop-Service KaliAccessAgent -Force -ErrorAction SilentlyContinue } catch {}
    if ((Test-Path $Python) -and (Test-Path $Agent)) { & $Python $Agent service remove | Out-Null }
}
Get-NetFirewallRule -DisplayName "KaliAccess Agent" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $env:LOCALAPPDATA "KaliAccess\desktop-helper.token") -ErrorAction SilentlyContinue
if ($RemoveProgramData) { Remove-Item -Recurse -Force $Root -ErrorAction SilentlyContinue }
Write-Host "KaliAccess service and desktop helper removed. C:\KaliAccess user files were not deleted."
