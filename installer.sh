#!/bin/bash

# Define the name of the virtual environment
venv_name="SisenseAI"

# Define the path to the virtual environment
venv_path="./venv/${venv_name}"

# Check if the virtual environment exists
if [ -d "${venv_path}" ]; then
  echo "Virtual environment already exists. Activating..."
  # Activate the environment
  source "${venv_path}/bin/activate"

  # Install required packages from requirements.txt using pip
  pip install -r requirements.txt
  pip install paramiko scp
  pip install scp
else
  echo "Creating new virtual environment..."
  # Create new directory "venv"
  mkdir -p "./venv"

  # Create new Python virtual environment with name "SisenseAI" inside the "venv" directory
  python3 -m venv "${venv_path}"

  # Activate the environment
  source "${venv_path}/bin/activate"

  # Install required packages from requirements.txt using pip
  pip install -r requirements.txt
fi

# Run installer.py
python3 installer.py

# Deactivate the environment
deactivate
