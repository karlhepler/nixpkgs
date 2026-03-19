---
name: telegram
description: Enable or disable Telegram gate for remote Claude Code interaction from your phone
---

# Telegram Gate

The Telegram gate lets you interact with a running Claude Code session from your phone via Telegram. When enabled for a session, the Telegram bot forwards your messages to that session and returns responses — so you can check in, give instructions, or stop work without being at your computer.

## How It Works

- Each Claude session registers itself by creating a flag file under `~/.claude/telegram/sessions/`
- A shared `telegram-bot` process watches for incoming Telegram messages and routes them to active sessions
- Send `/stop <session>` or `/stopall` from Telegram to interrupt work

## Setup (One-Time)

Add these to your `overconfig.nix` before using this command:

```nix
home.sessionVariables = {
  TELEGRAM_BOT_TOKEN = "your-bot-token-from-botfather";
  TELEGRAM_CHAT_ID   = "your-numeric-chat-id";
};
```

Run `hms` after saving. Get your bot token from [@BotFather](https://t.me/botfather) and your chat ID from [@userinfobot](https://t.me/userinfobot).

## Telegram Bot Commands

| Command | Effect |
|---------|--------|
| `/stop <session>` | Interrupt the named session |
| `/stopall` | Interrupt all active sessions |

---

## Usage

```
/telegram        # Enable for current session (same as /telegram on)
/telegram on     # Enable for current session
/telegram off    # Disable for current session
```

---

## Your Task

$ARGUMENTS

Execute the bash block below using the argument above ('on' enables, 'off' disables, no arg defaults to 'on'). Report any errors with exact output to the user.

```bash
set -euo pipefail

# Preflight: validate required env vars
for var in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID KANBAN_SESSION; do
  set +u
  val="${!var}"
  set -u
  [ -n "$val" ] || { echo "Error: $var is not set. Add it to overconfig.nix and run 'hms'."; exit 1; }
done

# Determine mode from arguments (default: on)
mode="${ARGUMENTS:-on}"

case "$mode" in
  off)
    rm -f ~/.claude/telegram/sessions/"$KANBAN_SESSION"
    echo "Telegram disabled for session: $KANBAN_SESSION"
    echo "(Bot daemon continues running for other active sessions)"
    echo "Remaining enabled sessions:"
    ls ~/.claude/telegram/sessions/ 2>/dev/null || echo "(none)"
    ;;

  on|*)
    # Create the session flag
    mkdir -p ~/.claude/telegram/sessions

    if [ -f ~/.claude/telegram/sessions/"$KANBAN_SESSION" ]; then
      echo "Telegram already enabled for session: $KANBAN_SESSION"
    else
      touch ~/.claude/telegram/sessions/"$KANBAN_SESSION"
      echo "Telegram enabled for session: $KANBAN_SESSION"
    fi

    # Check if bot is running
    bot_running=false
    if [ -f ~/.claude/telegram/bot.pid ]; then
      pid=$(cat ~/.claude/telegram/bot.pid)
      if kill -0 "$pid" 2>/dev/null; then
        bot_running=true
      fi
    fi

    # Start bot if not running
    if [ "$bot_running" = false ]; then
      command -v telegram-bot >/dev/null || { echo "Error: telegram-bot not found. Run 'hms' first."; exit 1; }
      mkdir -p ~/.claude/metrics
      nohup telegram-bot > ~/.claude/metrics/telegram-bot.log 2>&1 &
      echo $! > ~/.claude/telegram/bot.pid
      for i in 1 2 3; do
        sleep 0.5
        [ -f ~/.claude/telegram/bot.pid ] && break
      done
    fi

    # List enabled sessions
    echo "All enabled sessions:"
    ls ~/.claude/telegram/sessions/ 2>/dev/null || echo "(none)"
    ;;
esac
```
