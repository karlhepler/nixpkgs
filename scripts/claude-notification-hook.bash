set -eou pipefail

# Read JSON from stdin
json=$(cat)

# Extract data from the new hook format
data=$(echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    message = data.get('message', 'Claude needs input')
    event_name = data.get('hook_event_name', 'Unknown')
    session_id = data.get('session_id', '')
    cwd = data.get('cwd', '')
    
    # Create context-aware title based on event
    if 'error' in message.lower():
        title = 'Claude Error'
    elif 'input' in message.lower() or 'prompt' in message.lower():
        title = 'Claude Needs Input'
    else:
        title = 'Claude Notification'
    
    # Add context info if available
    context = ''
    if cwd:
        context = f' in {cwd.split(\"/\")[-1] if \"/\" in cwd else cwd}'
    
    print(f'{title}|{message}{context}')
except Exception as e:
    print('Claude Notification|Claude needs input')
")

# Split the output into title and message
IFS='|' read -r title message <<< "$data"

# Send notification with Alacritty activation on click
terminal-notifier -title "$title" -message "$message" -sound Ping -sender com.anthropic.claudefordesktop -execute 'osascript -e "tell application \"Alacritty\" to activate"'