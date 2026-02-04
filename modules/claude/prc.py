#!/usr/bin/env python3
"""
prc: PR Comment management CLI using GitHub GraphQL API exclusively

Comprehensive PR comment operations using GraphQL for optimal efficiency.
Outputs machine-readable JSON for consumption by Claude, Ralph, and Smithers.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple


def run_gh_graphql(query: str, variables: Dict) -> Tuple[int, str, str]:
    """Execute gh api graphql command and return (exit_code, stdout, stderr)."""
    try:
        args = ["gh", "api", "graphql", "-f", f"query={query}"]

        # Add variables as -F flags for proper type handling
        for key, value in variables.items():
            if isinstance(value, int):
                args.extend(["-F", f"{key}={value}"])
            else:
                args.extend(["-f", f"{key}={value}"])

        result = subprocess.run(
            args,
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
    code, stdout, stderr = run_gh_graphql(
        "query { viewer { login } }",
        {}
    )

    if code != 0:
        return None

    # Use gh pr view to get URL
    result = subprocess.run(
        ["gh", "pr", "view", "--json", "url", "--jq", ".url"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def parse_pr_url(url: str) -> Optional[Tuple[str, str, int]]:
    """Parse PR URL into (owner, repo, pr_number)."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if match:
        return match.group(1), match.group(2), int(match.group(3))
    return None


def get_pr_info(arg: Optional[str]) -> Tuple[Optional[Tuple[str, str, int]], Optional[Dict]]:
    """
    Get PR info from argument or infer from current branch.
    Returns ((owner, repo, pr_num), error_dict) - error_dict is None on success.
    """
    if arg is None:
        # Infer from current branch
        url = get_pr_from_branch()
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
        # Get repo info using gh
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


