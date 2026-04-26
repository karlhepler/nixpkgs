#!/usr/bin/env python3
"""
crew-lifecycle-hook: Multi-event hook that manages:

  1. SessionStart — drops a readiness sentinel file so 'crew create --tell'
     can wait deterministically for Claude Code to finish booting instead of
     using a fixed wall-clock timeout.

     Sentinel path: ${TMPDIR:-/tmp}/crew/ready-<session-name>
     The session name is derived from 'tmux display-message -p #W' (the tmux
     window name), which matches the --name argument passed to the staff
     command by 'crew create'.

  2. PostToolUse(Bash) — manages pulse cron lifecycle based on 'crew create'
     and 'crew dismiss' commands (unchanged from prior implementation).

Note: This hook uses direct print-to-stdout rather than the Send class pattern
used by senior-staff-cron-hook.py. The simpler direct-print approach is
appropriate here: the output channel is fixed (additionalContext JSON envelope)
and there is no testability benefit from the extra abstraction.

PostToolUse(Bash) behaviour:
- After 'crew create <name>': injects a CronCreate directive (idempotent —
  model checks CronList first and only creates if no pulse cron with the
  <<pulse-cron-v1>> sentinel exists).
- After 'crew dismiss <name>': injects a conditional CronDelete directive —
  model checks crew list for remaining Staff windows (excluding sstaff's own
  window, detected dynamically) and deletes the pulse cron only when zero
  Staff sessions with active work remain.

This replaces the SessionStart-based unconditional CronCreate approach so
that no tokens are spent when no Staff sessions are active.

Output format (PostToolUse hook):
    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}
    (exit 0 with no stdout) — silent for all other commands

Output format (SessionStart hook):
    No stdout. SessionStart writes a sentinel file as side effect; all status
    messages go to stderr. The {"result": ...} envelope is for shell-script
    hook patterns and does not apply here.

Fails open: any error results in silent exit 0.
"""

import argparse
import json
import os
import re
import subprocess
import sys


# Pulse cron schedule and label (must match what CronCreate uses so CronList
# can identify it for idempotency checks and CronDelete targeting).
_PULSE_CRON_SCHEDULE = "*/10 * * * *"
_PULSE_CRON_LABEL = "pulse-cron"

# Sentinel embedded as the FIRST LINE of the pulse cron prompt.
# Versioned (v1) so future prompt revisions can force-replace old crons by
# bumping the version. The install existence check matches this exact string
# via CronList grep — unambiguous, zero false positives.
_PULSE_CRON_SENTINEL = "<<pulse-cron-v1>>"

# Hook-level sentinel that prefixes all lifecycle directives (unchanged).
_SENTINEL = "<<pulse-cron-lifecycle>>"

# Active-work indicators (shared definition used in both pulse STEP 2 and
# dismiss activity check — single source of truth keeps them in sync).
_ACTIVITY_INDICATORS = (
    "local agents still running|Working for|Churned for|Baked for|"
    "✻ \\w+|[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]"
)

# Match 'crew create <name>' at the start of the command (.strip() removes leading whitespace before match).
_CREW_CREATE_RE = re.compile(r"crew\s+create\s+\S")

# Match 'crew dismiss <name>' at the start of the command (.strip() removes leading whitespace before match).
_CREW_DISMISS_RE = re.compile(r"crew\s+dismiss\s+\S")

# Directory and path for session readiness sentinels.
# crew create --tell waits on the sentinel; SessionStart drops it.
_SENTINEL_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "crew")
_SENTINEL_PREFIX = "ready-"

# Valid session name pattern (must match crew.py's _SAFE_NAME_RE).
# Validated before writing the sentinel to prevent path traversal.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sentinel_path(session_name: str) -> str:
    """Return the readiness sentinel path for the given session name."""
    return os.path.join(_SENTINEL_DIR, f"{_SENTINEL_PREFIX}{session_name}")


def _get_tmux_window_name() -> str | None:
    """Return the tmux window name (#W) for the current pane, or None on failure.

    Used by the SessionStart handler to derive the session name, which matches
    the --name argument passed to the staff command by 'crew create'.
    """
    tmux_env = os.environ.get("TMUX")
    if not tmux_env:
        return None
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#W"],
        capture_output=True,
        text=True,
        timeout=3,
    )
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name if name else None


def _additional_context(msg: str) -> str:
    """Wrap msg in the PostToolUse additionalContext response envelope."""
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    })


