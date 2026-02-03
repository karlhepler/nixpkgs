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
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime

# Constants
POLL_INTERVAL = 10  # seconds
MAX_CYCLES = 100
TERMINAL_STATES = {
    "pass", "fail", "skipping", "cancelled",
    "success", "failure", "skipped", "neutral", "stale",
    "action_required", "timed_out"  # Don't forget these terminal states
}


def log(msg: str):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


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
    """Get PR title, branch, etc."""
    code, stdout, _ = run_gh([
        "pr", "view", str(pr_number),
        "--json", "title,headRefName,baseRefName,body,url"
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
    has_conflicts: bool
) -> str:
    """Generate a focused prompt for Ralph based on what issues were found."""
    sections = []

    # Header
    title = pr_info.get("title", "Unknown")
    head = pr_info.get("headRefName", "Unknown")
    base = pr_info.get("baseRefName", "Unknown")

    sections.append(f"""# PR Watch Task

**PR:** {pr_url}
**Title:** {title}
**Branch:** {head} → {base}

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
        sections.append(
            "\n**Action:** Investigate each failure, fix the code, "
            "commit, and push."
        )

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

    # Footer with instructions
    sections.append("""
## Instructions

1. **Use kanban** - Create cards for each issue, track progress
2. **Use Staff Engineer patterns** - Delegate to sub-agents for investigation/fixes
3. **Be thorough** - Fix all issues before exiting
4. **Exit when done** - Don't loop forever, the CLI will re-check

When you've addressed all issues above, complete your work and exit.""")

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
    pr_arg = sys.argv[1] if len(sys.argv) > 1 else None
    pr_url = get_pr_url(pr_arg)
    owner, repo, pr_number = parse_pr_url(pr_url)

    log(f"🔍 Watching PR #{pr_number}: {pr_url}")
    log(f"Poll interval: {POLL_INTERVAL}s | Max cycles: {MAX_CYCLES}")

    for cycle in range(1, MAX_CYCLES + 1):
        log(f"━━━ Cycle {cycle}/{MAX_CYCLES} ━━━")

        # 1. Wait for checks to complete
        checks = wait_for_checks(pr_number)

        # 2. Gather intelligence
        failed_checks = get_failed_checks(checks)
        bot_comments = get_bot_comments(owner, repo, pr_number)
        conflicts = has_merge_conflicts(pr_number)
        pr_info = get_pr_info(pr_number)

        # 3. Report status
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

        # 4. Check if work needed
        if not work_needed(failed_checks, bot_comments, conflicts):
            log("✅ PR is completely ready to merge!")
            log(f"Completed in {cycle} cycle(s)")
            return 0

        # 5. Generate prompt and invoke Ralph
        log("📝 Generating prompt for Ralph...")
        prompt = generate_prompt(
            pr_url, pr_info, failed_checks, bot_comments, conflicts
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

        log(f"🚀 Invoking Ralph (burns {prompt_file})")
        try:
            # Run burns with the prompt file
            result = subprocess.run(
                ["burns", prompt_file],
                check=False  # Don't raise on non-zero exit
            )
            if result.returncode != 0:
                log(f"⚠️ Ralph exited with code {result.returncode}")
        finally:
            # Clean up prompt file
            try:
                os.unlink(prompt_file)
            except OSError:
                pass

        log("Ralph finished, re-checking PR status...")
        # Small delay before re-checking to let GitHub update
        time.sleep(5)

    log(f"⚠️ Reached max cycles ({MAX_CYCLES}) without PR being ready")
    return 1


if __name__ == "__main__":
    sys.exit(main())
