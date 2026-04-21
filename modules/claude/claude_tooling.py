"""
claude_tooling: Shared utility layer for prc, prr, and future Python CLIs.

Provides common PR resolution helpers that are used across multiple Claude
tooling scripts, eliminating duplication and drift between implementations.
"""

import json
import re
import subprocess
from typing import Dict, Optional, Tuple


def error_response(message: str, code: str = "ERROR", details: Optional[Dict] = None) -> Dict:
    """Build error response dict."""
    return {
        "error": message,
        "error_code": code,
        "details": details or {},
    }


def get_current_branch() -> Optional[str]:
    """Get current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def parse_pr_url(url: str) -> Optional[Tuple[str, str, int]]:
    """Parse PR URL into (owner, repo, pr_number)."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if match:
        return match.group(1), match.group(2), int(match.group(3))
    return None


def _get_pr_from_branch_with_connectivity_check() -> Optional[str]:
    """Get PR URL from current branch, first verifying GraphQL connectivity."""
    # Connectivity check via GraphQL (prc behavior)
    try:
        args = ["gh", "api", "graphql", "-f", "query={ viewer { login } }"]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
    except FileNotFoundError:
        return None

    result = subprocess.run(
        ["gh", "pr", "view", "--json", "url", "--jq", ".url"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def _get_pr_from_branch_direct() -> Optional[str]:
    """Get PR URL from current branch using gh pr view directly (no connectivity check)."""
    result = subprocess.run(
        ["gh", "pr", "view", "--json", "url", "--jq", ".url"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def get_pr_info(
    arg: Optional[str], validate_connection: bool = True
) -> Tuple[Optional[Tuple[str, str, int]], Optional[Dict]]:
    """
    Get PR info from argument or infer from current branch.

    Returns ((owner, repo, pr_num), error_dict) — error_dict is None on success.

    Args:
        arg: PR number as string, PR URL, or None to infer from current branch.
        validate_connection: When True (default), performs a GraphQL connectivity
            check before querying the current branch PR (prc behavior). When False,
            calls gh pr view directly without the connectivity check (prr behavior).
    """
    if arg is None:
        if validate_connection:
            url = _get_pr_from_branch_with_connectivity_check()
        else:
            url = _get_pr_from_branch_direct()

        if not url:
            return None, error_response(
                "Could not infer PR from current branch. Provide PR number or URL.",
                "PR_NOT_FOUND",
            )
        parsed = parse_pr_url(url)
        if not parsed:
            return None, error_response(f"Failed to parse PR URL: {url}", "INVALID_URL")
        return parsed, None

    # Check if it's a number
    if arg.isdigit():
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "owner,name"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            return None, error_response("Not in a git repository", "NOT_A_REPO")

        try:
            repo_info = json.loads(result.stdout)
            owner = repo_info["owner"]["login"]
            repo = repo_info["name"]
            return (owner, repo, int(arg)), None
        except (json.JSONDecodeError, KeyError):
            return None, error_response("Failed to parse repo info", "PARSE_ERROR")

    # Assume it's a URL
    parsed = parse_pr_url(arg)
    if not parsed:
        return None, error_response(f"Invalid PR URL: {arg}", "INVALID_URL")

    return parsed, None
