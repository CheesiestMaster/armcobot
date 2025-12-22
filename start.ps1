#!/usr/bin/env pwsh

# Remove flag files
if (Test-Path "./terminate.flag") {
    Remove-Item "./terminate.flag"
}
if (Test-Path "./update.flag") {
    Remove-Item "./update.flag"
}
# Clear the PID file
"" | Out-File -FilePath "./PID" -NoNewline

# Activate virtual environment
& .venv\Scripts\Activate.ps1
$env:LOOP_ACTIVE = "true"

$count = 0

while ($true) {
    # Create pending flag
    New-Item -Path "./pending.flag" -ItemType File -Force | Out-Null
    
    # Run main.py
    python main.py
    
    if (Test-Path "./terminate.flag") {
        Write-Host "Terminating..."
        break
    }

    if (Test-Path "./pending.flag") {
        $count++
        Write-Host "Restart count: $count"
        if ($count -gt 5) {
            Write-Host "Too many restarts without a successful init, terminating..."
            break
        }
    } else {
        $count = 0
    }
    Remove-Item "./pending.flag" -ErrorAction SilentlyContinue

    if (Test-Path "./update.flag") {
        Write-Host "Updating..."
        Remove-Item "./update.flag"
        git fetch
        $diff = git diff ./start.ps1
        if ($diff -ne "") {
            Write-Host "start.ps1 has changed, reexecuting..."
            git pull
            & $PSCommandPath $args
            exit
        }
        git pull
        Write-Host "Updated"
    }
    Write-Host "Restarting..."
    Start-Sleep -Seconds 1
}

# Deactivate virtual environment
deactivate
Remove-Item Env:\LOOP_ACTIVE

