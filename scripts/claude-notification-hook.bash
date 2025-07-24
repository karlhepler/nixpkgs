set -eou pipefail

# Read JSON from stdin
json=$(cat)

# Extract message field from JSON
message=$(echo "$json" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data.get('message', 'Claude needs input'))")

# Send notification without Show button
terminal-notifier -title 'Claude Needs Input' -message "$message" -sound Ping -sender com.anthropic.claudefordesktop