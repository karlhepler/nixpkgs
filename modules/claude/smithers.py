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
    --max-ralph-iterations N    Max Ralph invocations (default: 3)
                                Can also set via SMITHERS_MAX_RALPH_ITERATIONS env var
    --max-iterations N          Max watch loop cycles (default: 4)
                                Can also set via SMITHERS_MAX_ITERATIONS env var
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

# Constants
POLL_INTERVAL = 10  # seconds
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
    """Get all bot comments from the PR."""
    comments = {"issue_comments": [], "review_comments": [], "reviews": []}

    # Issue comments (PR conversation)
    code, stdout, _ = run_gh([
        "api", f"repos/{owner}/{repo}/issues/{pr_number}/comments",
        "--jq", '[.[] | select(.user.login | test("\\\\[bot\\\\]|bot$"; "i"))]'
    ])
    if code == 0 and stdout.strip():
        try:
            comments["issue_comments"] = json.loads(stdout)
        except json.JSONDecodeError:
            pass

    # Inline review comments
    code, stdout, _ = run_gh([
        "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
        "--jq", '[.[] | select(.user.login | test("\\\\[bot\\\\]|bot$"; "i"))]'
    ])
    if code == 0 and stdout.strip():
        try:
            comments["review_comments"] = json.loads(stdout)
        except json.JSONDecodeError:
            pass

    # Reviews
    code, stdout, _ = run_gh([
        "api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        "--jq", '[.[] | select(.user.login | test("\\\\[bot\\\\]|bot$"; "i"))]'
    ])
    if code == 0 and stdout.strip():
        try:
            comments["reviews"] = json.loads(stdout)
        except json.JSONDecodeError:
            pass

    return comments


def has_unaddressed_bot_comments(owner: str, repo: str, pr_number: int) -> bool:
    """Check if there are unaddressed bot comments (with zero replies).

    Only checks review_comments (inline) and reviews.
    Returns True if any bot comment exists with no replies.
    """
    # Check inline review comments for replies
    code, stdout, _ = run_gh([
        "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
        "--jq", '[.[] | select(.user.login | test("\\\\[bot\\\\]|bot$"; "i")) | select(.in_reply_to_id == null or .in_reply_to_id == 0)]'
    ])
    if code == 0 and stdout.strip() and stdout.strip() != "[]":
        try:
            comments = json.loads(stdout)
            if len(comments) > 0:
                return True
        except json.JSONDecodeError:
            pass

    return False


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
        "--json", "title,headRefName,baseRefName,body,url,state"
    ])
    if code != 0:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


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

    # Header
    title = pr_info.get("title", "Unknown")
    head = pr_info.get("headRefName", "Unknown")
    base = pr_info.get("baseRefName", "Unknown")

    remaining = total_iterations - work_iteration
    sections.append(f"""# PR Watch Task

**PR:** {pr_url}
**Title:** {title}
**Branch:** {head} → {base}

## Iteration Context

This is iteration {work_iteration} of {total_iterations}. You have {remaining} more attempt(s) after this one.

## Your Mission

Fix the issues found in this PR, then exit. The CLI will re-check after you're done.

**IMPORTANT:** Use kanban to track your work. Create cards for each issue you're fixing.""")

    # Failed checks section
    if failed_checks:
        sections.append("\n## Failed Checks\n")
        for check in failed_checks:
            name = check.get("name", "Unknown")
            link = check.get("link", "")
            sections.append(f"- **{name}**: [View logs]({link})")
        sections.append("""
**Action:** Investigate each failure:
1. If the failure is caused by your changes: Fix the code, commit, and push
2. If the failure is unrelated to your changes (flaky test, transient issue, infrastructure problem):
   - Use `gh run rerun <run-id>` to rerun the workflow
   - Extract run-id from the workflow link (e.g., github.com/.../runs/12345 → run-id is 12345)
   - Then exit - the CLI will check again and the rerun will likely pass""")

    # Bot comments section
    total_bot_comments = (
        len(bot_comments.get("issue_comments", [])) +
        len(bot_comments.get("review_comments", [])) +
        len(bot_comments.get("reviews", []))
    )

    if total_bot_comments > 0:
        sections.append(f"\n## Bot Comments ({total_bot_comments} total)\n")

        if bot_comments.get("issue_comments"):
            sections.append("### PR Conversation Comments")
            for comment in bot_comments["issue_comments"]:
                user = comment.get("user", {}).get("login", "Unknown")
                body = comment.get("body", "")[:500]
                url = comment.get("html_url", "")
                sections.append(
                    f"\n**{user}** ([link]({url})):\n```\n{body}\n```"
                )

        if bot_comments.get("review_comments"):
            sections.append("\n### Inline Code Review Comments")
            for comment in bot_comments["review_comments"]:
                user = comment.get("user", {}).get("login", "Unknown")
                body = comment.get("body", "")[:500]
                path = comment.get("path", "")
                url = comment.get("html_url", "")
                sections.append(
                    f"\n**{user}** on `{path}` ([link]({url})):\n```\n{body}\n```"
                )

        if bot_comments.get("reviews"):
            sections.append("\n### Reviews")
            for review in bot_comments["reviews"]:
                user = review.get("user", {}).get("login", "Unknown")
                body = review.get("body", "")[:500] if review.get("body") else "(no body)"
                state = review.get("state", "")
                url = review.get("html_url", "")
                sections.append(
                    f"\n**{user}** ({state}) ([link]({url})):\n```\n{body}\n```"
                )

        sections.append("""
**Recommended Tool:** Use `prc` CLI for efficient comment management:
- List unanswered bot comments: `prc list --bots-only --max-replies 0`
- Reply to specific comment: `prc reply <comment-id> "your message"`
- Resolve discussion thread: `prc resolve <thread-id>`
- See full workflow: `/manage-pr-comments` skill

All operations use GraphQL and output machine-readable JSON.

**Action:** Evaluate each bot comment. For actionable feedback:
1. Fix the issue in code
2. Commit and push
3. Reply to the comment thread explaining what you did""")

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

