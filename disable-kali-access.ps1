#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== KaliAccess - Disable SSH access ===" -ForegroundColor Cyan
Write-Host ""

$ruleName = "KaliAccess-SSH-LocalSubnet"

if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    Disable-NetFirewallRule -Name $ruleName
    Write-Host "Firewall rule disabled." -ForegroundColor Green
}

if (Get-Service sshd -ErrorAction SilentlyContinue) {
    Stop-Service sshd -Force -ErrorAction SilentlyContinue
    Set-Service sshd -StartupType Manual
    Write-Host "SSH service stopped and automatic startup disabled." -ForegroundColor Green
}

Write-Host ""
Write-Host "KaliAccess is disabled." -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to close"
