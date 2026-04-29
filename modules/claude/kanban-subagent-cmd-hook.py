#!/usr/bin/env python3
"""
kanban-subagent-cmd-hook: PreToolUse(Bash) hook that restricts kanban CLI usage
inside sub-agents to only `kanban criteria check` and `kanban criteria uncheck`.

All other kanban subcommands (do, start, done, cancel, defer, criteria add/remove,
list, show, etc.) are denied when called from a sub-agent context. Coordinators
(main session, no agent_id) are unaffected.

Output format (PreToolUse hook — block-only format):
  {"decision": "block", "reason": "..."}  — deny
  (exit 0 with no output)                 — allow (fail open)

Fails open: any error (JSON parse failure, empty stdin, shlex error) results in
allowing. Never accidentally block innocent commands.

Sub-agent detection: `payload.get("agent_id")` is the discriminator. Present →
sub-agent. Absent → main session (coordinator). This mirrors the production
implementation in kanban-pretool-hook.py:361-374.

RELIABILITY NOTE (verified against Claude Code 2.1.118, 2026-04-23):
'agent_id' is a single-point-of-failure. If the field is absent from a sub-agent
payload (version regression, format change) the safeguard silently bypasses.
Revisit on major Claude Code version bumps.

ALLOWED sub-agent kanban commands:
  kanban criteria check <card> <n> [--session <session>]
  kanban criteria uncheck <card> <n> [--session <session>]
  kanban --help / kanban help  (read-only, harmless)

DENIED (all others):
  kanban do, kanban start, kanban done, kanban cancel, kanban defer
  kanban criteria add, kanban criteria remove
  kanban list, kanban show, kanban session-hook, etc.

BYPASS MITIGATIONS:
  1. env/command/exec wrappers: `env kanban done 5`, `command kanban done 5`,
     `exec kanban done 5`, `/usr/bin/env kanban done 5` — detected by advancing
     past wrapper tokens in _find_kanban_segment().
  2. shell -c wrappers: `bash -c 'kanban done 5'`, `sh -c '...'`, `python3 -c
     '...'`, etc. — denied entirely for sub-agents via _deny_shell_wrapper().
"""

import json
import shlex
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Shell operator tokens — used to split compound commands.
_SHELL_OPS = frozenset(["&&", "||", ";", "|", "&"])

# Wrapper executables that transparently invoke another binary.
# When segment[0] is one of these, we advance past it to find the real binary.
_ENV_WRAPPERS = frozenset(["env", "/usr/bin/env"])
_COMMAND_WRAPPERS = frozenset(["command"])
_EXEC_WRAPPERS = frozenset(["exec"])
_ALL_WRAPPERS = _ENV_WRAPPERS | _COMMAND_WRAPPERS | _EXEC_WRAPPERS

# Shell runner binaries that accept -c <inline-script> arguments.
# Sub-agents invoking these with -c are equivalent to having unrestricted shell
# access for the purpose of kanban guard bypasses, so we deny them outright.
_SHELL_RUNNERS = frozenset(["bash", "sh", "zsh", "dash", "ksh", "fish"])
_SCRIPT_RUNNERS = frozenset(["python", "python3", "perl", "ruby"])
_ALL_INLINE_RUNNERS = _SHELL_RUNNERS | _SCRIPT_RUNNERS

# The -c / -e flag that introduces an inline script for each runner family.
_SHELL_INLINE_FLAGS = frozenset(["-c"])
_SCRIPT_INLINE_FLAGS = frozenset(["-e", "-c"])


# ---------------------------------------------------------------------------
# Sub-agent detection
# ---------------------------------------------------------------------------

def _is_sub_agent(payload: dict) -> bool:
    """Return True if this hook call comes from inside a sub-agent.

    Claude Code populates 'agent_id' in the hook payload only when the hook
    fires inside a subagent call. The field is absent in main-session calls.

    RELIABILITY NOTE (verified against Claude Code 2.1.118, 2026-04-23):
    This is a single-point-of-failure. If 'agent_id' is ever absent from a
    sub-agent payload (version regression, format change) or present in a
    main-session payload (future session IDs), the safeguard silently bypasses.
    Recommend revisiting on major Claude Code version bumps to verify the
    'agent_id' field remains a reliable sub-agent discriminator.
    """
    return bool(payload.get("agent_id"))


# ---------------------------------------------------------------------------
# Command tokenization
# ---------------------------------------------------------------------------

