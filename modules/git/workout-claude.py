#!/usr/bin/env python3
"""workout-claude - Batch worktree creation with TMUX automation and prompt injection

This is a WRAPPER around the existing workout command that adds:
- Batch creation: Process multiple branches at once via JSON input
- Prompt injection: Pass per-worktree prompts to Claude Code instances
- TMUX automation: Create detached windows for each worktree
- Claude integration: Launch staff with custom prompts in each window

CRITICAL: This script CALLS the existing workout command.
It does NOT duplicate workout's logic.

Input Format (JSON via stdin):
    [
        {"worktree": "branch-name", "prompt": "Context string for Claude"},
        {"worktree": "another-branch", "prompt": "Different context"}
    ]

Example Usage:
    echo '[{"worktree": "fix-auth", "prompt": "Look up Linear AUTH-123"}]' | workout-claude
    cat worktrees.json | workout-claude
"""

import json
import subprocess
import sys
from typing import List, Dict, Optional


def show_help() -> None:
    """Display help message"""
    help_text = """workout-claude - Batch worktree creation with TMUX windows and prompt injection

USAGE:
  echo '[{...}]' | workout-claude
  cat file.json | workout-claude
  workout-claude -h, --help

INPUT FORMAT (JSON via stdin):
  [
    {"worktree": "branch-name", "prompt": "Context for Claude Code"},
    {"worktree": "another-branch", "prompt": "Different context"}
  ]

  Each object MUST have:
    - worktree: Branch name (karlhepler/ prefix auto-added if missing)
    - prompt: Context string to pass to Claude Code via staff -p flag

DESCRIPTION:
  Creates multiple git worktrees with dedicated TMUX windows and
  Claude Code instances. Each Claude instance receives a custom prompt
  for context-aware parallel development workflows.

  This is a wrapper around the existing 'workout' command that adds:
  - JSON input processing for batch operations
  - Per-worktree prompt injection to Claude Code
  - Detached TMUX window creation per worktree
  - Automatic 'staff' (Claude Code) launch with prompts

FEATURES:
  - JSON input: Structured worktree + prompt definitions
  - Auto-prefixes: Adds karlhepler/ to branches (strips first if present)
  - Idempotent: Safe to run multiple times with same branches
  - Error resilient: Skips failures, continues with others
  - Detached mode: Windows created in background (no focus switch)
  - Window naming: Uses branch suffix only (no karlhepler/ prefix)
  - Prompt passthrough: Each Claude instance gets its specific context

EXAMPLES:
  # Single worktree with prompt
  echo '[{"worktree": "fix-auth", "prompt": "Linear AUTH-123: Fix OAuth flow"}]' | workout-claude

  # Multiple worktrees with different prompts
  cat << 'EOF' | workout-claude
  [
    {"worktree": "feature-x", "prompt": "Implement feature X from Linear FE-123"},
    {"worktree": "bug-456", "prompt": "Fix bug 456 - see Linear BUG-456"},
    {"worktree": "refactor-y", "prompt": "Refactor Y module per tech debt ticket"}
  ]
  EOF

  # From file
  cat worktrees.json | workout-claude

WHAT HAPPENS:
  For each JSON object:
  1. Validates worktree and prompt fields exist
  2. Calls existing 'workout' command to create worktree
  3. Creates TMUX window in detached mode
  4. Launches 'staff -p "prompt"' in the window (Claude Code with context)
  5. Reports success/failure

REQUIREMENTS:
  - git: Repository management
  - tmux: Window management
  - workout: Base worktree command (automatically available)
  - staff: Claude Code command (optional, warning if missing)
  - python3: JSON processing

NOTES:
  - For single worktree creation, use 'workout' command directly
  - TMUX windows are created in background (detached)
  - Window names use branch suffix only (no karlhepler/ prefix)
  - Worktrees organized in ~/worktrees/org/repo/branch/
  - Prompts passed via 'staff -p "prompt"' (non-interactive mode)
  - Invalid JSON or missing fields will cause immediate error

SEE ALSO:
  workout --help    Original worktree command
  tmux list-windows View all TMUX windows
  staff --help      Claude Code wrapper command
"""
    print(help_text, file=sys.stderr)


