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
    & .\.venv\Scripts\python.exe main.py
    
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

        $reexec = $false
        $repip = $false

        # Check if this script has changed on the remote (HEAD..upstream)
        git diff --quiet HEAD..@{u} -- $PSCommandPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "start.ps1 has changed in remote, scheduling reexec..."
            $reexec = $true
        }

        # Check if requirements.txt has changed on the remote (HEAD..upstream)
        git diff --quiet HEAD..@{u} -- requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Write-Host "requirements.txt has changed in remote, scheduling pip install..."
            $repip = $true
        }

        git pull

        if ($repip) {
            Write-Host "Installing updated requirements..."
            .\.venv\Scripts\python.exe -m pip install -r requirements.txt
        }

        if ($reexec) {
            Write-Host "Re-executing start.ps1..."
            & $PSCommandPath @args
            exit
        }

        Write-Host "Updated"
    }
    Write-Host "Restarting..."
    Start-Sleep -Seconds 1
}

# Deactivate virtual environment
deactivate
Remove-Item Env:\LOOP_ACTIVE

