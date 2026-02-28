#!/usr/bin/env python3
"""workout-smithers - Launch smithers (autonomous PR watcher) across multiple PRs in parallel TMUX windows

This script reads a JSON array from stdin and for each entry:
- Clones the repo if it doesn't exist locally
- Fetches the PR's head branch via gh
- Creates a git worktree via the workout command
- Opens a detached TMUX window pointed at the worktree
- Launches smithers <pr> in that window

CRITICAL: This script CALLS the existing workout and smithers commands.
It does NOT duplicate their logic.

Requires:
  GITHUB_REPOS_ROOT  env var pointing to the root where repos are cloned
                     e.g. /Users/karlhepler/github.com

Input Format (JSON via stdin):
    [
        {"pr": 123, "repo": "mazedesignhq/ops"},
        {"pr": 456, "repo": "mazedesignhq/api", "name": "api-fix"}
    ]

Example Usage:
    echo '[{"pr": 123, "repo": "mazedesignhq/ops"}]' | workout-smithers
    cat prs.json | workout-smithers
"""

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional


def show_help() -> None:
    """Display help message."""
    help_text = """workout-smithers - Launch smithers across multiple PRs in parallel TMUX windows

USAGE:
  echo '[{...}]' | workout-smithers
  cat file.json | workout-smithers
  workout-smithers -h, --help

INPUT FORMAT (JSON via stdin):
  [
    {"pr": 123, "repo": "mazedesignhq/ops"},
    {"pr": 456, "repo": "mazedesignhq/api", "name": "api-fix"}
  ]

  Each object MUST have:
    - pr:   PR number (integer)
    - repo: GitHub org/repo identifier (e.g. "mazedesignhq/ops")

  Each object MAY have:
    - name: TMUX window name (default: <repo-name>-<pr>, e.g. "ops-123")

ENVIRONMENT:
  GITHUB_REPOS_ROOT  Root directory where repos are cloned.
                     Must be set as an environment variable.
                     Example value: /Users/karlhepler/github.com
                     Repos are resolved as $GITHUB_REPOS_ROOT/<org>/<repo>

DESCRIPTION:
  For each PR entry:
  1. Resolve repo path: $GITHUB_REPOS_ROOT/<org/repo>
  2. Clone repo if it does not exist locally
  3. Fetch the PR's head branch name via gh
  4. Create/navigate to a worktree using the workout command
  5. Derive the worktree path from workout output
  6. Open a detached TMUX window pointed at the worktree
  7. Launch smithers <pr> in that window

  Prints a summary with ✓/✗ for each entry when complete.
  Failed entries are skipped; all others continue.

EXAMPLES:
  # Single PR
  echo '[{"pr": 123, "repo": "mazedesignhq/ops"}]' | workout-smithers

  # Multiple PRs with custom window names
  cat << 'EOF' | workout-smithers
  [
    {"pr": 101, "repo": "mazedesignhq/ops", "name": "ops-deploy"},
    {"pr": 202, "repo": "mazedesignhq/api"},
    {"pr": 303, "repo": "mazedesignhq/web", "name": "web-ui"}
  ]
  EOF

  # From file
  cat prs.json | workout-smithers

WHAT HAPPENS:
  For each JSON object:
  1. Validates pr and repo fields
  2. Clones repo if missing from $GITHUB_REPOS_ROOT
  3. Fetches PR head branch via gh pr view
  4. Calls workout <branch> in the repo to create/activate worktree
  5. Opens TMUX window in detached mode at the worktree path
  6. Sends 'smithers <pr>' to the window
  7. Reports success/failure

REQUIREMENTS:
  - GITHUB_REPOS_ROOT: Must be set as an environment variable
  - git: Repository cloning
  - gh: GitHub CLI for PR branch lookup
  - tmux: Window management
  - workout: Base worktree command
  - smithers: Autonomous PR watcher

SEE ALSO:
  smithers --help    PR watcher command
  workout --help     Worktree management command
  tmux list-windows  View all TMUX windows
"""
    print(help_text, file=sys.stderr)


