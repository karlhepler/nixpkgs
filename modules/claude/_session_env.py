"""
_session_env: Shared session-environment helpers for Claude Code hook scripts.

Provides the is_non_coordinator_session() predicate used by the three
kanban/orphan-agent hooks to skip processing when running inside a
non-coordinator session (Burns/Ralph, Personal Trainer, etc.).

Usage (via injected sys.path shim):
    from _session_env import is_non_coordinator_session

    if is_non_coordinator_session():
        return  # or sys.exit(0) / print(allow())
"""

import os


def is_non_coordinator_session() -> bool:
    """Return True if the current process is running inside a non-coordinator session.

    Non-coordinator sessions are identified by environment variable flags:
      - BURNS_SESSION=1       Ralph/Monty-Burns orchestrator session
      - PERSONAL_TRAINER_SESSION=1  Personal-trainer plugin session

    OR-logic: any flag being set returns True. Add new session-type flags
    here as new modes are introduced, then update each hook's module docstring.

    Called from the main() entry point of each kanban hook before processing
    any hook payload, allowing a clean early-exit before stdin is consumed.
    """
    return (
        os.environ.get("BURNS_SESSION") == "1"
        or os.environ.get("PERSONAL_TRAINER_SESSION") == "1"
    )
