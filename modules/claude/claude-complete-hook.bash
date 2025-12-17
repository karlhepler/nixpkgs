set -eou pipefail

# Read JSON from stdin
json=$(cat)

# Extract data using official Claude Code Stop hook fields
data=$(echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    hook_event_name = data.get('hook_event_name', 'Stop')
    transcript_path = data.get('transcript_path', '')

    # Extract directory from transcript_path (Stop hook doesn't provide cwd!)
    dir_name = ''
    if transcript_path:
        # transcript_path format: ~/.claude/projects/{project_name}/{session_id}.jsonl
        parts = transcript_path.split('/')
        if 'projects' in parts:
            idx = parts.index('projects')
            if idx + 1 < len(parts):
                dir_name = parts[idx + 1]

    # Determine title and message
    if hook_event_name == 'SubagentStop':
        title = 'Claude Subagent Complete'
        message = f'Subagent task finished{\" in \" + dir_name if dir_name else \"\"}'
    else:
        title = 'Claude Code Complete'
        message = f'Task finished{\" in \" + dir_name if dir_name else \"\"}'

    print(f'{title}|{message}')
except Exception as e:
    print('Claude Code Complete|Task finished')
")

# Split output
IFS='|' read -r title message <<< "$data"

# Send notification from Alacritty (using bundle ID to avoid path issues)
osascript -e "tell application id \"org.alacritty\" to display notification \"$message\" with title \"$title\" sound name \"Glass\""

# Set tmux window option for attention flag
# Can't ring bell directly because Claude Code is a TUI that would receive the keys
if [[ -n "${TMUX:-}" && -n "${TMUX_PANE:-}" ]]; then
  # Set custom window option to flag this window needs attention
  tmux set-window-option -t "$TMUX_PANE" @claude_attention 1
fi
