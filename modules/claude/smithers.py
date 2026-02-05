#!/usr/bin/env python3
"""
Smithers: Token-efficient PR watcher

Efficiently monitors a PR by:
1. Polling CI checks until terminal (cheap - no tokens)
2. Gathering bot comments and merge conflict status
3. Only invoking Ralph when work is needed
4. Looping until PR is completely ready to merge

Usage:
    smithers          # Infer PR from current branch
    smithers 123      # Use PR #123
    smithers <url>    # Use specific PR URL
    smithers --max-ralph-iterations N 123  # Custom Ralph iterations
    smithers --max-iterations N 123        # Custom watch cycles

Options:
    --max-ralph-iterations N    How many times to ask Ralph to fix issues (default: 3)
                                Can also set via SMITHERS_MAX_RALPH_ITERATIONS env var
    --max-iterations N          How many CI check cycles to monitor (default: 4)
                                Can also set via SMITHERS_MAX_ITERATIONS env var
    Priority: CLI flag > env var > default
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from wcwidth import wcswidth

# Constants
POLL_INTERVAL = 30  # seconds
DEFAULT_MAX_CYCLES = 4  # 4 CI checks: 3 with Ralph invocations + 1 final check
DEFAULT_MAX_RALPH_INVOCATIONS = 3
TERMINAL_STATES = {
    "pass", "fail", "skipping", "cancelled",
    "success", "failure", "skipped", "neutral", "stale",
    "action_required", "timed_out"  # Don't forget these terminal states
}


def log(msg: str):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


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


def send_notification(title: str, message: str, sound: str = "Ping"):
    """Send macOS notification via Alacritty (same as Claude hooks)."""
    try:
        # Escape double quotes to prevent command injection
        # Replace all " with \" to safely embed in AppleScript strings
        safe_title = title.replace('"', '\\"')
        safe_message = message.replace('"', '\\"')
        safe_sound = sound.replace('"', '\\"')

        subprocess.run([
            "osascript",
            "-e",
            f'tell application id "org.alacritty" to display notification "{safe_message}" with title "{safe_title}" sound name "{safe_sound}"'
        ], check=False, capture_output=True)
    except Exception:
        pass  # Silently fail if notification can't be sent


def run_gh(args: list) -> tuple:
    """Run gh command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def get_pr_url(arg: str) -> str:
    """Get PR URL from argument or infer from current branch."""
    if arg is None:
        # Infer from current branch
        code, stdout, _ = run_gh(["pr", "view", "--json", "url", "--jq", ".url"])
        if code != 0 or not stdout.strip():
            print(
                "Error: No PR found for current branch. "
                "Please provide a PR number or URL.",
                file=sys.stderr
            )
            sys.exit(1)
        return stdout.strip()

    if arg.isdigit():
        # PR number
        code, stdout, _ = run_gh(["pr", "view", arg, "--json", "url", "--jq", ".url"])
        if code != 0 or not stdout.strip():
            print(f"Error: Could not find PR #{arg}", file=sys.stderr)
            sys.exit(1)
        return stdout.strip()

    if arg.startswith("http://") or arg.startswith("https://"):
        return arg

    print(
        "Error: Invalid PR argument. Provide a PR number or URL.",
        file=sys.stderr
    )
    sys.exit(1)


def parse_pr_url(url: str) -> tuple:
    """Parse PR URL into (owner, repo, number)."""
    # https://github.com/owner/repo/pull/123
    parts = url.rstrip("/").split("/")
    try:
        pull_idx = parts.index("pull")
        owner = parts[pull_idx - 2]
        repo = parts[pull_idx - 1]
        number = int(parts[pull_idx + 1])
        return owner, repo, number
    except (ValueError, IndexError):
        print(f"Error: Could not parse PR URL: {url}", file=sys.stderr)
        sys.exit(1)


def get_check_status(pr_number: int) -> dict:
    """Get all checks and their status."""
    # Note: gh pr checks doesn't have 'conclusion' field, use 'bucket' instead
    # bucket values: pass, fail, pending, skipping, cancel
    code, stdout, stderr = run_gh([
        "pr", "checks", str(pr_number),
        "--json", "name,state,bucket,link"
    ])
    if code != 0:
        return {"error": stderr, "checks": []}

    try:
        checks = json.loads(stdout) if stdout.strip() else []
        return {"checks": checks, "error": None}
    except json.JSONDecodeError:
        return {"error": f"Failed to parse checks: {stdout}", "checks": []}


def check_is_terminal(check: dict) -> bool:
    """Check if a single check is in terminal state."""
    state = check.get("state", "").lower()
    bucket = check.get("bucket", "").lower()
    # A check is terminal if bucket is set (pass/fail/skipping/cancel) or state is terminal
    # bucket=pending means still running
    if bucket and bucket != "pending":
        return True
    return state in TERMINAL_STATES


def all_checks_terminal(checks: list) -> bool:
    """Check if all checks are in terminal state."""
    return all(check_is_terminal(c) for c in checks)


def get_failed_checks(checks: list) -> list:
    """Get checks that failed (not skipped/cancelled)."""
    failed = []
    for check in checks:
        bucket = check.get("bucket", "").lower()
        if bucket == "fail":
            failed.append(check)
    return failed


