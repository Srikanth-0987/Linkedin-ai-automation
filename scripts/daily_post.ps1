# Windows Task Scheduler Daily Execution Script for LinkedIn AI Content Automation
# Timezone: Asia/Kolkata

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# Ensure logs directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LogFile = Join-Path $LogDir "daily_run_$Timestamp.log"

Write-Output "==========================================================" | Tee-Object -FilePath $LogFile
Write-Output "   LINKEDIN AI CONTENT AUTOMATION - DAILY RUN SCHEDULER   " | Tee-Object -FilePath $LogFile
Write-Output "   Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') IST" | Tee-Object -FilePath $LogFile
Write-Output "==========================================================" | Tee-Object -FilePath $LogFile

# Verify virtual environment Python
if (-not (Test-Path $VenvPython)) {
    Write-Output "[ERROR] Virtual environment Python not found at: $VenvPython" | Tee-Object -FilePath $LogFile -Append
    Write-Output "Please initialize virtualenv: python -m venv .venv" | Tee-Object -FilePath $LogFile -Append
    exit 1
}

# Note regarding Ollama / Laptop Sleep
Write-Output "[INFO] Note: Local Ollama requires the laptop to be awake and ollama service running." | Tee-Object -FilePath $LogFile -Append

# Execute daily-run workflow
Push-Location $ProjectRoot
try {
    Write-Output "[RUN] Executing: python -m src.cli daily-run" | Tee-Object -FilePath $LogFile -Append
    & $VenvPython -m src.cli daily-run 2>&1 | Tee-Object -FilePath $LogFile -Append
    $ExitCode = $LASTEXITCODE
    Write-Output "`n[COMPLETE] Daily run completed with exit code: $ExitCode" | Tee-Object -FilePath $LogFile -Append
}
finally {
    Pop-Location
}
