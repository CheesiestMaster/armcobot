#!/bin/bash

echo "Creating Python virtual environment in .venv..."
python3 -m venv .venv

echo "Activating virtual environment..."
source .venv/bin/activate

echo "Installing Python dependencies from requirements.txt..."
pip install -r requirements.txt

echo "Deactivating virtual environment."
deactivate

echo "Setup complete."