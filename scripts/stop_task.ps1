# Script to Stop / Disable Windows Task Scheduler Automation for LinkedIn Content
# Run in PowerShell: powershell -ExecutionPolicy Bypass -File scripts\stop_task.ps1

param(
    [string]$TaskName = "LinkedInAIContentAutomation",
    [switch]$Remove = $false
)

Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host "       STOP LINKEDIN AI CONTENT AUTOMATION TASK           " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Yellow

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    if (-not $task) {
        Write-Host "`n[INFO] Scheduled task '$TaskName' is not currently registered." -ForegroundColor Cyan
        exit 0
    }

    if ($Remove) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "`n[SUCCESS] Scheduled task '$TaskName' has been completely REMOVED." -ForegroundColor Green
        Write-Host "To re-register in the future, run: powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1" -ForegroundColor Cyan
    } else {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Host "`n[SUCCESS] Scheduled task '$TaskName' is now PAUSED (DISABLED)." -ForegroundColor Green
        Write-Host "The system will NOT post to LinkedIn automatically." -ForegroundColor Green
        Write-Host "`nTo resume automation later, run:" -ForegroundColor Cyan
        Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start_task.ps1" -ForegroundColor White
        Write-Host "  OR: Enable-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
    }
}
catch {
    Write-Error "Failed to modify scheduled task: $_"
}
