#!/data/data/com.termux/files/usr/bin/bash

# PhoneClaw Termux Startup Script
# Usage: bash start_server.sh

PHONECLAW_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PHONECLAW_DIR"

# Create logs directory
mkdir -p logs

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
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "[✓] Virtual environment activated"
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "[✓] Virtual environment activated"
fi

echo "[✓] Starting PhoneClaw (auto-restart on crash)..."
echo "    Press Ctrl+C to stop"
echo ""

# Auto-restart loop — restarts PhoneClaw if it crashes
while true; do
    python3 run.py 2>&1 | tee -a logs/phoneclaw.log
    EXIT_CODE=$?
    echo ""
    echo "[!] PhoneClaw exited with code $EXIT_CODE"
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[✓] Clean shutdown"
        break
    fi
    echo "[↻] Restarting in 5 seconds... (Ctrl+C to stop)"
    sleep 5
done
