# Script to Register Windows Task Scheduler Job for LinkedIn Daily Automation
# Run in PowerShell as Administrator or standard user

param(
    [string]$Time = "18:00",
    [string]$TaskName = "LinkedInAIContentAutomation"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunnerScript = Join-Path $ScriptDir "daily_post.ps1"

if (-not (Test-Path $RunnerScript)) {
    Write-Error "Could not find daily_post.ps1 at: $RunnerScript"
    exit 1
}

Write-Host "Registering Windows Task Scheduler Job: '$TaskName'..." -ForegroundColor Cyan
Write-Host "Daily Posting Time: $Time (Asia/Kolkata) - 6:00 PM IST" -ForegroundColor Cyan
Write-Host "Target Script:      $RunnerScript" -ForegroundColor Cyan

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunnerScript`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 45)

try {
    # Unregister existing if present
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
    
    # Register new task
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Daily LinkedIn AI Content Automation: discovers tech news, generates concise post + 1200x1200px PNG graphic, and publishes via official LinkedIn API." | Out-Null
    
    Write-Host "`n[SUCCESS] Scheduled task '$TaskName' registered successfully!" -ForegroundColor Green
    Write-Host "It will trigger every day at $Time." -ForegroundColor Green
    Write-Host "Note: For local Ollama, ensure laptop is awake or powered on at scheduled time." -ForegroundColor Yellow
}
catch {
    Write-Error "Failed to register scheduled task: $_"
}