def validate_json_input(data: any) -> List[Dict[str, str]]:
    """Validate JSON input structure

    Args:
        data: Parsed JSON data

    Returns:
        List of validated worktree definitions

    Raises:
        ValueError: If validation fails
    """
    if not isinstance(data, list):
        raise ValueError("JSON input must be an array")

    if len(data) == 0:
        raise ValueError("JSON array cannot be empty")

    validated = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Item {i} is not an object")

        if "worktree" not in item:
            raise ValueError(f"Item {i} missing required field 'worktree'")

        if "prompt" not in item:
            raise ValueError(f"Item {i} missing required field 'prompt'")

        if not isinstance(item["worktree"], str):
            raise ValueError(f"Item {i} field 'worktree' must be a string")

        if not isinstance(item["prompt"], str):
            raise ValueError(f"Item {i} field 'prompt' must be a string")

        if not item["worktree"].strip():
            raise ValueError(f"Item {i} field 'worktree' cannot be empty")

        # prompt can be empty string (valid use case - just launch staff with no custom prompt)

        validated.append({
            "worktree": item["worktree"].strip(),
            "prompt": item["prompt"]
        })

    return validated


def normalize_branch_name(branch_input: str) -> tuple[str, str]:
    """Normalize branch name to karlhepler/ prefix format

    Args:
        branch_input: Raw branch name from JSON

    Returns:
        Tuple of (branch_suffix, full_branch_name)

    Example:
        normalize_branch_name("fix-auth") -> ("fix-auth", "karlhepler/fix-auth")
        normalize_branch_name("karlhepler/fix-auth") -> ("fix-auth", "karlhepler/fix-auth")
    """
    # Strip karlhepler/ prefix if present
    branch_suffix = branch_input
    if branch_suffix.startswith("karlhepler/"):
        branch_suffix = branch_suffix[len("karlhepler/"):]

    # Re-add prefix
    full_branch_name = f"karlhepler/{branch_suffix}"

    return branch_suffix, full_branch_name


def run_command(cmd: List[str], capture_output: bool = True) -> Optional[subprocess.CompletedProcess]:
    """Run command and return result

    Args:
        cmd: Command and arguments as list
        capture_output: Whether to capture stdout/stderr

    Returns:
        CompletedProcess if capture_output=True, None otherwise
    """
    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            return result
        else:
            subprocess.run(cmd, check=False)
            return None
    except Exception as e:
        print(f"Error running command {' '.join(cmd)}: {e}", file=sys.stderr)
        return None


def check_prerequisites() -> bool:
    """Check if required commands are available

    Returns:
        True if all required commands exist, False otherwise
    """
    # Check git repo
    result = run_command(["git", "rev-parse", "--git-dir"])
    if not result or result.returncode != 0:
        print("Error: Not in a git repository", file=sys.stderr)
        return False

    # Check git remote
    result = run_command(["git", "remote", "get-url", "origin"])
    if not result or result.returncode != 0:
        print("Error: Could not get git remote URL", file=sys.stderr)
        return False

    # Check tmux
    result = run_command(["which", "tmux"])
    if not result or result.returncode != 0:
        print("Error: tmux is required for batch worktree creation", file=sys.stderr)
        print("Install tmux or use 'workout' command for single worktrees", file=sys.stderr)
        return False

    # Check workout
    result = run_command(["which", "workout"])
    if not result or result.returncode != 0:
        print("Error: 'workout' command not found", file=sys.stderr)
        print("This wrapper requires the base workout command", file=sys.stderr)
        return False

    # Check staff (warning only)
    result = run_command(["which", "staff"])
    if not result or result.returncode != 0:
        print("Warning: 'staff' command not found - TMUX windows will be created but staff won't launch", file=sys.stderr)

    return True


