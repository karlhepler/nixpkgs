#!/usr/bin/env python3
"""
pr-comments: Comprehensive PR comment management CLI

Fetch, filter, reply to, resolve, and collapse GitHub PR comments.
Outputs machine-readable JSON for consumption by Claude, Ralph, and Smithers.
"""

import argparse
import json
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


def run_gh(args: List[str]) -> Tuple[int, str, str]:
    """Execute gh command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", "gh command not found. Please install GitHub CLI."


def error_response(message: str, code: str = "ERROR", details: Dict = None) -> Dict:
    """Build error response dict."""
    return {
        "error": message,
        "error_code": code,
        "details": details or {},
    }


def get_current_branch() -> Optional[str]:
    """Get current git branch name."""
    code, stdout, _ = run_gh(["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"])
    if code != 0:
        return None

    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_pr_from_branch() -> Optional[str]:
    """Get PR URL from current branch using gh pr view."""
    branch = get_current_branch()
    if not branch:
        return None

    code, stdout, stderr = run_gh(["pr", "view", "--json", "url", "--jq", ".url"])
    if code == 0 and stdout.strip():
        return stdout.strip()
    return None


def parse_pr_url(url: str) -> Optional[Tuple[str, str, int]]:
    """Parse PR URL into (owner, repo, pr_number)."""
    # Handle github.com URLs
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if match:
        return match.group(1), match.group(2), int(match.group(3))
    return None


def get_pr_url(arg: Optional[str]) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Get PR URL from argument or infer from current branch.
    Returns (url, error_dict) - error_dict is None on success.
    """
    if arg is None:
        # Infer from current branch
        url = get_pr_from_branch()
        if not url:
            return None, error_response(
                "Could not infer PR from current branch. Provide PR number or URL.",
                "PR_NOT_FOUND",
            )
        return url, None

    # Check if it's a number
    if arg.isdigit():
        # Get repo info
        code, stdout, _ = run_gh(["repo", "view", "--json", "owner,name"])
        if code != 0:
            return None, error_response("Not in a git repository", "NOT_A_REPO")

        try:
            repo_info = json.loads(stdout)
            owner = repo_info["owner"]["login"]
            repo = repo_info["name"]
            url = f"https://github.com/{owner}/{repo}/pull/{arg}"
            return url, None
        except (json.JSONDecodeError, KeyError):
            return None, error_response("Failed to parse repo info", "PARSE_ERROR")

    # Assume it's a URL
    parsed = parse_pr_url(arg)
    if not parsed:
        return None, error_response(f"Invalid PR URL: {arg}", "INVALID_URL")

    return arg, None


def fetch_issue_comments(owner: str, repo: str, pr_num: int) -> Tuple[Optional[List[Dict]], Optional[Dict]]:
    """Fetch PR-level (issue) comments."""
    code, stdout, stderr = run_gh([
        "api",
        f"/repos/{owner}/{repo}/issues/{pr_num}/comments",
        "--paginate",
        "--jq", ".",
    ])

    if code != 0:
        return None, error_response(f"Failed to fetch issue comments: {stderr}", "API_ERROR")

    try:
        comments = json.loads(stdout)
        # Add type and author_type fields
        for comment in comments:
            comment["type"] = "pr-level"
            comment["author_type"] = "bot" if "[bot]" in comment["user"]["login"] else "human"
        return comments, None
    except json.JSONDecodeError as e:
        return None, error_response(f"Failed to parse comments: {e}", "PARSE_ERROR")


def fetch_review_comments(owner: str, repo: str, pr_num: int) -> Tuple[Optional[List[Dict]], Optional[Dict]]:
    """Fetch inline review comments."""
    code, stdout, stderr = run_gh([
        "api",
        f"/repos/{owner}/{repo}/pulls/{pr_num}/comments",
        "--paginate",
        "--jq", ".",
    ])

    if code != 0:
        return None, error_response(f"Failed to fetch review comments: {stderr}", "API_ERROR")

    try:
        comments = json.loads(stdout)
        # Add type and author_type fields
        for comment in comments:
            comment["type"] = "inline"
            comment["author_type"] = "bot" if "[bot]" in comment["user"]["login"] else "human"
        return comments, None
    except json.JSONDecodeError as e:
        return None, error_response(f"Failed to parse comments: {e}", "PARSE_ERROR")


