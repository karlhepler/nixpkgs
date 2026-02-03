# Common functions shared by Claude Code hooks (inlined at build time)

# Get tmux context if in tmux
get_tmux_context() {
  local tmux_context=""
  if [[ -n "${TMUX:-}" && -n "${TMUX_PANE:-}" ]]; then
    local session_name window_name
    session_name=$(tmux display-message -t "$TMUX_PANE" -p '#S' 2>/dev/null || echo "")
    window_name=$(tmux display-message -t "$TMUX_PANE" -p '#W' 2>/dev/null || echo "")
    tmux_context="$session_name → $window_name"
  fi
  echo "$tmux_context"
}

# Send macOS notification via Alacritty
send_notification() {
  local title="$1"
  local message="$2"
  local sound="${3:-Ping}"

  # Escape double quotes to prevent command injection
  # Replace all " with \" to safely embed in AppleScript strings
  local safe_title="${title//\"/\\\"}"
  local safe_message="${message//\"/\\\"}"
  local safe_sound="${sound//\"/\\\"}"

  osascript -e "tell application id \"org.alacritty\" to display notification \"$safe_message\" with title \"$safe_title\" sound name \"$safe_sound\""
}

# Set tmux attention flags
set_tmux_attention() {
  if [[ -n "${TMUX:-}" && -n "${TMUX_PANE:-}" ]]; then
    # Set custom window option to flag this window needs attention
    tmux set-window-option -t "$TMUX_PANE" @claude_attention 1

    # Also set session-level flag so it shows in session chooser
    local session_name
    session_name=$(tmux display-message -p '#S')
    tmux set-option -t "$session_name" @session_needs_attention 1
  fi
}
