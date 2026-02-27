@echo off

if exist terminate.flag (
    del terminate.flag
)
if exist update.flag (
    del update.flag
)
echo. > PID

call .venv\Scripts\activate.bat
set LOOP_ACTIVE=true

set count=0

:loop
echo. > pending.flag
.\.venv\Scripts\python.exe main.py
if exist terminate.flag (
    echo Terminating...
    goto end
)

if exist pending.flag (
    set /a count+=1
    echo Restart count: %count%
    if %count% gtr 5 (
        echo Too many restarts without a successful init, terminating...
        goto end
    )
) else (
    set count=0
)
del pending.flag 2>nul

if exist update.flag (
    echo Updating...
    del update.flag
    git fetch

    set reexec=false
    set repip=false

    rem Check if this script has changed on the remote (HEAD..upstream)
    git diff --quiet HEAD..@{u} -- "%~f0"
    if errorlevel 1 (
        echo start.bat has changed in remote, scheduling reexec...
        set reexec=true
    )

    rem Check if requirements.txt has changed on the remote (HEAD..upstream)
    git diff --quiet HEAD..@{u} -- requirements.txt
    if errorlevel 1 (
        echo requirements.txt has changed in remote, scheduling pip install...
        set repip=true
    )

    git pull    

    if /I "%repip%"=="true" (
        echo Installing updated requirements...
        .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    )

    if /I "%reexec%"=="true" (
        echo Re-executing start.bat...
        call "%~f0" %*
        exit /b
    )

    echo Updated
)
echo Restarting...
timeout /t 1 >nul
goto loop

:end
call .venv\Scripts\deactivate.bat
set LOOP_ACTIVE=
