@echo off

if exist terminate.flag (
    del terminate.flag
)

call .venv\Scripts\activate.bat
set LOOP_ACTIVE=true

:loop
python main.py
if exist terminate.flag (
    goto end
)
timeout /t 1
goto loop

:end
call .venv\Scripts\deactivate.bat
set LOOP_ACTIVE=