def fetch_pr_comments_graphql(owner: str, repo: str, pr_num: int) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Fetch all PR comments via GraphQL with pagination.
    Returns both issue comments and review threads.
    """
    # Query both issue comments and review threads
    query = """
    query($owner: String!, $repo: String!, $pr: Int!, $commentsCursor: String, $threadsCursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          id
          number
          title

          comments(first: 100, after: $commentsCursor) {
            nodes {
              id
              databaseId
              body
              bodyText
              author {
                __typename
                login
              }
              createdAt
              updatedAt
              isMinimized
              minimizedReason
              url
            }
            pageInfo {
              endCursor
              hasNextPage
            }
          }

          reviewThreads(first: 100, after: $threadsCursor) {
            nodes {
              id
              isResolved
              isCollapsed
              isOutdated
              line
              originalLine
              startLine
              originalStartLine
              path
              comments(first: 100) {
                nodes {
                  id
                  databaseId
                  body
                  bodyText
                  author {
                    __typename
                    login
                  }
                  createdAt
                  updatedAt
                  isMinimized
                  minimizedReason
                  url
                  diffHunk
                  replyTo {
                    databaseId
                  }
                }
              }
            }
            pageInfo {
              endCursor
              hasNextPage
            }
          }
        }
      }
      rateLimit {
        cost
        remaining
        resetAt
        limit
      }
    }
    """

    all_issue_comments = []
    all_review_threads = []

    comments_cursor = None
    threads_cursor = None

    # Paginate through results
    while True:
        variables = {
            "owner": owner,
            "repo": repo,
            "pr": pr_num,
        }

        if comments_cursor:
            variables["commentsCursor"] = comments_cursor
        if threads_cursor:
            variables["threadsCursor"] = threads_cursor

        code, stdout, stderr = run_gh_graphql(query, variables)

        if code != 0:
            return None, error_response(f"Failed to fetch comments: {stderr}", "API_ERROR")

        try:
            data = json.loads(stdout)

            if "errors" in data:
                return None, error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

            pr_data = data["data"]["repository"]["pullRequest"]

            # Collect issue comments
            comments = pr_data["comments"]["nodes"]
            all_issue_comments.extend(comments)

            # Collect review threads
            threads = pr_data["reviewThreads"]["nodes"]
            all_review_threads.extend(threads)

            # Check pagination
            comments_has_next = pr_data["comments"]["pageInfo"]["hasNextPage"]
            threads_has_next = pr_data["reviewThreads"]["pageInfo"]["hasNextPage"]

            if comments_has_next:
                comments_cursor = pr_data["comments"]["pageInfo"]["endCursor"]
            else:
                comments_cursor = None

            if threads_has_next:
                threads_cursor = pr_data["reviewThreads"]["pageInfo"]["endCursor"]
            else:
                threads_cursor = None

            # Break if no more pages
            if not comments_has_next and not threads_has_next:
                break

        except (json.JSONDecodeError, KeyError) as e:
            return None, error_response(f"Failed to parse GraphQL response: {e}", "PARSE_ERROR")

    return {
        "issue_comments": all_issue_comments,
        "review_threads": all_review_threads,
        "rate_limit": data["data"]["rateLimit"],
    }, None


def normalize_comments(raw_data: Dict) -> List[Dict]:
    """
    Normalize GraphQL response into flat comment list.
    Handles both issue comments and review thread comments.
    """
    comments = []

    # Process issue comments (PR-level)
    for comment in raw_data["issue_comments"]:
        normalized = {
            "id": comment["databaseId"],
            "node_id": comment["id"],
            "type": "pr-level",
            "author": comment["author"]["login"] if comment["author"] else "[deleted]",
            "author_type": comment["author"]["__typename"] if comment["author"] else "Unknown",
            "is_bot": comment["author"]["__typename"] == "Bot" if comment["author"] else False,
            "body": comment["body"],
            "body_text": comment["bodyText"],
            "created_at": comment["createdAt"],
            "updated_at": comment["updatedAt"],
            "is_minimized": comment["isMinimized"],
            "minimized_reason": comment["minimizedReason"],
            "url": comment["url"],
            "path": None,
            "line": None,
            "diff_hunk": None,
            "thread_id": None,
            "is_resolved": None,
            "in_reply_to_id": None,
            "reply_count": 0,
        }
        comments.append(normalized)

    # Process review threads (inline comments)
    for thread in raw_data["review_threads"]:
        thread_id = thread["id"]
        is_resolved = thread["isResolved"]
        path = thread["path"]
        line = thread["line"] or thread["originalLine"]

        for comment in thread["comments"]["nodes"]:
            normalized = {
                "id": comment["databaseId"],
                "node_id": comment["id"],
                "type": "inline",
                "author": comment["author"]["login"] if comment["author"] else "[deleted]",
                "author_type": comment["author"]["__typename"] if comment["author"] else "Unknown",
                "is_bot": comment["author"]["__typename"] == "Bot" if comment["author"] else False,
                "body": comment["body"],
                "body_text": comment["bodyText"],
                "created_at": comment["createdAt"],
                "updated_at": comment["updatedAt"],
                "is_minimized": comment["isMinimized"],
                "minimized_reason": comment["minimizedReason"],
                "url": comment["url"],
                "path": path,
                "line": line,
                "diff_hunk": comment.get("diffHunk"),
                "thread_id": thread_id,
                "is_resolved": is_resolved,
                "in_reply_to_id": comment["replyTo"]["databaseId"] if comment.get("replyTo") else None,
                "reply_count": 0,
            }
            comments.append(normalized)

    # Build reply counts
    reply_map = {}
    for comment in comments:
        reply_to = comment.get("in_reply_to_id")
        if reply_to:
            reply_map[reply_to] = reply_map.get(reply_to, 0) + 1

    for comment in comments:
        comment["reply_count"] = reply_map.get(comment["id"], 0)

    return comments


def apply_filters(comments: List[Dict], args: argparse.Namespace) -> Tuple[Optional[List[Dict]], Optional[Dict]]:
    """
    Apply filters based on command-line arguments.
    Returns (filtered_list, error_dict) - error_dict is None on success.
    """
    filtered = comments

    # Filter by author
    if hasattr(args, "author") and args.author:
        filtered = [c for c in filtered if c["author"] == args.author]

    # Filter by author pattern (regex)
    if hasattr(args, "author_pattern") and args.author_pattern:
        try:
            pattern = re.compile(args.author_pattern)
            filtered = [c for c in filtered if pattern.search(c["author"])]
        except re.error as e:
            # Invalid regex - return error dict like other error cases
            return None, error_response(
                f"Invalid regex pattern: {args.author_pattern}. Error: {str(e)}",
                "INVALID_REGEX"
            )

    # Filter bots only
    if hasattr(args, "bots_only") and args.bots_only:
        filtered = [c for c in filtered if c["is_bot"]]

    # Filter inline only (exclude PR-level comments)
    if hasattr(args, "inline_only") and args.inline_only:
        filtered = [c for c in filtered if c["type"] == "inline"]

    # Filter by reply count
    if hasattr(args, "max_replies") and args.max_replies is not None:
        filtered = [c for c in filtered if c["reply_count"] <= args.max_replies]

    # Filter by resolved status
    if hasattr(args, "resolved") and args.resolved:
        filtered = [c for c in filtered if c.get("is_resolved") is True]

    if hasattr(args, "unresolved") and args.unresolved:
        filtered = [c for c in filtered if c.get("is_resolved") is False]

    return filtered, None


def cmd_list(args: argparse.Namespace) -> Dict:
    """List command: fetch, filter, and output comments."""
    pr_info, error = get_pr_info(args.pr)
    if error:
        return error

    owner, repo, pr_num = pr_info

    # Fetch comments via GraphQL
    raw_data, error = fetch_pr_comments_graphql(owner, repo, pr_num)
    if error:
        return error

    # Normalize comments
    comments = normalize_comments(raw_data)

    # Apply filters
    filtered, error = apply_filters(comments, args)
    if error:
        return error

    return {
        "comments": filtered,
        "rate_limit": raw_data["rate_limit"],
    }


def cmd_reply(args: argparse.Namespace) -> Dict:
    """Reply to a comment using GraphQL mutation."""
    pr_info, error = get_pr_info(None)
    if error:
        return error

    owner, repo, pr_num = pr_info
    comment_id = args.comment_id
    message = args.message

    # We need to determine if this is an inline comment (use thread reply)
    # or a PR-level comment (use addComment)

    # Fetch all comments to find the target
    raw_data, error = fetch_pr_comments_graphql(owner, repo, pr_num)
    if error:
        return error

    comments = normalize_comments(raw_data)
    target_comment = None

    for comment in comments:
        if comment["id"] == comment_id:
            target_comment = comment
            break

    if not target_comment:
        return error_response(f"Comment {comment_id} not found", "COMMENT_NOT_FOUND")

    # Rate limiting: space mutations 1 second apart
    time.sleep(1)

    if target_comment["type"] == "inline":
        # Use addPullRequestReviewThreadReply mutation
        mutation = """
        mutation($threadId: ID!, $body: String!) {
          addPullRequestReviewThreadReply(input: {
            pullRequestReviewThreadId: $threadId
            body: $body
          }) {
            comment {
              id
              databaseId
              body
              author {
                login
              }
            }
          }
        }
        """

        variables = {
            "threadId": target_comment["thread_id"],
            "body": message,
        }

        code, stdout, stderr = run_gh_graphql(mutation, variables)

        if code != 0:
            return error_response(f"Failed to reply: {stderr}", "API_ERROR")

        try:
            data = json.loads(stdout)

            if "errors" in data:
                return error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

            comment = data["data"]["addPullRequestReviewThreadReply"]["comment"]
            return {
                "success": True,
                "comment_id": comment["databaseId"],
                "node_id": comment["id"],
                "type": "inline",
            }
        except (json.JSONDecodeError, KeyError) as e:
            return error_response(f"Failed to parse response: {e}", "PARSE_ERROR")

    else:
        # PR-level comment - use addComment mutation
        # First get the PR node ID
        query = """
        query($owner: String!, $repo: String!, $pr: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $pr) {
              id
            }
          }
        }
        """

        variables = {
            "owner": owner,
            "repo": repo,
            "pr": pr_num,
        }

        code, stdout, stderr = run_gh_graphql(query, variables)

        if code != 0:
            return error_response(f"Failed to get PR ID: {stderr}", "API_ERROR")

        try:
            data = json.loads(stdout)
            pr_id = data["data"]["repository"]["pullRequest"]["id"]
        except (json.JSONDecodeError, KeyError) as e:
            return error_response(f"Failed to parse PR ID: {e}", "PARSE_ERROR")

        # Format reply with @mention
        body = f"@{target_comment['author']} {message}"

        mutation = """
        mutation($prId: ID!, $body: String!) {
          addComment(input: { subjectId: $prId, body: $body }) {
            commentEdge {
              node {
                id
                ... on IssueComment {
                  databaseId
                  body
                }
              }
            }
          }
        }
        """

        variables = {
            "prId": pr_id,
            "body": body,
        }

        code, stdout, stderr = run_gh_graphql(mutation, variables)

        if code != 0:
            return error_response(f"Failed to reply: {stderr}", "API_ERROR")

        try:
            data = json.loads(stdout)

            if "errors" in data:
                return error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

            comment = data["data"]["addComment"]["commentEdge"]["node"]
            return {
                "success": True,
                "comment_id": comment["databaseId"],
                "node_id": comment["id"],
                "type": "pr-level",
            }
        except (json.JSONDecodeError, KeyError) as e:
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

    variables = {"threadId": thread_id}

    # Rate limiting
    time.sleep(1)

    code, stdout, stderr = run_gh_graphql(mutation, variables)

    if code != 0:
        return error_response(f"Failed to resolve thread: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)

        if "errors" in data:
            return error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

        thread = data["data"]["resolveReviewThread"]["thread"]
        return {
            "success": True,
            "thread_id": thread["id"],
            "is_resolved": thread["isResolved"],
        }
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

    variables = {"threadId": thread_id}

    # Rate limiting
    time.sleep(1)

    code, stdout, stderr = run_gh_graphql(mutation, variables)

    if code != 0:
        return error_response(f"Failed to unresolve thread: {stderr}", "API_ERROR")

    try:
        data = json.loads(stdout)

        if "errors" in data:
            return error_response(f"GraphQL error: {data['errors']}", "GRAPHQL_ERROR")

        thread = data["data"]["unresolveReviewThread"]["thread"]
        return {
            "success": True,
            "thread_id": thread["id"],
            "is_resolved": thread["isResolved"],
        }
    except (json.JSONDecodeError, KeyError) as e:
        return error_response(f"Failed to parse response: {e}", "PARSE_ERROR")


def cmd_collapse(args: argparse.Namespace) -> Dict:
    """Collapse (minimize) comments using GraphQL mutation."""
    pr_info, error = get_pr_info(args.pr)
    if error:
        return error

    owner, repo, pr_num = pr_info

    # Fetch all comments
    raw_data, error = fetch_pr_comments_graphql(owner, repo, pr_num)
    if error:
        return error

    comments = normalize_comments(raw_data)

    # Apply filters to determine which comments to collapse
    filtered, error = apply_filters(comments, args)
    if error:
        return error

    if not filtered:
        return {
            "success": True,
            "message": "No comments matched filters",
            "collapsed_count": 0,
        }

    # Map reason to classifier
    reason_map = {
        "off-topic": "OFF_TOPIC",
        "spam": "SPAM",
        "outdated": "OUTDATED",
        "abuse": "ABUSE",
        "resolved": "RESOLVED",
    }

    classifier = reason_map.get(args.reason, "RESOLVED")

    # Minimize each comment
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

    collapsed = []
    errors = []

    for comment in filtered:
        variables = {
            "subjectId": comment["node_id"],
            "classifier": classifier,
        }

        # Rate limiting: 1 second between mutations
        time.sleep(1)

        code, stdout, stderr = run_gh_graphql(mutation, variables)

        if code != 0:
            errors.append({
                "comment_id": comment["id"],
                "error": stderr,
            })
            continue

        try:
            data = json.loads(stdout)

            if "errors" in data:
                errors.append({
                    "comment_id": comment["id"],
                    "error": str(data["errors"]),
                })
                continue

            collapsed.append(comment["id"])

        except (json.JSONDecodeError, KeyError) as e:
            errors.append({
                "comment_id": comment["id"],
                "error": f"Parse error: {e}",
            })

    return {
        "success": True,
        "collapsed_count": len(collapsed),
        "collapsed_ids": collapsed,
        "errors": errors,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PR Comment management CLI using GitHub GraphQL API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # list command
    list_parser = subparsers.add_parser("list", help="Fetch and filter PR comments")
    list_parser.add_argument("pr", nargs="?", help="PR number, URL, or omit to infer from branch")
    list_parser.add_argument("--author", help="Filter by specific author username")
    list_parser.add_argument("--author-pattern", help="Filter by author regex pattern")
    list_parser.add_argument("--bots-only", action="store_true", help="Only bot comments")
    list_parser.add_argument("--inline-only", action="store_true", help="Only inline review comments (not PR-level)")
    list_parser.add_argument("--max-replies", type=int, help="Maximum reply count")
    list_parser.add_argument("--resolved", action="store_true", help="Only resolved comments")
    list_parser.add_argument("--unresolved", action="store_true", help="Only unresolved comments")

    # reply command
    reply_parser = subparsers.add_parser("reply", help="Reply to a comment")
    reply_parser.add_argument("comment_id", type=int, help="Comment database ID to reply to")
    reply_parser.add_argument("message", help="Reply message")

    # resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Mark review thread as resolved")
    resolve_parser.add_argument("thread_id", help="Thread node ID to resolve")

    # unresolve command
    unresolve_parser = subparsers.add_parser("unresolve", help="Mark review thread as unresolved")
    unresolve_parser.add_argument("thread_id", help="Thread node ID to unresolve")

    # collapse command
    collapse_parser = subparsers.add_parser("collapse", help="Collapse (minimize) comments")
    collapse_parser.add_argument("pr", nargs="?", help="PR number, URL, or omit to infer from branch")
    collapse_parser.add_argument("--author", help="Filter by specific author")
    collapse_parser.add_argument("--author-pattern", help="Filter by author regex pattern")
    collapse_parser.add_argument("--bots-only", action="store_true", help="Only bot comments")
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