def _is_senior_staff() -> bool:
    """Return True if the current session is a Senior Staff session."""
    return os.environ.get("KANBAN_AGENT") == "senior-staff-engineer"


def _detect_own_window_index() -> str | None:
    """Detect sstaff's own tmux window index at hook-generation time.

    Uses `tmux display-message -p '#I'` which runs in sstaff's tmux client
    context (the hook executes inside the sstaff session), returning the
    current window index directly. This is more reliable than TMUX_PANE
    because it works even if TMUX_PANE is not set in the hook environment.

    Fallback: if tmux is unavailable or the call fails (e.g., hook running
    outside a tmux session during testing), returns None. The caller MUST
    treat None as a detection failure and emit a directive that does NOT
    CronDelete — safer to keep cron running than delete it wrongly.
    """
    tmux_env = os.environ.get("TMUX")
    if not tmux_env:
        # Not inside a tmux session — cannot detect window index.
        return None
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#I"],
        capture_output=True,
        text=True,
        timeout=3,
    )
    if result.returncode != 0:
        return None
    window_index = result.stdout.strip()
    if not window_index:
        return None
    if not re.fullmatch(r'\d+', window_index):
        print(
            f'[crew-lifecycle-hook] unexpected non-digit window index: {window_index!r}; returning None',
            file=sys.stderr,
        )
        return None
    return window_index


# The returned pulse prompt has three steps executed on one `crew status`
# call:
#   STEP 1: run the single call.
#   STEP 2: self-termination check — CronDelete if all other windows are idle.
#   STEP 3: actionability scan — surface stalls/completions/errors otherwise.
# STEP 2 and STEP 3 are mutually exclusive; STEP 3 only runs when STEP 2
# does not self-terminate.
def _build_pulse_cron_command(own_window_index: str) -> str:
    """Build the pulse cron command prompt with the dynamic window index injected.

    CronDelete-vs-CronCreate race note: if STEP 2 calls CronDelete just as a
    new 'crew create' fires, the crew-lifecycle-hook will emit a CronCreate
    directive immediately after. The CronCreate path uses an idempotent sentinel
    check (CronList + grep for <<pulse-cron-v1>> before creating), so the worst
    case is a brief cron gap — acceptable.
    """
    return (
        f"{_PULSE_CRON_SENTINEL}\n"
        f"STEP 1: Run `crew status --lines 10` once to get recent output from all active Claude panes. "
        f"If this command errors, skip this pulse cycle silently. "
        f"STEP 2 (self-termination check): Scan the `crew status` output. IGNORE any pane whose window index is `{own_window_index}` — "
        f"that is sstaff's own window running this pulse; only count activity from OTHER windows. "
        f"Active-work indicators: 'local agents still running', 'Working for', 'Churned for', 'Baked for', '✻ ' followed by a verb, or braille spinner characters (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏). "
        f"If NO OTHER window shows active-work indicators, all Staff panes are idle — "
        f"call CronList to find the cron whose prompt starts with '{_PULSE_CRON_SENTINEL}', "
        f"then call CronDelete with that cron's ID, then exit silently. "
        f"STEP 3 (actionability scan): If STEP 2 did NOT self-terminate (at least one other window has active-work indicators), "
        f"scan the same `crew status` output for actionable items (stalled panes, completed work, errors, permission prompts) "
        f"and surface them. Stay silent if nothing actionable."
    )


