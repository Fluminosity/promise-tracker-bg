# Registers a WEEKLY Windows scheduled task that refreshes the site data (local Ollama judge).
# Only needed if the update runs on this PC. If a Hermes agent runs it instead, skip this file (see hermes\WEEKLY_JOB.md).
# Run once, from this folder:   powershell -ExecutionPolicy Bypass -File .\schedule.ps1
# Remove later with:            Unregister-ScheduledTask -TaskName PromiseTrackerWeekly -Confirm:$false
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $python -Argument "pipeline\run_all.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 7:30am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName "PromiseTrackerWeekly" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Fetch news, judge promises with local Ollama, rebuild site/data.js" -Force
Write-Host "Scheduled: every Monday 07:30 (or at next logon if the PC was off)."
