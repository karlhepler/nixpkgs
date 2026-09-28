# Runs a command outside tmux's process tree so it can reach devices on the
# local network (LAN/SSH), bypassing macOS's Local Network privacy block.
#
# Why this exists: since macOS 26.7, Apple tightened Local Network privacy
# enforcement for background processes that detach from the app that
# started them. tmux's server does exactly that by design (it's how session
# persistence works) -- once detached, it's reparented to launchd and macOS
# no longer credits it as "spawned from Terminal," so anything run inside a
# tmux pane (ssh, deploy scripts, etc.) gets silently blocked, even though
# the exact same command works fine outside tmux. Re-signing the affected
# binaries (Alacritty, tmux) with stable identities was tried and does not
# fix this -- it's not an identity problem. Full investigation:
# scratchpad/alacritty-local-network-permission-bug.md
#
# The fix: submit the command as a one-shot launchd job instead of running
# it directly. A job launchd starts itself has no tmux/detached-daemon
# ancestry to distrust, so it isn't subject to the block. This does not
# change tmux's own auto-start behavior at all -- interactive sessions are
# unaffected.
#
# Limitation: launchd jobs have no controlling terminal, so a command that
# needs live interactive input (e.g. a typed password) will hang. Use SSH
# key auth for anything run through lan-run.
set -uo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: lan-run <command> [args...]" >&2
  exit 2
fi

label="com.karlhepler.lanrun.$$.$(date +%s)"
outfile=$(mktemp)
statusfile=$(mktemp)
wrapper=$(mktemp)

{
  printf '#!/bin/sh\n'
  printf 'cd %q || exit 1\n' "$PWD"
  # Forward the calling shell's exported environment into the job --
  # launchd jobs do NOT inherit it otherwise (confirmed separately: this
  # is the same reason the tmux-server launchd agent needed explicit env
  # sourcing to find PATH). Without this, anything relying on an exported
  # var (e.g. a deploy script's SSHPASS for non-interactive sshpass auth)
  # would silently break only when run through lan-run, not otherwise.
  #
  # declare -x, not compgen -e: compgen is a completion-only builtin and
  # is NOT present in the minimal bash writeShellApplication uses for
  # this script's own shebang -- confirmed directly (compgen: command
  # not found on the real deployed script, despite working when tested
  # under macOS's own full system bash by mistake). declare -x is a core
  # bash builtin present in any build, and its output is already
  # properly quoted shell syntax, so it can be emitted as-is.
  while IFS= read -r line; do
    case "$line" in
      "declare -x _="* | "declare -x SHLVL="* | "declare -x PWD="* | "declare -x OLDPWD="*) continue ;;
    esac
    printf '%s\n' "$line"
  done < <(declare -x)
  printf '%q ' "$@"
  printf '\n'
  printf 'echo $? > %q\n' "$statusfile"
} > "$wrapper"
chmod +x "$wrapper"

launchctl submit -l "$label" -o "$outfile" -e "$outfile" -- "$wrapper" >/dev/null

# Poll until the job is no longer listed as running. Long ceiling (~20 min)
# since a real deploy can take a while (package downloads, remote work).
for _ in $(seq 1 1200); do
  line=$(launchctl list 2>/dev/null | awk -v l="$label" '$3==l')
  if [ -z "$line" ]; then
    break
  fi
  pidcol=$(echo "$line" | awk '{print $1}')
  if [ "$pidcol" = "-" ]; then
    break
  fi
  sleep 1
done

launchctl remove "$label" 2>/dev/null || true

cat "$outfile"
code=1
if [ -f "$statusfile" ] && [ -s "$statusfile" ]; then
  code=$(cat "$statusfile")
fi
rm -f "$outfile" "$statusfile" "$wrapper"
exit "$code"