- **Use kanban** - Create cards for each issue, track progress
- **Delegate to sub-agents** - Use Staff Engineer patterns for investigation/fixes
- **Be thorough** - Don't skip issues or make partial fixes

## What NOT to Do

- ❌ Do NOT wait for CI checks to pass - smithers will re-check after you exit
- ❌ Do NOT try to verify check status yourself - that's smithers' job
- ❌ Do NOT loop or retry - fix once, push, exit. Smithers loops if needed.
- ❌ Do NOT exit if you have uncommitted or unpushed changes

**Exit immediately** after completing the acceptance criteria above. Smithers will re-check the PR and invoke you again if more work is needed.""")

    return "\n".join(sections)


def work_needed(failed_checks: list, bot_comments: dict, has_conflicts: bool) -> bool:
    """Determine if there's work for Ralph to do."""
    # Only invoke Ralph for failed checks or merge conflicts
    # Bot comments are informational and don't require automated fixes
    if failed_checks:
        return True
    if has_conflicts:
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
        help=f"Max Ralph invocations (default: {DEFAULT_MAX_RALPH_INVOCATIONS}, or SMITHERS_MAX_RALPH_ITERATIONS env var)"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=f"Max watch loop cycles (default: {DEFAULT_MAX_CYCLES}, or SMITHERS_MAX_ITERATIONS env var)"
    )

    args = parser.parse_args()

    # Determine max iterations: CLI flag > env var > default
    max_ralph_invocations = args.max_ralph_iterations
    if max_ralph_invocations is None:
        max_ralph_invocations = int(os.environ.get("SMITHERS_MAX_RALPH_ITERATIONS", DEFAULT_MAX_RALPH_INVOCATIONS))

    max_cycles = args.max_iterations
    if max_cycles is None:
        max_cycles = int(os.environ.get("SMITHERS_MAX_ITERATIONS", DEFAULT_MAX_CYCLES))

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
    try:
        for cycle in range(1, max_cycles + 1):
            ralph_invoked = main_loop_iteration(
                cycle, ralph_invocation_count, pr_number, pr_url, owner, repo,
                max_ralph_invocations, max_cycles
            )
            if ralph_invoked:
                ralph_invocation_count += 1

        # Check for cycle extension if unaddressed bot comments exist
        if has_unaddressed_bot_comments(owner, repo, pr_number):
            log("📝 Unaddressed bot comments detected - extending by ONE cycle")
            ralph_invoked = main_loop_iteration(
                max_cycles + 1, ralph_invocation_count, pr_number, pr_url, owner, repo,
                max_ralph_invocations, max_cycles + 1
            )
            if ralph_invoked:
                ralph_invocation_count += 1
    except KeyboardInterrupt:
        log("\n⚠️ Interrupted by user")
        send_notification(
            "Smithers Interrupted",
            f"PR #{pr_number} watch interrupted by user",
            "Basso"
        )
        return 130  # Standard exit code for SIGINT

    log(f"⚠️ Reached max cycles ({max_cycles}) without PR being ready")
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
    max_cycles: int
) -> bool:
    """Single iteration of the main watch loop.

    Returns True if Ralph was invoked, False otherwise.
    """
    log(f"━━━ Cycle {cycle}/{max_cycles} ━━━")

    # 1. Check if PR is already merged
    pr_info = get_pr_info(pr_number)
    pr_state = pr_info.get("state", "").upper()

    if pr_state == "MERGED":
        log("✅ PR is already merged!")
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
    total_bot = (
        len(bot_comments.get("issue_comments", [])) +
        len(bot_comments.get("review_comments", [])) +
        len(bot_comments.get("reviews", []))
    )
    conflict_str = "conflicts" if conflicts else "no conflicts"
    log(
        f"Status: {len(failed_checks)} failed checks | "
        f"{total_bot} bot comments | {conflict_str}"
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
        if all_pending and not failed_checks and not conflicts and total_bot == 0:
            log("⏳ No actionable work yet. All workflows pending. Continuing watch loop...")
            return False  # Don't invoke Ralph, CLI continues polling

    # 5. Check if work needed
    if not work_needed(failed_checks, bot_comments, conflicts):
        log("✅ PR is completely ready to merge!")
        log(f"Completed in {cycle} cycle(s)")
        # Send macOS notification
        send_notification(
            "Smithers Complete",
            f"PR #{pr_number} is ready to merge!\nCompleted in {cycle} cycle(s)",
            "Glass"
        )
        sys.exit(0)

    # 6. Handle final cycle - show errors but don't invoke Ralph
    if cycle == max_cycles:
        log("⚠️ Final cycle reached with unresolved issues")
        log(f"\nFailed checks: {len(failed_checks)}")

        # Show detailed failure information for each failed check
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

        log(f"\n❌ Could not resolve all issues after {max_ralph_invocations} Ralph invocation(s)")
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
    env["KANBAN_SESSION"] = f"smithers-pr-{pr_number}"

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
                log(f"⚠️ Ralph exited with code {result}")
        except subprocess.TimeoutExpired:
            log("⚠️ Ralph timed out after 60 minutes, killing process tree...")
            kill_process_tree(process.pid)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass  # Already killed
            log("✓ Ralph terminated due to timeout")
            # Don't raise - continue to next cycle for potential recovery
        except KeyboardInterrupt:
            log("⚠️ Received Ctrl+C, killing Ralph and all subprocesses...")
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
    # Small delay before re-checking to let GitHub update
    time.sleep(5)
    return True  # Indicate Ralph was invoked


if __name__ == "__main__":
    sys.exit(main())
