#!/usr/bin/env python3
"""stk-claude - Batch stacked worktree creation with TMUX automation and prompt injection

Like workout-claude, but uses 'stk work' instead of 'workout' so every worktree
gets a Graphite-tracked branch stacked on the current branch.

This is a WRAPPER around the existing stk command that adds:
- Batch creation: Process multiple branches at once via JSON input
- Prompt injection: Pass per-worktree prompts to Claude command instances
- TMUX automation: Create detached windows for each worktree
- Claude integration: Launch specified command with custom prompts in each window

CRITICAL: This script CALLS the existing stk command.
It does NOT duplicate stk's logic.

Input Format (JSON via stdin):
    [
        {"worktree": "branch-name", "prompt": "Context string for Claude"},
        {"worktree": "another-branch", "prompt": "Different context"}
    ]

Example Usage:
    echo '[{"worktree": "fix-auth", "prompt": "Look up Linear AUTH-123"}]' | stk-claude staff
    cat worktrees.json | stk-claude burns
"""

import json
import os
import subprocess
import sys
from typing import List, Dict, Optional


def show_help() -> None:
    """Display help message"""
    help_text = """stk-claude - Batch stacked worktree creation with TMUX windows and Claude command prompt injection

USAGE:
  echo '[{...}]' | stk-claude <command>
  cat file.json | stk-claude <command>
  stk-claude -h, --help

ARGUMENTS:
  <command>    Claude command to launch in each worktree (e.g., staff, burns)

INPUT FORMAT (JSON via stdin):
  [
    {"worktree": "branch-name", "prompt": "Context for Claude command"},
    {"worktree": "another-branch", "prompt": "Different context"},
    {"worktree": "ops-work", "prompt": "Fix infra issue", "repo": "~/path/to/other/repo"}
  ]

  Each object MUST have:
    - worktree: Branch name (karlhepler/ prefix auto-added if missing)
    - prompt: Context string to pass to Claude command as positional argument

  Each object MAY have:
    - repo: Path to a different git repository (e.g., "~/ops", "/Users/me/projects/other")
            When present, the worktree is created in that repo instead of the current one.

DESCRIPTION:
  Like workout-claude but uses 'stk work' instead of 'workout', so each worktree
  gets a Graphite-tracked branch stacked on the current branch of that repo.

  Creates multiple git worktrees with dedicated TMUX windows and
  Claude command instances. Each Claude instance receives a custom prompt
  for context-aware parallel development workflows.

FEATURES:
  - Graphite-tracked: Branches stacked on current branch via 'stk work'
  - JSON input: Structured worktree + prompt definitions
  - Auto-prefixes: Adds karlhepler/ to branches (strips first if present)
  - Idempotent: Safe to run multiple times with same branches
  - Error resilient: Skips failures, continues with others
  - Detached mode: Windows created in background (no focus switch)
  - Window naming: Uses branch suffix only (no karlhepler/ prefix)
  - Prompt passthrough: Each Claude instance gets its specific context

EXAMPLES:
  # Single stacked worktree with staff command
  echo '[{"worktree": "fix-auth", "prompt": "Linear AUTH-123: Fix OAuth flow"}]' | stk-claude staff

  # Multiple stacked worktrees with burns command
  cat << 'EOF' | stk-claude burns
  [
    {"worktree": "feature-x", "prompt": "Implement feature X from Linear FE-123"},
    {"worktree": "bug-456", "prompt": "Fix bug 456 - see Linear BUG-456"}
  ]
  EOF

  # Cross-repo: create stacked worktree in a different repository
  echo '[{"worktree": "fix-infra", "prompt": "Fix the deployment issue", "repo": "~/ops"}]' | stk-claude staff

SEE ALSO:
  stk --help        Stacked PR workflow commands
  workout-claude    Non-stacked variant (plain git branches)
  tmux list-windows View all TMUX windows
"""
    print(help_text, file=sys.stderr)


def validate_json_input(data: any) -> List[Dict[str, str]]:
    """Validate JSON input structure"""
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

        validated_item: Dict[str, str] = {
            "worktree": item["worktree"].strip(),
            "prompt": item["prompt"]
        }

        if "repo" in item:
            if not isinstance(item["repo"], str):
                raise ValueError(f"Item {i} field 'repo' must be a string")
            if not item["repo"].strip():
                raise ValueError(f"Item {i} field 'repo' cannot be empty")
            validated_item["repo"] = item["repo"].strip()

        validated.append(validated_item)

    return validated


def normalize_branch_name(branch_input: str) -> tuple[str, str]:
    """Normalize branch name to karlhepler/ prefix format"""
    branch_suffix = branch_input
    if branch_suffix.startswith("karlhepler/"):
        branch_suffix = branch_suffix[len("karlhepler/"):]

    full_branch_name = f"karlhepler/{branch_suffix}"
    return branch_suffix, full_branch_name


def run_command(cmd: List[str], capture_output: bool = True, cwd: Optional[str] = None) -> Optional[subprocess.CompletedProcess]:
    """Run command and return result"""
    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=cwd
            )
            return result
        else:
            subprocess.run(cmd, check=False, cwd=cwd)
            return None
    except Exception as e:
        print(f"Error running command {' '.join(cmd)}: {e}", file=sys.stderr)
        return None


