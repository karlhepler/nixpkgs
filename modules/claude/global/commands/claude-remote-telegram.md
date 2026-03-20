---
name: claude-remote-telegram
description: Enable or disable Telegram gate for remote Claude Code interaction from your phone; remote access, phone access, mobile, turn on telegram
---

# Telegram Gate

The Telegram gate lets you interact with a running Claude Code session from your phone via Telegram. When enabled for a session, the Telegram bot forwards your messages to that session and returns responses — so you can check in, give instructions, or stop work without being at your computer.

## Your Task

$ARGUMENTS

Execute the bash block below using the argument above ('on' enables, 'off' disables, no arg defaults to 'on'). Report any errors with exact output to the user.

## How It Works

- Each Claude session registers itself by creating a flag file under `~/.claude/claude-remote-telegram/sessions/`
- A shared `claude-remote-telegram` process watches for incoming Telegram messages and routes them to active sessions
- Send `/stop <session>` or `/stopall` from Telegram to interrupt work

## Setup (One-Time)

Add these to your `overconfig.nix` before using this command:

```nix
home.sessionVariables = {
  CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN = "your-bot-token-from-botfather";
  CLAUDE_REMOTE_TELEGRAM_CHAT_ID   = "your-numeric-chat-id";
};
```

Run `hms` after saving. Get your bot token from [@BotFather](https://t.me/botfather) and your chat ID from [@userinfobot](https://t.me/userinfobot).

Note: `overconfig.nix` is intentionally git-invisible (managed by hms) — no `git add` needed.

The `telegram-gate-hook` PreToolUse hook is also required for routing messages to the correct session. It is auto-configured via `hms` — no manual setup needed.

## Telegram Bot Commands

| Command | Effect |
|---------|--------|
| `/stop <session>` | Interrupt the named session |
| `/stopall` | Interrupt all active sessions |

---

## Usage

```
/claude-remote-telegram        # Enable for current session (same as /claude-remote-telegram on)
/claude-remote-telegram on     # Enable for current session
/claude-remote-telegram off    # Disable for current session
```

---

```bash
set -euo pipefail

# Preflight: validate required env vars
for var in CLAUDE_REMOTE_TELEGRAM_BOT_TOKEN CLAUDE_REMOTE_TELEGRAM_CHAT_ID; do
  set +u
  val="${!var}"
  set -u
  [ -n "$val" ] || { echo "Error: $var is not set. Add it to overconfig.nix and run 'hms'."; exit 1; }
done

if [ -z "${KANBAN_SESSION:-}" ]; then
  echo "Error: KANBAN_SESSION is not set — this skill must be run inside an active Claude Code session."
  exit 1
fi

# Determine mode from arguments (default: on)
mode="${ARGUMENTS:-on}"

case "$mode" in
  off)
    rm -f ~/.claude/claude-remote-telegram/sessions/"$KANBAN_SESSION"
    echo "Telegram disabled for session: $KANBAN_SESSION"
    echo "(Bot daemon continues running for other active sessions)"
    echo "Remaining enabled sessions:"
    ls ~/.claude/claude-remote-telegram/sessions/ 2>/dev/null || echo "(none)"
    ;;

  on)
    # Create the session flag
    mkdir -p ~/.claude/claude-remote-telegram/sessions

    if [ -f ~/.claude/claude-remote-telegram/sessions/"$KANBAN_SESSION" ]; then
      echo "Telegram already enabled for session: $KANBAN_SESSION"
    else
      touch ~/.claude/claude-remote-telegram/sessions/"$KANBAN_SESSION"
      echo "Telegram enabled for session: $KANBAN_SESSION"
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
      command -v claude-remote-telegram >/dev/null || { echo "Error: claude-remote-telegram not found. Run 'hms' first."; exit 1; }
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
```
