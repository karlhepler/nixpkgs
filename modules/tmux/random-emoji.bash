#!/usr/bin/env bash
# Select and set random emoji for tmux inactive window icon

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
