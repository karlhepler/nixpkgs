#!/usr/bin/env python3
"""
pr-slack-post: Post a PR completion notification to Slack webhook.

One-shot deduplication: writes a marker file on successful post so the same PR
is never posted twice across sessions. Use --force to bypass the marker check.

Reads SMITHERS_SLACK_WEBHOOK_URL from environment. Silently exits (code 0) when
the webhook URL is not set — matches the original smithers behavior.
"""

import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


POSITIVE_EMOJIS = ["😊", "🙏", "✨", "🎉", "🚀", "🙌", "🤝", "👏", "🎊"]


def marker_path(pr_number: int) -> Path:
    """Return the dedup marker file path for a given PR number."""
    return Path(".scratchpad") / f"pr-slack-posted-{pr_number}.flag"


def build_slack_payload(
    title: str,
    pr_url: str,
    repo: str,
    emoji: str,
    why: str,
    what: str,
) -> dict:
    """Build the Slack incoming-webhook payload.

    Preserves the canonical format from smithers.py _build_slack_payload().
    When why and what are provided, includes Why/What context sections.
    Falls back to a minimal link + footer when either is missing.
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
        status = response.getcode()
        if status < 200 or status >= 300:
            raise urllib.error.HTTPError(
                webhook_url, status, f"Non-2xx response: {status}", {}, None
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pr-slack-post",
        description=(
            "Post a PR completion notification to Slack. "
            "Deduplicates across sessions using a .scratchpad marker file."
        ),
    )
    parser.add_argument(
        "--pr",
        required=True,
        type=int,
        metavar="N",
        help="PR number (required)",
    )
    parser.add_argument(
        "--pr-url",
        required=True,
        metavar="URL",
        help="Full PR URL (e.g. https://github.com/org/repo/pull/123)",
    )
    parser.add_argument(
        "--title",
        required=True,
        metavar="TEXT",
        help="PR title",
    )
    parser.add_argument(
        "--repo",
        required=True,
        metavar="NAME",
        help="Repository name shown in the footer (e.g. my-repo)",
    )
    parser.add_argument(
        "--why",
        default="",
        metavar="TEXT",
        help="One-sentence Why summary (intent / problem / background)",
    )
    parser.add_argument(
        "--what",
        default="",
        metavar="TEXT",
        help="One-sentence What summary (implementation approach)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the dedup marker check and repost even if already posted",
    )

    args = parser.parse_args()

    # Dedup check
    marker = marker_path(args.pr)
    if marker.exists() and not args.force:
        print(
            f"Already posted for PR {args.pr}; use --force to repost",
            file=sys.stderr,
        )
        sys.exit(0)

    # Webhook URL check
    webhook_url = os.environ.get("SMITHERS_SLACK_WEBHOOK_URL")
    if not webhook_url:
        print(
            "Warning: SMITHERS_SLACK_WEBHOOK_URL not set — skipping Slack post",
            file=sys.stderr,
        )
        sys.exit(0)

    emoji = random.choice(POSITIVE_EMOJIS)
    payload = build_slack_payload(
        title=args.title,
        pr_url=args.pr_url,
        repo=args.repo,
        emoji=emoji,
        why=args.why,
        what=args.what,
    )

    try:
        post_to_webhook(webhook_url, payload)
    except urllib.error.HTTPError as exc:
        print(
            f"Error: Slack webhook returned HTTP {exc.code} for PR {args.pr}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(
            f"Error: Network error posting to Slack for PR {args.pr}: {exc.reason}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(
            f"Error: Unexpected error posting to Slack for PR {args.pr}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Write dedup marker on successful post
    marker.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    marker.write_text(ts + "\n")

    print(f"Posted to Slack for PR {args.pr}")


if __name__ == "__main__":
    main()
