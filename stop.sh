#!/usr/bin/env bash
# Stop Deal Forwarder background process

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PID_FILE="$DIR/forwarder.pid"

get_pids() {
    local pids=""
    if [ -f "$PID_FILE" ]; then
        pids=$(cat "$PID_FILE")
    fi
    local found_pids
    found_pids=$(pgrep -f "python.*forwarder\.py")
    if [ -n "$found_pids" ]; then
        pids="$pids $found_pids"
    fi
    echo "$pids" | tr ' ' '\n' | sort -u | grep -v '^$'
}

TARGET_PIDS=$(get_pids)

if [ -z "$TARGET_PIDS" ]; then
    echo "No running Deal Forwarder process found."
    rm -f "$PID_FILE"
    exit 0
fi

echo "Stopping Deal Forwarder process(es): $TARGET_PIDS..."
for pid in $TARGET_PIDS; do
    if ps -p "$pid" > /dev/null 2>&1; then
        kill -15 "$pid" 2>/dev/null
    fi
done

# Wait up to 5 seconds for clean exit
for i in {1..5}; do
    ALIVE=0
    for pid in $TARGET_PIDS; do
        if ps -p "$pid" > /dev/null 2>&1; then
            ALIVE=1
        fi
    done
    if [ "$ALIVE" -eq 0 ]; then
        break
    fi
    sleep 1
done

# Force kill if still hanging
for pid in $TARGET_PIDS; do
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "Process $pid did not terminate gracefully, sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null
    fi
done

rm -f "$PID_FILE"
echo "✓ Deal Forwarder stopped successfully."
