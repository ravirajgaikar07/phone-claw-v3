#!/data/data/com.termux/files/usr/bin/bash

# PhoneClaw Termux Startup Script
# Usage: bash start_server.sh

set -e

PHONECLAW_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PHONECLAW_DIR"

echo "=== PhoneClaw Starting ==="
echo "Directory: $PHONECLAW_DIR"

# Prevent phone from sleeping
termux-wake-lock
echo "[✓] Wake lock acquired"

# Start SSH if available
if command -v sshd &> /dev/null; then
    sshd 2>/dev/null || true
    echo "[✓] SSH started"
fi

# Activate venv if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "[✓] Virtual environment activated"
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "[✓] Virtual environment activated"
fi

# Check if supervisord is available
if command -v supervisord &> /dev/null; then
    echo "[✓] Starting with supervisord..."
    supervisord -c "$PHONECLAW_DIR/supervisord.conf"
else
    echo "[!] supervisord not found — running directly"
    echo "    Install with: pip install supervisor"
    echo "    Starting PhoneClaw directly..."
    python3 run.py
fi