def get_workflow_failure_details(owner: str, repo: str, check: dict) -> dict:
    """Fetch workflow run details and failure information for a failed check.

    Returns dict with:
    - link: URL to the workflow run
    - conclusion: Overall conclusion (failure, etc)
    - failures: List of failed job steps with messages
    """
    result = {
        "link": check.get("link", ""),
        "conclusion": check.get("bucket", "unknown"),
        "failures": []
    }

    # Extract run ID from the link URL
    # Format: https://github.com/owner/repo/actions/runs/12345/...
    link = check.get("link", "")
    if not link or "/actions/runs/" not in link:
        return result

    try:
        parts = link.split("/actions/runs/")
        if len(parts) < 2:
            return result
        run_id = parts[1].split("/")[0]

        # Fetch job details for this run
        code, stdout, _ = run_gh([
            "api", f"repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            "--jq", ".jobs[] | select(.conclusion == \"failure\") | {name: .name, steps: [.steps[] | select(.conclusion == \"failure\") | {name: .name, conclusion: .conclusion}]}"
        ])

        if code == 0 and stdout.strip():
            # Parse each failed job (one JSON object per line)
            for line in stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    job_data = json.loads(line)
                    job_name = job_data.get("name", "Unknown Job")
                    failed_steps = job_data.get("steps", [])

                    if failed_steps:
                        step_names = [s.get("name", "Unknown") for s in failed_steps]
                        result["failures"].append({
                            "job": job_name,
                            "steps": step_names
                        })
                except json.JSONDecodeError:
                    continue

    except Exception:
        # If we fail to parse or fetch, just return what we have
        pass

    return result


def get_bot_comments(owner: str, repo: str, pr_number: int) -> dict:
    """Get inline bot comments with zero replies from the PR using prc CLI."""
    # Use prc list to get inline bot comments with no replies (prevents duplicate handling)
    result = subprocess.run(
        ["prc", "list", str(pr_number), "--bots-only", "--inline-only", "--max-replies", "0"],
        capture_output=True,
        text=True,
        check=False
    )

    if result.returncode != 0:
        return {"comments": [], "error": result.stderr}

    try:
        data = json.loads(result.stdout)
        if "error" in data:
            return {"comments": [], "error": data["error"]}

        return data  # prc returns {"comments": [...], "rate_limit": {...}}
    except json.JSONDecodeError:
        return {"comments": [], "error": "Failed to parse prc output"}


def has_unaddressed_bot_comments(owner: str, repo: str, pr_number: int) -> bool:
    """Check if there are unaddressed bot comments (unresolved threads without smithers replies).

    Uses prc to check for actionable bot comments.
    """
    bot_comments = get_bot_comments(owner, repo, pr_number)
    return count_actionable_bot_comments(bot_comments) > 0


def count_actionable_bot_comments(bot_comments: dict) -> int:
    """Count actionable inline bot comments with zero replies.

    Uses prc with --max-replies 0 to only get threads with no replies.
    This automatically excludes threads where anyone (including smithers) has replied.

    Filters out:
    - Informational bots (linear-app, terraform-bot, github-actions, argocd, codecov, dependabot)
    - Already resolved review threads

    Returns count of inline bot comments that need action/response.
    """
    # Informational bots that don't require action
    informational_bots = {
        "linear-app[bot]",
        "linear-app",
        "terraform-bot",
        "github-actions[bot]",
        "github-actions",
        "argocd-bot",
        "argocd",
        "codecov[bot]",
        "codecov",
        "dependabot[bot]",
        "dependabot",
    }

    comments = bot_comments.get("comments", [])
    actionable_count = 0

    for comment in comments:
        author = comment.get("author", "").lower()

        # Skip informational bots
        if author in informational_bots:
            continue

        # Skip resolved threads
        if comment.get("is_resolved") is True:
            continue

        # prc --max-replies 0 already filtered out threads with replies
        # and --inline-only filtered out PR-level comments
        actionable_count += 1

    return actionable_count


def has_merge_conflicts(pr_number: int) -> bool:
    """Check if PR has merge conflicts."""
    code, stdout, _ = run_gh([
        "pr", "view", str(pr_number),
        "--json", "mergeable,mergeStateStatus"
    ])
    if code != 0:
        return False

    try:
        data = json.loads(stdout)
        mergeable = data.get("mergeable", "").upper()
        state = data.get("mergeStateStatus", "").upper()
        return mergeable == "CONFLICTING" or state == "DIRTY"
    except json.JSONDecodeError:
        return False


def get_pr_info(pr_number: int) -> dict:
    """Get PR title, branch, state, etc."""
    code, stdout, _ = run_gh([
        "pr", "view", str(pr_number),
        "--json", "title,headRefName,baseRefName,body,url,state,isDraft,reviewDecision,commits"
    ])
    if code != 0:
        return {}
    try:
        data = json.loads(stdout)
        # Count commits and approvals
        commits = data.get("commits", [])
        data["commit_count"] = len(commits)

        # Parse reviewDecision for approval count
        review_decision = data.get("reviewDecision", "")
        # reviewDecision values: APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED
        data["is_approved"] = review_decision == "APPROVED"

        return data
    except json.JSONDecodeError:
        return {}


def get_branch_comparison(owner: str, repo: str, base: str, head: str) -> dict:
    """Get branch comparison to determine if PR is behind base branch."""
    try:
        code, stdout, _ = run_gh([
            "api", f"repos/{owner}/{repo}/compare/{base}...{head}",
            "--jq", "{ahead_by: .ahead_by, behind_by: .behind_by, status: .status}"
        ])
        if code == 0 and stdout.strip():
            return json.loads(stdout)
    except (json.JSONDecodeError, Exception):
        pass
    return {"ahead_by": 0, "behind_by": 0, "status": "unknown"}


def get_cancelled_checks(checks: list) -> list:
    """Get checks that were cancelled."""
    cancelled = []
    for check in checks:
        bucket = check.get("bucket", "").lower()
        if bucket in ["cancel", "cancelled", "skipping"]:
            cancelled.append(check)
    return cancelled


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed time as 'Xm Ys' or 'Xs'."""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes}m {remaining_seconds}s"


def truncate_title(title: str, max_width: int = 60) -> str:
    """Truncate title to max display width with ellipsis.

    Args:
        title: The title string to truncate
        max_width: Maximum display width in terminal columns

    Returns:
        Title truncated to fit within max_width, with ellipsis if needed
    """
    display_width = wcswidth(title)
    if display_width < 0:  # Control characters or invalid
        display_width = len(title)

    if display_width <= max_width:
        return title

    # Binary search to find the right truncation point
    # We need to account for the ellipsis (3 characters = 3 display width)
    target_width = max_width - 3
    left, right = 0, len(title)

    while left < right:
        mid = (left + right + 1) // 2
        test_str = title[:mid]
        test_width = wcswidth(test_str)
        if test_width < 0:
            test_width = mid

        if test_width <= target_width:
            left = mid
        else:
            right = mid - 1

    return title[:left] + "..."


def ljust_display(text: str, width: int) -> str:
    """
    Left-justify text by display width, not character count.

    Handles emoji and CJK characters that display as 2 terminal columns
    but count as 1 character in Python strings.

    Args:
        text: The text to pad
        width: The desired display width in terminal columns

    Returns:
        The text padded with spaces to the specified display width
    """
    display_len = wcswidth(text)
    if display_len < 0:  # Control characters or invalid
        display_len = len(text)
    padding = width - display_len
    return text + ' ' * padding if padding > 0 else text


def format_status_card(
    status_emoji: str,
    status_message: str,
    pr_number: int,
    pr_url: str,
    pr_info: dict,
    owner: str,
    repo: str,
    cycles: int,
    elapsed_seconds: float,
    checks: list = None,
    bot_comments: dict = None
) -> str:
    """Format a rich card-like status display for smithers completion.

    Args:
        status_emoji: Emoji for the header (e.g., "✅", "🟡", "❌")
        status_message: Status message for the header
        pr_number: PR number
        pr_url: Full PR URL
        pr_info: PR metadata from get_pr_info()
        owner: Repository owner
        repo: Repository name
        cycles: Number of cycles completed
        elapsed_seconds: Total elapsed time in seconds
        checks: List of check results (optional)
        bot_comments: Bot comment data from get_bot_comments() (optional)

    Returns:
        Formatted card string with all relevant PR status information
    """
    # Extract PR metadata
    raw_title = pr_info.get("title", "Unknown PR")
    is_draft = pr_info.get("isDraft", False)
    commit_count = pr_info.get("commit_count", 0)
    is_approved = pr_info.get("is_approved", False)
    base_branch = pr_info.get("baseRefName", "main")
    head_branch = pr_info.get("headRefName", "unknown")

    # Get branch comparison
    comparison = get_branch_comparison(owner, repo, base_branch, head_branch)
    behind_by = comparison.get("behind_by", 0)

    # Determine PR status
    if is_draft:
        pr_status = "Draft"
    else:
        pr_status = "Ready"

    # Format approval status
    if is_approved:
        approval_str = "✓ Approved"
    else:
        approval_str = "🟡 Not approved"

    # Format branch status
    if behind_by > 0:
        branch_str = f"🟡 {behind_by} commit{'s' if behind_by != 1 else ''} behind {base_branch}"
    else:
        branch_str = f"✓ Up to date with {base_branch}"

    # Format elapsed time
    elapsed_str = format_elapsed_time(elapsed_seconds)

    # Calculate minimum card width based on URL length
    # Link line format: "│ 🔗 {url} │"
    # 🔗 emoji has display width of 2
    link_emoji_width = 2
    url_display_width = wcswidth(pr_url)
    if url_display_width < 0:
        url_display_width = len(pr_url)
    # Minimum width = left border (2) + emoji (2) + space (1) + url + right padding (1) + right border (1)
    min_width_for_link = 2 + link_emoji_width + 1 + url_display_width + 1 + 1

    # Use larger of: default 60 or minimum width needed for link
    card_width = max(60, min_width_for_link)

    # Now truncate title to fit within card width
    # Title line format: "│ #{number}: {title} │"
    title_prefix = f"#{pr_number}: "
    title_prefix_width = wcswidth(title_prefix)
    if title_prefix_width < 0:
        title_prefix_width = len(title_prefix)
    # Available width = card_width - left border (2) - right padding (1) - right border (1) - prefix
    available_title_width = card_width - 2 - 1 - 1 - title_prefix_width
    title = truncate_title(raw_title, available_title_width)

    # Build card with guaranteed right padding
    # ljust_display pads to (card_width - 2) to ensure 1 space before right border
    card = []
    card.append("╭" + "─" * (card_width - 2) + "╮")
    card.append(ljust_display(f"│ {status_emoji} {status_message}", card_width - 2) + " │")
    card.append("├" + "─" * (card_width - 2) + "┤")
    card.append(ljust_display(f"│ {title_prefix}{title}", card_width - 2) + " │")
    card.append(ljust_display(f"│ 🔗 {pr_url}", card_width - 2) + " │")
    card.append("├" + "─" * (card_width - 2) + "┤")
    card.append(ljust_display(f"│ Status: {pr_status} • {approval_str} • {commit_count} commit{'s' if commit_count != 1 else ''}", card_width - 2) + " │")
    card.append(ljust_display(f"│ Branch: {branch_str}", card_width - 2) + " │")
    card.append(ljust_display(f"│ Completed in {cycles} cycle{'s' if cycles != 1 else ''} ({elapsed_str})", card_width - 2) + " │")
    card.append("╰" + "─" * (card_width - 2) + "╯")

    result = "\n".join(card)

    # Add failed checks section if present
    if checks:
        failed_checks = get_failed_checks(checks)
        if failed_checks:
            result += f"\n\nFailed Checks ({len(failed_checks)}):"
            for check in failed_checks:
                name = check.get("name", "Unknown")
                link = check.get("link", "")
                result += f"\n  ❌ {name.ljust(20)} → {link}"

        # Add cancelled checks section if present
        cancelled_checks = get_cancelled_checks(checks)
        if cancelled_checks:
            result += f"\n\nCancelled Checks ({len(cancelled_checks)}):"
            for check in cancelled_checks:
                name = check.get("name", "Unknown")
                link = check.get("link", "")
                result += f"\n  ⚪ {name.ljust(20)} → {link}"

    # Add bot comments section if present
    if bot_comments:
        actionable_count = count_actionable_bot_comments(bot_comments)
        if actionable_count > 0:
            comments = bot_comments.get("comments", [])
            result += f"\n\nBot Comments ({actionable_count} unresolved):"
            for comment in comments[:3]:  # Show first 3
                author = comment.get("author", "Unknown")
                result += f"\n  • {author}"
            if actionable_count > 3:
                result += f"\n  • ... and {actionable_count - 3} more"

    return result


def audit_ralph_execution() -> None:
    """Audit Ralph's execution for prohibited command patterns.

    Post-execution security check that scans recent git commits for dangerous
    command patterns. Alerts user if prohibited operations detected.

    This provides defense-in-depth alongside:
    - Input sanitization (prevents prompt injection)
    - Prompt constraints (guides Ralph behavior)
    """
    import re

    # Prohibited command patterns (same as in safety constraints)
    prohibited_patterns = [
        r'kubectl\s+(apply|create|patch|delete|scale|exec|port-forward)',
        r'helm\s+(install|upgrade|uninstall)',
        r'terraform\s+(apply|destroy)',
        r'pulumi\s+(up|destroy)',
        r'aws\s+.*\s+(terminate|delete|modify)',
        r'gcloud\s+.*\s+(delete|update)',
        r'az\s+.*\s+(delete|update)',
        r'git\s+push\s+(-f|--force)',
        r'git\s+reset\s+--hard',
        r'sudo\s+',
        r'DROP\s+(DATABASE|TABLE)',
        r'DELETE\s+FROM\s+\w+\s*;',  # DELETE without WHERE
        r'TRUNCATE\s+TABLE',
    ]

    # Sensitive file patterns (detect credentials/secrets in commits)
    sensitive_file_patterns = [
        r'\.env',
        r'credentials\.json',
        r'secrets\.yaml',
        r'database\.yml',
        r'\.aws/credentials',
        r'\.kube/config',
        r'\.ssh/id_',
        r'[A-Z_]+_API_KEY\s*=',  # API_KEY=xxx patterns
        r'password\s*=\s*["\'][^"\']+["\']',  # password="xxx" patterns
    ]

    try:
        # Get commits from last 30 minutes (Ralph's execution window)
        result = subprocess.run(
            ["git", "log", "--since=30 minutes ago", "--format=%H|%s", "--"],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            return  # Git command failed, skip audit

        commits = result.stdout.strip().split('\n') if result.stdout.strip() else []
        violations = []

        for commit_line in commits:
            if not commit_line:
                continue

            commit_hash, commit_msg = commit_line.split('|', 1)

            # Check commit message for prohibited patterns
            for pattern in prohibited_patterns:
                if re.search(pattern, commit_msg, re.IGNORECASE):
                    violations.append(f"  🟡  {commit_hash[:7]}: {commit_msg[:80]}")
                    break

            # Check commit diff for prohibited patterns and sensitive files
            diff_result = subprocess.run(
                ["git", "show", "--format=", "--patch", "--name-only", commit_hash],
                capture_output=True,
                text=True,
                check=False
            )

            if diff_result.returncode == 0:
                # Check for prohibited commands
                for pattern in prohibited_patterns:
                    if re.search(pattern, diff_result.stdout, re.IGNORECASE):
                        violations.append(f"  🟡  {commit_hash[:7]}: Found prohibited command pattern in diff")
                        break

                # Check for sensitive files
                for pattern in sensitive_file_patterns:
                    if re.search(pattern, diff_result.stdout, re.IGNORECASE):
                        violations.append(f"  🔐 {commit_hash[:7]}: Potential sensitive file/credential detected")
                        break

        if violations:
            log("\n🚨 SECURITY ALERT: Prohibited command patterns detected in commits:")
            for violation in violations:
                log(violation)
            log("\n🟡  Please review these commits carefully. They may violate safety constraints.")
            log("    Run: git log --since=30 minutes ago --patch\n")

    except Exception as e:
        # Don't fail the whole process if audit fails
        log(f"🟡  Post-execution audit failed: {e}")


def sanitize_for_prompt(text: str, max_length: int = 2000) -> str:
    """Sanitize external content before injecting into LLM prompts.

    Prevents prompt injection attacks by:
    - Removing ANSI escape codes
    - HTML-escaping special characters
    - Neutralizing override keywords
    - Truncating safely to prevent context overflow

    Args:
        text: Raw text from external sources (PR titles, bot comments, etc.)
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


def generate_prompt(
    pr_url: str,
    pr_info: dict,
    failed_checks: list,
    bot_comments: dict,
    has_conflicts: bool,
    work_iteration: int,
    total_iterations: int
) -> str:
    """Generate a focused prompt for Ralph based on what issues were found."""
    sections = []

    # Header - sanitize all external content
    title = sanitize_for_prompt(pr_info.get("title", "Unknown"), max_length=200)
    head = sanitize_for_prompt(pr_info.get("headRefName", "Unknown"), max_length=100)
    base = sanitize_for_prompt(pr_info.get("baseRefName", "Unknown"), max_length=100)

    remaining = total_iterations - work_iteration
    sections.append(f"""# PR Watch Task

**PR:** {pr_url}
**Title:** {title}
**Branch:** {head} → {base}

## Iteration Context

This is iteration {work_iteration} of {total_iterations}. You have {remaining} more attempt(s) after this one.

## Your Mission

Fix the issues found in this PR, then exit. The CLI will re-check after you're done.

**IMPORTANT:** Use Ralph's built-in task system to track your work. Create tasks for each issue you're fixing.

## 🚨 CRITICAL SAFETY CONSTRAINTS

**You are running autonomously with elevated permissions. You MUST NEVER perform these operations:**

### Cluster & Infrastructure (PROHIBITED)
- ❌ Kubernetes: `kubectl apply/create/patch/delete/scale/exec/port-forward`
- ❌ Helm: `helm install/upgrade/uninstall`
- ❌ Terraform/IaC: `terraform apply/destroy`, `pulumi up/destroy`
- ❌ Cloud providers: EC2 terminate, RDS delete, S3 delete, autoscaling changes
- ✅ ALLOWED: Read-only operations (`kubectl get/describe/logs`, `terraform plan`)

### Secrets & IAM (PROHIBITED)
- ❌ Secrets: `aws secretsmanager put`, `vault write`, `kubectl create secret`
- ❌ IAM/RBAC: Role modifications, permission grants, access key changes
- ❌ Credentials: ANY operations on `~/.aws`, `~/.kube`, `~/.ssh`
- ❌ Sensitive files: NEVER read/commit `.env*`, `*.env`, `credentials.json`, `secrets.yaml`, `database.yml`, API keys
- 🟡 If you need config: Use non-sensitive examples, NOT real credentials
- ✅ ALLOWED: Read non-sensitive configuration (package.json, tsconfig.json, etc.)

### Databases (PROHIBITED)
- ❌ Schema changes: `DROP/ALTER/TRUNCATE/CREATE TABLE`
- ❌ Bulk operations: `DELETE FROM` or `UPDATE` without WHERE clause
- ✅ ALLOWED: `SELECT` queries, `SHOW/DESCRIBE` commands

### Git Operations (RESTRICTED)
- ❌ Force operations: `git push --force`, `git reset --hard`, `git clean -fd`
- ❌ Write outside git root: File operations must be within `$(git rev-parse --show-toplevel)`
- ✅ ALLOWED: Normal commits/pushes within current branch

### System Operations (PROHIBITED)
- ❌ Privilege escalation: `sudo`, privileged containers, `ssh` access
- ❌ Network operations: `iptables`, firewall changes, DNS modifications
- ❌ System modifications: `/etc`, `/usr`, `/var/lib` changes
- ❌ Process manipulation: `kill`, `systemctl` (except git/development processes)

### Pre-Flight Safety Pattern

Before ANY destructive operation:
1. **Verify scope**: Does this stay within the git repository?
2. **Check permissions**: Does this require elevated access?
3. **Use dry-run**: Try `--dry-run`, `terraform plan`, `git diff` first
4. **Ask yourself**: "Could this break production or leak data?"
5. **If unsure**: STOP and document the blocker in a task comment. DO NOT proceed.

### When to Exit Early

You have explicit permission to STOP and exit if:
- Required operation needs cluster/infrastructure writes
- Task requires modifying secrets or IAM
- Operation scope unclear or risky
- Any safety constraint would be violated

**Better to exit early than cause damage.** Document the blocker in your task system and exit.""")

    # Failed checks section
    if failed_checks:
        sections.append("\n## Failed Checks\n")
        for check in failed_checks:
            name = sanitize_for_prompt(check.get("name", "Unknown"), max_length=150)
            link = check.get("link", "")
            sections.append(f"- **{name}**: [View logs]({link})")
        sections.append("""
**Action:** Investigate each failure:
1. If the failure is caused by your changes: Fix the code, commit, and push
2. If the failure is unrelated to your changes (flaky test, transient issue, infrastructure problem):
   - Use `gh run rerun <run-id>` to rerun the workflow
   - Extract run-id from the workflow link (e.g., github.com/.../runs/12345 → run-id is 12345)
   - Then exit - the CLI will check again and the rerun will likely pass""")

    # Bot comments section - only show actionable inline comments
    actionable_count = count_actionable_bot_comments(bot_comments)
    all_comments = bot_comments.get("comments", [])

    # Filter for original thread comments only (not replies)
    thread_comments = [c for c in all_comments if c.get("in_reply_to_id") is None]
    total_bot_comments = len(thread_comments)

    if total_bot_comments > 0:
        sections.append(f"\n## Inline Bot Comments ({actionable_count} actionable, {total_bot_comments} total)\n")

        for comment in thread_comments:
            user = sanitize_for_prompt(comment.get("author", "Unknown"), max_length=50)
            body = sanitize_for_prompt(comment.get("body", ""), max_length=500)
            url = comment.get("url", "")
            path = sanitize_for_prompt(comment.get("path", ""), max_length=200)
            line = comment.get("line")
            thread_id = comment.get("thread_id", "")
            is_resolved = comment.get("is_resolved", False)
            reply_count = comment.get("reply_count", 0)

            resolved_str = " [RESOLVED]" if is_resolved else ""
            sections.append(
                f"\n**{user}** on `{path}:{line}` (thread: `{thread_id}`){resolved_str} ([link]({url})):\n```\n{body}\n```"
            )

            # Show reply count if there are replies
            if reply_count > 0:
                sections.append(f"  ↳ {reply_count} reply/replies")

        sections.append("""
**Recommended Tool:** Use `prc` CLI for efficient comment management:
- List unanswered bot comments: `prc list --bots-only --inline-only --max-replies 0`
- Reply to specific comment: `prc reply <comment-id> "your message"`
- Resolve discussion thread: `prc resolve <thread-id>`
- See full workflow: `/manage-pr-comments` skill

All operations use GraphQL and output machine-readable JSON.

**Action:** For EACH bot comment you must:
1. Fix the issue in code
2. Commit and push the fix
3. Reply to the comment thread: `prc reply <comment-id> "Fixed in commit <sha>: <explanation>"`
4. **MANDATORY:** Resolve the thread: `prc resolve <thread-id>`

**CRITICAL - Why Resolution Matters:**
- Smithers ONLY shows threads with ZERO replies
- Once you reply, the thread has 1+ replies
- If you DON'T resolve, smithers will show it again (but can't reply since it has replies)
- Resolution signals "this is handled, don't show it anymore"
- **Always resolve after replying** unless the thread requires further discussion (rare)""")

    # Merge conflicts section
    if has_conflicts:
        sections.append("""
## Merge Conflicts

This PR has merge conflicts that must be resolved.

**Action:**
1. Fetch latest from base branch
2. Resolve conflicts
3. Commit and push the resolution""")

    # Footer with acceptance criteria
    sections.append("""
## Acceptance Criteria - When to Exit

You MUST complete ALL of the following before exiting:

1. ✅ **All Failed Checks Fixed**:
   - Investigated root cause of EACH failure
   - Fixed the underlying code issue
   - Committed and pushed all fixes

2. ✅ **All Actionable Bot Comments Addressed**:
   - Evaluated EACH bot comment for actionability
   - Fixed code based on actionable feedback
   - Replied to comment threads with explanation + commit SHA
   - Committed and pushed all fixes

3. ✅ **All Merge Conflicts Resolved** (if present):
   - Fetched latest from base branch
   - Resolved ALL conflicts
   - Committed and pushed resolution

4. ✅ **All Changes Pushed to Remote**:
   - Zero pending local changes
   - All commits pushed to origin
   - Verify with `git status` before exiting

## How to Work

- **Use Ralph's task system** - Create tasks for each issue, track progress with `ralph tools task`
- **Delegate to sub-agents** - Use Ralph Coordinator patterns for investigation/fixes
- **Be thorough** - Don't skip issues or make partial fixes

## What NOT to Do

- ❌ Do NOT wait for CI checks to pass - smithers will re-check after you exit
- ❌ Do NOT try to verify check status yourself - that's smithers' job
- ❌ Do NOT loop or retry - fix once, push, exit. Smithers loops if needed.
- ❌ Do NOT exit if you have uncommitted or unpushed changes

**Exit immediately** after completing the acceptance criteria above. Smithers will re-check the PR and invoke you again if more work is needed.""")

    return "\n".join(sections)


def work_needed(failed_checks: list, has_conflicts: bool, owner: str, repo: str, pr_number: int) -> bool:
    """Determine if there's work for Ralph to do.

    Invokes Ralph when:
    - CI checks failed
    - Merge conflicts exist
    - Unaddressed inline bot comments exist
    """
    if failed_checks:
        return True
    if has_conflicts:
        return True
    if has_unaddressed_bot_comments(owner, repo, pr_number):
        return True
    return False


def wait_for_checks(pr_number: int) -> list:
    """Wait for all checks to reach terminal state, return the checks."""
    log("Waiting for CI checks to complete...")

    while True:
        status = get_check_status(pr_number)
        checks = status.get("checks", [])

        if not checks:
            log("No checks found, continuing...")
            return []

        terminal_count = sum(1 for c in checks if check_is_terminal(c))
        total = len(checks)

        if all_checks_terminal(checks):
            log(f"All {total} checks complete")
            return checks

        running_checks = [c["name"] for c in checks if not check_is_terminal(c)]
        running_str = ", ".join(running_checks[:3])
        if len(running_checks) > 3:
            running_str += "..."
        log(f"Checks: {terminal_count}/{total} complete. Waiting: {running_str}")
        time.sleep(POLL_INTERVAL)


def main():
    """Main entry point."""
    start_time = time.time()  # Track elapsed time

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Watch and manage a GitHub PR",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "pr",
        nargs="?",
        default=None,
        help="PR number, URL, or omit to infer from current branch"
    )
    parser.add_argument(
        "--max-ralph-iterations",
        type=int,
        default=None,
        help=f"Max Ralph invocations (default: {DEFAULT_MAX_RALPH_INVOCATIONS}). Override with SMITHERS_MAX_RALPH_ITERATIONS env var"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=f"Max watch loop cycles (default: {DEFAULT_MAX_CYCLES}). Override with SMITHERS_MAX_ITERATIONS env var"
    )

    args = parser.parse_args()

    # Determine max iterations: CLI flag > env var > default
    max_ralph_invocations = args.max_ralph_iterations
    if max_ralph_invocations is None:
        try:
            max_ralph_invocations = int(os.environ.get("SMITHERS_MAX_RALPH_ITERATIONS", DEFAULT_MAX_RALPH_INVOCATIONS))
        except ValueError:
            print(
                f"Error: SMITHERS_MAX_RALPH_ITERATIONS environment variable must be a valid integer. "
                f"Got: '{os.environ.get('SMITHERS_MAX_RALPH_ITERATIONS')}'",
                file=sys.stderr
            )
            sys.exit(1)

    max_cycles = args.max_iterations
    if max_cycles is None:
        try:
            max_cycles = int(os.environ.get("SMITHERS_MAX_ITERATIONS", DEFAULT_MAX_CYCLES))
        except ValueError:
            print(
                f"Error: SMITHERS_MAX_ITERATIONS environment variable must be a valid integer. "
                f"Got: '{os.environ.get('SMITHERS_MAX_ITERATIONS')}'",
                file=sys.stderr
            )
            sys.exit(1)

    # Validate positive integers
    if max_ralph_invocations < 1:
        print("Error: max-ralph-iterations must be a positive integer", file=sys.stderr)
        sys.exit(1)
    if max_cycles < 1:
        print("Error: max-iterations must be a positive integer", file=sys.stderr)
        sys.exit(1)

    pr_url = get_pr_url(args.pr)
    owner, repo, pr_number = parse_pr_url(pr_url)

    log(f"🔍 Watching PR #{pr_number}: {pr_url}")
    log(f"Poll interval: {POLL_INTERVAL}s | Max cycles: {max_cycles}")

    ralph_invocation_count = 0
    current_cycle = 0  # Track which cycle we're on
    try:
        for cycle in range(1, max_cycles + 1):
            current_cycle = cycle
            ralph_invoked = main_loop_iteration(
                cycle, ralph_invocation_count, pr_number, pr_url, owner, repo,
                max_ralph_invocations, max_cycles, start_time
            )
            if ralph_invoked:
                ralph_invocation_count += 1

        # Check for cycle extension if unaddressed bot comments exist
        if has_unaddressed_bot_comments(owner, repo, pr_number):
            log("📝 Unaddressed bot comments detected - extending by ONE cycle")
            current_cycle = max_cycles + 1
            ralph_invoked = main_loop_iteration(
                max_cycles + 1, ralph_invocation_count, pr_number, pr_url, owner, repo,
                max_ralph_invocations, max_cycles + 1, start_time
            )
            if ralph_invoked:
                ralph_invocation_count += 1
    except KeyboardInterrupt:
        # Calculate elapsed time
        elapsed = time.time() - start_time

        # Get PR info and checks for card display
        pr_info = get_pr_info(pr_number)
        status = get_check_status(pr_number)
        checks = status.get("checks", [])
        bot_comments = get_bot_comments(owner, repo, pr_number)

        # Display status card
        print("\n" + format_status_card(
            "🟡", "Interrupted by User",
            pr_number, pr_url, pr_info, owner, repo,
            current_cycle, elapsed, checks, bot_comments
        ))

        send_notification(
            "Smithers Interrupted",
            f"PR #{pr_number} watch interrupted by user",
            "Basso"
        )
        return 130  # Standard exit code for SIGINT

    # Calculate elapsed time for max cycles exit
    elapsed = time.time() - start_time

    # Get final PR info and checks
    pr_info = get_pr_info(pr_number)
    status = get_check_status(pr_number)
    checks = status.get("checks", [])
    bot_comments = get_bot_comments(owner, repo, pr_number)

    # Display status card for max cycles
    print("\n" + format_status_card(
        "🟡", "Max Cycles Reached",
        pr_number, pr_url, pr_info, owner, repo,
        max_cycles, elapsed, checks, bot_comments
    ))

    send_notification(
        "Smithers Max Cycles",
        f"PR #{pr_number} reached {max_cycles} cycles without being ready",
        "Sosumi"
    )
    return 1


