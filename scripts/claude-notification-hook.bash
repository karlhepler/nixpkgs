set -eou pipefail

# Read JSON from stdin
json=$(cat)

# Extract data using official Claude Code hook fields
data=$(echo "$json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    message = data.get('message', 'Claude needs input')
    notification_type = data.get('notification_type', '')
    hook_event_name = data.get('hook_event_name', 'Notification')
    cwd = data.get('cwd', '')

    # Use notification_type for better title categorization
    if notification_type == 'permission_prompt':
        title = 'Claude Permission Request'
    elif notification_type == 'idle_prompt':
        title = 'Claude Waiting'
    elif notification_type == 'auth_success':
        title = 'Claude Authenticated'
    elif notification_type == 'elicitation_dialog':
        title = 'Claude Needs Input'
    elif 'error' in message.lower():
        title = 'Claude Error'
    else:
        title = 'Claude Notification'

    # Add context if available
    if cwd:
        dir_name = cwd.split('/')[-1] if '/' in cwd else cwd
        message = f'{message} [in {dir_name}]'

    print(f'{title}|{message}')
except Exception as e:
    print('Claude Notification|Claude needs input')
")

# Split output
IFS='|' read -r title message <<< "$data"

# Send notification from Alacritty (using bundle ID to avoid path issues)
osascript -e "tell application id \"org.alacritty\" to display notification \"$message\" with title \"$title\" sound name \"Ping\""