def _normalize_semicolons(tokens: list) -> list:
    """Expand tokens that embed bare semicolons into separate operator tokens.

    shlex.split does not treat ';' as an operator — it merges it with adjacent
    content when there is no surrounding whitespace (e.g., 'cmd;next'). This
    function splits those embedded semicolons so _split_on_shell_ops can
    correctly identify command segment boundaries.
    """
    result = []
    for tok in tokens:
        if ';' not in tok:
            result.append(tok)
            continue
        parts = tok.split(';')
        for i, part in enumerate(parts):
            if part:
                result.append(part)
            if i < len(parts) - 1:
                result.append(';')
    return result


def _split_on_shell_ops(tokens: list) -> list:
    """Split token list on shell control operators into command segments."""
    segments = []
    current = []
    for tok in tokens:
        if tok in _SHELL_OPS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _tokenize_command(command: str) -> list:
    """Tokenize a shell command string using shlex, splitting on operators.

    Returns a list of segments where each segment is a list of tokens.
    Fails open (returns empty list) on shlex errors.
    """
    if not command or not command.strip():
        return []
    segments_out = []
    for line in command.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            # Unterminated quotes or other shlex error — fail open
            continue
        tokens = _normalize_semicolons(tokens)
        segments_out.extend(_split_on_shell_ops(tokens))
    return segments_out


# ---------------------------------------------------------------------------
# Kanban command classification
# ---------------------------------------------------------------------------

def _is_kanban_binary(token: str) -> bool:
    """Return True if token is the kanban CLI binary name.

    Matches:
      - 'kanban'              (bare name, not followed by hyphen/word chars)
      - '.kanban-wrapped'     (the wrapped variant used by the CLI infra)
      - '/path/to/bin/kanban' (absolute path to kanban binary)

    Does NOT match:
      - 'kanban-foo'          (hyphen-prefixed binary — different tool)
      - 'cat' or 'echo'      (unrelated tools)
      - '.kanban/foo.json'   (path containing .kanban directory)
    """
    if not token:
        return False
    # Exact name (coordinator uses this)
    if token == "kanban":
        return True
    # Wrapped variant used by CLI infrastructure
    if token == ".kanban-wrapped":
        return True
    # Absolute path ending in /bin/kanban
    if token.endswith("/bin/kanban") and "/" in token:
        return True
    return False


def _is_shell_wrapper_invocation(segment: list) -> bool:
    """Return True if this segment is a shell/script runner with an inline -c/-e flag.

    Detects patterns like:
      bash -c 'kanban done 5'
      sh -c 'kanban cancel 5'
      zsh -c '...'
      python3 -c 'subprocess.run(["kanban", "done", "5"])'
      perl -e '...'
      ruby -e '...'

    These are blocked entirely for sub-agents because static analysis cannot
    inspect the inline script content, making them equivalent to unrestricted
    shell access from the guard's perspective. Sub-agents have direct Bash tool
    access and never need to wrap commands in shell-runner -c layers.

    Does NOT block:
      bash some-script.sh          (script-file invocation, not -c)
      bash                         (interactive shell, no -c)
    """
    if not segment:
        return False
    binary = segment[0].split("/")[-1]  # strip path prefix, e.g. /bin/bash → bash
    if binary not in _ALL_INLINE_RUNNERS:
        return False
    # Determine which inline flags apply to this runner family
    if binary in _SHELL_RUNNERS:
        inline_flags = _SHELL_INLINE_FLAGS
    else:
        inline_flags = _SCRIPT_INLINE_FLAGS
    # Scan remaining tokens for the inline flag
    for tok in segment[1:]:
        if tok in inline_flags:
            return True
        # Stop scanning at the first non-flag token (i.e., the script argument)
        if not tok.startswith("-"):
            break
    return False


def _advance_past_env_wrapper(segment: list, start: int) -> int:
    """Advance index past `env` wrapper tokens to find the real binary.

    Handles:
      env kanban done 5              → advances 1 (past 'env')
      env KEY=VAL kanban done 5      → advances past 'env' and all KEY=VAL pairs
      env -i kanban done 5           → advances past 'env' and '-i'
      env -u VAR kanban done 5       → advances past 'env', '-u', 'VAR'
      env -- kanban done 5           → advances past 'env' and '--'
    """
    i = start + 1  # skip 'env' / '/usr/bin/env' itself
    while i < len(segment):
        tok = segment[i]
        if tok == "--":
            i += 1
            break
        if tok == "-i":
            i += 1
            continue
        if tok == "-u" and i + 1 < len(segment):
            i += 2  # skip '-u' and the variable name
            continue
        if tok.startswith("-"):
            i += 1  # other env flags (e.g., -0, --null) — skip
            continue
        if "=" in tok and not tok.startswith("-"):
            i += 1  # KEY=VALUE assignment — skip
            continue
        break  # first non-flag, non-assignment token is the real binary
    return i


