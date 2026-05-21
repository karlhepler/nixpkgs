#!/usr/bin/env python3
"""
smithers-post: Post a PR-ready-for-merge Slack notification with Block Kit formatting.

Fetches PR metadata via gh CLI, optionally generates Why/What summaries via a
haiku sub-agent, then POSTs a rich Block Kit message to SMITHERS_SLACK_WEBHOOK_URL.

Usage:
    smithers-post 123              # Post PR #123 (infer repo from current branch)
    smithers-post <pr-url>         # Post using full PR URL
    smithers-post                  # Infer PR from current branch
    smithers-post --no-summaries 123  # Skip Why/What generation, use PR body directly
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import urllib.error
import urllib.request


POSITIVE_EMOJIS = ["😊", "🙏", "✨", "🎉", "🚀", "🙌", "🤝", "👏", "🎊"]


def run_gh(args: list) -> tuple:
    """Run gh command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def resolve_pr_url(pr_arg: str) -> str:
    """Resolve PR argument to a full URL.

    Accepts: PR number (str digits), full URL, or None to infer from branch.
    Exits non-zero with a clear message on failure.
    """
    if pr_arg is None:
        code, stdout, _ = run_gh(["pr", "view", "--json", "url", "--jq", ".url"])
        if code != 0 or not stdout.strip():
            print(
                "Error: No PR found for current branch. "
                "Provide a PR number or URL.",
                file=sys.stderr,
            )
            sys.exit(1)
        return stdout.strip()

    if pr_arg.isdigit():
        code, stdout, _ = run_gh(["pr", "view", pr_arg, "--json", "url", "--jq", ".url"])
        if code != 0 or not stdout.strip():
            print(f"Error: Could not find PR #{pr_arg}", file=sys.stderr)
            sys.exit(1)
        return stdout.strip()

    if pr_arg.startswith("http://") or pr_arg.startswith("https://"):
        return pr_arg

    print(
        "Error: Invalid PR argument. Provide a PR number, URL, or omit to infer from branch.",
        file=sys.stderr,
    )
    sys.exit(1)


def parse_pr_url(url: str) -> tuple:
    """Parse PR URL into (owner, repo, number).

    Expects the canonical GitHub format: https://github.com/owner/repo/pull/123
    Exits non-zero if the URL cannot be parsed.
    """
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


