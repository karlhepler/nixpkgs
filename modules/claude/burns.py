#!/usr/bin/env python3
"""
Burns: Run Ralph Orchestrator with Ralph Coordinator output style

Usage:
    burns "prompt string"                      # Inline prompt, will create PR
    burns path/to/file.md                      # Prompt from file, will create PR
    burns --pr 123 "prompt"                    # PR already exists (e.g., from smithers)
    burns --pr https://github.com/... "prompt" # PR URL provided
    burns --max-ralph-iterations N "prompt"    # Custom max iterations

Options:
    --pr NUMBER_OR_URL          Pull request already exists (skips PR creation requirement)
    --max-ralph-iterations N    Max iterations for Ralph (default: 3)
                                Can also set via BURNS_MAX_RALPH_ITERATIONS env var
                                Priority: CLI flag > env var > default
"""

import argparse
import os
import signal
import subprocess
import sys
import time

# Path to Ralph Coordinator hat YAML (substituted by Nix at build time)
STAFF_ENGINEER_HAT = "STAFF_ENGINEER_HAT_YAML"
DEFAULT_MAX_ITERATIONS = 3


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


def sanitize_for_prompt(text: str, max_length: int = 2000) -> str:
    """Sanitize external content before injecting into LLM prompts.

    Prevents prompt injection attacks by:
    - Removing ANSI escape codes
    - HTML-escaping special characters
    - Neutralizing override keywords
    - Truncating safely to prevent context overflow

    Args:
        text: Raw text from external sources (user input, file content, etc.)
        max_length: Maximum length after sanitization

    Returns:
        Sanitized text safe for prompt injection
    """
    import re
    import html

    if not text or not isinstance(text, str):
        return ""

    # Strip ANSI escape codes (color codes, control sequences)
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    text = re.sub(r'\x1b\][0-9;]*\x07', '', text)

    # HTML-escape to neutralize markup injection
    text = html.escape(text)

    # Neutralize common prompt injection keywords by adding whitespace breaks
    # This prevents "IGNORE ALL PREVIOUS INSTRUCTIONS" style attacks
    override_keywords = [
        'IGNORE', 'OVERRIDE', 'SYSTEM', 'ADMIN', 'ROOT', 'SUDO',
        'DISREGARD', 'FORGET', 'BYPASS', 'DISABLE', 'ENABLE',
        'PREVIOUS INSTRUCTIONS', 'ALL CONSTRAINTS', 'SAFETY'
    ]

    for keyword in override_keywords:
        # Case-insensitive replacement with zero-width spaces to break keyword matching
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        text = pattern.sub(lambda m: '\u200b'.join(m.group(0)), text)

    # Truncate safely - avoid cutting mid-word
    if len(text) > max_length:
        text = text[:max_length].rsplit(' ', 1)[0] + '... [truncated]'

    return text


def main():
    """Main entry point."""
    # Validate Nix substitution occurred (check if hat file exists)
    if not os.path.isfile(STAFF_ENGINEER_HAT):
        print(
            f"Error: Ralph Coordinator hat not found at: {STAFF_ENGINEER_HAT}",
            file=sys.stderr
        )
        sys.exit(1)

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Run Ralph Orchestrator with Ralph Coordinator output style",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "prompt",
        help="Prompt string or path to prompt file"
    )
    parser.add_argument(
        "--max-ralph-iterations",
        type=int,
        default=None,
        help=f"Max iterations for Ralph (default: {DEFAULT_MAX_ITERATIONS}). Override with BURNS_MAX_RALPH_ITERATIONS env var"
    )
    parser.add_argument(
        "--pr",
        type=str,
        default=None,
        help="PR number or URL if pull request already exists (e.g., '123' or 'https://github.com/owner/repo/pull/123')"
    )

    args = parser.parse_args()

    # Determine max iterations: CLI flag > env var > default
    max_iterations = args.max_ralph_iterations
    if max_iterations is None:
        try:
            max_iterations = int(os.environ.get("BURNS_MAX_RALPH_ITERATIONS", DEFAULT_MAX_ITERATIONS))
        except ValueError:
            print(
                f"Error: BURNS_MAX_RALPH_ITERATIONS environment variable must be a valid integer. "
                f"Got: '{os.environ.get('BURNS_MAX_RALPH_ITERATIONS')}'",
                file=sys.stderr
            )
            sys.exit(1)

    # Validate positive integer
    if max_iterations < 1:
        print("Error: max-ralph-iterations must be a positive integer", file=sys.stderr)
        sys.exit(1)

    # Build the full prompt (from file or string)
    if os.path.isfile(args.prompt):
        # Read prompt from file
        with open(args.prompt, 'r') as f:
            full_prompt = f.read()
    else:
        # Use prompt string directly
        full_prompt = args.prompt

    # Append PR context to prompt (sanitize user input)
    if args.pr:
        # PR exists - append context (sanitize PR identifier)
        pr_safe = sanitize_for_prompt(args.pr, max_length=200)
        full_prompt += f"\n\n---\n\n## Pull Request Context\n\n**Pull request already exists:** {pr_safe}\n\nYou do NOT need to create a pull request. The PR already exists and is being watched."
    else:
        # No PR - require creation before exit
        full_prompt += "\n\n---\n\n## Pull Request Requirement\n\n**No pull request exists yet for this branch.**\n\nBefore you can exit, you MUST:\n1. Ensure all changes are committed\n2. Create a pull request using `gh pr create`\n3. Verify the PR was created successfully\n\nYou cannot complete this work without creating a PR."

    # Build ralph command with constructed prompt
    cmd = [
        "ralph", "run",
        "-a",  # Auto-approve
        "-c", STAFF_ENGINEER_HAT,
        "--max-iterations", str(max_iterations),
        "-p", full_prompt,  # Always use -p with constructed prompt
    ]

    # Prepare environment
    env = os.environ.copy()

    # Run Ralph as subprocess (not exec) so we can handle Ctrl+C
    try:
        process = subprocess.Popen(cmd, env=env)
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
