#!/bin/bash

# Tmux Activity Monitor
# Monitors a tmux window and sends a command from a file if there's no activity

COMMAND_FILE="${1:-command.txt}"
SESSION="${2:-2}"
WINDOW="${3:-0}"
TIMEOUT="${4:-30}"  # seconds to wait before triggering

# Read command from file or use default
if [ -f "$COMMAND_FILE" ]; then
    COMMAND=$(cat "$COMMAND_FILE")
    echo "Reading command from file: $COMMAND_FILE"
else
    COMMAND="ls -lah"
    echo "Command file not found: $COMMAND_FILE"
    echo "Using default command: $COMMAND"
    echo "Create $COMMAND_FILE to customize the command"
fi

echo "Monitoring tmux session: $SESSION (window: $WINDOW)"
echo "Command to send: $COMMAND"
echo "Command file: $COMMAND_FILE"
echo "Timeout: $TIMEOUT seconds"
echo "Press Ctrl+C to stop"
echo "---"

# Get initial content
last_content=$(tmux capture-pane -t "$SESSION:$WINDOW" -p)

while true; do
    sleep "$TIMEOUT"

    # Get current content
    current_content=$(tmux capture-pane -t "$SESSION:$WINDOW" -p)

    # Compare content (ignore trailing whitespace differences)
    if [ "$last_content" = "$current_content" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - No activity detected, sending command from $COMMAND_FILE..."
        # Use paste-buffer for large content to avoid paste mode issues
        echo "$COMMAND" | tmux load-buffer -
        tmux paste-buffer -t "$SESSION:$WINDOW"
        # Send enter to trigger the command
        sleep 0.2
        tmux send-keys -t "$SESSION:$WINDOW" C-m
        # Small delay to ensure paste completes
        sleep 0.3
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Activity detected, content changed"
        last_content="$current_content"
    fi
done