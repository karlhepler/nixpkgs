#!/usr/bin/env bash
set -euo pipefail

# Preflight: validate required env vars
[ -n "${CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN:-}" ] || { echo "Error: CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN is not set. Add it to overconfig.nix and run 'hms'."; exit 1; }
[ -n "${CLAUDE_REMOTE_TELEGRAM_CHAT_ID:-}" ] || { echo "Error: CLAUDE_REMOTE_TELEGRAM_CHAT_ID is not set. Add it to overconfig.nix and run 'hms'."; exit 1; }
[ -n "${KANBAN_SESSION:-}" ] || { echo "Error: KANBAN_SESSION is not set — this command must be run inside an active Claude Code session."; exit 1; }

# Determine mode from first argument (default: on)
mode="${1:-on}"

case "$mode" in
  off)
    rm -f ~/.claude/claude-remote-telegram/sessions/"$KANBAN_SESSION"
    rm -f ~/.claude/claude-remote-telegram/panes/"$KANBAN_SESSION"
    echo "Telegram disabled for session: $KANBAN_SESSION"
    echo "(Bot daemon continues running for other active sessions)"
    echo "Remaining enabled sessions:"
    ls ~/.claude/claude-remote-telegram/sessions/ 2>/dev/null || echo "(none)"
    ;;

  on)
    # Create the session flag
    mkdir -p ~/.claude/claude-remote-telegram/sessions
    mkdir -p ~/.claude/claude-remote-telegram/panes

    if [ -f ~/.claude/claude-remote-telegram/sessions/"$KANBAN_SESSION" ]; then
      echo "Telegram already enabled for session: $KANBAN_SESSION"
    else
      touch ~/.claude/claude-remote-telegram/sessions/"$KANBAN_SESSION"
      echo "Telegram enabled for session: $KANBAN_SESSION"
    fi

    # Register the tmux pane so the bot can send keystrokes on Allow/Deny
    if [ -n "${TMUX_PANE:-}" ]; then
      printf '%s' "$TMUX_PANE" > ~/.claude/claude-remote-telegram/panes/"$KANBAN_SESSION"
      echo "Registered tmux pane: $TMUX_PANE"
    else
      echo "Warning: TMUX_PANE is not set — Allow/Deny keystrokes will not work for this session"
    fi

    # Check if bot is running
    bot_running=false
    if [ -f ~/.claude/claude-remote-telegram/bot.pid ]; then
      pid=$(cat ~/.claude/claude-remote-telegram/bot.pid)
      if kill -0 "$pid" 2>/dev/null; then
        bot_running=true
      fi
    fi

    # Start bot if not running
    if [ "$bot_running" = false ]; then
      mkdir -p ~/.claude/metrics
      nohup claude-remote-telegram > ~/.claude/metrics/claude-remote-telegram.log 2>&1 &
      echo $! > ~/.claude/claude-remote-telegram/bot.pid
    fi

    # List enabled sessions
    echo "All enabled sessions:"
    ls ~/.claude/claude-remote-telegram/sessions/ 2>/dev/null || echo "(none)"
    ;;

  *)
    echo "Unknown argument: $mode. Use 'on' or 'off'."
    exit 1
    ;;
esac
