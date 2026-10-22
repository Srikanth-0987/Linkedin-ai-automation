# Script to Resume / Enable Windows Task Scheduler Automation for LinkedIn Content
# Run in PowerShell: powershell -ExecutionPolicy Bypass -File scripts\start_task.ps1

param(
    [string]$TaskName = "LinkedInAIContentAutomation"
)

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "      RESUME LINKEDIN AI CONTENT AUTOMATION TASK          " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    if (-not $task) {
        Write-Host "`n[INFO] Task '$TaskName' not found. Registering a fresh daily schedule at 18:00 (6:00 PM)..." -ForegroundColor Cyan
        & "$PSScriptRoot\register_task.ps1"
        exit 0
    }

    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Host "`n[SUCCESS] Scheduled task '$TaskName' is now ACTIVE (ENABLED)!" -ForegroundColor Green
    Write-Host "Daily automated publishing will run at 6:00 PM IST." -ForegroundColor Green
}
catch {
    Write-Error "Failed to enable scheduled task: $_"
}