def fetch_pr_info(pr_number: int) -> dict:
    """Fetch PR title and body via gh CLI.

    Returns dict with keys: title, body, headRepository (owner/name), url.
    Exits non-zero on failure.
    """
    code, stdout, stderr = run_gh([
        "pr", "view", str(pr_number),
        "--json", "title,body,headRepository,url",
    ])
    if code != 0:
        print(f"Error: Failed to fetch PR info: {stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        print(f"Error: Failed to parse PR info JSON: {exc}", file=sys.stderr)
        sys.exit(1)


def extract_section(body: str, heading: str) -> str:
    """Extract a section from PR body markdown by heading name.

    Looks for '## Why' or '## What' style headings and returns the paragraph
    that follows, up to the next heading or end of body.
    Strips leading/trailing whitespace. Returns empty string if not found.
    """
    pattern = re.compile(
        r"^##\s+" + re.escape(heading) + r"\s*\n+(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    if not match:
        return ""
    return match.group(1).strip()


def _parse_haiku_json_response(stdout_content: str) -> tuple:
    """Extract and parse the why/what JSON from a haiku agent's stdout.

    The haiku agent wraps its output in a JSON envelope with a "result" field.
    The result may contain a raw JSON object or a markdown code-fenced JSON block.

    Returns:
        (why, what) strings, or (None, None) on any parse failure.
    """
    if not stdout_content:
        print("_parse_haiku_json_response: empty stdout", file=sys.stderr)
        return (None, None)

    try:
        wrapper = json.loads(stdout_content)
    except json.JSONDecodeError as exc:
        print(f"_parse_haiku_json_response: invalid JSON envelope: {exc}", file=sys.stderr)
        return (None, None)

    result_text = wrapper.get("result", "")
    if not result_text:
        print("_parse_haiku_json_response: missing 'result' field in envelope", file=sys.stderr)
        return (None, None)

    result_text = result_text.strip()

    # Strip markdown code fences and any preamble text
    json_start = result_text.find("```json")
    if json_start >= 0:
        result_text = result_text[json_start + 7:]
    elif result_text.find("```") >= 0:
        json_start = result_text.find("```")
        result_text = result_text[json_start + 3:]

    if result_text.endswith("```"):
        result_text = result_text[:-3]
    result_text = result_text.strip()

    try:
        response_data = json.loads(result_text)
    except json.JSONDecodeError as exc:
        print(f"_parse_haiku_json_response: failed to parse result JSON: {exc}", file=sys.stderr)
        return (None, None)

    why_line = response_data.get("why", "").strip()
    what_line = response_data.get("what", "").strip()

    if not why_line or not what_line:
        print(
            f"_parse_haiku_json_response: missing why/what fields (why={bool(why_line)}, what={bool(what_line)})",
            file=sys.stderr,
        )
        return (None, None)

    return (why_line, what_line)


def generate_pr_summaries(pr_number: int, pr_url: str, pr_title: str) -> tuple:
    """Spawn a haiku agent to generate concise Why/What summaries for the PR.

    Returns (why, what) strings, or (None, None) on any failure.
    Failure is always non-fatal — callers fall back to PR body extraction.
    """
    agent_prompt = (
        f"You are analyzing GitHub PR #{pr_number} to generate summaries for team notification.\n\n"
        f"PR: #{pr_number}\n"
        f"URL: {pr_url}\n"
        f"Title: {pr_title}\n\n"
        "Tasks:\n"
        "1. Use gh CLI to explore this PR:\n"
        f"   - Read full description: `gh pr view {pr_number}`\n"
        "   - Review commits and changes\n\n"
        "2. Generate two summaries:\n"
        "   - Why: One sentence explaining the intent/problem/background\n"
        "   - What: One sentence explaining the specific implementation approach\n\n"
        "Be SPECIFIC and CONCRETE. Avoid vague terms like 'improved' or 'updated'.\n\n"
        'Return ONLY valid JSON with this structure:\n'
        '{\n'
        '  "why": "your sentence here",\n'
        '  "what": "your sentence here"\n'
        '}'
    )

    claude_cmd = [
        "claude", "-p", "--model", "haiku",
        "--output-format", "json",
        "--allowedTools", "Bash,Read,Edit,Grep,Glob",
        "--max-turns", "10",
    ]
    try:
        result = subprocess.run(claude_cmd, input=agent_prompt,
                                capture_output=True, text=True,
                                timeout=60, check=False)

        if result.returncode != 0:
            return (None, None)

        return _parse_haiku_json_response(result.stdout.strip())

    except subprocess.TimeoutExpired:
        return (None, None)
    except Exception as exc:
        print(f"⚠️  generate_pr_summaries failed: {exc}", file=sys.stderr)
        return (None, None)


def build_slack_payload(
    title: str,
    pr_url: str,
    repo: str,
    emoji: str,
    why: str,
    what: str,
) -> dict:
    """Build the Slack incoming-webhook Block Kit payload.

    Preserves the canonical format from smithers.py _build_slack_payload().
    When why and what are provided, includes Why/What context sections.
    Falls back to a minimal link + footer when either is missing.

    Args:
        title: PR title displayed as a bolded mrkdwn link
        pr_url: Full PR URL (linked in the title)
        repo: Repository name shown in the footer (e.g. 'mazedesignhq/maze-monorepo')
        emoji: Positive emoji for the sign-off line
        why: Why summary sentence, or empty string for fallback
        what: What summary sentence, or empty string for fallback

    Returns:
        Slack incoming webhook payload dict with Block Kit blocks.
    """
    mrkdwn_title = f"*<{pr_url}|:github: {title}>*"
    footer_text = f"📦 {repo} • Please take a look. Thanks! {emoji}"

    if why and what:
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Why?*\n{why}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*What?*\n{what}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": footer_text,
                    }
                ],
            },
        ]
    else:
        blocks = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": footer_text,
                    }
                ],
            }
        ]

    return {
        "text": mrkdwn_title,
        "mrkdwn": True,
        "attachments": [
            {
                "color": "#36a64f",
                "fallback": title,
                "blocks": blocks,
            }
        ],
    }


