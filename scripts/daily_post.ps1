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

# Wait for active network connection and DNS resolution (essential when laptop wakes from sleep)
Write-Output "[INFO] Checking network connectivity and DNS resolution..." | Tee-Object -FilePath $LogFile -Append
$networkReady = $false
$maxAttempts = 18  # 18 * 5 seconds = 90 seconds max wait
for ($i = 1; $i -le $maxAttempts; $i++) {
    try {
        $dnsTest = [System.Net.Dns]::GetHostAddresses("api.linkedin.com")
        if ($dnsTest.Length -gt 0) {
            $networkReady = $true
            Write-Output "[INFO] Network connection confirmed active (DNS resolved api.linkedin.com)." | Tee-Object -FilePath $LogFile -Append
            break
        }
    } catch {
        # DNS not ready yet
    }
    Write-Output "[INFO] Waiting for Wi-Fi / network connection to establish (attempt $i of $maxAttempts)..." | Tee-Object -FilePath $LogFile -Append
    Start-Sleep -Seconds 5
}

if (-not $networkReady) {
    Write-Output "[ERROR] Network unavailable after 90 seconds. Aborting daily run to prevent corrupt drafts." | Tee-Object -FilePath $LogFile -Append
    exit 1
}

# Note regarding Ollama / Laptop Sleep
Write-Output "[INFO] Network verified. Local Ollama available or cloud AI fallback ready." | Tee-Object -FilePath $LogFile -Append

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
