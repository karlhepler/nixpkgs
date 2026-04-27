#!/usr/bin/env bash
# Repo convention: the `# brief` line is human-readable in-source documentation
# mirroring the Nix `meta.description` for this shellapp. TOOLS.md is auto-
# generated from the Nix `description`, not this line — keep them in sync.
# brief Open a Cathy composer in nvim, targeting a tmux pane. Args: [<N> | <window> | <window>.<N>]. Default pane 0 of current window.
set -euo pipefail

pane="${1:-0}"

# SECURITY: validation must reject every char outside [a-zA-Z0-9_. -]
# — the value is interpolated unquoted into the nvim Ex-command string
# at the exec line below. Allowing any other char (semicolons, pipes,
# backslashes, quotes, parentheses, newlines, etc.) would create either
# a shell injection or an Ex-command injection vector. Spaces are safe
# in this context: the entire interpolated value sits inside a single
# double-quoted shell string passed as one argv element to `nvim -c`,
# and nvim's Ex-command parser preserves whitespace within the args of
# a user-command declared with `nargs = '?'`. Do NOT loosen this set
# without auditing the interpolation site.
#
# NOTE: bash cannot parse a literal space inside a case-glob bracket
# expression; the pattern is held in a variable so the string
# *[!a-zA-Z0-9_. -]* is a valid shell assignment while the case uses
# glob expansion of that variable.
_invalid_chars='*[!a-zA-Z0-9_. -]*'
# shellcheck disable=SC2254  # intentional glob expansion: pattern holds chars invalid in bracket expr with spaces
case "$pane" in
  $_invalid_chars)
    echo "cathy: argument may only contain alphanumeric, dot, dash, underscore, or space (got: '$pane')" >&2
    echo "usage: cathy [<pane_index> | <window_name> | <window_name>.<pane_index>]" >&2
    exit 2
    ;;
esac

# nvim requires a terminal; bail with exit 1 (not 2) if stdout is not a TTY so
# callers can distinguish validation failure (exit 2) from launch failure (exit 1).
[ -t 1 ] || { echo "cathy: requires a terminal (stdout is not a tty)" >&2; exit 1; }

exec nvim -c "Cathy ${pane}"
