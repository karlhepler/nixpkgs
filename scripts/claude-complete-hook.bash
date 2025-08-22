set -eou pipefail

# Read JSON from stdin
json=$(cat)

# Extract data from the new hook format
data=$(echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    session_id = data.get('session_id', '')
    cwd = data.get('cwd', '')
    hook_event_name = data.get('hook_event_name', 'Stop')
    
    # Create context-aware message
    message = 'Task finished'
    if cwd:
        dir_name = cwd.split('/')[-1] if '/' in cwd else cwd
        message = f'Task finished in {dir_name}'
    
    # Determine title based on event
    if 'error' in str(data).lower():
        title = 'Claude Code Error'
    elif hook_event_name == 'SubagentStop':
        title = 'Claude Subagent Complete'
    else:
        title = 'Claude Code Complete'
    
    print(f'{title}|{message}')
except Exception as e:
    print('Claude Code Complete|Task finished')
")

# Split the output into title and message
IFS='|' read -r title message <<< "$data"

# Send notification with Alacritty activation on click
terminal-notifier -title "$title" -message "$message" -sound Glass -sender com.anthropic.claudefordesktop -activate org.alacritty