#!/usr/bin/env bash
# Check status of Deal Forwarder

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PID_FILE="$DIR/forwarder.pid"
LOG_FILE="$DIR/forwarder.log"

RUNNING_PID=""
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        RUNNING_PID="$PID"
    fi
fi

if [ -z "$RUNNING_PID" ]; then
    RUNNING_PID=$(pgrep -f "python.*forwarder\.py" | head -n 1)
fi

echo "=================================================="
if [ -n "$RUNNING_PID" ]; then
    echo "Status: RUNNING (PID: $RUNNING_PID)"
    ps -p "$RUNNING_PID" -o pid,user,%cpu,%mem,etime,command | head -n 2
else
    echo "Status: STOPPED"
fi
echo "=================================================="

if [ -f "$LOG_FILE" ]; then
    echo "Recent Log Output (last 15 lines):"
    echo "--------------------------------------------------"
    tail -n 15 "$LOG_FILE"
    echo "--------------------------------------------------"
fi
