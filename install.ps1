#!/usr/bin/env pwsh

Write-Host "Creating Python virtual environment in .venv..."
python -m venv .venv

Write-Host "Activating virtual environment..."
& .venv\Scripts\Activate.ps1

Write-Host "Installing Python dependencies from requirements.txt..."
pip install -r requirements.txt

Write-Host "Deactivating virtual environment."
deactivate

Write-Host "Setup complete."

