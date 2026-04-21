#!/usr/bin/env python3
"""
prr: PR Review submission CLI using GitHub REST API

Submit structured GitHub PR reviews with inline comments from a findings JSON file.
Outputs machine-readable JSON for consumption by Claude, Ralph, and Smithers.
"""

import argparse
import json
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from claude_tooling import error_response, get_current_branch, parse_pr_url, get_pr_info


def run_gh_api(path: str, method: str = "GET", payload: Optional[Dict] = None) -> Tuple[int, str, str]:
    """Execute gh api REST command and return (exit_code, stdout, stderr)."""
    if method == "GET":
        args = ["gh", "api", path]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        # POST/PATCH/PUT: pipe JSON payload via stdin using --input -
        args = ["gh", "api", path, "--method", method, "--input", "-"]
        result = subprocess.run(
            args,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
    return result.returncode, result.stdout, result.stderr


def get_head_sha(owner: str, repo: str, pr_num: int) -> Tuple[Optional[str], Optional[Dict]]:
    """Get the head commit SHA for a PR."""
    result = subprocess.run(
        ["gh", "pr", "view", str(pr_num), "--repo", f"{owner}/{repo}", "--json", "headRefOid", "--jq", ".headRefOid"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, error_response(f"Failed to get head SHA: {result.stderr}", "API_ERROR")
    sha = result.stdout.strip()
    if not sha:
        return None, error_response("Head SHA was empty", "PARSE_ERROR")
    return sha, None


def load_findings(findings_path: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Load and validate findings JSON from file."""
    try:
        with open(findings_path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, error_response(f"Findings file not found: {findings_path}", "FILE_NOT_FOUND")
    except json.JSONDecodeError as e:
        return None, error_response(f"Invalid JSON in findings file: {e}", "INVALID_JSON")

    if "body" not in data:
        return None, error_response("Findings JSON missing required 'body' field", "INVALID_FINDINGS")
    if "comments" not in data or not isinstance(data["comments"], list):
        return None, error_response("Findings JSON missing required 'comments' array", "INVALID_FINDINGS")

    return data, None


def determine_event(comments: List[Dict], override: Optional[str]) -> str:
    """Determine review event from findings severity or explicit override."""
    if override:
        return override
    has_blocking = any(c.get("severity") == "blocking" for c in comments)
    return "REQUEST_CHANGES" if has_blocking else "COMMENT"


def cmd_submit(args: argparse.Namespace) -> Dict:
    """Submit command: load findings, build payload, post review."""
    # Load findings file
    findings, error = load_findings(args.findings)
    if error:
        return error

    # Resolve PR info
    pr_arg = str(args.pr) if args.pr is not None else None
    pr_info, error = get_pr_info(pr_arg, validate_connection=False)
    if error:
        return error
    owner, repo, pr_num = pr_info

    # Get head commit SHA
    head_sha, error = get_head_sha(owner, repo, pr_num)
    if error:
        return error

    body = findings["body"]
    all_comments = findings["comments"]

    # Separate inline vs body-level findings
    inline_comments = [c for c in all_comments if c.get("path") is not None and c.get("line") is not None]
    body_comments = [c for c in all_comments if c.get("path") is None and c.get("line") is None]

    # Append body-level findings to review body
    if body_comments:
        body_lines = [body]
        for c in body_comments:
            body_lines.append(c['body'])
        body = "\n\n".join(body_lines)

    # Determine review event
    event = determine_event(all_comments, getattr(args, "event", None))

    # Build REST payload
    payload_comments = []
    for c in inline_comments:
        payload_comments.append({
            "path": c["path"],
            "line": c["line"],
            "side": c.get("side", "RIGHT"),
            "body": c['body'],
        })

    payload = {
        "body": body,
        "commit_id": head_sha,
        "event": event,
        "comments": payload_comments,
    }

    # POST review
    api_path = f"repos/{owner}/{repo}/pulls/{pr_num}/reviews"
    code, stdout, stderr = run_gh_api(api_path, method="POST", payload=payload)

    if code != 0:
        return error_response(f"Failed to submit review: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return error_response(f"Failed to parse API response: {e}", "PARSE_ERROR")

    review_id = data.get("id")
    html_url = data.get("html_url", "")

    return {
        "review_id": review_id,
        "html_url": html_url,
        "inline_count": len(inline_comments),
        "body_count": len(body_comments),
        "event": event,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Submit GitHub PR reviews with inline comments from a structured findings JSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # submit command
    submit_parser = subparsers.add_parser("submit", help="Submit a PR review from a findings JSON file")
    submit_parser.add_argument("pr", nargs="?", help="PR number, URL, or omit to infer from branch")
    submit_parser.add_argument("--findings", required=True, help="Path to findings JSON file")
    submit_parser.add_argument(
        "--event",
        choices=["COMMENT", "REQUEST_CHANGES", "APPROVE"],
        help="Override review event (default: auto-determined from severity fields)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    # Route to command handlers
    try:
        if args.command == "submit":
            result = cmd_submit(args)
        else:
            result = error_response(f"Unknown command: {args.command}", "INVALID_COMMAND")

        # Output JSON
        print(json.dumps(result, indent=2))

        # Exit with appropriate code
        if "error" in result:
            sys.exit(1)
        sys.exit(0)

    except KeyboardInterrupt:
        print(json.dumps(error_response("Interrupted by user", "INTERRUPTED")), file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(json.dumps(error_response(f"Unexpected error: {e}", "UNEXPECTED_ERROR")), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
