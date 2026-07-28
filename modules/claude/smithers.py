#!/usr/bin/env python3
"""
smithers: v3 PR watcher — foreground CLI (phase 1, cards 1-2)

Manually-started, foreground CLI that will own its own poll loop and watch a
single pull request to completion (§ Process model, .scratchpad/2967-v3-design.md).
Card 1 shipped the CLI skeleton, the fail-closed billing preflight, and a
minimal JSONL logging scaffold. Card 2 (this revision) adds the GitHub read
adapter: `PRSnapshot`, the immutable value object the gate reasons over, and
`fetch_pr_snapshot()`, which builds one from `gh pr view`, `gh pr checks`, and
`prc list`. The gate itself (`tick`) and the poll loop's body remain TODO
stubs for later phase-1 cards.

Usage:
    smithers watch <pr>             # Watch PR #<pr> (or full URL) in the foreground
    smithers watch <pr> --dry-run   # Skeleton-only: parses args, runs the
                                     # preflight, does not mutate anything
    smithers --help

Fully ephemeral: no state file, no schema, no persistence across a restart
(§ Architecture, State model). All state, once later cards add it, lives only
in this process's memory for the life of the run.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration (12-factor: env-var overrides bound to typed constants)
# ---------------------------------------------------------------------------

DEFAULT_LOG_PATH = os.environ.get(
    "SMITHERS_LOG_PATH",
    os.path.expanduser("~/.local/state/smithers/smithers.jsonl"),
)

# Environment variables that, if present, would silently route Claude Code
# billing to pay-as-you-go API rates instead of the subscription plan v3's
# whole economic case depends on (§ Policy risk, Hazard 1). Order mirrors
# Anthropic's documented credential-resolution precedence.
REFUSAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "AWS_BEARER_TOKEN_BEDROCK",
)

# NOTE: CLAUDE_CODE_OAUTH_TOKEN is deliberately NOT in REFUSAL_ENV_VARS. It is
# Anthropic's documented headless-auth mechanism for SUBSCRIPTION billing
# (generated via `claude setup-token`, intended for CI/scripts/launchd —
# exactly v3's own deployment shape), not a raw-API-billing signal. Refusing
# on it would break the exact billing mode v3 depends on: it would stop
# smithers from ever running under the one auth path Anthropic recommends for
# unattended, subscription-billed automation like this tool. Do not re-add it.


# ---------------------------------------------------------------------------
# Structured JSONL logging scaffold
# ---------------------------------------------------------------------------

def log_event(log_path: str, event_type: str, **fields: Any) -> None:
    """Append one JSON object per line to log_path: a timestamp, an event
    type, and whatever extra fields the caller supplies.

    Minimal by design (§ card scope) — later cards emit the poll loop, gate,
    and session-lifecycle messages through this same helper.
    """
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
    }
    record.update(fields)

    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Billing preflight (§ Policy risk, Hazard 1 — fail-closed, no override)
# ---------------------------------------------------------------------------

def billing_preflight(env: Dict[str, str], accept_api_billing: bool, log_path: str) -> None:
    """Fail-closed billing preflight.

    Runs as the very first operation of a watch — before any GitHub call,
    before state is read, and before the poll loop is ever entered. On
    detecting a credential environment variable that would route billing to
    pay-as-you-go API rates, logs the offending variable NAME ONLY (never its
    value) and exits non-zero without doing any work.

    There is no environment-variable override and no degraded mode. The only
    bypass is the explicit --i-accept-api-billing command-line flag, which
    the caller must pass deliberately (accept_api_billing=True here).
    """
    if accept_api_billing:
        return

    for var_name in REFUSAL_ENV_VARS:
        if env.get(var_name):
            _refuse_billing(var_name, log_path)


def _refuse_billing(var_name: str, log_path: str) -> None:
    """Log the offending variable NAME ONLY and exit non-zero. Refuse means
    refuse: no degraded mode, no warn-and-continue."""
    message = (
        f"billing preflight: {var_name} is set; refusing to run "
        "(would bill at raw API rates)"
    )
    log_event(log_path, "preflight_refused", var=var_name, message=message)
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# PRSnapshot — the immutable value object the gate reasons over (§ Ports and
# adapters, .scratchpad/2967-v3-design.md). Built fresh on every poll by the
# GitHub read adapter below; never mutated once constructed.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Approval:
    """One APPROVED review, sourced from `gh pr view --json latestReviews`."""

    author: str
    submitted_at: Optional[str]  # ISO8601, or None if the field was missing


@dataclass(frozen=True)
class CommentThread:
    """One unresolved comment thread, sourced from
    `prc list --format json --unresolved`.

    `type`, `in_reply_to_id`, and `reply_count` mirror `prc.py`'s own
    normalized comment schema byte-for-byte (`prc.py:210,226-227,242,258-259`)
    — added per peer review #3011 so the gate (a later card) can implement
    the actionable-bot-comment trigger's "not itself a reply, zero existing
    replies" predicate and the fix-loop-vs-merge-gate `--inline-only` split
    without reaching around this type. Like every other field here, a key
    entirely absent from the underlying JSON becomes an explicit `None`
    ("unknown") via `_get_field` — never silently defaulted (e.g.
    `reply_count` missing is `None`, not a fabricated `0`)."""

    thread_id: Optional[str]
    author: str
    url: Optional[str]
    type: Optional[str]  # "inline" (review thread comment) or "pr-level" (issue comment)
    in_reply_to_id: Optional[int]  # id of the comment this replies to; None if not a reply OR if missing
    reply_count: Optional[int]  # number of replies to this comment; None only if the field itself was missing


@dataclass(frozen=True)
class PRSnapshot:
    """Immutable snapshot of one pull request at one instant.

    Every field GitHub might not report is Optional and left as an explicit
    None ("unknown") rather than defaulted to a falsy value when the
    underlying JSON key is entirely absent — see `_get_field` below. An
    empty tuple, by contrast, is always a legitimate "genuinely zero of
    these" result (e.g. no unresolved threads), never a stand-in for a
    failed fetch — a fetch failure is a FetchFailure, never a PRSnapshot.
    """

    pr_number: int
    head_sha: Optional[str]
    is_draft: Optional[bool]
    mergeable: Optional[str]  # GitHub enum: MERGEABLE | CONFLICTING | UNKNOWN
    merge_state_status: Optional[str]  # GitHub enum: CLEAN | DIRTY | BLOCKED | BEHIND | ...

    # CI checks, bucketed by `gh pr checks --json bucket`'s own five values
    # (verified via `gh pr checks --help`: pass, fail, pending, skipping, cancel).
    checks_pass: Tuple[str, ...]
    checks_fail: Tuple[str, ...]
    checks_pending: Tuple[str, ...]
    checks_other: Tuple[str, ...]  # gh's "skipping"/"cancel" buckets — non-blocking
    checks_unknown: Tuple[str, ...]  # a check entry's own bucket field was missing/unrecognized

    review_decision: Optional[str]  # APPROVED | CHANGES_REQUESTED | REVIEW_REQUIRED | None
    approvals: Tuple[Approval, ...]

    # Unresolved threads, split by author kind so the gate can distinguish
    # bot from human noise (§ The gate, trigger 3). "unknown" holds threads
    # whose is_bot field was missing from prc's output — never silently
    # folded into "human".
    unresolved_bot_threads: Tuple[CommentThread, ...]
    unresolved_human_threads: Tuple[CommentThread, ...]
    unresolved_unknown_author_threads: Tuple[CommentThread, ...]

    # Always None in this adapter cut. `gh pr view --help`'s JSON FIELDS list
    # (checked locally) has no merge-queue field, so this is left as an
    # explicit unknown rather than guessed. A later card can add a dedicated
    # `mergeQueueEntry` GraphQL query (mirroring prc.py's run_gh_graphql
    # pattern) if § The gate trigger 4 (merge-queue eviction) needs it.
    merge_queue_state: Optional[str]


@dataclass(frozen=True)
class FetchFailure:
    """A typed, non-raised read-adapter failure.

    Distinguishes a genuine GitHub/tool API failure from a legitimate empty
    result (§ card scope, Error handling). An empty list of checks or
    comments is valid PRSnapshot data; a FetchFailure means the adapter could
    not get an answer from the underlying tool at all. Never raised past the
    adapter boundary — always returned as the second element of a
    (result, failure) tuple.
    """

    source: str  # e.g. "gh pr view", "gh pr checks", "prc list"
    message: str


# ---------------------------------------------------------------------------
# GitHub read adapter (§ Ports and adapters — reads only, never mutates)
# ---------------------------------------------------------------------------

def _get_field(data: Dict[str, Any], key: str, source: str, log_path: str) -> Any:
    """Defensive dict lookup.

    If `key` is entirely absent from `data`, logs a warning and returns None
    (an explicit unknown). If `key` is present but its own value is None or
    empty, that is the tool's own legitimate value and is returned as-is with
    no warning — the distinction is "field missing" versus "field present
    and genuinely empty/null".
    """
    if key not in data:
        log_event(log_path, "fetch_field_missing", source=source, field=key)
        return None
    return data[key]


def _run_json_command(cmd: List[str], source: str, log_path: str) -> Tuple[Optional[Any], Optional[FetchFailure]]:
    """Shell out to `cmd` and parse stdout as JSON.

    A non-zero exit code alone is NOT treated as a failure: e.g. `gh pr
    checks` legitimately exits non-zero when checks are pending or failing,
    and that is real PRSnapshot data, not an adapter error. Only a missing
    executable, or stdout that isn't valid non-empty JSON, becomes a
    FetchFailure — this is what keeps a genuine API/tool failure
    distinguishable from a legitimate "nothing found" result.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        failure = FetchFailure(source=source, message=f"{cmd[0]} not found on PATH")
        log_event(log_path, "fetch_failed", source=source, message=failure.message)
        return None, failure

    stdout = result.stdout.strip()
    if not stdout:
        message = result.stderr.strip() or f"exited {result.returncode} with no output"
        failure = FetchFailure(source=source, message=message)
        log_event(log_path, "fetch_failed", source=source, message=failure.message)
        return None, failure

    try:
        return json.loads(stdout), None
    except json.JSONDecodeError as e:
        failure = FetchFailure(source=source, message=f"could not parse JSON: {e}")
        log_event(log_path, "fetch_failed", source=source, message=failure.message)
        return None, failure


