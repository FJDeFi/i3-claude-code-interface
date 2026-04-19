# Tmux Activity Monitor

A smart tmux monitor that automatically sends commands when no activity is detected in a specified tmux window.

## Features

- 📝 **Command File Support**: Read commands from a text file instead of command line arguments
- 🎯 **Smart Monitoring**: Detects when content changes and only sends commands during inactivity
- 📄 **Large File Support**: Handles large text pastes without "Paste from lines" issues
- 🔄 **Auto-Trigger**: Automatically sends Enter to execute pasted commands
- ⚡ **Lightweight**: Minimal resource usage with configurable timeouts

## Quick Start

### Basic Usage

```bash
# Use default command.txt file and settings
./tmux-monitor.sh
```

### Custom Command File

```bash
# Use your own command file
./tmux-monitor.sh my-command.txt
```

### Full Customization

```bash
# Specify all parameters
./tmux-monitor.sh command.txt 2 0 30
```

## Configuration

### Command File Format

Create a text file with the command you want to inject:

```bash
# Simple command
echo "ls -la" > command.txt

# Multi-line command (will be sent as one block)
cat > command.txt << EOF
git status
git add .
git commit -m "update"
EOF
```

### Command File Arguments

The script reads parameters in this order:
1. **Command file** (optional, default: `command.txt`)
2. **Session number** (optional, default: `2`)
3. **Window number** (optional, default: `0`)
4. **Timeout in seconds** (optional, default: `30`)

## Examples

### Example 1: Git Status Monitor

```bash
# Create command file
echo "git status" > command.txt

# Run monitor
./tmux-monitor.sh command.txt 1 0 45
```

### Example 2: System Status Checker

```bash
# Create a system monitoring command
cat > system-check.txt << EOF
echo "=== System Status ==="
date
uptime
df -h
free -m
EOF

./tmux-monitor.sh system-check.txt 2 1 60
```

### Example 3: Development Workflow

```bash
# Auto-save workflow
cat > auto-save.txt << EOF
echo "Auto-saving..."
git add .
git commit -m "auto-save $(date)"
git push origin main
EOF

./tmux-monitor.sh auto-save.txt 3 0 300  # 5 minute intervals
```

## How It Works

1. **Read Command**: Loads the entire content from your command file
2. **Monitor**: Checks tmux window content every `TIMEOUT` seconds
3. **Detect Inactivity**: If content hasn't changed, it's inactive
4. **Paste Command**: Uses `tmux load-buffer` and `paste-buffer` for large files
5. **Send Enter**: Automatically triggers the command with Enter key
6. **Repeat**: Continues monitoring until stopped with Ctrl+C

## File Structure

```
.
├── tmux-monitor.sh     # Main script (make executable with chmod +x)
├── command.txt        # Default command file (edit this to customize)
└── README.md          # This file
```

## Advanced Usage

### Working with Large Text Files

The script is optimized for large content:

```bash
# Works with files containing thousands of lines
./tmux-monitor.sh large-file.txt 1 0 120
```

### Custom Session/Window Configuration

Monitor different tmux sessions:

```bash
# Monitor session 1, window 3
./tmux-monitor.sh command.txt 1 3 60

# Monitor session 0, window 0 (main session)
./tmux-monitor.sh command.txt 0 0 30
```

### Multiple Command Files

Create different command files for different purposes:

```bash
# For development
./tmux-monitor.sh dev-commands.txt 2 0 30

# For monitoring
./tmux-monitor.sh mon-commands.txt 3 0 60
```

## Troubleshooting

### Common Issues

1. **Permission Denied**
   ```bash
   chmod +x tmux-monitor.sh
   ```

2. **Command File Not Found**
   - The script will use `ls -lah` as default
   - Create a `command.txt` file to customize

3. **Tmux Session Not Accessible**
   - Ensure you're in a tmux session
   - Check session/window numbers exist

4. **Large Paste Issues**
   - The script uses `load-buffer` + `paste-buffer` to handle large files
   - No "Paste from lines" message should appear

### Debug Mode

Add debug output by checking variables:

```bash
# Show current configuration
echo "Command file: ${1:-command.txt}"
echo "Session: ${2:-2}"
echo "Window: ${3:-0}"
echo "Timeout: ${4:-30}"
```

## Tips & Best Practices

1. **Use Descriptive File Names**
   ```bash
   echo "git status" > git-monitor.txt
   echo "docker ps" > docker-monitor.txt
   ```

2. **Keep Commands Relevant**
   - Commands should be useful for monitoring
   - Avoid interactive commands that require user input

3. **Set Appropriate Timeouts**
   - Short timeouts (10-30s) for quick checks
   - Long timeouts (60-300s) for heavy operations

4. **Clean Up Old Command Files**
   - Remove unused command files
   - Archive important ones

## Reference

### tmux Commands Used

- `tmux capture-pane -t session:window -p`: Capture window content
- `tmux load-buffer -`: Load content into paste buffer
- `tmux paste-buffer -t session:window`: Paste from buffer
- `tmux send-keys -t session:window C-m`: Send Enter key

### Exit the Script

Press `Ctrl+C` to stop the monitoring at any time.

## Contributing

Feel free to modify the script for your needs. The core logic is simple and can be easily extended.