def check_prerequisites(command: str, check_git_cwd: bool = True) -> bool:
    """Check if required commands are available"""
    if check_git_cwd:
        result = run_command(["git", "rev-parse", "--git-dir"])
        if not result or result.returncode != 0:
            print("Error: Not in a git repository", file=sys.stderr)
            return False

        result = run_command(["git", "remote", "get-url", "origin"])
        if not result or result.returncode != 0:
            print("Error: Could not get git remote URL", file=sys.stderr)
            return False

    result = run_command(["which", "tmux"])
    if not result or result.returncode != 0:
        print("Error: tmux is required for batch worktree creation", file=sys.stderr)
        return False

    result = run_command(["which", "stk"])
    if not result or result.returncode != 0:
        print("Error: 'stk' command not found", file=sys.stderr)
        print("This wrapper requires the stk command", file=sys.stderr)
        return False

    result = run_command(["which", command])
    if not result or result.returncode != 0:
        print(f"Warning: '{command}' command not found - TMUX windows will be created but {command} won't launch", file=sys.stderr)

    return True


def create_worktree_with_prompt(worktree_def: Dict[str, str], command: str) -> bool:
    """Create stacked worktree via stk work and launch Claude command with prompt"""
    branch_suffix, full_branch_name = normalize_branch_name(worktree_def["worktree"])
    prompt = worktree_def["prompt"]

    cwd: Optional[str] = None
    repo_path = worktree_def.get("repo")
    if repo_path:
        expanded = os.path.expanduser(repo_path)
        if not os.path.isdir(expanded):
            print(f"  ✗ Repo path does not exist: {repo_path}", file=sys.stderr)
            return False
        check = run_command(["git", "rev-parse", "--git-dir"], cwd=expanded)
        if not check or check.returncode != 0:
            print(f"  ✗ Not a git repository: {repo_path}", file=sys.stderr)
            return False
        cwd = expanded
        print(f"  Using repo: {expanded}", file=sys.stderr)

    print(f"Processing: {branch_suffix}...", file=sys.stderr)

    # Call stk work to create graphite-tracked branch + worktree
    result = run_command(["stk", "work", full_branch_name], cwd=cwd)

    if not result or result.returncode != 0:
        print("  ✗ Failed to create stacked worktree", file=sys.stderr)
        if result and result.stderr:
            for line in result.stderr.split('\n'):
                if line and not line.startswith('cd '):
                    print(f"    {line}", file=sys.stderr)
        return False

    # Parse worktree path from stk work output (same format as workout: cd 'path')
    worktree_path = None
    for line in result.stdout.split('\n'):
        if line.startswith("cd '"):
            worktree_path = line[4:-1]
            break

    if not worktree_path:
        print("  ⚠ Could not determine worktree path from stk work output", file=sys.stderr)
        return False

    print(f"  ✓ Created stacked worktree: {worktree_path}", file=sys.stderr)

    # Create detached TMUX window
    tmux_result = run_command([
        "tmux", "new-window",
        "-d",
        "-c", worktree_path,
        "-n", branch_suffix
    ])

    if not tmux_result or tmux_result.returncode != 0:
        print("  ⚠ Failed to create TMUX window (worktree created successfully)", file=sys.stderr)
        return True

    print(f"  ✓ Created TMUX window: {branch_suffix}", file=sys.stderr)

    command_result = run_command(["which", command])
    if not command_result or command_result.returncode != 0:
        return True

    if prompt:
        context_prefix = (
            "IMPORTANT: You are already in the correct git worktree and on the correct branch. "
            "Do all your work in this directory. Do NOT create new branches or new worktrees. "
            "You are in the right place - just start working.\n\n"
        )
        full_prompt = context_prefix + prompt
        escaped_prompt = full_prompt.replace('"', '\\"')
        claude_cmd = f'{command} "{escaped_prompt}"'
    else:
        claude_cmd = command

    run_command([
        "tmux", "send-keys",
        "-t", branch_suffix,
        claude_cmd,
        "Enter"
    ], capture_output=False)

    if prompt:
        print(f"  ✓ Launched {command} with custom prompt in window", file=sys.stderr)
    else:
        print(f"  ✓ Launched {command} in window", file=sys.stderr)

    return True


def main():
    """Main entry point"""
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        show_help()
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Error: Missing required command argument", file=sys.stderr)
        print("Usage: echo '[{...}]' | stk-claude <command>", file=sys.stderr)
        print("Example: echo '[{...}]' | stk-claude staff", file=sys.stderr)
        print("Run 'stk-claude --help' for full documentation", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if sys.stdin.isatty():
        print("Error: stk-claude requires JSON input via stdin", file=sys.stderr)
        print(f"Usage: echo '[{{...}}]' | stk-claude {command}", file=sys.stderr)
        print("Run 'stk-claude --help' for full documentation", file=sys.stderr)
        sys.exit(1)

    try:
        json_input = sys.stdin.read()
        data = json.loads(json_input)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading stdin: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        worktree_defs = validate_json_input(data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    needs_cwd_check = any("repo" not in item for item in worktree_defs)

    if not check_prerequisites(command, check_git_cwd=needs_cwd_check):
        sys.exit(1)

    created = []
    failed = []

    for worktree_def in worktree_defs:
        if create_worktree_with_prompt(worktree_def, command):
            branch_suffix = normalize_branch_name(worktree_def["worktree"])[0]
            created.append(branch_suffix)
        else:
            branch_suffix = normalize_branch_name(worktree_def["worktree"])[0]
            failed.append(branch_suffix)
        print(file=sys.stderr)

    print("═" * 63, file=sys.stderr)
    print("BATCH STACKED WORKTREE CREATION SUMMARY", file=sys.stderr)
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

    if failed:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