def fetch_review_threads(owner: str, repo: str, pr_num: int) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Fetch review thread metadata via GraphQL."""
    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              viewerCanResolve
              comments(first: 100) {
                nodes {
                  databaseId
                  isMinimized
                  minimizedReason
                }
              }
            }
          }
        }
      }
    }
    """

    code, stdout, stderr = run_gh([
        "api", "graphql",
        "-f", f"query={query}",
        "-F", f"owner={owner}",
        "-F", f"repo={repo}",
        "-F", f"pr={pr_num}",
    ])

    if code != 0:
        return None, error_response(f"Failed to fetch review threads: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)
        if "errors" in data:
            return None, error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

        # Build mapping of comment ID to thread metadata
        thread_map = {}
        threads = data.get("data", {}).get("repository", {}).get("pullRequest", {}).get("reviewThreads", {}).get("nodes", [])

        for thread in threads:
            thread_id = thread["id"]
            is_resolved = thread["isResolved"]

            for comment in thread.get("comments", {}).get("nodes", []):
                comment_id = comment["databaseId"]
                thread_map[comment_id] = {
                    "thread_id": thread_id,
                    "is_resolved": is_resolved,
                    "is_minimized": comment.get("isMinimized", False),
                    "minimized_reason": comment.get("minimizedReason"),
                }

        return thread_map, None
    except (json.JSONDecodeError, KeyError) as e:
        return None, error_response(f"Failed to parse thread data: {e}", "PARSE_ERROR")


def parse_reply_relationships(comments: List[Dict]) -> None:
    """Parse HTML reply markers and set in_reply_to_id for PR-level comments."""
    for comment in comments:
        if comment["type"] != "pr-level":
            continue

        body = comment.get("body", "")
        # Look for <!-- reply-to: https://github.com/.../pull/123#issuecomment-456 -->
        match = re.search(r"<!-- reply-to: .*/issuecomment-(\d+) -->", body)
        if match:
            parent_id = int(match.group(1))
            comment["in_reply_to_id"] = parent_id
        else:
            comment["in_reply_to_id"] = None


def build_comment_tree(comments: List[Dict]) -> None:
    """Build parent-child relationships and count direct replies."""
    # Build ID to comment map
    comment_map = {c["id"]: c for c in comments}

    # Initialize reply fields
    for comment in comments:
        comment["reply_count"] = 0
        comment["replies"] = []

    # Build relationships
    for comment in comments:
        # Inline comments use in_reply_to_id from API
        parent_id = comment.get("in_reply_to_id")
        if parent_id and parent_id in comment_map:
            parent = comment_map[parent_id]
            parent["reply_count"] += 1
            parent["replies"].append(comment)


def enrich_comments(comments: List[Dict], thread_map: Dict) -> None:
    """Enrich comments with thread metadata."""
    for comment in comments:
        comment_id = comment["id"]

        if comment["type"] == "inline" and comment_id in thread_map:
            meta = thread_map[comment_id]
            comment["thread_id"] = meta["thread_id"]
            comment["is_resolved"] = meta["is_resolved"]
            comment["is_minimized"] = meta["is_minimized"]
            comment["minimized_reason"] = meta["minimized_reason"]
        else:
            comment["thread_id"] = None
            comment["is_resolved"] = None
            comment["is_minimized"] = False
            comment["minimized_reason"] = None


def apply_filters(comments: List[Dict], args: argparse.Namespace) -> List[Dict]:
    """Apply filters based on command-line arguments."""
    filtered = comments

    # Filter by type
    if args.pr_comments and not args.inline_comments:
        filtered = [c for c in filtered if c["type"] == "pr-level"]
    elif args.inline_comments and not args.pr_comments:
        filtered = [c for c in filtered if c["type"] == "inline"]

    # Filter by reply count
    if hasattr(args, "min_replies") and args.min_replies is not None:
        filtered = [c for c in filtered if c["reply_count"] >= args.min_replies]
    if hasattr(args, "max_replies") and args.max_replies is not None:
        filtered = [c for c in filtered if c["reply_count"] <= args.max_replies]

    # Filter by resolved status
    if hasattr(args, "resolved") and args.resolved:
        filtered = [c for c in filtered if c.get("is_resolved") is True]
    if hasattr(args, "unresolved") and args.unresolved:
        filtered = [c for c in filtered if c.get("is_resolved") is False]

    return filtered


def normalize_comment(comment: Dict) -> Dict:
    """Normalize comment object to match output schema."""
    return {
        "id": comment["id"],
        "type": comment["type"],
        "author": comment["user"]["login"],
        "author_type": comment["author_type"],
        "body": comment.get("body", ""),
        "created_at": comment.get("created_at", ""),
        "updated_at": comment.get("updated_at", ""),
        "html_url": comment.get("html_url", ""),
        "path": comment.get("path"),
        "line": comment.get("line") or comment.get("original_line"),
        "diff_hunk": comment.get("diff_hunk"),
        "in_reply_to_id": comment.get("in_reply_to_id"),
        "reply_count": comment.get("reply_count", 0),
        "replies": [normalize_comment(r) for r in comment.get("replies", [])],
        "thread_id": comment.get("thread_id"),
        "is_resolved": comment.get("is_resolved"),
        "is_minimized": comment.get("is_minimized", False),
        "minimized_reason": comment.get("minimized_reason"),
    }


def cmd_list(args: argparse.Namespace) -> Dict:
    """List command: fetch, filter, and output comments."""
    # Get PR URL
    url, error = get_pr_url(args.pr)
    if error:
        return error

    parsed = parse_pr_url(url)
    if not parsed:
        return error_response(f"Failed to parse PR URL: {url}", "INVALID_URL")

    owner, repo, pr_num = parsed

    # Fetch comments
    issue_comments, error = fetch_issue_comments(owner, repo, pr_num)
    if error:
        return error

    review_comments, error = fetch_review_comments(owner, repo, pr_num)
    if error:
        return error

    # Fetch thread metadata
    thread_map, error = fetch_review_threads(owner, repo, pr_num)
    if error:
        return error

    # Combine all comments
    all_comments = issue_comments + review_comments

    # Process relationships
    parse_reply_relationships(all_comments)
    build_comment_tree(all_comments)
    enrich_comments(all_comments, thread_map)

    # Apply filters
    filtered = apply_filters(all_comments, args)

    # Normalize output
    output = [normalize_comment(c) for c in filtered]

    return {"comments": output}


def detect_comment_type(comment_id: int, owner: str, repo: str, pr_num: int) -> Tuple[Optional[str], Optional[Dict]]:
    """Detect if comment is inline or PR-level."""
    # Try fetching as review comment first
    code, stdout, _ = run_gh([
        "api",
        f"/repos/{owner}/{repo}/pulls/comments/{comment_id}",
    ])

    if code == 0:
        return "inline", None

    # Try as issue comment
    code, stdout, _ = run_gh([
        "api",
        f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
    ])

    if code == 0:
        return "pr-level", None

    return None, error_response(f"Comment {comment_id} not found", "COMMENT_NOT_FOUND")


def format_pr_level_reply(parent_comment: Dict, message: str) -> str:
    """Format PR-level reply with HTML marker and @mention."""
    author = parent_comment["user"]["login"]
    html_url = parent_comment["html_url"]

    return f"""<!-- reply-to: {html_url} -->
@{author} {message}"""


def cmd_reply(args: argparse.Namespace) -> Dict:
    """Reply to a comment."""
    # Get PR URL
    url, error = get_pr_url(None)
    if error:
        return error

    parsed = parse_pr_url(url)
    if not parsed:
        return error_response(f"Failed to parse PR URL: {url}", "INVALID_URL")

    owner, repo, pr_num = parsed
    comment_id = args.comment_id
    message = args.message

    # Detect comment type
    comment_type, error = detect_comment_type(comment_id, owner, repo, pr_num)
    if error:
        return error

    if comment_type == "inline":
        # Reply to inline comment
        code, stdout, stderr = run_gh([
            "api",
            f"/repos/{owner}/{repo}/pulls/{pr_num}/comments/{comment_id}/replies",
            "-f", f"body={message}",
        ])

        if code != 0:
            return error_response(f"Failed to reply: {stderr}", "API_ERROR")

        try:
            result = json.loads(stdout)
            return {"success": True, "comment_id": result["id"], "type": "inline"}
        except json.JSONDecodeError as e:
            return error_response(f"Failed to parse response: {e}", "PARSE_ERROR")

    else:  # pr-level
        # Fetch parent comment to get author and URL
        code, stdout, stderr = run_gh([
            "api",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
        ])

        if code != 0:
            return error_response(f"Failed to fetch parent comment: {stderr}", "API_ERROR")

        try:
            parent = json.loads(stdout)
        except json.JSONDecodeError as e:
            return error_response(f"Failed to parse parent comment: {e}", "PARSE_ERROR")

        # Format reply
        body = format_pr_level_reply(parent, message)

        # Post as new issue comment
        code, stdout, stderr = run_gh([
            "api",
            f"/repos/{owner}/{repo}/issues/{pr_num}/comments",
            "-f", f"body={body}",
        ])

        if code != 0:
            return error_response(f"Failed to reply: {stderr}", "API_ERROR")

        try:
            result = json.loads(stdout)
            return {"success": True, "comment_id": result["id"], "type": "pr-level"}
        except json.JSONDecodeError as e:
            return error_response(f"Failed to parse response: {e}", "PARSE_ERROR")


def cmd_resolve(args: argparse.Namespace) -> Dict:
    """Resolve a review thread."""
    thread_id = args.thread_id

    mutation = """
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread {
          id
          isResolved
        }
      }
    }
    """

    code, stdout, stderr = run_gh([
        "api", "graphql",
        "-f", f"query={mutation}",
        "-F", f"threadId={thread_id}",
    ])

    if code != 0:
        return error_response(f"Failed to resolve thread: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)
        if "errors" in data:
            return error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

        thread = data["data"]["resolveReviewThread"]["thread"]
        return {"success": True, "thread_id": thread["id"], "is_resolved": thread["isResolved"]}
    except (json.JSONDecodeError, KeyError) as e:
        return error_response(f"Failed to parse response: {e}", "PARSE_ERROR")


def cmd_unresolve(args: argparse.Namespace) -> Dict:
    """Unresolve a review thread."""
    thread_id = args.thread_id

    mutation = """
    mutation($threadId: ID!) {
      unresolveReviewThread(input: {threadId: $threadId}) {
        thread {
          id
          isResolved
        }
      }
    }
    """

    code, stdout, stderr = run_gh([
        "api", "graphql",
        "-f", f"query={mutation}",
        "-F", f"threadId={thread_id}",
    ])

    if code != 0:
        return error_response(f"Failed to unresolve thread: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)
        if "errors" in data:
            return error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

        thread = data["data"]["unresolveReviewThread"]["thread"]
        return {"success": True, "thread_id": thread["id"], "is_resolved": thread["isResolved"]}
    except (json.JSONDecodeError, KeyError) as e:
        return error_response(f"Failed to parse response: {e}", "PARSE_ERROR")


def get_current_user() -> Tuple[Optional[str], Optional[Dict]]:
    """Get currently authenticated GitHub user."""
    code, stdout, stderr = run_gh(["api", "user", "--jq", ".login"])
    if code != 0:
        return None, error_response(f"Failed to get current user: {stderr}", "AUTH_ERROR")
    return stdout.strip(), None


def minimize_comment(comment_id: int, comment_type: str, reason: str, owner: str, repo: str) -> Tuple[bool, Optional[Dict]]:
    """Minimize a single comment using REST API."""
    # Map reason to GitHub's minimized_reason
    reason_map = {
        "off-topic": "OFF_TOPIC",
        "spam": "SPAM",
        "outdated": "OUTDATED",
        "abuse": "ABUSE",
        "resolved": "RESOLVED",
    }

    minimized_reason = reason_map.get(reason, "RESOLVED")

    # Get endpoint for node ID lookup
    if comment_type == "inline":
        endpoint = f"/repos/{owner}/{repo}/pulls/comments/{comment_id}"
    else:
        endpoint = f"/repos/{owner}/{repo}/issues/comments/{comment_id}"

    # Minimize via GraphQL (more reliable than REST PATCH)
    # First, get the node ID
    code, stdout, stderr = run_gh(["api", endpoint, "--jq", ".node_id"])
    if code != 0:
        return False, error_response(f"Failed to get node ID: {stderr}", "API_ERROR")

    node_id = stdout.strip()

    mutation = """
    mutation($subjectId: ID!, $classifier: ReportedContentClassifiers!) {
      minimizeComment(input: {subjectId: $subjectId, classifier: $classifier}) {
        minimizedComment {
          isMinimized
          minimizedReason
        }
      }
    }
    """

    code, stdout, stderr = run_gh([
        "api", "graphql",
        "-f", f"query={mutation}",
        "-F", f"subjectId={node_id}",
        "-F", f"classifier={minimized_reason}",
    ])

    if code != 0:
        return False, error_response(f"Failed to minimize comment: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)
        if "errors" in data:
            error_msg = data["errors"][0]["message"] if data["errors"] else "Unknown error"
            return False, error_response(f"GraphQL error: {error_msg}", "GRAPHQL_ERROR")

        return True, None
    except (json.JSONDecodeError, KeyError) as e:
        return False, error_response(f"Failed to parse response: {e}", "PARSE_ERROR")


def cmd_collapse(args: argparse.Namespace) -> Dict:
    """Collapse (minimize) comments for a target user."""
    # Get PR URL
    url, error = get_pr_url(args.pr)
    if error:
        return error

    parsed = parse_pr_url(url)
    if not parsed:
        return error_response(f"Failed to parse PR URL: {url}", "INVALID_URL")

    owner, repo, pr_num = parsed

    # Determine target user
    if args.me:
        target_user, error = get_current_user()
        if error:
            return error
    elif args.user:
        target_user = args.user
    else:
        return error_response("Must specify --user or --me", "INVALID_ARGS")

    reason = args.reason or "resolved"

    # Fetch all comments
    issue_comments, error = fetch_issue_comments(owner, repo, pr_num)
    if error:
        return error

    review_comments, error = fetch_review_comments(owner, repo, pr_num)
    if error:
        return error

    all_comments = issue_comments + review_comments

    # Filter by target user
    target_comments = [
        c for c in all_comments
        if c["user"]["login"] == target_user
    ]

    if not target_comments:
        return {"success": True, "message": f"No comments found for user {target_user}", "collapsed_count": 0}

    # Minimize each comment
    collapsed = []
    errors = []

    for comment in target_comments:
        success, error = minimize_comment(
            comment["id"],
            comment["type"],
            reason,
            owner,
            repo,
        )

        if success:
            collapsed.append(comment["id"])
        else:
            errors.append({"comment_id": comment["id"], "error": error})

    return {
        "success": True,
        "collapsed_count": len(collapsed),
        "collapsed_ids": collapsed,
        "errors": errors,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Comprehensive PR comment management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # list command
    list_parser = subparsers.add_parser("list", help="Fetch and filter PR comments")
    list_parser.add_argument("pr", nargs="?", help="PR number, URL, or omit to infer from branch")
    list_parser.add_argument("--pr-comments", action="store_true", help="Only PR-level comments")
    list_parser.add_argument("--inline-comments", action="store_true", help="Only inline review comments")
    list_parser.add_argument("--min-replies", type=int, help="Minimum reply count")
    list_parser.add_argument("--max-replies", type=int, help="Maximum reply count")
    list_parser.add_argument("--resolved", action="store_true", help="Only resolved comments")
    list_parser.add_argument("--unresolved", action="store_true", help="Only unresolved comments")

    # reply command
    reply_parser = subparsers.add_parser("reply", help="Reply to a comment")
    reply_parser.add_argument("comment_id", type=int, help="Comment ID to reply to")
    reply_parser.add_argument("message", help="Reply message")

    # resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Mark review thread as resolved")
    resolve_parser.add_argument("thread_id", help="Thread ID to resolve")

    # unresolve command
    unresolve_parser = subparsers.add_parser("unresolve", help="Mark review thread as unresolved")
    unresolve_parser.add_argument("thread_id", help="Thread ID to unresolve")

    # collapse command
    collapse_parser = subparsers.add_parser("collapse", help="Collapse (minimize) comments")
    collapse_parser.add_argument("pr", nargs="?", help="PR number, URL, or omit to infer from branch")
    collapse_parser.add_argument("--user", help="Target specific user")
    collapse_parser.add_argument("--me", action="store_true", help="Target current authenticated user")
    collapse_parser.add_argument(
        "--reason",
        choices=["off-topic", "spam", "outdated", "abuse", "resolved"],
        default="resolved",
        help="Minimize reason (default: resolved)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    # Route to command handlers
    try:
        if args.command == "list":
            result = cmd_list(args)
        elif args.command == "reply":
            result = cmd_reply(args)
        elif args.command == "resolve":
            result = cmd_resolve(args)
        elif args.command == "unresolve":
            result = cmd_unresolve(args)
        elif args.command == "collapse":
            result = cmd_collapse(args)
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