def validate_json_input(data: object) -> List[Dict]:
    """Validate JSON input structure.

    Args:
        data: Parsed JSON data

    Returns:
        List of validated PR definitions

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

        if "pr" not in item:
            raise ValueError(f"Item {i} missing required field 'pr'")

        if "repo" not in item:
            raise ValueError(f"Item {i} missing required field 'repo'")

        pr = item["pr"]
        if not isinstance(pr, int) or isinstance(pr, bool):
            raise ValueError(f"Item {i} field 'pr' must be an integer")

        if pr <= 0:
            raise ValueError(f"Item {i} field 'pr' must be a positive integer")

        repo = item["repo"]
        if not isinstance(repo, str) or not repo.strip():
            raise ValueError(f"Item {i} field 'repo' must be a non-empty string")

        if "/" not in repo or repo.count("/") != 1:
            raise ValueError(f"Item {i} field 'repo' must be in 'org/repo' format")

        validated_item: Dict = {
            "pr": pr,
            "repo": repo.strip(),
        }

        if "name" in item:
            name = item["name"]
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Item {i} field 'name' must be a non-empty string")
            validated_item["name"] = name.strip()

        validated.append(validated_item)

    return validated


def derive_window_name(repo: str, pr: int) -> str:
    """Derive default TMUX window name from repo and PR number.

    Args:
        repo: org/repo string (e.g. "mazedesignhq/ops")
        pr:   PR number

    Returns:
        Window name (e.g. "ops-123")
    """
    repo_name = repo.split("/")[1]
    return f"{repo_name}-{pr}"


def derive_worktree_path(branch: str, repo_path: str, repos_root: str, repo: str) -> str:
    """Derive the expected worktree path from the branch and repo.

    workout organizes worktrees as ~/worktrees/<org>/<repo>/karlhepler/<branch-suffix>/
    The branch-suffix strips the karlhepler/ prefix if present.

    Args:
        branch: Full branch name (may or may not have karlhepler/ prefix)
        repo_path: Absolute path to the local repo clone
        repos_root: Value of GITHUB_REPOS_ROOT
        repo: org/repo string

    Returns:
        Expected worktree path
    """
    org, repo_name = repo.split("/")
    branch_suffix = branch
    if branch_suffix.startswith("karlhepler/"):
        branch_suffix = branch_suffix[len("karlhepler/"):]
    home_dir = os.path.expanduser("~")
    return os.path.join(home_dir, "worktrees", org, repo_name, "karlhepler", branch_suffix)


def run_command(
    cmd: List[str],
    capture_output: bool = True,
    cwd: Optional[str] = None,
) -> Optional[subprocess.CompletedProcess]:
    """Run command and return result.

    Args:
        cmd:            Command and arguments as list
        capture_output: Whether to capture stdout/stderr
        cwd:            Working directory (None = current directory)

    Returns:
        CompletedProcess if capture_output=True, None otherwise
    """
    try:
        if capture_output:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=cwd,
            )
        else:
            subprocess.run(cmd, check=False, cwd=cwd)
            return None
    except Exception as e:
        print(f"Error running command {' '.join(cmd)}: {e}", file=sys.stderr)
        return None


def ensure_repo_cloned(repo: str, repo_path: str) -> bool:
    """Clone repo if it does not exist locally.

    Args:
        repo:      org/repo string
        repo_path: Target path for the clone

    Returns:
        True if repo is available (already existed or cloned), False on failure
    """
    if os.path.isdir(repo_path):
        return True

    parent_dir = os.path.dirname(repo_path)
    os.makedirs(parent_dir, exist_ok=True)

    print(f"  Cloning {repo}...", file=sys.stderr)
    result = run_command(
        ["git", "clone", f"git@github.com:{repo}.git", repo_path],
        capture_output=True,
    )

    if not result or result.returncode != 0:
        print(f"  x Failed to clone {repo}", file=sys.stderr)
        if result and result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line:
                    print(f"    {line}", file=sys.stderr)
        return False

    print(f"  Cloned to {repo_path}", file=sys.stderr)
    return True


def fetch_pr_branch(pr: int, repo: str) -> Optional[str]:
    """Fetch the head branch name for a PR via gh.

    Args:
        pr:   PR number
        repo: org/repo string

    Returns:
        Branch name, or None on failure
    """
    result = run_command([
        "gh", "pr", "view", str(pr),
        "-R", repo,
        "--json", "headRefName",
        "-q", ".headRefName",
    ])

    if not result or result.returncode != 0:
        print(f"  x Failed to fetch branch for PR #{pr}", file=sys.stderr)
        if result and result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line:
                    print(f"    {line}", file=sys.stderr)
        return None

    branch = result.stdout.strip()
    if not branch:
        print(f"  x gh returned empty branch name for PR #{pr}", file=sys.stderr)
        return None

    return branch


def create_worktree(branch: str, repo_path: str) -> Optional[str]:
    """Create or navigate to a worktree via the workout command.

    Args:
        branch:    Branch name to create worktree for
        repo_path: Absolute path to the local repo clone

    Returns:
        Worktree path on success, None on failure
    """
    result = run_command(["workout", branch], cwd=repo_path)

    if not result or result.returncode != 0:
        print("  x Failed to create worktree", file=sys.stderr)
        if result and result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line and not line.startswith("cd "):
                    print(f"    {line}", file=sys.stderr)
        return None

    # workout outputs: cd '/path/to/worktree'
    worktree_path = None
    for line in result.stdout.split("\n"):
        if line.startswith("cd '"):
            worktree_path = line[4:-1]  # Strip "cd '" prefix and "'" suffix
            break

    if not worktree_path:
        print("  x Could not determine worktree path from workout output", file=sys.stderr)
        return None

    return worktree_path


def open_tmux_window(window_name: str, worktree_path: str) -> bool:
    """Create a detached TMUX window at the worktree path.

    Args:
        window_name:   Name for the TMUX window
        worktree_path: Working directory for the window

    Returns:
        True on success, False on failure
    """
    result = run_command([
        "tmux", "new-window",
        "-d",
        "-n", window_name,
        "-c", worktree_path,
    ])

    if not result or result.returncode != 0:
        print(f"  x Failed to create TMUX window '{window_name}'", file=sys.stderr)
        if result and result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line:
                    print(f"    {line}", file=sys.stderr)
        return False

    return True


def launch_smithers(window_name: str, pr: int) -> None:
    """Send smithers <pr> to the TMUX window.

    Args:
        window_name: Target TMUX window name
        pr:          PR number to watch
    """
    run_command([
        "tmux", "send-keys",
        "-t", window_name,
        f"smithers {pr}",
        "Enter",
    ], capture_output=False)


def process_entry(entry: Dict, repos_root: str) -> bool:
    """Process a single PR entry end-to-end.

    Args:
        entry:      Validated entry dict with pr, repo, optional name
        repos_root: Value of GITHUB_REPOS_ROOT

    Returns:
        True on success, False on failure
    """
    pr = entry["pr"]
    repo = entry["repo"]
    window_name = entry.get("name") or derive_window_name(repo, pr)
    repo_path = os.path.join(repos_root, repo)

    print(f"Processing: PR #{pr} ({repo}) -> window '{window_name}'...", file=sys.stderr)

    if not ensure_repo_cloned(repo, repo_path):
        return False

    branch = fetch_pr_branch(pr, repo)
    if not branch:
        return False

    print(f"  Branch: {branch}", file=sys.stderr)

    worktree_path = create_worktree(branch, repo_path)
    if not worktree_path:
        return False

    print(f"  Worktree: {worktree_path}", file=sys.stderr)

    if not open_tmux_window(window_name, worktree_path):
        print("  Warning: worktree created but TMUX window failed", file=sys.stderr)
        return True  # Worktree success counts even if TMUX fails

    print(f"  TMUX window: {window_name}", file=sys.stderr)

    launch_smithers(window_name, pr)
    print(f"  Launched smithers {pr} in window '{window_name}'", file=sys.stderr)

    return True


def check_prerequisites() -> bool:
    """Check that required commands are available.

    Returns:
        True if all required commands exist, False otherwise
    """
    required = ["tmux", "workout", "gh", "smithers"]
    all_ok = True

    for cmd in required:
        result = run_command(["which", cmd])
        if not result or result.returncode != 0:
            print(f"Error: required command '{cmd}' not found", file=sys.stderr)
            all_ok = False

    return all_ok


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        show_help()
        sys.exit(0)

    # Fail fast if GITHUB_REPOS_ROOT is not set
    repos_root = os.environ.get("GITHUB_REPOS_ROOT", "")
    if not repos_root:
        print("Error: GITHUB_REPOS_ROOT is not set.", file=sys.stderr)
        print("Please set GITHUB_REPOS_ROOT as an environment variable.", file=sys.stderr)
        sys.exit(1)

    repos_root = os.path.expanduser(repos_root)
    if not os.path.isdir(repos_root):
        print(f"Error: GITHUB_REPOS_ROOT does not exist: {repos_root}", file=sys.stderr)
        print("Create the directory or set GITHUB_REPOS_ROOT to a valid path.", file=sys.stderr)
        sys.exit(1)

    if sys.stdin.isatty():
        print("Error: workout-smithers requires JSON input via stdin", file=sys.stderr)
        print("Usage: echo '[{...}]' | workout-smithers", file=sys.stderr)
        print("       cat file.json | workout-smithers", file=sys.stderr)
        print("Run 'workout-smithers --help' for full documentation", file=sys.stderr)
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
        entries = validate_json_input(data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not check_prerequisites():
        sys.exit(1)

    succeeded = []
    failed = []

    for entry in entries:
        label = f"PR #{entry['pr']} ({entry['repo']})"
        if process_entry(entry, repos_root):
            succeeded.append(label)
        else:
            failed.append(label)
        print(file=sys.stderr)  # Blank line between entries

    # Print summary
    print("=" * 63, file=sys.stderr)
    print("WORKOUT SMITHERS SUMMARY", file=sys.stderr)
    print("=" * 63, file=sys.stderr)
    print(file=sys.stderr)

    if succeeded:
        print(f"Succeeded ({len(succeeded)}):", file=sys.stderr)
        for label in succeeded:
            print(f"  + {label}", file=sys.stderr)
        print(file=sys.stderr)

    if failed:
        print(f"Failed ({len(failed)}):", file=sys.stderr)
        for label in failed:
            print(f"  x {label}", file=sys.stderr)
        print(file=sys.stderr)

    print("Use 'tmux list-windows' to see all windows", file=sys.stderr)
    print("Use 'tmux select-window -t <name>' to switch to a window", file=sys.stderr)

    if failed:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