def post_to_webhook(webhook_url: str, payload: dict) -> None:
    """POST JSON payload to the Slack incoming webhook URL.

    Raises:
        urllib.error.HTTPError: On non-2xx HTTP responses.
        urllib.error.URLError: On network errors.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        response.read()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="smithers-post",
        description=(
            "Post a PR-ready-for-merge Slack notification with Block Kit formatting. "
            "Fetches PR metadata via gh CLI, generates Why/What summaries, "
            "and POSTs to SMITHERS_SLACK_WEBHOOK_URL."
        ),
        epilog=(
            "Examples:\n"
            "  smithers-post 123                  # Post PR #123\n"
            "  smithers-post https://github.com/org/repo/pull/123\n"
            "  smithers-post                      # Infer PR from current branch\n"
            "  smithers-post --no-summaries 123   # Skip haiku agent, use PR body\n\n"
            "Environment:\n"
            "  SMITHERS_SLACK_WEBHOOK_URL  Slack incoming webhook URL (required to post)\n\n"
            "Exit codes:\n"
            "  0  Posted successfully, or SMITHERS_SLACK_WEBHOOK_URL not set (graceful skip)\n"
            "  1  Post failed (network error, HTTP error, or unexpected exception)\n"
            "  2  Argument error (handled by argparse)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pr",
        nargs="?",
        metavar="PR",
        help="PR number, full URL, or omit to infer from current branch",
    )
    parser.add_argument(
        "--no-summaries",
        action="store_true",
        help=(
            "Skip haiku agent summary generation. "
            "Uses Why/What sections from the PR body if present, "
            "otherwise falls back to a minimal notification."
        ),
    )

    args = parser.parse_args()

    # Validate SMITHERS_SLACK_WEBHOOK_URL before doing any work
    webhook_url = os.environ.get("SMITHERS_SLACK_WEBHOOK_URL")
    if not webhook_url:
        print(
            "Warning: SMITHERS_SLACK_WEBHOOK_URL not set — skipping Slack post",
            file=sys.stderr,
        )
        sys.exit(0)

    if not webhook_url.startswith("https://hooks.slack.com/"):
        print(
            "Error: SMITHERS_SLACK_WEBHOOK_URL must start with https://hooks.slack.com/",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve PR URL and parse once
    pr_url = resolve_pr_url(args.pr)
    owner, repo_name, pr_number = parse_pr_url(pr_url)
    full_repo = f"{owner}/{repo_name}"

    # Fetch PR metadata
    pr_info = fetch_pr_info(pr_number)
    title = pr_info.get("title", "Unknown PR")
    body = pr_info.get("body", "") or ""

    # Determine Why/What summaries
    why = ""
    what = ""

    if not args.no_summaries:
        why, what = generate_pr_summaries(pr_number, pr_url, title)
        why = why or ""
        what = what or ""

    # Fall back to PR body sections if summaries not available
    if not (why and what):
        why = extract_section(body, "Why") or why
        what = extract_section(body, "What") or what
        # Also try "What This Does" heading (common PR template variant)
        if not what:
            what = extract_section(body, "What This Does")

    emoji = random.choice(POSITIVE_EMOJIS)
    payload = build_slack_payload(
        title=title,
        pr_url=pr_url,
        repo=full_repo,
        emoji=emoji,
        why=why,
        what=what,
    )

    try:
        post_to_webhook(webhook_url, payload)
    except urllib.error.HTTPError as exc:
        print(
            f"Error: Slack webhook returned HTTP {exc.code} for PR {pr_number}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(
            f"Error: Network error posting to Slack for PR {pr_number}: {exc.reason}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(
            f"Error: Unexpected error posting to Slack for PR {pr_number}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Posted to Slack for PR {pr_number} ({full_repo})")


if __name__ == "__main__":
    main()