def _on_session_start() -> None:
    """Drop a readiness sentinel file for the current session.

    Called when the hook fires as a SessionStart event. The sentinel's
    existence signals to 'crew create --tell' (waiting in the spawning
    process) that Claude Code has fully initialised and is ready for input.

    Session name is derived from the tmux window name (#W), which matches
    the --name argument passed to the staff command by 'crew create'.

    Fails silently: if the session name cannot be determined, cannot be
    validated, or if the sentinel directory or file cannot be created, the
    function logs to stderr and returns without error. The outer ceiling in
    _wait_for_sentinel handles the case where the sentinel never appears.
    """
    session_name = _get_tmux_window_name()
    if not session_name:
        print(
            "[crew-lifecycle-hook] SessionStart: could not determine tmux window name; "
            "skipping sentinel write",
            file=sys.stderr,
        )
        return

    # Validate session name before computing the path — prevents path traversal
    # via a malicious or unexpected tmux window name containing '..', '/', etc.
    if not _SAFE_NAME_RE.match(session_name):
        print(
            f"[crew-lifecycle-hook] SessionStart: session name {session_name!r} "
            "contains unsafe characters; skipping sentinel write",
            file=sys.stderr,
        )
        return

    sentinel = _sentinel_path(session_name)
    try:
        # mode=0o700: sentinel directory accessible by owner only.
        os.makedirs(_SENTINEL_DIR, mode=0o700, exist_ok=True)
        # O_CREAT | O_WRONLY | O_NOFOLLOW: creates file if absent, overwrites if
        # present, and refuses to follow a symlink at the target path (prevents
        # symlink-redirect attacks). Mode 0o600: readable/writable by owner only.
        fd = os.open(sentinel, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    except OSError as exc:
        import errno
        if exc.errno == errno.ELOOP:
            print(
                f"[crew-lifecycle-hook] SessionStart: sentinel path '{sentinel}' is a symlink; "
                "skipping sentinel write (O_NOFOLLOW protection)",
                file=sys.stderr,
            )
        else:
            print(
                f"[crew-lifecycle-hook] SessionStart: failed to write sentinel '{sentinel}': {exc}",
                file=sys.stderr,
            )
        return

    print(
        f"[crew-lifecycle-hook] SessionStart: sentinel written: {sentinel}",
        file=sys.stderr,
    )


def _on_crew_create() -> None:
    """Emit CronCreate directive (idempotent: model checks CronList first)."""
    own_window_index = _detect_own_window_index()

    if own_window_index is None:
        # Detection failed — emit a safe no-op directive rather than a
        # potentially wrong CronCreate. Fail open: keep any existing cron
        # running rather than risk installing one with incorrect window info.
        print(
            "[crew-lifecycle-hook] own window detection failed; emitting fallback directive",
            file=sys.stderr,
        )
        msg = (
            f"{_SENTINEL} A new Staff session was just created, but sstaff's tmux window "
            f"index could not be detected at hook time. Skip CronCreate for this cycle — "
            f"the cron will be installed on the next 'crew create' once detection succeeds."
        )
        print(_additional_context(msg))
        return

    pulse_cron_command = _build_pulse_cron_command(own_window_index)
    msg = (
        f"{_SENTINEL} A new Staff session was just created. "
        f"Call CronList now. Inspect each cron's prompt text for the sentinel string '{_PULSE_CRON_SENTINEL}'. "
        f"If any cron prompt already contains '{_PULSE_CRON_SENTINEL}', skip CronCreate — pulse cron is already installed. "
        f"Otherwise call CronCreate with schedule '{_PULSE_CRON_SCHEDULE}' and label '{_PULSE_CRON_LABEL}' and this command:\n\n"
        f"```\n{pulse_cron_command}\n```"
    )
    print(_additional_context(msg))


def _on_crew_dismiss() -> None:
    """Emit CronDelete directive (conditional: only if no Staff windows with active work remain).

    Uses Option B: the dismiss directive checks both presence AND activity.
    Activity uses the same indicators as the pulse STEP 2 (_ACTIVITY_INDICATORS),
    keeping the activity gate defined in one place. This avoids an idle Staff
    window at a shell prompt keeping the cron alive indefinitely.
    """
    own_window_index = _detect_own_window_index()

    if own_window_index is None:
        # Detection failed — fail open: do NOT CronDelete. Safer to leave the
        # cron running than risk deleting it when other Staff sessions may still
        # be active. The cron will be re-evaluated on the next pulse cycle.
        print(
            "[crew-lifecycle-hook] own window detection failed; emitting fallback directive",
            file=sys.stderr,
        )
        msg = (
            f"{_SENTINEL} A Staff session was just dismissed, but sstaff's tmux window "
            f"index could not be detected at hook time. Leave the cron running — "
            f"it will self-terminate on next pulse if no activity is detected."
        )
        print(_additional_context(msg))
        return

    crew_find_cmd = "crew find '" + _ACTIVITY_INDICATORS + "' --lines 30"
    msg = (
        f"{_SENTINEL} A Staff session was just dismissed. "
        f"If any `crew` command errors, leave the cron running. "
        f"Otherwise, call `crew list --format xml` now. "
        f"Count windows whose index is NOT {own_window_index} (those are Staff session windows, not sstaff's own window). "
        f"If zero such windows remain, call CronList to find the cron whose prompt starts with '{_PULSE_CRON_SENTINEL}', "
        f"then call CronDelete with that cron's ID. "
        f"If one or more Staff windows remain, run `{crew_find_cmd}` "
        f"against those windows. "
        f"Active-work indicators: 'local agents still running', 'Working for', 'Churned for', 'Baked for', '✻ ' followed by a verb, or braille spinner characters (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏). "
        f"If `crew find` returns no matches across all remaining Staff windows, all sessions are idle — "
        f"call CronList to find the cron whose prompt starts with '{_PULSE_CRON_SENTINEL}', "
        f"then call CronDelete with that cron's ID. "
        f"If `crew find` matched at least one active-work indicator, leave the cron running."
    )
    print(_additional_context(msg))


def show_help() -> None:
    print("crew-lifecycle-hook - Multi-event hook: SessionStart sentinel + PostToolUse pulse cron")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  1. SessionStart: drops a readiness sentinel file so 'crew create --tell'")
    print("     can wait deterministically instead of using a wall-clock timeout.")
    print("  2. PostToolUse(Bash): manages pulse cron lifecycle based on 'crew create'")
    print("     and 'crew dismiss' commands.")
    print()
    print("SENTINEL (SessionStart):")
    print("  Fires in every session. Derives session name from tmux window name (#W).")
    print("  Writes: ${TMPDIR:-/tmp}/crew/ready-<session-name>")
    print("  crew create --tell waits on this file (deterministic readiness signal).")
    print("  Fails silently if session name or sentinel directory unavailable.")
    print()
    print("TRIGGER (PostToolUse):")
    print("  PostToolUse(Bash) — fires after every Bash tool call.")
    print("  Only emits context when the command is 'crew create ...' or 'crew dismiss ...'.")
    print("  Silent for all other commands.")
    print("  Only fires for Senior Staff sessions (KANBAN_AGENT=senior-staff-engineer).")
    print()
    print("CRON INSTALL (crew create):")
    print("  Detects sstaff's own tmux window index via 'tmux display-message -p #I'.")
    print("  Injects: call CronList; grep prompts for <<pulse-cron-v1>> sentinel;")
    print("  if match found, skip CronCreate (idempotent). Otherwise CronCreate.")
    print("  Fallback: if window detection fails, emits a safe no-op directive.")
    print()
    print("CRON DELETE (crew dismiss):")
    print("  Uses detected window index to identify Staff windows vs sstaff's own.")
    print("  Checks both presence AND activity before deleting — idle Staff windows")
    print("  do not keep the cron alive. Activity uses same indicators as pulse STEP 2.")
    print("  Fallback: if window detection fails, leaves cron running (fail open).")
    print()
    print("PULSE CRON (self-terminating):")
    print("  Pulse STEP 2 calls CronDelete itself when zero activity detected.")
    print("  This ensures idle sessions eventually stop the cron without a dismiss.")
    print()
    print("OUTPUT:")
    print("  SessionStart: writes sentinel file; no stdout (logs to stderr only).")
    print("  PostToolUse: emits hookSpecificOutput.additionalContext with lifecycle directive.")
    print("  Silent (no stdout) for non-matching commands or non-sstaff sessions.")
    print()
    print("CONFIGURATION:")
    print("  Configured in modules/claude/default.nix as SessionStart and PostToolUse(Bash) hook.")


def _is_session_start_payload(payload: dict) -> bool:
    """Return True if the payload looks like a SessionStart event.

    SessionStart payloads lack 'tool_name'; PostToolUse payloads have it.
    We check positively: if 'session_id' is present and 'tool_name' is absent,
    treat it as SessionStart. Fall back to checking 'hook_event_name' if present.
    """
    if payload.get("hook_event_name") == "SessionStart":
        return True
    # Heuristic: session_id present and tool_name absent = SessionStart
    if "session_id" in payload and "tool_name" not in payload:
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    raw = sys.stdin.read()

    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Dispatch on event type: SessionStart vs PostToolUse(Bash).
    # SessionStart fires for ALL session types — no sstaff guard, sentinel is needed
    # for staff sessions too.
    if _is_session_start_payload(payload):
        _on_session_start()
        sys.exit(0)

    # Fast-path: only process Bash tool calls (defense-in-depth if matcher config changes).
    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    # Only act for Senior Staff sessions
    if not _is_senior_staff():
        print("[crew-lifecycle-hook] non-sstaff session; skipped", file=sys.stderr)
        sys.exit(0)

    command = payload.get("tool_input", {}).get("command", "").strip()

    if _CREW_CREATE_RE.match(command):
        _on_crew_create()
    elif _CREW_DISMISS_RE.match(command):
        _on_crew_dismiss()

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"[crew-lifecycle-hook] unhandled exception: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        pass  # Fail open — never break PostToolUse/SessionStart for all sessions
