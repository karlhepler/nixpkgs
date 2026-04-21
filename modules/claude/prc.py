#!/usr/bin/env python3
"""
prc: PR Comment management CLI using GitHub GraphQL API exclusively

Comprehensive PR comment operations using GraphQL for optimal efficiency.
Outputs XML by default (machine-readable for Claude, Ralph, Smithers).
Use --format json for JSON output, --format human for human-readable output.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from claude_tooling import error_response, get_current_branch, parse_pr_url, get_pr_info


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


def strip_body_fields(comment: Dict, max_body_len: Optional[int] = None) -> Dict:
    """
    Return a copy of comment with body fields removed (metadata-only).
    If max_body_len is provided, truncate body fields to that length instead.
    """
    result = {k: v for k, v in comment.items() if k not in ("body", "body_text", "diff_hunk")}
    return result


def truncate_body_fields(comment: Dict, max_body_len: int) -> Dict:
    """Return a copy of comment with body fields truncated to max_body_len chars."""
    result = dict(comment)
    for field in ("body", "body_text", "diff_hunk"):
        val = result.get(field)
        if isinstance(val, str) and len(val) > max_body_len:
            result[field] = val[:max_body_len] + "..."
    return result


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


def _dict_to_xml_element(parent: ET.Element, key: str, value) -> None:
    """Recursively serialize a value into an XML child element under parent."""
    child = ET.SubElement(parent, key)
    if value is None:
        child.set("null", "true")
    elif isinstance(value, bool):
        child.text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        child.text = str(value)
    elif isinstance(value, str):
        child.text = value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                item_el = ET.SubElement(child, "item")
                for k, v in item.items():
                    _dict_to_xml_element(item_el, k, v)
            else:
                item_el = ET.SubElement(child, "item")
                item_el.text = str(item) if item is not None else ""
                if item is None:
                    item_el.set("null", "true")
    elif isinstance(value, dict):
        for k, v in value.items():
            _dict_to_xml_element(child, k, v)
    else:
        child.text = str(value)


def serialize_xml(result: Dict, root_tag: str = "response") -> str:
    """Serialize a response dict to an indented XML string."""
    root = ET.Element(root_tag)
    for key, value in result.items():
        _dict_to_xml_element(root, key, value)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def emit_result(result: Dict, fmt: str) -> None:
    """Print result to stdout in the requested format."""
    if fmt == "xml":
        print(serialize_xml(result))
    else:
        # json and human both emit JSON; human is reserved for future tabular output
        print(json.dumps(result, indent=2))


def cmd_list(args: argparse.Namespace) -> Dict:
    """List command: fetch, filter, and output comments."""
    pr_info, error = get_pr_info(args.pr, validate_connection=True)
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

    # Apply body field handling based on --full / --max-body-len
    full = getattr(args, "full", False)
    max_body_len = getattr(args, "max_body_len", None)

    if full and max_body_len is not None:
        filtered = [truncate_body_fields(c, max_body_len) for c in filtered]
    elif not full:
        filtered = [strip_body_fields(c) for c in filtered]
    # else: full=True, no max_body_len — return complete body fields as-is

    return {
        "comments": filtered,
        "rate_limit": raw_data["rate_limit"],
    }


def cmd_reply(args: argparse.Namespace) -> Dict:
    """Reply to a comment using GraphQL mutation."""
    pr_info, error = get_pr_info(None, validate_connection=True)
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


def cmd_collapse(args: argparse.Namespace) -> None:
    """
    Collapse (minimize) comments using GraphQL mutation.

    Silent on success (exit 0). Errors go to stderr + exit 1.
    Pass --verbose / -v to emit a formatted success report.
    """
    pr_info, error = get_pr_info(args.pr, validate_connection=True)
    if error:
        print(error["error"], file=sys.stderr)
        sys.exit(1)

    owner, repo, pr_num = pr_info

    # Fetch all comments
    raw_data, error = fetch_pr_comments_graphql(owner, repo, pr_num)
    if error:
        print(error["error"], file=sys.stderr)
        sys.exit(1)

    comments = normalize_comments(raw_data)

    # Apply filters to determine which comments to collapse
    filtered, error = apply_filters(comments, args)
    if error:
        print(error["error"], file=sys.stderr)
        sys.exit(1)

    if not filtered:
        # Nothing to do — silent success
        sys.exit(0)

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

    if errors:
        # Always report errors to stderr and exit non-zero
        for err in errors:
            print(f"Error collapsing comment {err['comment_id']}: {err['error']}", file=sys.stderr)
        sys.exit(1)

    # Success: emit verbose report only if requested
    if args.verbose:
        result = {
            "success": True,
            "collapsed_count": len(collapsed),
            "collapsed_ids": collapsed,
            "errors": errors,
        }
        emit_result(result, args.format)

    sys.exit(0)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="PR Comment management CLI using GitHub GraphQL API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # NOTE: This CLI uses --format (not --output-style). The kanban CLI uses
    # --output-style=xml for historical reasons; these Python CLIs standardize
    # on --format. Coordinators must use the correct flag per tool.
    parser.add_argument(
        "--format",
        choices=["xml", "json", "human"],
        default="xml",
        help="Output format (default: xml). Note: kanban uses --output-style, not --format.",
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
    list_parser.add_argument(
        "--full",
        action="store_true",
        help="Include full comment body text (default: metadata-only, no body)",
    )
    list_parser.add_argument(
        "--max-body-len",
        type=int,
        metavar="N",
        help="Truncate each comment body to N chars (requires --full)",
    )

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
    collapse_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Emit collapse summary on success (format controlled by --format)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    # collapse has its own exit-code management; handle separately
    if args.command == "collapse":
        cmd_collapse(args)
        return

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
        else:
            result = error_response(f"Unknown command: {args.command}", "INVALID_COMMAND")

        # Error results: emit structured payload to stdout, caller distinguishes via exit 1
        if "error" in result:
            emit_result(result, args.format)
            sys.exit(1)

        # Emit successful result to stdout
        emit_result(result, args.format)
        sys.exit(0)

    except KeyboardInterrupt:
        print(serialize_xml(error_response("Interrupted by user", "INTERRUPTED")), file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(serialize_xml(error_response(f"Unexpected error: {e}", "UNEXPECTED_ERROR")), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
