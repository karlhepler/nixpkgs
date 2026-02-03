#!/usr/bin/env python3
"""
Burns: Run Ralph Orchestrator with Staff Engineer hat

Usage:
    burns "prompt string"    # Inline prompt (uses -p flag)
    burns path/to/file.md    # Prompt from file (uses -P flag)
"""

import os
import signal
import subprocess
import sys
import time

# Path to Staff Engineer hat YAML (substituted by Nix at build time)
STAFF_ENGINEER_HAT = "STAFF_ENGINEER_HAT_YAML"
MAX_ITERATIONS = 100


def get_all_descendants(pid):
    """Recursively find all descendant PIDs of a given process.

    Uses pgrep -P to find immediate children, then recursively finds their children.
    Works across session boundaries because pgrep -P filters by PPID, which is
    preserved even when processes call setsid().
    """
    descendants = []
    try:
        # Get immediate children using pgrep -P
        result = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            check=False
        )
        children = result.stdout.strip().split('\n') if result.stdout.strip() else []

        for child in children:
            if child:
                child_pid = int(child)
                descendants.append(child_pid)
                # Recursively get grandchildren
                descendants.extend(get_all_descendants(child_pid))
    except Exception:
        pass  # Ignore errors during tree traversal

    return descendants


def kill_process_tree(pid):
    """Kill a process and all its descendants.

    This uses recursive pgrep -P to find all descendants (even those that called
    setsid() and are in different sessions/process groups), then kills them in
    reverse order (children first, then parents) with SIGKILL for guaranteed
    termination.

    This approach is necessary because Ralph uses portable-pty which calls setsid()
    before spawning Claude CLI, causing Claude processes to escape killpg() but
    still maintaining the parent-child relationship (PPID).
    """
    # Get full process tree
    all_pids = [pid] + get_all_descendants(pid)

    # Kill in reverse order (children first, then parents)
    # This prevents orphaned processes
    for target_pid in reversed(all_pids):
        try:
            os.kill(target_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Process already exited
        except PermissionError:
            pass  # Can't kill (shouldn't happen for our own processes)
        except Exception:
            pass  # Ignore other errors

    # Small delay to let kernel clean up
    time.sleep(0.1)


def main():
    """Main entry point."""
    # Validate Nix substitution occurred (check if hat file exists)
    if not os.path.isfile(STAFF_ENGINEER_HAT):
        print(
            f"Error: Staff Engineer hat not found at: {STAFF_ENGINEER_HAT}",
            file=sys.stderr
        )
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Error: burns requires one argument (prompt string or file path)")
        sys.exit(1)

    arg = sys.argv[1]

    # Build ralph command
    cmd = [
        "ralph", "run",
        "-a",  # Auto-approve
        "-c", STAFF_ENGINEER_HAT,
        "--max-iterations", str(MAX_ITERATIONS),
    ]

    # Check if argument is a file path
    if os.path.isfile(arg):
        # It's a file - use -P flag
        cmd.extend(["-P", arg])
    else:
        # It's a prompt string - use -p flag
        cmd.extend(["-p", arg])

    # Run Ralph as subprocess (not exec) so we can handle Ctrl+C
    try:
        process = subprocess.Popen(cmd)
        exit_code = process.wait()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        # User pressed Ctrl+C - kill Ralph and all its descendants
        print("\n⚠️  Received Ctrl+C, killing Ralph and all subprocesses...", file=sys.stderr)
        kill_process_tree(process.pid)
        try:
            # Wait for cleanup (should be quick since we SIGKILL'd)
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass  # Already killed, just cleanup
        print("✓ Ralph terminated", file=sys.stderr)
        sys.exit(130)  # Standard exit code for SIGINT (128 + 2)


if __name__ == "__main__":
    main()