def _bucket_checks(checks: List[Dict[str, Any]], log_path: str) -> Dict[str, Tuple[str, ...]]:
    """Bucket `gh pr checks --json bucket,name,workflow` entries into pass /
    fail / pending / other (skipping, cancel) / unknown (missing or
    unrecognized bucket value)."""
    buckets: Dict[str, List[str]] = {"pass": [], "fail": [], "pending": [], "other": [], "unknown": []}
    known_other = {"skipping", "cancel"}

    for check in checks:
        name = _get_field(check, "name", "gh pr checks", log_path) or "<unnamed check>"
        bucket = _get_field(check, "bucket", "gh pr checks", log_path)
        if bucket in ("pass", "fail", "pending"):
            buckets[bucket].append(name)
        elif bucket in known_other:
            buckets["other"].append(name)
        else:
            log_event(log_path, "fetch_field_unexpected", source="gh pr checks", field="bucket", value=bucket)
            buckets["unknown"].append(name)

    return {key: tuple(names) for key, names in buckets.items()}


def _fetch_unresolved_threads(
    pr: str, log_path: str
) -> Tuple[Optional[Dict[str, Tuple[CommentThread, ...]]], Optional[FetchFailure]]:
    """Fetch unresolved comment threads via `prc list --format json
    --unresolved`, split into bot / human / unknown-author buckets."""
    data, failure = _run_json_command(
        ["prc", "list", pr, "--format", "json", "--unresolved"], "prc list", log_path
    )
    if failure:
        return None, failure

    comments = _get_field(data, "comments", "prc list", log_path) or []

    bot: List[CommentThread] = []
    human: List[CommentThread] = []
    unknown: List[CommentThread] = []

    for comment in comments:
        author = _get_field(comment, "author", "prc list", log_path) or "<unknown author>"
        thread_id = _get_field(comment, "thread_id", "prc list", log_path)
        url = _get_field(comment, "url", "prc list", log_path)
        is_bot = _get_field(comment, "is_bot", "prc list", log_path)
        thread_type = _get_field(comment, "type", "prc list", log_path)
        in_reply_to_id = _get_field(comment, "in_reply_to_id", "prc list", log_path)
        reply_count = _get_field(comment, "reply_count", "prc list", log_path)

        thread = CommentThread(
            thread_id=thread_id,
            author=author,
            url=url,
            type=thread_type,
            in_reply_to_id=in_reply_to_id,
            reply_count=reply_count,
        )
        if is_bot is True:
            bot.append(thread)
        elif is_bot is False:
            human.append(thread)
        else:
            unknown.append(thread)

    return {"bot": tuple(bot), "human": tuple(human), "unknown": tuple(unknown)}, None


