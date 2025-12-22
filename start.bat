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
python main.py
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
    git diff start.bat >nul 2>&1
    if not errorlevel 1 (
        echo start.bat has changed, reexecuting...
        git pull
        call "%~f0" %*
        exit /b
    )
    git pull
    echo Updated
)
echo Restarting...
timeout /t 1 >nul
goto loop

:end
call .venv\Scripts\deactivate.bat
set LOOP_ACTIVE=
