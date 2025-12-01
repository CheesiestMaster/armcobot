@echo off

echo Creating Python virtual environment in .venv...
python -m venv .venv

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing Python dependencies from requirements.txt...
pip install -r requirements.txt

echo Deactivating virtual environment.
deactivate

echo Setup complete.

