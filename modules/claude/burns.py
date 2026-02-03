#!/usr/bin/env python3
"""
Burns: Run Ralph Orchestrator with Staff Engineer hat

Usage:
    burns "prompt string"    # Inline prompt (uses -p flag)
    burns path/to/file.md    # Prompt from file (uses -P flag)
"""

import os
import sys

# Path to Staff Engineer hat YAML (substituted by Nix at build time)
STAFF_ENGINEER_HAT = "STAFF_ENGINEER_HAT_YAML"
MAX_ITERATIONS = 100


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

    # Exec ralph (replaces this process)
    os.execvp("ralph", cmd)


if __name__ == "__main__":
    main()
