#!/usr/bin/env python3
"""
smithers: v3 PR watcher — foreground CLI (phase 1, cards 1-4 + PR auto-detect)

Manually-started, foreground CLI that will own its own poll loop and watch a
single pull request to completion (§ Process model, .scratchpad/2967-v3-design.md).
Card 1 shipped the CLI skeleton, the fail-closed billing preflight, and a
minimal JSONL logging scaffold. Card 2 added the GitHub read adapter:
`PRSnapshot`, the immutable value object the gate reasons over, and
`fetch_pr_snapshot()`, which builds one from `gh pr view`, `gh pr checks`, and
`prc list`. Card 3 added the `Message` union and the pure `tick` gate handler
with its five TRIGGERS. Card 4 added the gate's six SUPPRESSORS. Card 3019
added PR auto-detection from the current git worktree. This revision (card
3021) wires the foreground poll loop itself — preflight, fetch, tick, and
send, on a bounded cadence — completing phase 1 (§ Build plan, phase 1). Fix
execution (invoking Claude) is a clearly-marked stub owned by phase 3. Card
3027 closes a peer-review finding: the three TERMINAL gate suppressors
(fix/cycle budget exhausted, stagnated) now emit `Stop{reason}` instead of a
silent `NoWorkNeeded`, and the poll loop exits on `Stop` rather than
spinning forever, structurally incapable of ever acting again. Card 3031
adds cross-restart Slack dedup with no local state file: `notify_slack` now
asks Slack itself, via a narrowly-scoped headless Claude invocation
(`query_slack_dedup`), whether a post about this PR already exists before
posting — replacing the old in-run-only in-memory dedup, which never
survived a restart. Card 3032 replaces the phase-3 fix-execution stub with
a real one: `_invoke_fix_session` blocks on `staff -p --model sonnet
--effort high --permission-mode dontAsk`, wrapped in an external wall-clock
ceiling that kills the whole process tree on expiry; `poll_loop` now builds
a bounded task brief from the `PRSnapshot` per attempt and advances the
gate's own `fix_count`/`stagnation_count` counters as attempts complete —
closing the loop from detection to repair. Card 3046 closes the last seam
gap: `execute_land` is the GitHub mutation adapter that actually runs `gh pr
merge` for a `Land` message (nothing executed it before this card, even
though `tick` already emitted it), and `execute_disarm` is its safety
counterpart — `tick` now emits `Disarm` on every terminal path (landing, and
every TERMINAL-suppressor `Stop` alike), and `execute_disarm` permanently
revokes merge authority for the rest of the process once it fires, so a
later stale `Land` can never merge a PR the watch has already stopped
watching. Both adapters are bound in `build_send` alongside the others.
Card 3052 adds two more closing pieces. `sweep_threads`/`replied_and_resolved`
give Smithers a way to actually CLOSE a bot thread out — reply and resolve as
one atomic action via `prc reply`/`prc resolve`, never a partial success —
and `_is_ready_to_land` now hard-blocks landing while any actionable bot
thread remains unresolved. Separately, `_is_approval_watch_cadence` lets
`poll_loop` fall back to a slower `APPROVAL_WATCH_POLL_SECONDS` cadence while
a PR is clean and merely waiting on a human reviewer, reverting to the normal
cadence the moment that stops being true. Card 3060 closes four findings from
a security audit of this file. `tick` now checks `_held(req)` — a coordinator
hold or manual-merge opt-out — BEFORE ever emitting `Land`, even when the
snapshot is otherwise fully ready to land: previously ready-to-land bypassed
every suppressor including the operator's own hold, locked in by a since-
deleted test. `_sanitize_for_brief` neutralizes every externally-sourced
string (failing CI check names, thread author/URL) before it is interpolated
into the fix session's task brief — a CI check's displayed name is
attacker-controlled, so this closes a concrete prompt-injection path.
`_invoke_fix_session` now hands the fix session subprocess an explicit,
filtered environment (`_build_fix_session_env`/`FIX_SESSION_ENV_ALLOWLIST`)
instead of silently inheriting the operator's entire shell, and `FIX_SESSION_
CMD` now carries mechanically-enforced `--disallowedTools` deny rules for
`gh pr merge`/`kubectl`/`aws`/`gcloud`, marking the session with
`SMITHERS_FIX_SESSION=1` for a future scoped `PreToolUse` hook — making
`FIX_SESSION_CONSTRAINTS`'s prose enforceable rather than merely requested.
Card 3068 closes a peer-review finding (.scratchpad/smithers-devex-review.md
Finding 1): `sweep_threads` was fully implemented, unit-tested, and never
called from `poll_loop` — the third instance of this file's built-but-
unwired defect class, after `Notify` and `Land`. `poll_loop` now calls
`sweep_threads` every cycle, immediately before the gate evaluates this same
cycle's `TickRequest`, so a thread it closes out can never also re-fire
Trigger 3 or block Trigger 5 in that same tick. Separately, `--no-merge` is
a new CLI flag giving an operator a real, reachable way to set
`manual_merge_opt_out` (§ audit Finding 2) — previously correct in `_held`
but unreachable from the real binary. `coordinator_hold` had the identical
unreachability problem with no legitimate caller of its own to wire it to;
it is removed from `TickRequest`/`_held` rather than left dangling (YAGNI —
a speculative "some other process pauses this watch" caller can be added
once one actually exists).

Usage:
    smithers                        # Auto-detect the PR for the current git
                                     # branch and watch it in the foreground
    smithers <pr>                   # Watch PR #<pr> (or full URL) instead of
                                     # auto-detecting
    smithers watch <pr>             # Equivalent to `smithers <pr>` — kept for
                                     # backward compatibility, not required
    smithers --dry-run              # Skeleton-only: parses args, runs the
                                     # preflight and PR resolution, does not
                                     # poll or mutate anything
    smithers --help

Fully ephemeral: no state file, no schema, no persistence across a restart
(§ Architecture, State model). All state, once later cards add it, lives only
in this process's memory for the life of the run.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


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
# (generated via `claude setup-token`, intended for CI/scripts/other
# unattended automation), not a raw-API-billing signal. Refusing
# on it would break the exact billing mode v3 depends on: it would stop
# smithers from ever running under the one auth path Anthropic recommends for
# unattended, subscription-billed automation like this tool. Do not re-add it.

# Cross-restart Slack dedup (§ query_slack_dedup, § notify_slack) — the exact
# MCP tool name the dedup probe is allowlisted to, PER INVOCATION, via
# `--allowedTools`. Verified against `claude --help`'s documented
# `mcp__<server>__<tool>` naming convention (already established elsewhere in
# this codebase, e.g. `mcp__context7__resolve-library-id` in
# global/CLAUDE.md) — never assumed to generalize from the Bash/file-tool
# examples in `claude --help`'s own usage text.
SLACK_SEARCH_TOOL = "mcp__claude_ai_Slack__slack_search_public"

# Wall-clock bound on the dedup probe (§ query_slack_dedup, "bound the
# cost") — a scoped, allowlisted call should complete in 1-2 turns; this
# caps the worst case (a hung invocation) rather than letting a single tick
# block the poll loop indefinitely.
SLACK_DEDUP_TIMEOUT_SECONDS = int(os.environ.get("SMITHERS_SLACK_DEDUP_TIMEOUT_SECONDS", "45"))

# Approval-watch cadence (card 3052, § APPROVAL-WATCH CADENCE;
# `_is_approval_watch_cadence`, `poll_loop`) — the slower polling interval
# used while a PR is clean and merely waiting on a human reviewer
# (§ `_is_clean_awaiting_review`). Polling at the ordinary Active-tier
# baseline (`PollLoopConfig.poll_interval_seconds`, 60s) buys nothing in this
# state: nothing Smithers does makes a human approve faster, and every extra
# poll is a pure GitHub API round trip. 900s (15 minutes) is a full order of
# magnitude slower than the 60s baseline, and still gets Smithers back to
# work well within one work session of a review landing.
APPROVAL_WATCH_POLL_SECONDS = int(os.environ.get("SMITHERS_APPROVAL_WATCH_POLL_SECONDS", "900"))

# Trigger 3's exclusion list (§ The gate, trigger 3; .scratchpad/2967-v3-
# design.md:81 — "an unfiltered 'any bot comment' trigger fires on
# informational bot noise with no way to suppress it, which is exactly the
# false-positive class the Node implementation's allowlist exists to
# prevent"). Kept deliberately small and conservative
# (.scratchpad/3033-swe-devex-review.md Finding 4): a bot wrongly excluded
# here silently drops genuine feedback, which is worse than one spurious fix
# invocation. Override via SMITHERS_INFORMATIONAL_BOT_AUTHORS
# (comma-separated) or --informational-bot-authors, which both win over this
# default (§ _resolve_informational_bot_authors).
DEFAULT_INFORMATIONAL_BOT_AUTHORS: Tuple[str, ...] = ("codecov[bot]",)


def _resolve_informational_bot_authors(
    explicit: Optional[str], env: Dict[str, str]
) -> Tuple[str, ...]:
    """Resolve the Trigger 3 exclusion list. Precedence: the explicit
    `--informational-bot-authors` CLI flag, then
    `SMITHERS_INFORMATIONAL_BOT_AUTHORS` (comma-separated, whitespace
    trimmed, empty entries dropped), then `DEFAULT_INFORMATIONAL_BOT_AUTHORS`.
    An explicit value that parses to zero authors (empty string, or only
    commas/whitespace) falls back to the default rather than silently
    disabling the exclusion list."""
    raw = explicit if explicit is not None else env.get("SMITHERS_INFORMATIONAL_BOT_AUTHORS")
    if raw is None:
        return DEFAULT_INFORMATIONAL_BOT_AUTHORS
    authors = tuple(a.strip() for a in raw.split(",") if a.strip())
    return authors if authors else DEFAULT_INFORMATIONAL_BOT_AUTHORS


# Fix execution (§ Fix execution, § Failure modes,
# .scratchpad/2967-v3-design.md) — the external wall-clock ceiling on ONE
# blocking fix-session invocation. "Proposed: 20 minutes — wider than a bare
# one-shot prompt would need, since the staff-engineer persona's own
# review/delegation apparatus takes real time" (§ Failure modes). The CLI
# kills the subprocess's entire process tree if this is exceeded and records
# the attempt as failed — never as a crash.
FIX_INVOCATION_TIMEOUT_SECONDS = int(os.environ.get("SMITHERS_FIX_INVOCATION_TIMEOUT_SECONDS", "1200"))

# The settled fix-session invocation (§ How the CLI starts the fix). `-p`,
# `--model sonnet`, `--effort high`, and `--permission-mode dontAsk` are
# explicit user decisions — not defaults this module infers — and must never
# be substituted. `staff.bash` execs `claude ... "$@"`, so these, appended
# last, cleanly override its own `opus[1m]`/`xhigh`/`auto` defaults
# (`modules/claude/staff.bash:12-17`) with no change to `staff.bash` itself.
# `--output-format json` is layered on top so the cost estimate and session
# id can be logged (§ Output parsing and trust) — it is not one of the four
# settled tokens above, and nothing in its payload is ever allowed to drive
# a decision; the prompt itself goes via stdin, never as a trailing argument.
#
# `--disallowedTools` (§ audit Finding 3 — BLOCKING; card 3060 Fix 4) makes
# `FIX_SESSION_CONSTRAINTS`'s prose ("do NOT merge", "no cluster/secrets/
# IAM/system operations") mechanically enforced rather than something the
# fix session merely chooses to honor — belt and braces with the prose, not
# a replacement for it: the prose tells a cooperative model what not to do,
# these deny rules stop an uncooperative or injected one (§ Fix 2, prompt
# injection reaching this same session via CI check names). Verified against
# Claude Code 2.1.220 (`.scratchpad/smithers-tool-restriction-research.md`):
# a `Bash(...)` deny rule is a hard floor in EVERY permission mode, including
# `bypassPermissions`, so it is not weakened by `--permission-mode dontAsk`
# above; it matches each subcommand of a compound `&&`-chained command
# independently, so chaining can't smuggle a denied command past it; and
# `Bash(gh pr merge *)` requires a word boundary after "merge", so it does
# NOT match a bare, argument-less `gh pr merge` — `Bash(gh pr merge)` is the
# separate, exact-match rule that closes that gap. `kubectl`/`aws`/`gcloud`
# don't need the same two-rule treatment: every realistic invocation carries
# a subcommand argument, so a bare `Bash(<tool> *)` already blocks "every
# matching call" per the same research.
FIX_SESSION_CMD: Tuple[str, ...] = (
    "staff", "-p",
    "--model", "sonnet",
    "--effort", "high",
    "--permission-mode", "dontAsk",
    "--output-format", "json",
    "--disallowedTools",
    "Bash(gh pr merge) Bash(gh pr merge *) Bash(kubectl *) Bash(aws *) Bash(gcloud *)",
)

# Safety constraints carried into every fix session's task brief (§ Security
# and safety constraints; § How the CLI starts the fix). Also the vehicle for
# the no-delegation instruction: a PreToolUse hook denies cardless Agent-tool
# delegation, so a fix session that tries to delegate burns turns on denials
# before giving up — telling it not to bother saves that cost outright.
FIX_SESSION_CONSTRAINTS = (
    "Constraints for this session:\n"
    "- Do the work directly yourself. Do NOT delegate any part of it via "
    "the Agent tool — a PreToolUse hook denies cardless Agent-tool "
    "delegation for this invocation, so any attempt to delegate will only "
    "burn turns on denials before giving up.\n"
    "- No cluster, secrets, IAM, database, or system operations.\n"
    "- Do NOT merge this pull request under any circumstance. Merging is "
    "the watching CLI's own decision, re-derived from a fresh GitHub read "
    "on its next poll — never this session's."
)


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
    `reply_count` missing is `None`, not a fabricated `0`).

    `comment_id` (card 3052, § THREAD SWEEP WITH ATOMIC REPLY-AND-RESOLVE)
    is `prc.py`'s own `id`/`databaseId` field (`prc.py:208,240`) — the
    integer `prc reply <comment_id>` expects. Deliberately distinct from
    `thread_id`, which is the GraphQL node id `prc resolve <thread_id>`
    expects: a sweep needs BOTH to close a thread out atomically."""

    thread_id: Optional[str]
    author: str
    url: Optional[str]
    type: Optional[str]  # "inline" (review thread comment) or "pr-level" (issue comment)
    in_reply_to_id: Optional[int]  # id of the comment this replies to; None if not a reply OR if missing
    reply_count: Optional[int]  # number of replies to this comment; None only if the field itself was missing
    comment_id: Optional[int] = None  # prc.py's own "id" (databaseId) — what `prc reply` addresses


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
# PR resolution (§ card 3019) — bare `smithers` auto-detects the PR for the
# current git worktree/branch; an explicit PR number or URL always overrides.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolutionFailure:
    """A typed, non-raised failure explaining why smithers could not resolve
    a PR to watch (§ card scope, Error handling). Never raised past
    `resolve_pr` — a caller gets a typed failure with a specific reason it
    can print a clear, actionable message for, never a stack trace."""

    reason: str  # "not_a_git_repo" | "gh_unavailable" | "gh_unauthenticated" | "no_pr_for_branch" | "gh_error"
    message: str


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    """Thin subprocess.run wrapper: capture output as text, never raise on a
    non-zero exit (the caller inspects returncode itself). Deliberately does
    NOT catch FileNotFoundError — callers that need to distinguish "binary
    not on PATH" from any other failure do that at the call site (see
    resolve_pr's gh auth status call)."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _resolution_failed(reason: str, message: str, log_path: str) -> ResolutionFailure:
    log_event(log_path, "resolve_pr_failed", reason=reason, message=message)
    return ResolutionFailure(reason=reason, message=message)


def resolve_pr(explicit_pr: Optional[str], log_path: str) -> Tuple[Optional[str], Optional[ResolutionFailure]]:
    """Resolve the PR identifier smithers should watch (§ card 3019, § How to
    start a watch).

    If `explicit_pr` is truthy (a PR number or a full PR URL passed on the
    command line), it always wins — returned unchanged with no resolution
    attempted, no git/gh calls made at all.

    Otherwise, auto-detects the PR belonging to the current git branch:
    confirms the working directory is inside a git repository, confirms `gh`
    is on PATH and authenticated, then asks `gh pr view --json number,url`
    with NO pr argument — this is `gh`'s own documented behavior (verified
    via `gh pr view --help`: "Without an argument, the pull request that
    belongs to the current branch is displayed"), not a smithers-invented
    convention.

    Never raises past this boundary — every failure returns a typed
    ResolutionFailure with a distinct reason instead (§ card scope, Error
    handling), so a caller can print a clear message rather than a stack
    trace for each of: not in a git repo, gh missing, gh unauthenticated, no
    PR exists for this branch, or any other gh error.
    """
    if explicit_pr:
        return explicit_pr, None

    repo_check = _run(["git", "rev-parse", "--is-inside-work-tree"])
    if repo_check.returncode != 0:
        return None, _resolution_failed(
            "not_a_git_repo",
            "not inside a git repository — cd into a repo with a pull request, "
            "or pass a PR number/URL explicitly",
            log_path,
        )

    try:
        auth_check = _run(["gh", "auth", "status"])
    except FileNotFoundError:
        return None, _resolution_failed(
            "gh_unavailable",
            "gh is not installed or not on PATH — install the GitHub CLI, "
            "or pass a PR number/URL explicitly",
            log_path,
        )

    if auth_check.returncode != 0:
        return None, _resolution_failed(
            "gh_unauthenticated",
            "gh is not authenticated — run `gh auth login`, or pass a PR number/URL explicitly",
            log_path,
        )

    view = _run(["gh", "pr", "view", "--json", "number,url"])
    if view.returncode != 0:
        stderr = view.stderr.strip()
        if "no pull requests found" in stderr.lower():
            return None, _resolution_failed(
                "no_pr_for_branch",
                "no pull request found for the current branch — open one first, "
                f"or pass a PR number/URL explicitly ({stderr or 'gh reported no PR'})",
                log_path,
            )
        return None, _resolution_failed(
            "gh_error",
            stderr or f"gh pr view exited {view.returncode} with no output",
            log_path,
        )

    try:
        data = json.loads(view.stdout)
    except json.JSONDecodeError as e:
        return None, _resolution_failed(
            "gh_error", f"could not parse gh pr view output: {e}", log_path
        )

    number = data.get("number")
    if number is None:
        return None, _resolution_failed(
            "gh_error", "gh pr view response had no PR number", log_path
        )

    return str(number), None


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
        comment_id = _get_field(comment, "id", "prc list", log_path)

        thread = CommentThread(
            thread_id=thread_id,
            author=author,
            url=url,
            type=thread_type,
            in_reply_to_id=in_reply_to_id,
            reply_count=reply_count,
            comment_id=comment_id,
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
# Message union (§ Ports and adapters) — the pure handler's own output
# vocabulary. Frozen, stdlib-only. The composition root (`poll_loop`, below)
# fans these out to adapters (GitHub mutation, session lifecycle,
# notification, state update, scheduler, structured log, test spy).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoWorkNeeded:
    """No trigger fired this tick (or nothing actionable). Nothing to do."""


@dataclass(frozen=True)
class StartFixSession:
    """Invoke Claude: a trigger fired and (once a later card adds them) no
    suppressor blocked it. `brief` construction — the actual prompt handed
    to the fix session — is owned by the fix-execution card; this trigger
    only decides *that* a session should start, not what to tell it."""

    name: str
    brief: str


@dataclass(frozen=True)
class DismissSession:
    name: str
    outcome: str


@dataclass(frozen=True)
class Land:
    method: str


@dataclass(frozen=True)
class Disarm:
    reason: str


@dataclass(frozen=True)
class Notify:
    title: str
    body: str
    sound: bool


@dataclass(frozen=True)
class Stop:
    reason: str


@dataclass(frozen=True)
class UpdateState:
    next: Any


@dataclass(frozen=True)
class Reschedule:
    interval_seconds: int


Message = Union[
    NoWorkNeeded,
    StartFixSession,
    DismissSession,
    Land,
    Disarm,
    Notify,
    Stop,
    UpdateState,
    Reschedule,
]


# ---------------------------------------------------------------------------
# The gate's TRIGGERS (§ The gate) — pure predicates over a PRSnapshot. See
# further below for the six SUPPRESSORS, evaluated by `tick` after a trigger
# fires: any one of them can still block invocation.
# ---------------------------------------------------------------------------

def _has_failing_check(snapshot: PRSnapshot) -> bool:
    """Trigger 1: at least one CI check is in a `fail` bucket."""
    return len(snapshot.checks_fail) > 0


def _has_merge_conflict(snapshot: PRSnapshot) -> bool:
    """Trigger 2: the PR has merge conflicts with its base."""
    return snapshot.mergeable == "CONFLICTING"


def _is_actionable_bot_thread(thread: CommentThread, informational_bot_authors: Tuple[str, ...]) -> bool:
    """Trigger 3's per-thread predicate — v1's `isActionableBotComment()`
    (VERIFIED at `2962-researcher-review.md`, gap-analysis table; see
    .scratchpad/2967-v3-design.md § The gate): not on the informational-bot
    exclusion list, not itself a reply, and with zero existing replies.
    (Bot authorship itself is already established by the caller only ever
    passing threads from `unresolved_bot_threads`.)

    `reply_count` of `None` means UNKNOWN (`prc list` didn't report the
    field) and is deliberately NOT treated as zero — an unproven reply count
    must not silently read as "definitely no replies", so an unknown thread
    is conservatively treated as not-yet-actionable rather than risking a
    duplicate fix invocation on a thread that may already have a reply.
    Only a confirmed `reply_count == 0` counts as "zero existing replies".
    """
    if thread.author in informational_bot_authors:
        return False
    if thread.in_reply_to_id is not None:
        return False
    return thread.reply_count == 0


def _has_actionable_bot_comment(snapshot: PRSnapshot, informational_bot_authors: Tuple[str, ...]) -> bool:
    """Trigger 3: at least one actionable bot comment exists."""
    return any(
        _is_actionable_bot_thread(thread, informational_bot_authors)
        for thread in snapshot.unresolved_bot_threads
    )


def _merge_queue_evicted(prior_merge_queue_state: Optional[str], current_merge_queue_state: Optional[str]) -> bool:
    """Trigger 4: a previously-confirmed merge-queue entry has bounced to
    null before the PR merged (v2's merge-queue-eviction case, `SKILL.md:374`)
    — treated as a CI failure rather than silently re-enqueued.

    Structurally unreachable today, by construction rather than by a guard
    clause: `fetch_pr_snapshot` hard-codes `merge_queue_state=None` on every
    real snapshot (no `gh pr view --json` field exposes it — see
    `PRSnapshot`'s own docstring), and `TickRequest.prior_merge_queue_state`
    defaults to `None` with nothing yet writing anything else into it
    (`poll_loop`, the only future writer of that field, is still a
    `NotImplementedError` stub — see `TestPhaseStubsExist`). Both sides of
    the AND below are therefore always `None` in real usage today, so this
    predicate always evaluates to False through the real code path. It
    requires NO further code change to start firing correctly the moment a
    later card wires a real prior-confirmed value in — see
    `TestMergeQueueEvictionTrigger` in test_smithers.py, which locks in both
    the "fires once wired" behavior and today's unreachability.
    """
    return prior_merge_queue_state is not None and current_merge_queue_state is None


def _is_ready_to_land(snapshot: PRSnapshot, informational_bot_authors: Tuple[str, ...]) -> bool:
    """Trigger 5: the PR is fully satisfied and ready to land — routes to
    the deterministic land action, not a Claude invocation.

    A minimal readiness predicate over the fields this card's PRSnapshot
    carries: not a draft, at least one check exists and every existing
    check is in the `pass` bucket (none failing/pending/unknown), the
    branch is cleanly mergeable, and the review decision is APPROVED. v1's
    debounced "confirmed clean" wait (`CleanConfirmedAt`, § State model) is
    owned by a later card — this predicate answers only "is the snapshot
    clean right now", with no debounce.

    Unresolved bot threads are a HARD merge blocker (card 3052, § THREAD
    SWEEP WITH ATOMIC REPLY-AND-RESOLVE): reuses `_has_actionable_bot_comment`
    — the SAME predicate Trigger 3 uses — evaluated over the snapshot's own
    FULL `unresolved_bot_threads` tuple as fetched, never a filtered or
    partial view, so readiness can never be inferred from an incomplete
    listing. Any actionable bot thread blocks landing outright, even when
    every other readiness condition below is otherwise satisfied.
    """
    if snapshot.is_draft:
        return False
    if not snapshot.checks_pass:
        return False
    if snapshot.checks_fail or snapshot.checks_pending or snapshot.checks_unknown:
        return False
    if snapshot.mergeable != "MERGEABLE":
        return False
    if snapshot.merge_state_status != "CLEAN":
        return False
    if _has_actionable_bot_comment(snapshot, informational_bot_authors):
        return False
    return snapshot.review_decision == "APPROVED"


# ---------------------------------------------------------------------------
# The gate's SUPPRESSORS (§ The gate) — pure predicates over a TickRequest.
# Any one of the six blocks invocation even when a trigger fires. The billing
# preflight is deliberately NOT one of these: it runs ahead of `tick` entirely
# (§ Policy risk, Hazard 1), never as a suppressor evaluated here.
# ---------------------------------------------------------------------------

def _fix_budget_exhausted(req: "TickRequest") -> bool:
    """Suppressor 1: fix_count >= max_fix_invocations (v2's
    max_ralph_invocations, default 4)."""
    return req.fix_count >= req.max_fix_invocations


def _cycle_budget_exhausted(req: "TickRequest") -> bool:
    """Suppressor 2: cycle >= max_cycles (default 10, from v2)."""
    return req.cycle >= req.max_cycles


def _stagnated(req: "TickRequest") -> bool:
    """Suppressor 3: stagnation_count >= 2 — HEAD did not advance across two
    consecutive fix cycles (v2 Step 13)."""
    return req.stagnation_count >= 2


def _only_pending_checks_and_nothing_else_actionable(req: "TickRequest") -> bool:
    """Suppressor 4: every check is still pending and nothing else is
    actionable — v1's early-exit branch, which skipped the gate entirely
    rather than evaluating it. Mirrors the negation of every other trigger
    condition so pending-only checks never fall through to an action."""
    snapshot = req.pr_snapshot
    if not snapshot.checks_pending:
        return False
    if snapshot.checks_fail:
        return False
    if _has_merge_conflict(snapshot):
        return False
    if _has_actionable_bot_comment(snapshot, req.informational_bot_authors):
        return False
    if _merge_queue_evicted(req.prior_merge_queue_state, snapshot.merge_queue_state):
        return False
    return True


def _held(req: "TickRequest") -> bool:
    """Suppressor 5: a manual-merge opt-out is recorded in state (§ card
    3068 Fix 2 — the operator's `--no-merge` flag, wired through `poll_loop`
    onto `TickRequest.manual_merge_opt_out`). `coordinator_hold` used to be
    checked here too, but had no caller anywhere that could ever set it to
    True in the real binary — removed rather than left permanently
    unreachable (§ module docstring, card 3068)."""
    return req.manual_merge_opt_out


def _fix_session_in_flight(req: "TickRequest") -> bool:
    """Suppressor 6: the in-memory active_fix_session record is non-null and
    not yet cleared — a fix session is already in flight for this PR (§ Fix
    execution, Concurrency guard). Genuinely distinct from fix_count: that
    counter only increments on a failed/dismissed attempt, never on session
    start, so on its own it cannot stop a second StartFixSession from firing
    while a first session is still successfully working."""
    return req.active_fix_session is not None


def _suppressed(req: "TickRequest") -> bool:
    """Any one of the six suppressors blocks invocation (§ The gate)."""
    return (
        _fix_budget_exhausted(req)
        or _cycle_budget_exhausted(req)
        or _stagnated(req)
        or _only_pending_checks_and_nothing_else_actionable(req)
        or _held(req)
        or _fix_session_in_flight(req)
    )


# ---------------------------------------------------------------------------
# Terminal vs. transient suppressors (§ The gate; card 3027 peer-review
# finding). The six suppressors above split into two kinds:
#
#   TERMINAL — represents permanent exhaustion of a bounded resource for this
#   watch. `cycle`, `fix_count`, and `stagnation_count` are all monotonically
#   non-decreasing for the life of a watch (poll_loop only ever increments
#   them), so once one of these three trips, EVERY future tick is doomed to
#   be suppressed the same way forever. Silently emitting NoWorkNeeded on
#   every subsequent tick would leave the watch looking alive (the pane is
#   still polling) while being structurally incapable of ever acting again —
#   the invisible-degradation failure this card exists to close. Terminal
#   suppressors emit `Stop{reason}` instead, and are checked ahead of (and
#   independent of) whether any trigger fired this tick — the watch is over
#   regardless of what happens to be actionable at this exact instant:
#     - Suppressor 1, `_fix_budget_exhausted`   -> "fix_budget_exhausted"
#     - Suppressor 2, `_cycle_budget_exhausted` -> "cycle_budget_exhausted"
#     - Suppressor 3, `_stagnated`              -> "stagnation_limit_reached"
#
#   TRANSIENT — means "not right now", and legitimately clears on its own on
#   a later tick with no external intervention: all-pending checks resolve,
#   the operator lifts the `--no-merge` opt-out, an in-flight fix session
#   finishes. These three keep emitting `NoWorkNeeded`, exactly as before
#   this card:
#     - Suppressor 4, `_only_pending_checks_and_nothing_else_actionable`
#     - Suppressor 5, `_held` (the operator's manual-merge opt-out)
#     - Suppressor 6, `_fix_session_in_flight`
# ---------------------------------------------------------------------------

TERMINAL_SUPPRESSOR_REASONS: Tuple[Tuple[Callable[["TickRequest"], bool], str], ...] = (
    (_fix_budget_exhausted, "fix_budget_exhausted"),
    (_cycle_budget_exhausted, "cycle_budget_exhausted"),
    (_stagnated, "stagnation_limit_reached"),
)


def _terminal_suppression_reason(req: "TickRequest") -> Optional[str]:
    """Returns the reason string for the first TERMINAL suppressor that has
    tripped (§ classification above), or None if none has. A caller checks
    this ahead of the trigger/transient-suppressor path entirely: a terminal
    suppressor means this watch is over, not merely "nothing to invoke a fix
    for right now"."""
    for predicate, reason in TERMINAL_SUPPRESSOR_REASONS:
        if predicate(req):
            return reason
    return None


@dataclass(frozen=True)
class TickRequest:
    """Immutable input to `tick` (§ Ports and adapters).

    Carries the gate's TRIGGERS inputs plus the six SUPPRESSORS' state
    (§ The gate). Suppressor state is threaded through this request rather
    than read from anywhere else — the pure handler must never reach around
    its own input to find out whether it's allowed to act. The full
    `Config`/`State` typed models (land method, real merge-queue wiring,
    tmux-derived `active_fix_session`, ...) still belong to later
    fix-execution/land/poll-loop cards — not invented here ahead of scope
    (YAGNI); this card only adds the fields the six suppressors need.
    """

    pr_snapshot: PRSnapshot
    prior_merge_queue_state: Optional[str] = None
    informational_bot_authors: Tuple[str, ...] = ()

    # Suppressor state (§ The gate) — any one of these blocks invocation
    # even when a trigger fires.
    fix_count: int = 0
    max_fix_invocations: int = 4  # v2's max_ralph_invocations default
    cycle: int = 0
    max_cycles: int = 10  # v2's default
    stagnation_count: int = 0  # HEAD didn't advance across N consecutive fix cycles (v2 Step 13)
    active_fix_session: Optional[str] = None  # non-None means a fix session is already in flight for this PR
    manual_merge_opt_out: bool = False  # the operator's --no-merge flag (§ card 3068 Fix 2)


# ---------------------------------------------------------------------------
# Notify construction (§ Ports and adapters; § Feature parity checklist rows
# 42/44; .scratchpad/3033-swe-devex-review.md Finding 2) — the pure handler's
# own vocabulary for WHEN a notification belongs, kept separate from the
# adapters that decide HOW to deliver one. Only ever called from inside
# `tick`, never from `poll_loop`/the composition root (§ card 3035
# constraints: emission is a gate decision, not an adapter-side concern).
# ---------------------------------------------------------------------------

def _is_clean_awaiting_review(snapshot: PRSnapshot) -> bool:
    """True inside `tick`'s "no trigger fired" branch when the PR is
    genuinely clean — CI fully green, not merely all-pending — and not a
    draft, but not yet ready to land because review has not been approved.
    Mirrors v2's Step 7a: "the PR is clean ... but cannot be merged yet —
    typically because review is required. Notify reviewers via Slack"
    (modules/claude/global/skills/smithers/SKILL.md:351) — the exact
    behavior the cross-restart Slack dedup subsystem (card 3031) was built
    for.

    Only ever consulted from inside the "no trigger fired" branch of `tick`
    (or, since card 3052, `poll_loop`'s `_is_approval_watch_cadence` — the
    same precondition applies there too, guarded by its own `_trigger_fired`
    check first), so checks_fail, merge conflicts, actionable bot comments,
    and merge-queue eviction are already known-false by construction (§ The
    gate TRIGGERS) — this predicate only adds the checks those triggers
    don't cover: draft state, pending/unknown checks, and review approval.
    """
    if snapshot.is_draft:
        return False
    if not snapshot.checks_pass or snapshot.checks_pending or snapshot.checks_unknown:
        return False
    return snapshot.review_decision != "APPROVED"


def _clean_awaiting_review_notify(snapshot: PRSnapshot) -> Notify:
    """The Notify emitted alongside `NoWorkNeeded` when
    `_is_clean_awaiting_review` holds (§ above). `sound=False`: this is a
    recurring, non-terminal state that can repeat every poll cycle while
    review is pending — not a one-time terminal outcome — and
    `notify_slack`'s cross-restart dedup (card 3031) is what keeps this
    from posting to Slack more than once per PR, not this predicate."""
    return Notify(
        title="Smithers",
        body=f"PR #{snapshot.pr_number} is clean and awaiting review",
        sound=False,
    )


def _terminal_stop_notify(snapshot: PRSnapshot, reason: str) -> Notify:
    """The macOS-audible Notify accompanying every terminal `Stop{reason}`
    (§ Feature parity checklist row 44: "keep the distinct sounds per
    terminal state"). Safe to fire unconditionally here: every TERMINAL
    suppressor already halts the watch for real (`poll_loop` returns on
    `Stop`), unlike a hypothetical Land-time notification, which would be
    premature today since no adapter yet performs the real GitHub mutation
    (§ Feature parity checklist row 13 — a later phase)."""
    return Notify(
        title="Smithers",
        body=f"PR #{snapshot.pr_number} watch stopped: {reason}",
        sound=True,
    )


def _trigger_fired(
    snapshot: PRSnapshot,
    prior_merge_queue_state: Optional[str],
    informational_bot_authors: Tuple[str, ...],
) -> bool:
    """True when any of the four TRIGGERS fires (§ The gate). Extracted so
    `tick`'s own gate evaluation and `poll_loop`'s approval-watch-cadence
    decision (card 3052, § APPROVAL_WATCH_POLL_SECONDS,
    `_is_approval_watch_cadence`) share ONE definition of "a trigger fired"
    and can never diverge — a second, independently-reimplemented copy in
    `poll_loop` could silently drift from the gate's own logic over time."""
    return (
        _has_failing_check(snapshot)
        or _has_merge_conflict(snapshot)
        or _has_actionable_bot_comment(snapshot, informational_bot_authors)
        or _merge_queue_evicted(prior_merge_queue_state, snapshot.merge_queue_state)
    )


def _is_approval_watch_cadence(
    snapshot: PRSnapshot,
    prior_merge_queue_state: Optional[str],
    informational_bot_authors: Tuple[str, ...],
) -> bool:
    """§ APPROVAL-WATCH CADENCE (card 3052): True exactly when `poll_loop`
    should sleep `APPROVAL_WATCH_POLL_SECONDS` (the slow cadence) rather than
    `PollLoopConfig.poll_interval_seconds` (the normal/Active-tier baseline)
    after this cycle — no trigger fired AND the snapshot is genuinely
    clean-awaiting-review (§ `_is_clean_awaiting_review`), the exact same
    condition `tick` uses to decide whether to emit the recurring
    awaiting-review `Notify`.

    Recomputed fresh from the just-fetched snapshot every single cycle, with
    no memory of the prior cycle's cadence — so a PR that starts failing CI
    again, picks up a new actionable bot comment, or gets approved, returns
    to the normal cadence on its very next poll. Nothing strands the loop on
    the slow interval past the cycle where the state actually changed.
    """
    if _trigger_fired(snapshot, prior_merge_queue_state, informational_bot_authors):
        return False
    return _is_clean_awaiting_review(snapshot)


def tick(req: TickRequest, send: Callable[[Message], None]) -> None:
    """The pure gate handler (§ Ports and adapters; § The gate).

    Pure: no I/O, no mutation, never raises — every outcome, including
    "nothing to do", leaves through `send`. Invoke Claude if and only if ALL
    suppressors are clear AND at least one trigger fires: a fired trigger
    still yields NoWorkNeeded if any one of the three TRANSIENT suppressors
    is active, since none of them carve out a distinct message of their own
    (§ The gate) — the observable outcome of "transiently suppressed" and
    "nothing fired" are the same at this layer.

    A TERMINAL suppressor (fix/cycle budget exhausted, or stagnated — see
    `_terminal_suppression_reason`) is checked ahead of, and independent of,
    whether any trigger fired: it means this watch is over, so it emits
    `Stop{reason}` rather than a silent `NoWorkNeeded` — card 3027, closing
    the peer-review finding that a poll loop could keep polling forever
    after budget exhaustion while structurally unable to ever act again.
    Ready-to-land is still checked first and bypasses every NON-HOLD
    suppressor, terminal or transient — a fully clean, ready-to-land
    snapshot lands regardless of exhausted fix/cycle/stagnation budgets or
    an in-flight fix session.

    An operator hold is the one suppressor exempt from that bypass (§ audit
    Finding 2 — BLOCKING; card 3060 Fix 1): `_held(req)` — `manual_merge_
    opt_out`, reachable today via the real `--no-merge` CLI flag (§ card
    3068 Fix 2) — is checked BEFORE `Land` is ever emitted, even when the
    snapshot is otherwise fully ready to land. A field named
    `manual_merge_opt_out` means "do not merge this for me"; it must win over
    a green, approved, mergeable snapshot, not the other way around. A held,
    ready-to-land snapshot yields a plain `NoWorkNeeded` — the same
    transient-suppression outcome `_held` produces everywhere else in this
    gate (§ The gate, Suppressor 5) — never `Land`.

    Every terminal path — landing (success) and every TERMINAL-suppressor
    Stop alike — also emits `Disarm{reason}` immediately after, unconditional
    on which terminal reason applies (§ card 3046, closing the seam gap where
    Land/Disarm existed in the Message union but nothing ever executed or
    constructed them). Once a watch reaches any terminal state, Smithers must
    permanently give up its authority to merge, so a later `Land` — a retry,
    a stale timer, a resumed state file — can never execute after the watch
    has stopped.
    """
    snapshot = req.pr_snapshot

    if _is_ready_to_land(snapshot, req.informational_bot_authors):
        if _held(req):
            send(NoWorkNeeded())
            return
        send(Land(method="squash"))
        send(Disarm(reason="landed"))
        return

    terminal_reason = _terminal_suppression_reason(req)
    if terminal_reason is not None:
        send(Stop(reason=terminal_reason))
        send(_terminal_stop_notify(snapshot, terminal_reason))
        send(Disarm(reason=terminal_reason))
        return

    trigger_fired = _trigger_fired(snapshot, req.prior_merge_queue_state, req.informational_bot_authors)

    if not trigger_fired:
        if _is_clean_awaiting_review(snapshot):
            send(_clean_awaiting_review_notify(snapshot))
        send(NoWorkNeeded())
        return

    if _suppressed(req):
        send(NoWorkNeeded())
        return

    send(StartFixSession(name=f"smithers-fix-pr-{snapshot.pr_number}", brief=""))


# ---------------------------------------------------------------------------
# GitHub mutation adapter (Land) and the Disarm safety adapter (§ Ports and
# adapters). `execute_land` performs the real merge via `gh pr merge`,
# honouring `msg.method`; `execute_disarm` permanently revokes merge
# authority for the remainder of this process. Both bind to their own
# message type only — a silent no-op on any other message, exactly like
# every other adapter in this file — and share one mutable `armed` dict,
# closed over per watch by `build_send` (§ composition root) the same way
# `notify_slack`'s `already_posted` dict is shared: a plain, same-process
# cache, never a second, independently-disagreeing source of truth.
# ---------------------------------------------------------------------------

LAND_METHOD_FLAGS: Dict[str, str] = {
    "squash": "--squash",
    "merge": "--merge",
    "rebase": "--rebase",
}


def execute_land(msg: Message, pr_number: Optional[str], log_path: str, armed: Dict[str, bool]) -> None:
    """The GitHub mutation adapter — binds to `Land` messages and performs
    the real merge via `gh pr merge <pr> <method-flag>` (§ Ports and adapters
    table: "GitHub mutation | Land | gh pr merge"). Reuses the `_run`
    subprocess convention already established by `resolve_pr` — capture
    output as text, never raise, inspect `returncode` at the call site.

    Never raises past this boundary for an OPERATIONAL failure (§ card
    scope, never-raise discipline; § peer review Finding 3, card 3068 Fix
    3): any refusal `gh` itself reports — branch protection, a check that
    turned red since the snapshot was fetched, etc. — is logged and this
    function returns. That refusal is correct and final; it is never
    retried with an escalated flag. This does NOT cover a missing `gh`
    binary: `_run` deliberately does not catch `FileNotFoundError` (§ `_run`
    docstring) — an absent, Nix-guaranteed dependency is an environment
    fault this adapter is intended to surface, not swallow (§ CLAUDE.md §
    Scripting Principles).

    HARD PROHIBITION: never passes a force-merge flag, GitHub's
    administrator-override flag, or any other branch-protection-bypass flag
    to `gh`. `LAND_METHOD_FLAGS` is the only source of flags this function
    ever adds to the command.

    Refuses outright, before ever invoking `gh`, once `armed["armed"]` is
    False (§ execute_disarm) — a stale `Land` reaching this adapter after
    the watch has already disarmed must never merge.
    """
    if not isinstance(msg, Land):
        return

    if not armed.get("armed", True):
        log_event(log_path, "land_refused_disarmed", pr=pr_number, method=msg.method)
        return

    if pr_number is None:
        log_event(log_path, "land_skipped_no_pr_number", method=msg.method)
        return

    flag = LAND_METHOD_FLAGS.get(msg.method, "--squash")
    result = _run(["gh", "pr", "merge", pr_number, flag])

    if result.returncode != 0:
        log_event(
            log_path,
            "land_failed",
            pr=pr_number,
            method=msg.method,
            message=(result.stderr or "").strip()[:500],
        )
        return

    log_event(log_path, "land_succeeded", pr=pr_number, method=msg.method)


def execute_disarm(msg: Message, log_path: str, armed: Dict[str, bool]) -> None:
    """The disarm adapter — binds to `Disarm` messages and permanently
    revokes merge authority for the remainder of this process (§ Ports and
    adapters; § card 3046). Flips the shared `armed["armed"]` flag to False;
    every `Land` `execute_land` sees from this point on, for the life of the
    process, is refused unconditionally — there is no re-arm."""
    if not isinstance(msg, Disarm):
        return

    armed["armed"] = False
    log_event(log_path, "disarmed", reason=msg.reason)


# ---------------------------------------------------------------------------
# Thread sweep with atomic reply-and-resolve (card 3052, § THREAD SWEEP WITH
# ATOMIC REPLY-AND-RESOLVE) — the GitHub comment-mutation adapter that
# actually closes a bot thread out. `_fetch_unresolved_threads` /
# `_is_actionable_bot_thread` could already READ and CLASSIFY a thread, but
# nothing could CLOSE one out before this card.
#
# THE GOVERNING RULE: reply and resolve are a single atomic action. A reply
# without a matching resolve is a defect, not a partial success — `prc.py`'s
# own `is_resolved` field (mirrored onto every `CommentThread` via
# `_fetch_unresolved_threads`) only flips when a thread is EXPLICITLY
# resolved, so a replied-to-but-unresolved thread re-triggers Trigger 3 (§
# `_is_actionable_bot_thread`) on every subsequent poll, spamming the pull
# request with a comment every cycle forever. This holds on EVERY path a
# caller might use this adapter for — deferral, a terminal cap-stop, or a
# known-limitation acknowledgment alike: if Smithers replies at all, it
# resolves, or it reports the thread as still open.
#
# Both `prc reply` and `prc resolve` go through the SAME never-raising `_run`
# subprocess convention `resolve_pr`/`execute_land` already established —
# `gh api` + `jq` is never used here; `prc` is the one canonical tool for
# every PR comment mutation in this repo.
# ---------------------------------------------------------------------------

DEFAULT_THREAD_SWEEP_REPLY_MESSAGE = (
    "Smithers: acknowledged. Closing out this thread as part of the "
    "automated pull request watch."
)


def replied_and_resolved(thread: CommentThread, reply_message: str, log_path: str) -> bool:
    """The atomicity guarantee (§ THREAD SWEEP WITH ATOMIC REPLY-AND-RESOLVE).

    Returns True ONLY when BOTH the reply and the resolve succeed. It is
    structurally impossible for this function to report success after a
    reply whose resolve failed: the resolve is attempted immediately after a
    successful reply, in the same call, and any resolve failure flips the
    return value to False right there — there is no code path that can
    return True without having just observed `prc resolve` exit zero. If the
    reply itself fails, the resolve is never even attempted (nothing was
    said, so there is nothing to mark closed).

    Never raises for an OPERATIONAL failure (§ card scope, never-raise
    discipline matching `execute_land`/`execute_disarm`; § peer review
    Finding 3, card 3068 Fix 3) — a non-zero `prc` exit, a missing
    `comment_id`/`thread_id`, or any other outcome `prc` itself can report
    is logged via `log_event` and returned as a plain bool; a caller never
    sees an exception out of this adapter for any of those. This does NOT
    cover a missing `prc` binary: both `_run` calls below go through the
    shared `_run` helper, which deliberately does not catch
    `FileNotFoundError` — an absent, Nix-guaranteed dependency is an
    environment fault this adapter is intended to surface, not swallow.
    """
    if thread.comment_id is None:
        log_event(
            log_path,
            "thread_sweep_reply_skipped_no_comment_id",
            thread_id=thread.thread_id,
            author=thread.author,
            url=thread.url,
        )
        return False

    if thread.thread_id is None:
        log_event(
            log_path,
            "thread_sweep_resolve_skipped_no_thread_id",
            comment_id=thread.comment_id,
            author=thread.author,
            url=thread.url,
        )
        return False

    reply_result = _run(["prc", "reply", str(thread.comment_id), reply_message])
    if reply_result.returncode != 0:
        log_event(
            log_path,
            "thread_sweep_reply_failed",
            comment_id=thread.comment_id,
            thread_id=thread.thread_id,
            author=thread.author,
            message=(reply_result.stderr or "").strip()[:500],
        )
        return False

    log_event(
        log_path,
        "thread_sweep_replied",
        comment_id=thread.comment_id,
        thread_id=thread.thread_id,
        author=thread.author,
    )

    resolve_result = _run(["prc", "resolve", str(thread.thread_id)])
    if resolve_result.returncode != 0:
        # A reply landed but the resolve did not — exactly the defect state
        # the governing rule exists to prevent. Logged under its own distinct
        # event name (never folded into "thread_sweep_reply_failed") so this
        # class of failure is greppable on its own.
        log_event(
            log_path,
            "thread_sweep_resolve_failed_after_reply",
            comment_id=thread.comment_id,
            thread_id=thread.thread_id,
            author=thread.author,
            message=(resolve_result.stderr or "").strip()[:500],
        )
        return False

    log_event(
        log_path,
        "thread_sweep_resolved",
        comment_id=thread.comment_id,
        thread_id=thread.thread_id,
        author=thread.author,
    )
    return True


def sweep_threads(
    threads: Tuple[CommentThread, ...],
    informational_bot_authors: Tuple[str, ...],
    log_path: str,
    reply_message: str = DEFAULT_THREAD_SWEEP_REPLY_MESSAGE,
) -> Tuple[CommentThread, ...]:
    """The thread-sweep adapter (§ THREAD SWEEP WITH ATOMIC REPLY-AND-
    RESOLVE) — walks `threads` (the snapshot's own FULL, unfiltered
    `unresolved_bot_threads` tuple — never a filtered or partial listing, so
    a caller can never infer a clean state from an incomplete view) and
    closes out every ACTIONABLE one (§ `_is_actionable_bot_thread`, the SAME
    predicate Trigger 3 uses) via `replied_and_resolved`'s atomic
    reply-then-resolve.

    Returns the threads that remain open after this sweep: every
    non-actionable thread (left untouched, exactly as it was — e.g. an
    informational-bot-list exclusion, or one already replied to) plus any
    actionable thread whose reply-and-resolve did not fully succeed. Per the
    governing rule, there is no distinct "partially closed" state to report:
    a thread this function did not manage to close out atomically is
    reported exactly like one it never touched — still open.

    Never raises for an OPERATIONAL failure (§ never-raise discipline;
    § card 3068 Fix 3) — every per-thread outcome is logged by
    `replied_and_resolved` itself, which draws the same operational-vs-
    missing-binary distinction its own docstring states.
    """
    still_open: List[CommentThread] = []
    for thread in threads:
        if not _is_actionable_bot_thread(thread, informational_bot_authors):
            still_open.append(thread)
            continue
        if not replied_and_resolved(thread, reply_message, log_path):
            still_open.append(thread)
    return tuple(still_open)


# ---------------------------------------------------------------------------
# Notification adapters (§ Ports and adapters) — bind to `Notify` messages.
# `send` fans every message out to every adapter (see `fan_out` below), so
# each adapter is responsible for filtering to what it binds; any message
# that isn't a `Notify` is a silent no-op here.
# ---------------------------------------------------------------------------

def notify_macos(msg: Message, log_path: str) -> None:
    """macOS notification adapter, via `osascript` (§ Ports and adapters
    table: "Notification | Notify | macOS osascript + Slack via
    smithers-post"). Unconditional: the CLI's one dry-run mechanism is
    `cmd_watch`'s own early return before `build_send` is ever constructed
    (§ card 3035 Fix 3) — this adapter carries no second, unreachable
    dry-run branch of its own."""
    if not isinstance(msg, Notify):
        return

    script = f"display notification {json.dumps(msg.body)} with title {json.dumps(msg.title)}"
    if msg.sound:
        script += ' sound name "default"'
    _run(["osascript", "-e", script])
    log_event(log_path, "notify_macos", title=msg.title, sound=msg.sound)


def _build_slack_dedup_prompt(pr_reference: str) -> str:
    """The dedup probe's prompt (§ query_slack_dedup). Searches by the PR
    reference itself — its number or URL — never by channel: the
    `smithers-post` incoming webhook is write-only and never reveals which
    channel it posts to (§ notify_slack docstring), so a channel-scoped
    query has nothing to key on. A prior post WILL contain this PR's own
    link or number regardless of which channel it landed in, so that is
    what dedup keys on instead. Demands a single bare token back so the
    caller parses an exact field, never screen-scraped prose (§ card
    constraints)."""
    return (
        f"Search Slack for any existing message about pull request "
        f"{pr_reference}. Search for the PR's own number or URL "
        f"({pr_reference!r}) — do not search by channel; a prior post about "
        "this PR will contain that link or number regardless of which "
        "channel it was posted to.\n\n"
        f"Use the {SLACK_SEARCH_TOOL} tool to run the search.\n\n"
        "Respond with EXACTLY one word and nothing else: "
        "DUPLICATE if you find an existing message about this PR, or "
        "NOT_DUPLICATE if you do not."
    )


def _parse_slack_dedup_response(stdout_content: str) -> Optional[bool]:
    """Parse the dedup probe's `--output-format json` envelope into a strict
    True/False/None verdict (§ query_slack_dedup). Mirrors
    `smithers-post.py`'s own `_parse_haiku_json_response` shape (a "result"
    field inside a JSON envelope), but deliberately does NOT screen-scrape
    prose (§ card constraints) — only an EXACT "DUPLICATE" or
    "NOT_DUPLICATE" token (case-insensitive, whitespace-trimmed) is
    accepted; anything else returns None, which is the caller's signal to
    fail OPEN rather than guess."""
    if not stdout_content:
        return None

    try:
        wrapper = json.loads(stdout_content)
    except json.JSONDecodeError:
        return None

    result_text = wrapper.get("result")
    if not isinstance(result_text, str):
        return None

    token = result_text.strip().upper()
    if token == "DUPLICATE":
        return True
    if token == "NOT_DUPLICATE":
        return False
    return None


def query_slack_dedup(pr_reference: str, log_path: str) -> Optional[bool]:
    """Ask Slack itself whether a post about `pr_reference` already exists,
    via a headless `claude -p` invocation allowlisted to EXACTLY
    `SLACK_SEARCH_TOOL` — nothing else.

    Why per-invocation, not a settings grant: `perm` cannot grant a tool
    globally — both `allow` and `always` write project-local
    `.claude/settings.local.json` (§ Reference Documentation, perm CLI
    mechanics), and smithers runs from arbitrary repos, so there is no
    single settings file to grant into. Instead the allowlist is passed PER
    INVOCATION via `--allowedTools`, combined with `--permission-mode
    dontAsk` so anything outside that one tool is denied outright rather
    than prompted for. This is least-privilege by construction, needs no
    settings change anywhere, and works identically from any repo.

    Returns True (a duplicate exists — do not post), False (none found —
    safe to post), or None on ANY failure: the tool denied, the invocation
    erroring, a timeout, or unparseable output. None is always the caller's
    cue to FAIL OPEN and post anyway (§ card constraints, fail-open
    direction) — a missed dedup costs one duplicate Slack message, while a
    dedup that fails CLOSED would silently swallow the one notification
    this whole watch exists to deliver, which is strictly worse. Never
    raises past this boundary; every failure is logged with a reason
    instead.
    """
    cmd = [
        "claude", "-p",
        "--model", "sonnet",
        "--output-format", "json",
        "--allowedTools", SLACK_SEARCH_TOOL,
        "--permission-mode", "dontAsk",
    ]
    prompt = _build_slack_dedup_prompt(pr_reference)

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=SLACK_DEDUP_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log_event(log_path, "slack_dedup_query_failed", pr=pr_reference, message=str(e))
        return None

    if result.returncode != 0:
        log_event(
            log_path,
            "slack_dedup_query_failed",
            pr=pr_reference,
            message=f"claude exited {result.returncode}: {result.stderr.strip()}",
        )
        return None

    verdict = _parse_slack_dedup_response(result.stdout.strip())
    if verdict is None:
        log_event(
            log_path,
            "slack_dedup_query_failed",
            pr=pr_reference,
            message="could not parse a DUPLICATE/NOT_DUPLICATE verdict from claude's output",
        )
    return verdict


def notify_slack(
    msg: Message,
    pr_number: Optional[str],
    log_path: str,
    already_posted: Dict[str, bool],
) -> None:
    """Slack notification adapter — exclusively via the `smithers-post` CLI
    (§ Policy risk / decisions row 42: no MCP, no curl, no hand-rolled
    wrapper). `smithers-post` fetches its own PR title/body/summaries and
    posts Block Kit formatting; this adapter only decides *whether* and
    *when* to invoke it — never reimplements its formatting or its gh calls.

    `smithers-post.py` was read directly for this card (its argparse surface
    is `pr`, `--no-summaries`, `--webhook-url` only — see `smithers-post.py`)
    and carries NO built-in dedup of its own — verified by source
    inspection, not assumed.

    Cross-restart dedup (§ card 3031): this fully-ephemeral CLI (§ module
    docstring) has no state file to remember "already posted" across a
    restart. Instead, `query_slack_dedup` asks Slack itself — via a headless
    Claude invocation scoped to exactly the Slack search tool — whether a
    post about this PR already exists. `already_posted` remains as a
    same-run, zero-cost first check: once a PR has been posted (or
    confirmed a duplicate) once in this run, every later tick short-circuits
    before ever invoking Claude again. The two mechanisms never disagree,
    because `already_posted` is only ever set from the outcome of the very
    query it goes on to short-circuit — it is a cache of that query's
    result, not a second, independent source of truth. If the Slack query
    itself fails for ANY reason, this adapter FAILS OPEN and posts anyway,
    logging that dedup could not be verified (§ query_slack_dedup docstring
    for why that direction, not the reverse, is required).

    Unconditional, like `notify_macos`: the CLI's one dry-run mechanism is
    `cmd_watch`'s own early return before `build_send` is ever constructed
    (§ card 3035 Fix 3) — this adapter carries no second, unreachable
    dry-run branch of its own.
    """
    if not isinstance(msg, Notify):
        return
    if pr_number is None:
        return
    if already_posted.get(pr_number):
        log_event(log_path, "notify_slack_dedup_skip", pr=pr_number, source="in_memory")
        return

    verdict = query_slack_dedup(pr_number, log_path)
    if verdict is True:
        already_posted[pr_number] = True
        log_event(log_path, "notify_slack_dedup_skip", pr=pr_number, source="slack_query")
        return
    if verdict is None:
        log_event(log_path, "notify_slack_dedup_query_failed_posting_anyway", pr=pr_number)

    _run(["smithers-post", str(pr_number)])
    already_posted[pr_number] = True
    log_event(log_path, "notify_slack", pr=pr_number, title=msg.title)


# ---------------------------------------------------------------------------
# Structured log adapter (§ Ports and adapters) — receives every message
# unconditionally, regardless of type, for post-hoc debugging.
# ---------------------------------------------------------------------------

def log_adapter(msg: Message, log_path: str) -> None:
    log_event(log_path, "message", type=type(msg).__name__, **msg.__dict__)


# ---------------------------------------------------------------------------
# The composition root (§ Ports and adapters) — binds real adapters to the
# `send` output port via fan-out: one emitted message reaches every bound
# adapter. Wires the GitHub mutation adapter (`execute_land`) and the disarm
# safety adapter (`execute_disarm`, § card 3046), the notification adapters
# (macOS + Slack), and the structured log adapter. Fix execution
# (`StartFixSession`) is deliberately NOT one of these `send`-bound adapters —
# it is invoked directly by `poll_loop` itself (§ Fix execution), not fanned
# out here. The scheduler belongs to a later card that owns that message type
# (§ card scope, OUT OF SCOPE) — an unbound message type is simply logged
# here, never silently mutated.
# ---------------------------------------------------------------------------

def fan_out(handlers: List[Callable[[Message], None]]) -> Callable[[Message], None]:
    """`send := fanOut([]Handler{...})` (§ Ports and adapters) — a plain
    function that calls every bound handler with the same message."""

    def send(msg: Message) -> None:
        for handler in handlers:
            handler(msg)

    return send


def build_send(
    pr_number: Optional[str],
    log_path: str,
    already_posted: Optional[Dict[str, bool]] = None,
) -> Callable[[Message], None]:
    """The composition root: builds the real `send` port for one watch run
    on one PR, with real adapters wired via `fan_out` (§ Ports and adapters,
    Composition-root corollary). `already_posted` is exposed as a parameter
    so a caller can share one dict across multiple `tick()` calls in a
    future poll loop; a fresh dict is created when omitted.

    `armed` (§ card 3046) is a fresh, always-True mutable flag scoped to
    this one watch — never a parameter, unlike `already_posted` — since
    re-arming across watches would defeat the whole point of the safety
    mechanism: each new `build_send` call is a fresh watch, starting
    fully armed, that can only ever be disarmed once and never re-armed
    for its own lifetime.

    No `dry_run` parameter: the CLI's one dry-run mechanism is `cmd_watch`'s
    own early return before this composition root is ever constructed
    (§ card 3035 Fix 3) — see `notify_macos`/`notify_slack`."""
    if already_posted is None:
        already_posted = {}
    armed: Dict[str, bool] = {"armed": True}

    return fan_out(
        [
            lambda msg: execute_land(msg, pr_number, log_path, armed),
            lambda msg: execute_disarm(msg, log_path, armed),
            lambda msg: notify_macos(msg, log_path),
            lambda msg: notify_slack(msg, pr_number, log_path, already_posted),
            lambda msg: log_adapter(msg, log_path),
        ]
    )


# ---------------------------------------------------------------------------
# The poll loop (§ Process model, § Poll loop and cadence) — the foreground
# CLI's own composition root. Owns cadence internally; does not exit between
# polls. Phase 4 owns the full Active/Approval-watch adaptive-cadence swap
# (§ Build plan, phase 4) — this card wires only the single baseline
# interval (the 60s Active value) plus the exponential GitHub-API-error
# backoff table (§ Failure and retry).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PollLoopConfig:
    """Resolved thresholds/intervals for one `poll_loop` run.

    `max_cycles=None` (the default) means the loop runs until its pane is
    killed (§ Process model, § How to stop a watch) — the production shape.
    Tests pass a finite bound so the loop actually returns rather than
    depending on a side effect to break out (§ card scope, "the loop
    terminates on its bound").
    """

    max_cycles: Optional[int] = None
    poll_interval_seconds: int = 60  # the Active-tier baseline (§ Poll loop and cadence)
    backoff_intervals_seconds: Tuple[int, ...] = (300, 900, 1800)
    max_fix_invocations: int = 4  # v2's max_ralph_invocations default
    informational_bot_authors: Tuple[str, ...] = ()
    accept_api_billing: bool = False
    env: Optional[Dict[str, str]] = None  # override for tests; live os.environ read fresh every tick otherwise
    manual_merge_opt_out: bool = False  # the operator's --no-merge flag (§ card 3068 Fix 2)


# Bound on any single externally-sourced field once run through
# `_sanitize_for_brief` (§ audit Finding 1) — generous enough to keep a real
# CI check name or thread URL fully readable, small enough that no single
# field can balloon the brief.
SANITIZE_FOR_BRIEF_MAX_LENGTH = 200


def _sanitize_for_brief(text: str) -> str:
    """Neutralize one externally-sourced string before it is interpolated
    into the fix session's task brief (§ audit Finding 1 — BLOCKING,
    concrete prompt injection; card 3060 Fix 2).

    `snapshot.checks_fail` names come straight from `gh pr checks`'s `name`
    field with zero sanitization between the GitHub API and the prompt text:
    anyone who can push a workflow file on a PR branch controls a CI check's
    displayed name, and can set it to arbitrary, injected-instruction-shaped
    text. `thread.author` and the thread's URL/id (§ audit Finding 10) are a
    materially narrower, GitHub-structurally-constrained variant of the same
    class, but are routed through this same helper rather than trusted as a
    special case — one sanitizer, applied uniformly to every externally-
    sourced field this function interpolates.

    Strips CR/LF (and every other ASCII control character) so injected text
    can never introduce what would read as a new instruction line in the
    brief, collapses the resulting whitespace, and truncates to
    `SANITIZE_FOR_BRIEF_MAX_LENGTH` so no single field can balloon the brief.
    Does NOT attempt to make the brief injection-proof overall (§ audit
    Finding 11 — the fix session still visits comment URLs itself with its
    own unrestricted tools, a separate, only-partially-inherent surface this
    helper does not and cannot close). Scope is exactly: text smithers
    itself interpolates is neutralized first.
    """
    if not text:
        return ""

    without_control_chars = "".join(
        " " if (ch in ("\n", "\r") or ord(ch) < 32 or ord(ch) == 127) else ch for ch in text
    )
    collapsed = " ".join(without_control_chars.split())

    if len(collapsed) > SANITIZE_FOR_BRIEF_MAX_LENGTH:
        return collapsed[:SANITIZE_FOR_BRIEF_MAX_LENGTH] + "…"
    return collapsed


def _build_fix_task_brief(snapshot: PRSnapshot, informational_bot_authors: Tuple[str, ...]) -> str:
    """Assemble the fix session's task brief from the `PRSnapshot` the gate
    just acted on (§ How the CLI starts the fix). Bounded by design: tells
    the fix session WHAT is actionable this cycle — failing checks, merge
    conflicts, actionable bot threads — never dumps the whole snapshot, and
    never chooses HOW to fix any of it ("No Ralph, no Burns, no hats ... the
    choosing is left entirely to the staff-engineer subprocess itself",
    § Fix execution). The subprocess inherits the CLI's own working
    directory, already the checked-out worktree for this PR — no separate
    `--branch`/`--repo` plumbing is needed (§ How the CLI starts the fix).

    Every externally-sourced field interpolated below — failing check names,
    thread author, thread URL/id — is routed through `_sanitize_for_brief`
    first (§ audit Finding 1, card 3060 Fix 2): CI check names in particular
    are attacker-controlled and reach this function with zero sanitization
    from `gh pr checks` itself.
    """
    lines: List[str] = [
        f"Fix pull request #{snapshot.pr_number}. The current working "
        "directory is already the checked-out worktree for this PR.",
        "",
        "What is actionable this cycle:",
    ]

    if snapshot.checks_fail:
        sanitized_checks = ", ".join(_sanitize_for_brief(name) for name in snapshot.checks_fail)
        lines.append(f"- Failing CI checks: {sanitized_checks}")

    if snapshot.mergeable == "CONFLICTING":
        lines.append("- Merge conflicts with the base branch need resolving.")

    for thread in snapshot.unresolved_bot_threads:
        if _is_actionable_bot_thread(thread, informational_bot_authors):
            location = thread.url or f"thread {thread.thread_id}"
            lines.append(
                f"- Unresolved bot comment from {_sanitize_for_brief(thread.author)}: "
                f"{_sanitize_for_brief(location)}"
            )

    lines.extend(["", FIX_SESSION_CONSTRAINTS])
    return "\n".join(lines)


@dataclass(frozen=True)
class FixAttemptResult:
    """Outcome of one blocking fix-session invocation (§ Exit handling).

    Exactly one of three outcomes, never conflated: `"completed"` (the
    process exited zero), `"failed"` (a non-zero exit, or the process could
    not even be started), or `"timeout"` (the wall-clock ceiling was
    exceeded and the process tree was killed — treated as a failed attempt,
    not a crash, per § Failure modes).

    `session_id`/`cost_usd` are parsed from the `--output-format json`
    envelope PURELY for logging (§ Output parsing and trust) — nothing here
    is derived from `.result` prose, and nothing downstream may treat
    `outcome == "completed"` as proof the fix actually worked. Only the next
    GitHub poll, re-deriving ground truth from `gh`, can prove that.
    """

    outcome: str  # "completed" | "failed" | "timeout"
    returncode: Optional[int]
    session_id: Optional[str] = None
    cost_usd: Optional[float] = None
    message: str = ""


def _parse_fix_session_envelope(stdout_content: str) -> Dict[str, Any]:
    """Best-effort parse of the `--output-format json` envelope for LOGGING
    ONLY (§ Output parsing and trust) — `session_id` and a cost estimate if
    present, nothing else. Mirrors `_parse_slack_dedup_response`'s own
    fail-safe shape: never raises, and an unparseable or missing envelope
    simply yields an empty dict rather than a fabricated value."""
    if not stdout_content:
        return {}
    try:
        wrapper = json.loads(stdout_content)
    except json.JSONDecodeError:
        return {}
    if not isinstance(wrapper, dict):
        return {}

    fields: Dict[str, Any] = {}
    if isinstance(wrapper.get("session_id"), str):
        fields["session_id"] = wrapper["session_id"]
    cost = wrapper.get("total_cost_usd", wrapper.get("cost_usd"))
    if isinstance(cost, (int, float)):
        fields["cost_usd"] = cost
    return fields


def _kill_fix_session_process_tree(process: "subprocess.Popen", log_path: str, name: str) -> None:
    """Kill the fix session's ENTIRE process group, not just its own PID
    (§ Failure modes: the CLI "kills the subprocess if it is exceeded").
    `staff.bash` execs `claude` directly (same PID), but a running Claude
    session can itself spawn further subprocesses (Bash tool invocations,
    etc.) that a bare `process.kill()` would orphan rather than terminate.
    The process is started with `start_new_session=True` (see
    `_invoke_fix_session`) so the whole tree shares one process group id,
    killable with a single signal."""
    try:
        pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        log_event(log_path, "fix_invocation_kill_did_not_reap", name=name)


# The fix session subprocess's environment allowlist (§ audit Finding 6 —
# MEDIUM; card 3060 Fix 3). `subprocess.Popen` inherits the ENTIRE parent
# environment when `env=` is omitted — every secret exported in the
# operator's own shell (cloud credentials, other API tokens) would otherwise
# be reachable to the fix session's Bash tool, which (per FIX_SESSION_
# CONSTRAINTS/Fix 4) has broad access beyond the small deny list this card
# adds. An explicit ALLOWlist, never a blocklist, so nothing not named here
# can leak through by omission:
#   - PATH, HOME: so the subprocess can find and run `staff`/`claude`/`gh`
#     at all, and so `gh` finds its stored, file-based credentials under
#     `$HOME/.config/gh` (verified via `gh help environment`: `GH_CONFIG_DIR`
#     defaults to `$XDG_CONFIG_HOME/gh` if set, else `$HOME/.config/gh`) —
#     confirmed this operator's `gh` auth is exactly that file-based kind
#     (`~/.config/gh/hosts.yml` present) and `XDG_CONFIG_HOME` is unset here,
#     so `HOME` alone reaches the real config directory.
#   - LANG, LC_ALL: `subprocess.Popen(..., text=True)` decodes the child's
#     stdout/stderr using the locale's preferred encoding; dropping these
#     risks a decode failure on any non-ASCII text a real `staff`/`claude`
#     invocation is likely to produce or echo back.
#   - CLAUDE_CODE_OAUTH_TOKEN: Anthropic's own documented headless-auth
#     mechanism for SUBSCRIPTION billing (see `REFUSAL_ENV_VARS` above) —
#     forwarded only if the parent actually has it set, never synthesized.
# Deliberately EXCLUDES GH_TOKEN/GITHUB_TOKEN: `gh`'s own file-based stored
# credentials (above) already authenticate it without handing a raw,
# live token to the session's broad tool surface — confirmed via `gh help
# environment` that these env vars only take PRECEDENCE over, never replace
# the need for, stored credentials, so omitting them does not break `gh`
# auth for an operator who has already run `gh auth login`.
FIX_SESSION_ENV_ALLOWLIST: Tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


def _build_fix_session_env(base_env: Dict[str, str]) -> Dict[str, str]:
    """Build the filtered environment for the fix session subprocess (§
    audit Finding 6; card 3060 Fix 3) from `base_env` — never `os.environ`
    read directly here, so every caller (and every test) controls exactly
    what this function sees, matching the rest of this module's env-as-
    parameter convention (`billing_preflight`, `PollLoopConfig.env`).

    Carries forward only `FIX_SESSION_ENV_ALLOWLIST` entries that are
    actually present in `base_env` — never synthesizes a value for a
    variable that isn't already set — and always adds `SMITHERS_FIX_SESSION
    = "1"` (§ card 3060 Fix 4), marking this subprocess as smithers-spawned
    so a future `PreToolUse` hook can scope deny logic to it specifically
    (modelled on the existing `git-no-verify-hook.py` pattern; the hook
    itself is out of this card's scope).

    Never re-admits a `REFUSAL_ENV_VARS` entry, however it reached
    `base_env`: `FIX_SESSION_ENV_ALLOWLIST` has zero overlap with
    `REFUSAL_ENV_VARS` by construction (an allowlist, not a blocklist), and
    `test_no_refusal_env_var_reaches_the_child_environment` asserts this
    holds directly rather than trusting it to hold by inspection alone —
    re-admitting one of those variables here would silently defeat
    `billing_preflight`'s own fail-closed control for the fix session's own
    billing.
    """
    filtered = {name: base_env[name] for name in FIX_SESSION_ENV_ALLOWLIST if name in base_env}
    filtered["SMITHERS_FIX_SESSION"] = "1"
    return filtered


def _invoke_fix_session(
    msg: StartFixSession, log_path: str, env: Optional[Dict[str, str]] = None
) -> FixAttemptResult:
    """The fix-execution adapter (§ Fix execution) — a single blocking
    `staff -p --model sonnet --effort high --permission-mode dontAsk`
    subprocess invocation (`FIX_SESSION_CMD`), wrapped in an external
    wall-clock ceiling (`FIX_INVOCATION_TIMEOUT_SECONDS`, § Failure modes).
    The prompt (`msg.brief`) is piped via stdin, never as a trailing
    argument. Runs to completion and terminates itself; this call blocks
    until it does, is killed for exceeding the ceiling, or fails to start.

    `env` (§ audit Finding 6; card 3060 Fix 3) is the caller's own base
    environment — `poll_loop` passes through the same per-cycle `env` dict
    it already reads for `billing_preflight`, so both share one source of
    truth for "what the operator's environment looks like this cycle"; a
    caller that omits it gets a fresh `os.environ` read here instead
    (mirroring `PollLoopConfig.env`'s own override-for-tests convention).
    Either way, `base_env` is never handed to the subprocess directly — it
    is always passed through `_build_fix_session_env` first, so the child
    only ever inherits the small, explicit allowlist that helper defines.

    Per § Output parsing and trust, the ONLY things a caller may treat as a
    control signal are `FixAttemptResult.outcome` and `.returncode` — never
    the content of `.message`, which exists purely for logging. Whether the
    fix actually worked is re-derived from GitHub on the next poll, never
    from anything this function returns.
    """
    base_env = env if env is not None else dict(os.environ)
    subprocess_env = _build_fix_session_env(base_env)

    try:
        process = subprocess.Popen(
            list(FIX_SESSION_CMD),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own process group so a timeout can kill the whole tree
            env=subprocess_env,
        )
    except OSError as e:
        log_event(log_path, "fix_invocation_failed_to_start", name=msg.name, message=str(e))
        return FixAttemptResult(outcome="failed", returncode=None, message=str(e))

    try:
        stdout, stderr = process.communicate(input=msg.brief, timeout=FIX_INVOCATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_fix_session_process_tree(process, log_path, msg.name)
        log_event(
            log_path,
            "fix_invocation_timeout",
            name=msg.name,
            timeout_seconds=FIX_INVOCATION_TIMEOUT_SECONDS,
        )
        return FixAttemptResult(
            outcome="timeout",
            returncode=None,
            message=f"exceeded {FIX_INVOCATION_TIMEOUT_SECONDS}s wall-clock ceiling",
        )

    envelope = _parse_fix_session_envelope(stdout)

    if process.returncode != 0:
        log_event(
            log_path,
            "fix_invocation_failed",
            name=msg.name,
            returncode=process.returncode,
            message=(stderr or "").strip()[:500],
            **envelope,
        )
        return FixAttemptResult(
            outcome="failed",
            returncode=process.returncode,
            message=(stderr or "").strip(),
            **envelope,
        )

    log_event(log_path, "fix_invocation_completed", name=msg.name, **envelope)
    return FixAttemptResult(outcome="completed", returncode=0, **envelope)


def poll_loop(pr: str, config: PollLoopConfig, send: Callable[[Message], None], log_path: str) -> None:
    """The in-process poll loop — foreground, owns its own cadence, does not
    exit between polls (§ Process model, § Poll loop and cadence).

    Per tick, in order: (1) the billing preflight runs first — fail-closed,
    ahead of EVERY tick, not merely once at process startup, and never one of
    the gate's six suppressors (§ Policy risk, Hazard 1; § The gate) — a
    watch started today can still be running tomorrow under a changed
    environment; (2) a fresh `PRSnapshot` is fetched; (3) `sweep_threads`
    (§ card 3052, wired here by card 3068 Fix 1) closes out every actionable
    bot thread in the just-fetched snapshot BEFORE the gate ever sees it —
    the snapshot handed to `tick` this cycle already reflects the sweep, so
    a thread closed out this cycle can never also fire Trigger 3 or block
    Trigger 5 in the SAME tick; (4) the pure `tick` gate handler decides
    what to do; (5) every resulting `Message` fans out through `send`, with
    `StartFixSession` additionally handed to `_invoke_fix_session` (§ Fix
    execution) — a real, blocking `staff -p` invocation, not a stub. The
    same per-cycle `env` dict billing_preflight just checked is passed
    straight through to `_invoke_fix_session`, which filters it down to a
    small allowlist before the subprocess ever sees it (§ audit Finding 6;
    card 3060 Fix 3) — one source of truth for "the operator's environment
    this cycle", never a second, independently-read `os.environ`.

    A GitHub fetch failure never reaches `tick` at all — no GitHub read (it
    already failed), no gate evaluation, no fix invocation (§ Failure and
    retry) — the loop backs off instead (exponential, capped at
    `config.backoff_intervals_seconds[-1]`) and retries next cycle. A
    legitimately empty result (e.g. zero checks, zero comments) is never
    treated as a failure — `fetch_pr_snapshot`'s own typed
    `(snapshot, FetchFailure)` contract already makes that distinction; this
    loop just acts on it.

    A `Stop` message (a TERMINAL suppressor tripped — § classification above
    `_terminal_suppression_reason`) ends the loop immediately: `send` still
    receives it like any other message (so the structured log and any bound
    notification adapters see it), but no further sleep or poll happens
    after it (§ card 3027) — this is what keeps the loop from spinning
    forever, invisibly incapable of acting, once a budget is exhausted.

    Two of the gate's own suppressor counters are advanced here, once per
    fix attempt (§ Fix execution, "the attempt cap and stagnation check
    already exist in the gate as terminal suppressors" — this loop only
    keeps the counters they read honest, it never re-implements the
    suppressor logic itself): `fix_count` increments on every invocation,
    completed or not. `stagnation_count` — "HEAD unchanged across 2
    consecutive fix invocations" (§ Failure modes) — is checked once per
    cycle, comparing the freshly-fetched HEAD against the HEAD recorded at
    the PRIOR fix invocation; the comparison is deferred to the cycle
    immediately following an invocation (`stagnation_check_pending`) so a
    quiet run with no trigger firing at all never inflates it — only
    consecutive INVOCATIONS with no forward progress do.

    Approval-watch cadence (card 3052, § APPROVAL-WATCH CADENCE): the sleep
    at the end of each cycle uses `APPROVAL_WATCH_POLL_SECONDS` instead of
    `config.poll_interval_seconds` whenever `_is_approval_watch_cadence`
    holds for the snapshot just fetched this cycle — the PR is clean and
    genuinely has nothing left to do but wait on a human reviewer. This is
    recomputed fresh every cycle (never carried over from the prior one), so
    the loop returns to the normal cadence immediately once CI starts
    failing again, a new actionable bot comment lands, or review clears.
    """
    cycle = 0
    consecutive_failures = 0
    fix_count = 0
    stagnation_count = 0
    last_fix_attempt_head_sha: Optional[str] = None
    stagnation_check_pending = False
    prior_merge_queue_state: Optional[str] = None
    active_fix_session: Optional[str] = None
    stopped = False
    snapshot: Optional[PRSnapshot] = None  # rebound each cycle; only ever read inside _handle

    def _handle(msg: Message) -> None:
        nonlocal stopped, fix_count, last_fix_attempt_head_sha, stagnation_check_pending
        send(msg)
        if isinstance(msg, StartFixSession):
            brief = _build_fix_task_brief(snapshot, config.informational_bot_authors)
            _invoke_fix_session(StartFixSession(name=msg.name, brief=brief), log_path, env=env)
            fix_count += 1
            last_fix_attempt_head_sha = snapshot.head_sha
            stagnation_check_pending = True
        if isinstance(msg, Stop):
            stopped = True

    while config.max_cycles is None or cycle < config.max_cycles:
        cycle += 1

        env = config.env if config.env is not None else dict(os.environ)
        billing_preflight(env, config.accept_api_billing, log_path)

        snapshot, failure = fetch_pr_snapshot(pr, log_path)

        if failure is not None:
            consecutive_failures += 1
            backoff_index = min(consecutive_failures - 1, len(config.backoff_intervals_seconds) - 1)
            backoff_seconds = config.backoff_intervals_seconds[backoff_index]
            log_event(
                log_path,
                "poll_fetch_failed",
                source=failure.source,
                message=failure.message,
                backoff_seconds=backoff_seconds,
            )
            time.sleep(backoff_seconds)
            continue

        consecutive_failures = 0

        if stagnation_check_pending:
            if snapshot.head_sha == last_fix_attempt_head_sha:
                stagnation_count += 1
            else:
                stagnation_count = 0
            stagnation_check_pending = False

        # Thread sweep (§ card 3052; wired here by card 3068 Fix 1, closing
        # a peer-review finding that `sweep_threads` was fully implemented
        # and unit-tested but never called from anywhere in production).
        # Runs BEFORE this cycle's TickRequest is built, so a thread it
        # closes out atomically feeds the SAME cycle's gate evaluation —
        # left un-swept, an actionable thread keeps re-firing Trigger 3
        # (§ `_has_actionable_bot_comment`) every cycle forever, burning the
        # fix budget until the whole watch permanently Stops/Disarms itself
        # over a comment Smithers never actually attempted to close.
        still_open_bot_threads = sweep_threads(
            snapshot.unresolved_bot_threads, config.informational_bot_authors, log_path
        )
        snapshot = replace(snapshot, unresolved_bot_threads=still_open_bot_threads)

        req = TickRequest(
            pr_snapshot=snapshot,
            prior_merge_queue_state=prior_merge_queue_state,
            informational_bot_authors=config.informational_bot_authors,
            fix_count=fix_count,
            max_fix_invocations=config.max_fix_invocations,
            cycle=cycle,
            stagnation_count=stagnation_count,
            active_fix_session=active_fix_session,
            manual_merge_opt_out=config.manual_merge_opt_out,
        )
        tick(req, _handle)

        if stopped:
            log_event(log_path, "poll_loop_stopped", cycle=cycle)
            return

        approval_watch = _is_approval_watch_cadence(
            snapshot, prior_merge_queue_state, config.informational_bot_authors
        )
        prior_merge_queue_state = snapshot.merge_queue_state
        time.sleep(APPROVAL_WATCH_POLL_SECONDS if approval_watch else config.poll_interval_seconds)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Flat parser, no subcommands (§ card 3019).

    `watch` used to be a required subcommand (`smithers watch <pr>`). The
    design's stated primary invocation is bare `smithers` with no arguments
    at all (§ How to start a watch, .scratchpad/2967-v3-design.md), which
    auto-detects the PR for the current git branch — there is no required
    `smithers watch <pr>` form any more. `main()` strips a leading literal
    "watch" token before parsing so the old form still works as a plain
    alias, without this parser needing to know about it."""
    parser = argparse.ArgumentParser(
        prog="smithers",
        description=(
            "Smithers v3: a foreground CLI that watches one pull request to "
            "completion, polling GitHub in plain code and invoking Claude "
            "only when work is actually needed.\n\n"
            "Bare `smithers`, with no arguments, auto-detects the pull request\n"
            "belonging to the current git branch. An explicit PR number or URL\n"
            "argument targets that PR instead of auto-detecting.\n\n"
            "Examples:\n"
            "  smithers\n"
            "  smithers 123\n"
            "  smithers 123 --dry-run\n"
            "  smithers https://github.com/owner/repo/pull/123\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pr",
        metavar="PR",
        nargs="?",
        default=None,
        help=(
            "PR number or full URL to watch. If omitted, auto-detects the PR "
            "belonging to the current git branch."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse arguments and resolve the PR only; do not poll or mutate anything",
    )
    parser.add_argument(
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
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        default=DEFAULT_LOG_PATH,
        help=f"JSONL log destination (default: {DEFAULT_LOG_PATH} or $SMITHERS_LOG_PATH)",
    )
    parser.add_argument(
        "--informational-bot-authors",
        metavar="AUTHORS",
        default=None,
        dest="informational_bot_authors",
        help=(
            "Comma-separated bot authors excluded from the actionable-bot-"
            "comment trigger (§ The gate, trigger 3) — e.g. coverage bots "
            "that comment informationally and never expect a fix. Overrides "
            "$SMITHERS_INFORMATIONAL_BOT_AUTHORS. Default: "
            f"{', '.join(DEFAULT_INFORMATIONAL_BOT_AUTHORS)}"
        ),
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        default=False,
        dest="no_merge",
        help=(
            "Watch and fix this pull request, but never merge it — the "
            "operator merges it manually. Wires straight through to the "
            "gate's manual-merge opt-out suppressor (§ The gate, Suppressor "
            "5; § audit Finding 2): a snapshot that is otherwise fully "
            "ready to land still yields no action instead of Land while "
            "this flag is set."
        ),
    )

    return parser


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

def cmd_watch(args: argparse.Namespace) -> int:
    billing_preflight(dict(os.environ), args.accept_api_billing, args.log_file)

    pr, failure = resolve_pr(args.pr, args.log_file)
    if failure is not None:
        print(f"Error: {failure.message}", file=sys.stderr)
        return 1

    log_event(args.log_file, "watch_started", pr=pr, dry_run=args.dry_run)

    if args.dry_run:
        print(f"smithers watch: dry run for PR {pr!r} — preflight passed, no further action taken")
        return 0

    send = build_send(pr_number=pr, log_path=args.log_file)
    config = PollLoopConfig(
        accept_api_billing=args.accept_api_billing,
        informational_bot_authors=_resolve_informational_bot_authors(
            args.informational_bot_authors, dict(os.environ)
        ),
        manual_merge_opt_out=args.no_merge,
    )
    poll_loop(pr, config, send, args.log_file)
    return 0


def main(argv: Optional[list] = None) -> int:
    """Entry point. Bare `smithers` (no arguments) is the primary invocation
    (§ How to start a watch) — cmd_watch resolves the PR to watch from the
    current git branch when args.pr is None. A leading literal "watch" token
    is stripped here for backward compatibility with the earlier
    `smithers watch <pr>` subcommand form — it is accepted, never required."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "watch":
        argv = argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return cmd_watch(args)


if __name__ == "__main__":
    sys.exit(main())