def fetch_pr_snapshot(pr: str, log_path: str) -> Tuple[Optional[PRSnapshot], Optional[FetchFailure]]:
    """The GitHub read adapter (§ Ports and adapters).

    Builds an immutable PRSnapshot from `gh pr view`, `gh pr checks`, and
    `prc list` — read-only, never mutates the PR. Returns (snapshot, None) on
    success, or (None, FetchFailure) if any of the three underlying tools
    could not be reached or produced parseable output. Never raises past this
    boundary (§ card scope, Error handling); a caller gets a typed failure it
    can act on instead of an exception.
    """
    view_data, failure = _run_json_command(
        [
            "gh", "pr", "view", pr, "--json",
            "number,headRefOid,isDraft,mergeable,mergeStateStatus,reviewDecision,latestReviews",
        ],
        "gh pr view",
        log_path,
    )
    if failure:
        return None, failure

    pr_number = _get_field(view_data, "number", "gh pr view", log_path)
    if pr_number is None:
        return None, FetchFailure(source="gh pr view", message="response had no PR number")

    checks_data, failure = _run_json_command(
        ["gh", "pr", "checks", pr, "--json", "bucket,name,workflow"], "gh pr checks", log_path
    )
    if failure:
        return None, failure

    threads, failure = _fetch_unresolved_threads(pr, log_path)
    if failure:
        return None, failure

    check_buckets = _bucket_checks(checks_data, log_path)

    latest_reviews = _get_field(view_data, "latestReviews", "gh pr view", log_path) or []
    approvals = tuple(
        Approval(
            author=(_get_field(r, "author", "gh pr view", log_path) or {}).get("login", "<unknown>"),
            submitted_at=_get_field(r, "submittedAt", "gh pr view", log_path),
        )
        for r in latest_reviews
        if _get_field(r, "state", "gh pr view", log_path) == "APPROVED"
    )

    return (
        PRSnapshot(
            pr_number=pr_number,
            head_sha=_get_field(view_data, "headRefOid", "gh pr view", log_path),
            is_draft=_get_field(view_data, "isDraft", "gh pr view", log_path),
            mergeable=_get_field(view_data, "mergeable", "gh pr view", log_path),
            merge_state_status=_get_field(view_data, "mergeStateStatus", "gh pr view", log_path),
            checks_pass=check_buckets["pass"],
            checks_fail=check_buckets["fail"],
            checks_pending=check_buckets["pending"],
            checks_other=check_buckets["other"],
            checks_unknown=check_buckets["unknown"],
            review_decision=_get_field(view_data, "reviewDecision", "gh pr view", log_path),
            approvals=approvals,
            unresolved_bot_threads=threads["bot"],
            unresolved_human_threads=threads["human"],
            unresolved_unknown_author_threads=threads["unknown"],
            merge_queue_state=None,
        ),
        None,
    )