def _advance_past_command_wrapper(segment: list, start: int) -> int:
    """Advance index past `command` builtin flags to find the real binary.

    Handles:
      command kanban done 5          → advances 1 (past 'command')
      command -p kanban done 5       → advances past 'command' and '-p'
      command -v kanban done 5       → advances past 'command' and '-v'
      command -V kanban done 5       → advances past 'command' and '-V'
    """
    i = start + 1  # skip 'command' itself
    while i < len(segment):
        tok = segment[i]
        if tok in ("-p", "-v", "-V"):
            i += 1
            continue
        break
    return i


def _advance_past_exec_wrapper(segment: list, start: int) -> int:
    """Advance index past `exec` builtin flags to find the real binary.

    Handles:
      exec kanban done 5             → advances 1 (past 'exec')
      exec -c kanban done 5          → advances past 'exec' and '-c'
      exec -l kanban done 5          → advances past 'exec' and '-l'
      exec -a NAME kanban done 5     → advances past 'exec', '-a', 'NAME'
    """
    i = start + 1  # skip 'exec' itself
    while i < len(segment):
        tok = segment[i]
        if tok == "-a" and i + 1 < len(segment):
            i += 2  # skip '-a' and the name argument
            continue
        if tok in ("-c", "-l"):
            i += 1
            continue
        break
    return i


def _skip_flags_with_args(tokens: list, start: int) -> int:
    """Advance index past any leading flags that take an argument value.

    Returns the index of the first non-flag token after `start`,
    or len(tokens) if we exhaust the list.
    """
    # kanban global flags that take a value argument
    flags_with_args = {"--session", "--output-style", "--output", "--format"}
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok in flags_with_args:
            i += 2  # skip flag + value
            continue
        if tok.startswith("--") and "=" in tok:
            i += 1  # --flag=value, no separate arg token
            continue
        break
    return i


def _is_allowed_kanban_subcommand(tokens_after_kanban: list) -> bool:
    """Return True if the kanban subcommand is in the allow-list for sub-agents.

    Allowed:
      kanban criteria check <card> <n> [options]
      kanban criteria uncheck <card> <n> [options]
      kanban --help
      kanban help

    Denied: everything else.

    tokens_after_kanban: the tokens following the 'kanban' binary token,
    with global flags already stripped.
    """
    if not tokens_after_kanban:
        # `kanban` with no args — deny (not a useful read-only command)
        return False

    first = tokens_after_kanban[0]

    # Allow help (read-only, harmless)
    if first in ("--help", "-h", "help"):
        return True

    # Allow only `criteria check` and `criteria uncheck`
    if first == "criteria":
        if len(tokens_after_kanban) >= 2:
            second = tokens_after_kanban[1]
            if second in ("check", "uncheck"):
                return True
        # `criteria` with no subcommand or other subcommand (add, remove, etc.) → deny
        return False

    return False


