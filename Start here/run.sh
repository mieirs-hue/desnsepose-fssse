#!/bin/bash
# Shortcut to run the Invisible Thesis Calibration 2 daemon

# Get the directory where the script is located
BASE_DIR=$(dirname "$(readlink -f "$0")")

# Define the path to the virtual environment's activate script
VENV_ACTIVATE="$BASE_DIR/.venv/bin/activate"

# Define the path to the Python daemon script
DAEMON_SCRIPT="$BASE_DIR/sentry_daemon.py"

# Check if the virtual environment exists
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "[ERROR] Python virtual environment not found at $BASE_DIR/.venv"
    echo "Please run the setup process again."
    exit 1
fi

# Check if the daemon script exists
if [ ! -f "$DAEMON_SCRIPT" ]; then
    echo "[ERROR] Daemon script not found at $DAEMON_SCRIPT"
    exit 1
fi

# Activate the virtual environment and run the daemon
source "$VENV_ACTIVATE"
echo "[SYSTEM] Virtual environment activated."
echo "[SYSTEM] Starting the 'Invisible Thesis' daemon..."
python "$DAEMON_SCRIPT" "$@"
