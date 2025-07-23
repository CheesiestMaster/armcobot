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

:loop
python main.py
if exist terminate.flag (
    echo Terminating...
    goto end
)
if exist update.flag (
    echo Updating...
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