def _find_kanban_segment(segments: list) -> "list | None":
    """Return the kanban portion of the first segment that invokes the kanban binary.

    Returns the sub-slice of the segment starting at the kanban binary token,
    or None if no kanban invocation found. The returned slice always has the
    kanban binary as its first element, enabling callers to strip it uniformly.

    We look for kanban as the BINARY name (first non-flag token of a segment),
    not as a substring anywhere (e.g., `cat .kanban/foo.json` is not a kanban
    CLI invocation).

    Wrapper handling — env/command/exec prefix the real binary. When segment[0]
    is one of these known wrappers, we advance past wrapper-specific flags and
    assignments to check whether the underlying binary is kanban. The returned
    slice starts at the kanban binary, not at the wrapper:

      env kanban done 5              → ['kanban', 'done', '5']
      env KEY=VAL kanban done 5      → ['kanban', 'done', '5']
      /usr/bin/env kanban done 5     → ['kanban', 'done', '5']
      command kanban done 5          → ['kanban', 'done', '5']
      exec kanban done 5             → ['kanban', 'done', '5']
      kanban done 5                  → ['kanban', 'done', '5']
    """
    for segment in segments:
        if not segment:
            continue
        first_token = segment[0]
        if _is_kanban_binary(first_token):
            return segment  # starts at kanban binary already
        # Check for wrapper prefix: advance past wrapper tokens to find real binary
        if first_token in _ENV_WRAPPERS:
            real_idx = _advance_past_env_wrapper(segment, 0)
            if real_idx < len(segment) and _is_kanban_binary(segment[real_idx]):
                return segment[real_idx:]
        elif first_token in _COMMAND_WRAPPERS:
            real_idx = _advance_past_command_wrapper(segment, 0)
            if real_idx < len(segment) and _is_kanban_binary(segment[real_idx]):
                return segment[real_idx:]
        elif first_token in _EXEC_WRAPPERS:
            real_idx = _advance_past_exec_wrapper(segment, 0)
            if real_idx < len(segment) and _is_kanban_binary(segment[real_idx]):
                return segment[real_idx:]
    return None


# ---------------------------------------------------------------------------
# Denial output
# ---------------------------------------------------------------------------

def _deny(command: str) -> None:
    """Print a block decision to stdout and exit."""
    # Sanitize for embedding in message (strip non-printable characters)
    safe_cmd = "".join(
        c for c in command if c.isprintable() or c in ("\t", "\n")
    )
    reason = (
        "Sub-agents may only call 'kanban criteria check' and "
        "'kanban criteria uncheck'. "
        f"Attempted: {safe_cmd!r}. "
        "The coordinator handles all other lifecycle commands "
        "(do/start/done/cancel/defer/criteria add/remove)."
    )
    print(json.dumps({"decision": "block", "reason": reason}, separators=(",", ":")))


def _deny_shell_wrapper(command: str) -> None:
    """Print a block decision for shell-wrapper (-c/-e) invocations.

    Sub-agents may not use shell-wrapper invocations (bash -c, sh -c,
    python3 -c, etc.) because these are equivalent to unrestricted shell
    access for the purposes of the kanban guard. Static analysis cannot
    inspect inline script content. Sub-agents have direct Bash tool access
    and do not need shell-runner wrapper layers.
    """
    safe_cmd = "".join(
        c for c in command if c.isprintable() or c in ("\t", "\n")
    )
    reason = (
        "Sub-agents may not use shell-wrapper invocations "
        "(bash -c, sh -c, zsh -c, python -c, python3 -c, perl -e, ruby -e, etc.). "
        "Use direct command invocation instead. "
        f"Attempted: {safe_cmd!r}."
    )
    print(json.dumps({"decision": "block", "reason": reason}, separators=(",", ":")))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()

    # Fail-open: empty or whitespace-only stdin
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Fail-open: invalid JSON
        sys.exit(0)

    # Only inspect Bash tool calls
    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    # Only restrict sub-agents — coordinators are unrestricted
    if not _is_sub_agent(payload):
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "")

    # Fail-open: empty command
    if not command:
        sys.exit(0)

    # Tokenize the command into segments split by shell operators
    segments = _tokenize_command(command)

    # If tokenization failed entirely (e.g., shlex errors), fail-open
    if not segments:
        sys.exit(0)

    # Check for shell/script runner -c invocations before kanban detection.
    # These bypass static kanban analysis entirely by embedding the kanban call
    # inside a string argument that shlex treats as a single opaque token.
    # Deny them outright — sub-agents have direct Bash tool access.
    for segment in segments:
        if _is_shell_wrapper_invocation(segment):
            _deny_shell_wrapper(command)
            sys.exit(0)

    # Find the first segment that invokes the kanban binary
    kanban_segment = _find_kanban_segment(segments)

    # No kanban invocation found — allow (e.g., ls, git status)
    if kanban_segment is None:
        sys.exit(0)

    # Strip the leading kanban binary token and any global flags-with-args
    # to find the subcommand
    tokens_after_binary = kanban_segment[1:]
    start = _skip_flags_with_args(tokens_after_binary, 0)
    subcommand_tokens = tokens_after_binary[start:]

    if _is_allowed_kanban_subcommand(subcommand_tokens):
        sys.exit(0)

    # Denied — emit block decision
    _deny(command)
    sys.exit(0)


if __name__ == "__main__":
    main()