# ---------------------------------------------------------------------------
# TODO stubs — attachment points for later phase-1 cards. Not called yet.
# ---------------------------------------------------------------------------

def poll_loop(pr: str, config: Any, send: Callable[[Any], None], log_path: str) -> None:
    """TODO(phase1-card3+): the in-process poll loop — the composition root.

    Signature extended per peer review carry-forward (#3006 Finding 2): now
    carries `config` (resolved thresholds/intervals) and `send` (the same
    output port `tick()` already expects), mirroring `tick`'s own seam so a
    later card can fill in this body without another signature change.

    Will own the CLI's own sleep/tick cadence — 60s Active / 600s
    Approval-watch / exponential backoff on API errors (§ Poll loop and
    cadence) — fetch a PRSnapshot each iteration via fetch_pr_snapshot, build
    a TickRequest from in-memory State + config, call tick(req, send), and
    apply the resulting messages back into its own loop state. Runs entirely
    in plain code while idle; costs zero Claude tokens until the gate fires.
    """
    raise NotImplementedError("poll loop body lands in a later phase-1 card")


def tick(req: Any, send: Callable[[Any], None]) -> None:
    """TODO(phase1-card3): the pure gate handler.

    Signature mirrors § Ports and adapters: `Tick(req: TickRequest, send:
    Callable[[Message], None])`. Takes an immutable snapshot of prior State
    plus a fetched PRSnapshot and resolved Config; emits typed Messages
    (NoWorkNeeded, StartFixSession, DismissSession, Land, Disarm, Notify,
    Stop, UpdateState, Reschedule) through the send output port. Performs no
    I/O, mutates nothing, never raises (§ The gate).
    """
    raise NotImplementedError("gate lands in phase1-card3")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smithers",
        description=(
            "Smithers v3: a foreground CLI that watches one pull request to "
            "completion, polling GitHub in plain code and invoking Claude "
            "only when work is actually needed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_watch = sub.add_parser(
        "watch",
        help="Watch a single pull request in the foreground until it merges or stops",
        description=(
            "Watch a single pull request in the foreground until it merges,\n"
            "is stopped by a suppressor, or hits its attempt cap.\n\n"
            "Runs in a tmux pane and owns its own poll loop internally — this\n"
            "is not a daemon and does not persist state across a restart.\n\n"
            "Example:\n"
            "  smithers watch 123\n"
            "  smithers watch 123 --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_watch.add_argument(
        "pr",
        metavar="PR",
        help="PR number or full URL to watch",
    )
    p_watch.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse arguments and run the billing preflight only; do not poll or mutate anything",
    )
    p_watch.add_argument(
        "--i-accept-api-billing",
        action="store_true",
        default=False,
        dest="accept_api_billing",
        help=(
            "Explicit bypass for the billing preflight. There is no environment-"
            "variable override — this flag is the only way to run with a "
            "credential environment variable present that would bill at raw API rates."
        ),
    )
    p_watch.add_argument(
        "--log-file",
        metavar="PATH",
        default=DEFAULT_LOG_PATH,
        help=f"JSONL log destination (default: {DEFAULT_LOG_PATH} or $SMITHERS_LOG_PATH)",
    )

    return parser


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

def cmd_watch(args: argparse.Namespace) -> int:
    billing_preflight(dict(os.environ), args.accept_api_billing, args.log_file)

    log_event(args.log_file, "watch_started", pr=args.pr, dry_run=args.dry_run)

    if args.dry_run:
        print(f"smithers watch: dry run for PR {args.pr!r} — preflight passed, no further action taken")
        return 0

    # TODO(phase1-card3+): poll_loop(args.pr, config, send, args.log_file)
    print(
        f"smithers watch: skeleton only for PR {args.pr!r} — "
        "poll loop and gate land in later phase-1 cards"
    )
    return 0


def main(argv: Optional[list] = None) -> int:
    """Entry point. `watch` is currently the only subcommand, and
    `add_subparsers(..., required=True)` guarantees `args.command == "watch"`
    by the time parsing succeeds — there is no second command to fall through
    to, so there is deliberately no fallback branch here (peer review #3006
    Finding 4 flagged the previous `else: parser.print_help(); return 1`
    branch as dead code no test could ever reach; removed rather than kept
    as untested filler)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return cmd_watch(args)


if __name__ == "__main__":
    sys.exit(main())
