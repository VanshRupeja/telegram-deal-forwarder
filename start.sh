#!/usr/bin/env bash
# Start Deal Forwarder in background

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PID_FILE="$DIR/forwarder.pid"
LOG_FILE="$DIR/forwarder.log"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Deal Forwarder is ALREADY running (PID: $PID)."
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Fallback check
EXISTING_PID=$(pgrep -f "python.*forwarder\.py" | head -n 1)
if [ -n "$EXISTING_PID" ]; then
    echo "Deal Forwarder is ALREADY running (PID: $EXISTING_PID)."
    echo "$EXISTING_PID" > "$PID_FILE"
    exit 0
fi

echo "Starting Telegram Deal Forwarder in background..."
nohup "$DIR/venv/bin/python3" "$DIR/forwarder.py" >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 2
if ps -p "$NEW_PID" > /dev/null 2>&1; then
    echo "✓ Telegram Deal Forwarder started successfully (PID: $NEW_PID)."
    echo "Logs are being written to: $LOG_FILE"
    echo "Run './status.sh' to check status, or 'tail -f forwarder.log' to watch live logs."
else
    echo "✗ Failed to start forwarder. Check $LOG_FILE for details."
    exit 1
fi