def create_worktree_with_prompt(worktree_def: Dict[str, str]) -> bool:
    """Create worktree and launch Claude with prompt

    Args:
        worktree_def: Dict with 'worktree' and 'prompt' keys

    Returns:
        True if successful, False otherwise
    """
    branch_suffix, full_branch_name = normalize_branch_name(worktree_def["worktree"])
    prompt = worktree_def["prompt"]

    print(f"Processing: {branch_suffix}...", file=sys.stderr)

    # Call existing workout command to create/navigate to worktree
    result = run_command(["workout", full_branch_name])

    if not result or result.returncode != 0:
        print("  ✗ Failed to create worktree", file=sys.stderr)
        if result and result.stderr:
            # Show error messages (excluding the cd line)
            for line in result.stderr.split('\n'):
                if line and not line.startswith('cd '):
                    print(f"    {line}", file=sys.stderr)
        return False

    # Parse worktree path from workout output
    # workout outputs: cd '/path/to/worktree'
    worktree_path = None
    for line in result.stdout.split('\n'):
        if line.startswith("cd '"):
            worktree_path = line[4:-1]  # Strip "cd '" prefix and "'" suffix
            break

    if not worktree_path:
        print("  ⚠ Could not determine worktree path from workout output", file=sys.stderr)
        return False

    print(f"  ✓ Created worktree: {worktree_path}", file=sys.stderr)

    # Create detached TMUX window
    tmux_result = run_command([
        "tmux", "new-window",
        "-d",  # detached
        "-c", worktree_path,  # start directory
        "-n", branch_suffix  # window name
    ])

    if not tmux_result or tmux_result.returncode != 0:
        print("  ⚠ Failed to create TMUX window (worktree created successfully)", file=sys.stderr)
        return True  # Worktree creation succeeded, just TMUX failed

    print(f"  ✓ Created TMUX window: {branch_suffix}", file=sys.stderr)

    # Check if staff command is available
    staff_result = run_command(["which", "staff"])
    if not staff_result or staff_result.returncode != 0:
        return True  # Success - worktree and window created, staff just not available

    # Launch staff with prompt in the window
    # Use staff "prompt" for interactive mode with prompt auto-execution
    if prompt:
        # Prepend worktree context to orient the receiving Claude
        context_prefix = (
            "IMPORTANT: You are already in the correct git worktree and on the correct branch. "
            "Do all your work in this directory. Do NOT create new branches or new worktrees. "
            "You are in the right place - just start working.\n\n"
        )
        full_prompt = context_prefix + prompt

        # Escape double quotes in prompt for shell command
        escaped_prompt = full_prompt.replace('"', '\\"')
        staff_cmd = f'staff "{escaped_prompt}"'
    else:
        # No prompt - just launch staff interactively
        staff_cmd = "staff"

    run_command([
        "tmux", "send-keys",
        "-t", branch_suffix,
        staff_cmd,
        "Enter"
    ], capture_output=False)

    if prompt:
        print("  ✓ Launched staff with custom prompt in window", file=sys.stderr)
    else:
        print("  ✓ Launched staff in window", file=sys.stderr)

    return True


def main():
    """Main entry point"""
    # Check for help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        show_help()
        sys.exit(0)

    # Check for non-stdin invocation (error)
    if sys.stdin.isatty():
        print("Error: workout-claude requires JSON input via stdin", file=sys.stderr)
        print("Usage: echo '[{...}]' | workout-claude", file=sys.stderr)
        print("       cat file.json | workout-claude", file=sys.stderr)
        print("Run 'workout-claude --help' for full documentation", file=sys.stderr)
        sys.exit(1)

    # Check prerequisites
    if not check_prerequisites():
        sys.exit(1)

    # Read and parse JSON from stdin
    try:
        json_input = sys.stdin.read()
        data = json.loads(json_input)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading stdin: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate JSON structure
    try:
        worktree_defs = validate_json_input(data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Process each worktree
    created = []
    failed = []

    for worktree_def in worktree_defs:
        if create_worktree_with_prompt(worktree_def):
            branch_suffix = normalize_branch_name(worktree_def["worktree"])[0]
            created.append(branch_suffix)
        else:
            branch_suffix = normalize_branch_name(worktree_def["worktree"])[0]
            failed.append(branch_suffix)
        print(file=sys.stderr)  # Blank line between entries

    # Print summary
    print("═" * 63, file=sys.stderr)
    print("BATCH WORKTREE CREATION SUMMARY", file=sys.stderr)
    print("═" * 63, file=sys.stderr)
    print(file=sys.stderr)

    if created:
        print(f"✓ Successfully created ({len(created)}):", file=sys.stderr)
        for branch in created:
            print(f"  - {branch}", file=sys.stderr)
        print(file=sys.stderr)

    if failed:
        print(f"✗ Failed ({len(failed)}):", file=sys.stderr)
        for branch in failed:
            print(f"  - {branch}", file=sys.stderr)
        print(file=sys.stderr)

    print("Use 'tmux list-windows' to see all windows", file=sys.stderr)
    print("Use 'tmux select-window -t <name>' to switch to a window", file=sys.stderr)

    # Exit with error if any failed
    if failed:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