def main_loop_iteration(
    cycle: int,
    ralph_invocation_count: int,
    pr_number: int,
    pr_url: str,
    owner: str,
    repo: str,
    max_ralph_invocations: int,
    max_cycles: int,
    start_time: float
) -> bool:
    """Single iteration of the main watch loop.

    Returns True if Ralph was invoked, False otherwise.
    """
    log(f"━━━ Cycle {cycle}/{max_cycles} ━━━")

    # 1. Check if PR is already merged
    pr_info = get_pr_info(pr_number)
    pr_state = pr_info.get("state", "").upper()

    if pr_state == "MERGED":
        elapsed = time.time() - start_time
        status = get_check_status(pr_number)
        checks = status.get("checks", [])
        bot_comments = get_bot_comments(owner, repo, pr_number)

        print("\n" + format_status_card(
            "✅", "PR Already Merged",
            pr_number, pr_url, pr_info, owner, repo,
            cycle, elapsed, checks, bot_comments
        ))

        send_notification(
            "Smithers Complete",
            f"PR #{pr_number} is already merged",
            "Glass"
        )
        sys.exit(0)

    # 2. Wait for checks to complete
    checks = wait_for_checks(pr_number)

    # 3. Gather intelligence
    failed_checks = get_failed_checks(checks)
    bot_comments = get_bot_comments(owner, repo, pr_number)
    conflicts = has_merge_conflicts(pr_number)

    # 4. Report status
    actionable_bot = count_actionable_bot_comments(bot_comments)
    conflict_str = "conflicts" if conflicts else "no conflicts"
    log(
        f"Status: {len(failed_checks)} failed checks | "
        f"{actionable_bot} actionable bot comments | {conflict_str}"
    )

    # 4.5. Early exit if nothing is actionable yet
    # Safety check: If checks exist but all are pending, and no other actionable work
    # This handles edge cases where wait_for_checks might return early
    if checks:
        pending_checks = [c for c in checks if not check_is_terminal(c)]
        all_pending = len(pending_checks) == len(checks)

        # Only exit early if NO actionable work exists
        # Bot comments with pending checks = can work on comments while waiting
        # Failed checks or conflicts = must wait for terminal state first
        if all_pending and not failed_checks and not conflicts and actionable_bot == 0:
            log("⏳ No actionable work yet. All workflows pending. Continuing watch loop...")
            return False  # Don't invoke Ralph, CLI continues polling

    # 5. Check if work needed
    if not work_needed(failed_checks, conflicts, owner, repo, pr_number):
        elapsed = time.time() - start_time

        print("\n" + format_status_card(
            "✅", "PR Ready to Merge",
            pr_number, pr_url, pr_info, owner, repo,
            cycle, elapsed, checks, bot_comments
        ))

        # Send macOS notification
        send_notification(
            "Smithers Complete",
            f"PR #{pr_number} is ready to merge!\nCompleted in {cycle} cycle(s)",
            "Glass"
        )
        sys.exit(0)

    # 6. Handle final cycle - show errors but don't invoke Ralph
    if cycle == max_cycles:
        elapsed = time.time() - start_time

        log("🟡 Final cycle reached with unresolved issues")

        # Show detailed failure information for each failed check
        if failed_checks:
            log(f"\nFailed checks: {len(failed_checks)}")
            for check in failed_checks:
                check_name = check.get("name", "Unknown")
                log(f"\n  ❌ {check_name}")

                # Fetch detailed failure information
                details = get_workflow_failure_details(owner, repo, check)
                link = details.get("link")
                if link:
                    log(f"     Link: {link}")

                failures = details.get("failures", [])
                if failures:
                    log("     Failed jobs/steps:")
                    for failure in failures:
                        job = failure.get("job", "Unknown")
                        steps = failure.get("steps", [])
                        log(f"       • {job}")
                        for step in steps:
                            log(f"         - {step}")
                else:
                    log("     No detailed failure information available")

        if conflicts:
            log("\n  ❌ Merge conflicts detected")

        # Display status card
        print("\n" + format_status_card(
            "❌", "Max Ralph Invocations Reached",
            pr_number, pr_url, pr_info, owner, repo,
            cycle, elapsed, checks, bot_comments
        ))

        send_notification(
            "Smithers Max Iterations",
            f"PR #{pr_number} has unresolved issues after {max_ralph_invocations} attempts",
            "Sosumi"
        )
        sys.exit(1)

    # 7. Calculate work iteration based on Ralph invocations (not smithers cycles)
    # Ralph is invoked up to max_ralph_invocations times
    work_iteration = ralph_invocation_count + 1
    total_iterations = max_ralph_invocations

    # 8. Generate prompt and invoke Ralph
    log("📝 Generating prompt for Ralph...")
    prompt = generate_prompt(
        pr_url, pr_info, failed_checks, bot_comments, conflicts,
        work_iteration, total_iterations
    )

    # Write to temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        prefix="smithers-prompt-",
        dir="/tmp",
        delete=False
    ) as f:
        f.write(prompt)
        prompt_file = f.name

    # Prepare environment with Ralph configuration
    env = os.environ.copy()
    env["BURNS_MAX_RALPH_ITERATIONS"] = str(max_ralph_invocations)

    log(f"🚀 Invoking Ralph (iteration {work_iteration}/{total_iterations}): burns {prompt_file}")
    try:
        # Run burns with the prompt file
        # Use Popen with process group for proper signal handling
        # This ensures all child processes (Ralph and its subprocesses) get signals
        process = subprocess.Popen(
            ["burns", prompt_file],
            env=env,
            start_new_session=True  # Create new process group
        )
        try:
            result = process.wait(timeout=3600)  # 60-minute timeout
            if result != 0:
                log(f"🟡 Ralph exited with code {result}")
        except subprocess.TimeoutExpired:
            log("🟡 Ralph timed out after 60 minutes, killing process tree...")
            kill_process_tree(process.pid)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass  # Already killed
            log("✓ Ralph terminated due to timeout")
            # Don't raise - continue to next cycle for potential recovery
        except KeyboardInterrupt:
            log("🟡 Received Ctrl+C, killing Ralph and all subprocesses...")
            # Use recursive tree killer since killpg() doesn't work
            # (processes escape via setsid() but maintain PPID relationship)
            kill_process_tree(process.pid)
            try:
                # Wait for cleanup (should be quick since we SIGKILL'd)
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass  # Already killed, just cleanup
            log("✓ Ralph terminated")
            raise  # Re-raise to exit smithers
    finally:
        # Clean up prompt file
        try:
            os.unlink(prompt_file)
        except OSError:
            pass

    log("Ralph finished, re-checking PR status...")

    # Post-execution security audit
    audit_ralph_execution()

    # Small delay before re-checking to let GitHub update
    time.sleep(5)
    return True  # Indicate Ralph was invoked


if __name__ == "__main__":
    sys.exit(main())
