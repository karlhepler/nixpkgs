#!/usr/bin/env bash
set -eou pipefail

# Select and set random emoji for tmux inactive window icon

show_help() {
  echo "random-emoji - Set random emoji for tmux window icon"
  echo
  echo "USAGE:"
  echo "  random-emoji    Set random emoji icon for current tmux window"
  echo
  echo "DESCRIPTION:"
  echo "  Selects a random emoji from a predefined list and sets it as the"
  echo "  tmux window icon for both active and inactive states."
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

EMOJIS=(
  "🎯" "🚀" "⚡" "🔥" "💡" "🎨" "🎭" "🎪"
  "🎸" "🎮" "🎲" "🎰" "🎳" "⚽" "🏀" "🏈"
  "🌟" "⭐" "✨" "💫" "🌈" "🌺" "🌸" "🌼"
  "🍕" "🍔" "🍟" "🍿" "🎂" "🍰" "🧁" "🍪"
  "☕" "🍵" "🧃" "🥤" "🍺" "🍻" "🥂" "🍷"
  "🐶" "🐱" "🐭" "🐹" "🦊" "🐻" "🐼" "🦁"
  "🦄" "🐉" "🦋" "🐝" "🐛" "🦗" "🐢" "🐠"
  "💎" "🔮" "🎁" "🎀" "🎈" "🎉" "🎊" "🏆"
)

# Select random emoji from array
RANDOM_EMOJI="${EMOJIS[$RANDOM % ${#EMOJIS[@]}]}"

# Set tmux window option for current window
tmux set-window-option @theme_plugin_inactive_window_icon "$RANDOM_EMOJI"
tmux set-window-option @theme_plugin_active_window_icon "$RANDOM_EMOJI"
