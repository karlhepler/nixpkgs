"""
Tests for smithers.py — phase 1, card 1: CLI skeleton + billing preflight.

Covers argument parsing (watch subcommand, --dry-run) and the fail-closed
billing preflight (§ Policy risk, Hazard 1, .scratchpad/2967-v3-design.md):
  - refuses when any raw-API-billing credential env var is present
  - logs the offending variable NAME only, never its value
  - does NOT refuse when only CLAUDE_CODE_OAUTH_TOKEN is set (subscription auth)
  - the only bypass is the explicit --i-accept-api-billing flag
"""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import smithers as smithers_module
from smithers import (
    REFUSAL_ENV_VARS,
    CommentThread,
    FetchFailure,
    Land,
    Notify,
    NoWorkNeeded,
    PollLoopConfig,
    PRSnapshot,
    ResolutionFailure,
    StartFixSession,
    Stop,
    TickRequest,
    billing_preflight,
    build_parser,
    build_send,
    cmd_watch,
    fetch_pr_snapshot,
    log_event,
    main,
    poll_loop,
    resolve_pr,
    tick,
)


# ---------------------------------------------------------------------------
# Helper: build a fake subprocess.run result (mirrors test_crew.py's pattern)
# ---------------------------------------------------------------------------

def fake_run_result(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


# ---------------------------------------------------------------------------
# Recorded fixture strings for the GitHub read adapter — no network calls.
# ---------------------------------------------------------------------------

GH_VIEW_FIXTURE = json.dumps({
    "number": 123,
    "headRefOid": "abc123def456",
    "isDraft": False,
    "mergeable": "MERGEABLE",
    "mergeStateStatus": "CLEAN",
    "reviewDecision": "APPROVED",
    "latestReviews": [
        {"author": {"login": "alice"}, "state": "APPROVED", "submittedAt": "2026-07-20T10:00:00Z"},
        {"author": {"login": "bob"}, "state": "CHANGES_REQUESTED", "submittedAt": "2026-07-19T10:00:00Z"},
    ],
})

GH_CHECKS_FIXTURE = json.dumps([
    {"name": "build", "bucket": "pass", "workflow": "CI"},
    {"name": "test", "bucket": "fail", "workflow": "CI"},
    {"name": "lint", "bucket": "pending", "workflow": "CI"},
    {"name": "optional-check", "bucket": "skipping", "workflow": "CI"},
    {"name": "weird-check", "bucket": "totally-unrecognized-value", "workflow": "CI"},
])

PRC_LIST_FIXTURE = json.dumps({
    "comments": [
        {
            "id": 1, "author": "coderabbitai", "is_bot": True,
            "thread_id": "T_1", "url": "https://example/1",
            "type": "inline", "is_resolved": False,
            "in_reply_to_id": None, "reply_count": 0,
        },
        {
            "id": 2, "author": "karlhepler", "is_bot": False,
            "thread_id": "T_2", "url": "https://example/2",
            "type": "inline", "is_resolved": False,
            "in_reply_to_id": 5, "reply_count": 2,
        },
    ],
    "rate_limit": {"cost": 1, "remaining": 4999, "resetAt": "2026-07-28T00:00:00Z", "limit": 5000},
})


def make_gh_side_effect(
    view: str = GH_VIEW_FIXTURE,
    checks: str = GH_CHECKS_FIXTURE,
    prc: str = PRC_LIST_FIXTURE,
    checks_returncode: int = 0,
):
    """Build a subprocess.run side_effect that routes gh/prc commands to
    recorded fixture strings, keyed off the command's own argv shape."""

    def side_effect(cmd, **kwargs):
        if cmd[:3] == ["gh", "pr", "view"]:
            return fake_run_result(stdout=view)
        if cmd[:3] == ["gh", "pr", "checks"]:
            return fake_run_result(stdout=checks, returncode=checks_returncode)
        if cmd[:2] == ["prc", "list"]:
            return fake_run_result(stdout=prc)
        raise AssertionError(f"unexpected command in test: {cmd}")

    return side_effect


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

class TestArgumentParsing:
    """Flat parser, no subcommands (§ card 3019) — the `pr` positional is
    optional (nargs="?") so bare `smithers` parses cleanly with args.pr=None."""

    def test_pr_argument_is_optional(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.pr is None

    def test_accepts_explicit_pr_number(self):
        parser = build_parser()
        args = parser.parse_args(["123"])
        assert args.pr == "123"

    def test_accepts_explicit_pr_url(self):
        parser = build_parser()
        args = parser.parse_args(["https://github.com/karlhepler/nixpkgs/pull/123"])
        assert args.pr == "https://github.com/karlhepler/nixpkgs/pull/123"

    def test_accepts_dry_run_flag(self):
        parser = build_parser()
        args = parser.parse_args(["123", "--dry-run"])
        assert args.dry_run is True

    def test_dry_run_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["123"])
        assert args.dry_run is False

    def test_accept_api_billing_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["123"])
        assert args.accept_api_billing is False

    def test_accept_api_billing_flag(self):
        parser = build_parser()
        args = parser.parse_args(["123", "--i-accept-api-billing"])
        assert args.accept_api_billing is True

    def test_no_arguments_at_all_does_not_error(self):
        """Bare `smithers` — the design's stated primary invocation — must
        parse cleanly, not raise SystemExit like the old required-subcommand
        shape did."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.pr is None
        assert args.dry_run is False

    def test_top_level_help_exits_zero(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0


class TestWatchAliasStripping:
    """`main()` strips a leading literal "watch" token before handing argv to
    the parser, so the earlier `smithers watch <pr>` form keeps working as a
    plain alias even though the parser itself no longer defines a subcommand
    (§ card 3019)."""

    def test_watch_prefix_is_stripped_before_parsing(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        result = main(["watch", "123", "--dry-run", "--log-file", log_path])
        assert result == 0

    def test_watch_prefix_and_bare_form_resolve_the_same_pr(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        main(["watch", "123", "--dry-run", "--log-file", log_path])
        out_with_watch = capsys.readouterr().out

        main(["123", "--dry-run", "--log-file", log_path])
        out_without_watch = capsys.readouterr().out

        assert "123" in out_with_watch
        assert "123" in out_without_watch

    def test_watch_alone_with_no_pr_leaves_pr_none_for_resolution(self, tmp_path):
        parser = build_parser()
        argv = ["watch"]
        if argv and argv[0] == "watch":
            argv = argv[1:]
        args = parser.parse_args(argv)
        assert args.pr is None


# ---------------------------------------------------------------------------
# Billing preflight — refusal list
# ---------------------------------------------------------------------------

class TestBillingPreflightRefusal:
    @pytest.mark.parametrize("var_name", REFUSAL_ENV_VARS)
    def test_refuses_when_variable_set(self, var_name, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        env = {var_name: "sk-ant-super-secret-value"}

        with pytest.raises(SystemExit) as exc_info:
            billing_preflight(env, accept_api_billing=False, log_path=log_path)

        assert exc_info.value.code != 0

    @pytest.mark.parametrize("var_name", REFUSAL_ENV_VARS)
    def test_logs_variable_name_but_never_the_value(self, var_name, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        secret_value = "sk-ant-super-secret-value-should-never-appear-anywhere"
        env = {var_name: secret_value}

        with pytest.raises(SystemExit):
            billing_preflight(env, accept_api_billing=False, log_path=log_path)

        log_contents = open(log_path).read()
        assert var_name in log_contents
        assert secret_value not in log_contents

        record = json.loads(log_contents.strip().splitlines()[-1])
        assert record["event"] == "preflight_refused"
        assert record["var"] == var_name
        assert "ts" in record

        captured = capsys.readouterr()
        assert secret_value not in captured.err
        assert secret_value not in captured.out

    def test_clean_environment_does_not_refuse(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        billing_preflight({}, accept_api_billing=False, log_path=log_path)
        # No exception raised == success; nothing should have been logged either.
        assert not os.path.exists(log_path)


# ---------------------------------------------------------------------------
# Billing preflight — CLAUDE_CODE_OAUTH_TOKEN must NOT be a refusal trigger
# ---------------------------------------------------------------------------

class TestOAuthTokenExcluded:
    def test_oauth_token_not_in_refusal_list(self):
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in REFUSAL_ENV_VARS

    def test_does_not_refuse_when_only_oauth_token_set(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        env = {"CLAUDE_CODE_OAUTH_TOKEN": "some-subscription-headless-token"}

        # Must not raise SystemExit.
        billing_preflight(env, accept_api_billing=False, log_path=log_path)
        assert not os.path.exists(log_path)

    def test_oauth_token_alongside_unrelated_vars_still_passes(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        env = {
            "CLAUDE_CODE_OAUTH_TOKEN": "some-subscription-headless-token",
            "PATH": "/usr/bin:/bin",
            "HOME": "/Users/someone",
        }
        billing_preflight(env, accept_api_billing=False, log_path=log_path)
        assert not os.path.exists(log_path)


# ---------------------------------------------------------------------------
# Billing preflight — explicit bypass flag is the only override
# ---------------------------------------------------------------------------

class TestExplicitBypass:
    def test_bypass_flag_allows_refusal_variable_through(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        env = {"ANTHROPIC_API_KEY": "sk-ant-whatever"}

        # Must not raise SystemExit when the operator explicitly accepts API billing.
        billing_preflight(env, accept_api_billing=True, log_path=log_path)
        assert not os.path.exists(log_path)

    def test_no_environment_variable_override_exists(self, tmp_path):
        """There is no env-var escape hatch — only the explicit CLI flag bypasses
        the preflight. Setting an arbitrary 'override' style env var alongside a
        refusal variable must still refuse."""
        log_path = str(tmp_path / "smithers.jsonl")
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-whatever",
            "SMITHERS_SKIP_PREFLIGHT": "1",
            "SMITHERS_ALLOW_API_BILLING": "1",
        }
        with pytest.raises(SystemExit):
            billing_preflight(env, accept_api_billing=False, log_path=log_path)


# ---------------------------------------------------------------------------
# JSONL logging scaffold
# ---------------------------------------------------------------------------

class TestLogEvent:
    def test_writes_one_json_object_per_line(self, tmp_path):
        log_path = str(tmp_path / "nested" / "smithers.jsonl")
        log_event(log_path, "watch_started", pr="123", dry_run=False)
        log_event(log_path, "watch_started", pr="456", dry_run=True)

        lines = open(log_path).read().strip().splitlines()
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["event"] == "watch_started"
        assert first["pr"] == "123"
        assert first["dry_run"] is False
        assert "ts" in first

        second = json.loads(lines[1])
        assert second["pr"] == "456"
        assert second["dry_run"] is True

    def test_creates_parent_directory_if_missing(self, tmp_path):
        log_path = str(tmp_path / "does" / "not" / "exist" / "smithers.jsonl")
        log_event(log_path, "watch_started", pr="1")
        assert os.path.exists(log_path)


# ---------------------------------------------------------------------------
# TODO stubs — attachment points exist with the intended signatures.
# `poll_loop` itself is fully wired now (§ card 3021) — see the dedicated
# TestPollLoop* classes below. Only fix execution (phase 3) remains a stub.
# ---------------------------------------------------------------------------

class TestPhaseStubsExist:
    def test_fix_invocation_stub_logs_and_does_not_raise(self, tmp_path):
        """`_invoke_fix_stub` fixes the call site's intended signature for
        phase 3 (§ card scope, OUT OF SCOPE) without crashing the loop when a
        trigger fires today."""
        log_path = str(tmp_path / "smithers.jsonl")
        smithers_module._invoke_fix_stub(
            StartFixSession(name="smithers-fix-pr-123", brief=""), log_path
        )

        lines = open(log_path).read().strip().splitlines()
        assert any(json.loads(line)["event"] == "fix_invocation_stub_todo" for line in lines)


# ---------------------------------------------------------------------------
# PRSnapshot construction from realistic fixture payloads
# ---------------------------------------------------------------------------

class TestPRSnapshotConstruction:
    def test_builds_snapshot_from_fixtures(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert isinstance(snapshot, PRSnapshot)
        assert snapshot.pr_number == 123
        assert snapshot.head_sha == "abc123def456"
        assert snapshot.is_draft is False
        assert snapshot.mergeable == "MERGEABLE"
        assert snapshot.merge_state_status == "CLEAN"
        assert snapshot.review_decision == "APPROVED"
        assert snapshot.merge_queue_state is None

    def test_checks_bucketed_pass_fail_pending_other_unknown(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert snapshot.checks_pass == ("build",)
        assert snapshot.checks_fail == ("test",)
        assert snapshot.checks_pending == ("lint",)
        assert snapshot.checks_other == ("optional-check",)
        assert snapshot.checks_unknown == ("weird-check",)

    def test_only_approved_reviews_become_approvals(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert len(snapshot.approvals) == 1
        assert snapshot.approvals[0].author == "alice"
        assert snapshot.approvals[0].submitted_at == "2026-07-20T10:00:00Z"

    def test_empty_checks_list_is_legitimate_not_a_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect(checks=json.dumps([]))):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert snapshot.checks_pass == ()
        assert snapshot.checks_fail == ()
        assert snapshot.checks_pending == ()


# ---------------------------------------------------------------------------
# Bot-versus-human unresolved thread distinction
# ---------------------------------------------------------------------------

class TestUnresolvedThreadDistinction:
    def test_distinguishes_bot_and_human_threads(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert len(snapshot.unresolved_bot_threads) == 1
        assert snapshot.unresolved_bot_threads[0].author == "coderabbitai"
        assert len(snapshot.unresolved_human_threads) == 1
        assert snapshot.unresolved_human_threads[0].author == "karlhepler"
        assert snapshot.unresolved_unknown_author_threads == ()

    def test_type_in_reply_to_id_and_reply_count_parsed_correctly(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        bot_thread = snapshot.unresolved_bot_threads[0]
        assert bot_thread.type == "inline"
        assert bot_thread.in_reply_to_id is None
        assert bot_thread.reply_count == 0

        human_thread = snapshot.unresolved_human_threads[0]
        assert human_thread.type == "inline"
        assert human_thread.in_reply_to_id == 5
        assert human_thread.reply_count == 2

    def test_missing_type_field_becomes_unknown_not_default(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        prc_missing_type = json.dumps({
            "comments": [
                {
                    "id": 4, "author": "coderabbitai", "is_bot": True,
                    "thread_id": "T_4", "url": "https://example/4",
                    "is_resolved": False, "in_reply_to_id": None, "reply_count": 0,
                },
            ],
            "rate_limit": {},
        })
        with patch("subprocess.run", side_effect=make_gh_side_effect(prc=prc_missing_type)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert len(snapshot.unresolved_bot_threads) == 1
        assert snapshot.unresolved_bot_threads[0].type is None

        log_contents = open(log_path).read()
        assert "fetch_field_missing" in log_contents
        assert '"field": "type"' in log_contents

    def test_missing_in_reply_to_id_field_becomes_unknown_not_default(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        prc_missing_in_reply_to_id = json.dumps({
            "comments": [
                {
                    "id": 5, "author": "coderabbitai", "is_bot": True,
                    "thread_id": "T_5", "url": "https://example/5",
                    "type": "inline", "is_resolved": False, "reply_count": 0,
                },
            ],
            "rate_limit": {},
        })
        with patch("subprocess.run", side_effect=make_gh_side_effect(prc=prc_missing_in_reply_to_id)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert len(snapshot.unresolved_bot_threads) == 1
        assert snapshot.unresolved_bot_threads[0].in_reply_to_id is None

        log_contents = open(log_path).read()
        assert "fetch_field_missing" in log_contents
        assert '"field": "in_reply_to_id"' in log_contents

    def test_missing_reply_count_field_becomes_unknown_not_zero(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        prc_missing_reply_count = json.dumps({
            "comments": [
                {
                    "id": 6, "author": "coderabbitai", "is_bot": True,
                    "thread_id": "T_6", "url": "https://example/6",
                    "type": "inline", "is_resolved": False, "in_reply_to_id": None,
                },
            ],
            "rate_limit": {},
        })
        with patch("subprocess.run", side_effect=make_gh_side_effect(prc=prc_missing_reply_count)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert len(snapshot.unresolved_bot_threads) == 1
        # Explicit unknown (None), never a fabricated 0 that would look like
        # "genuinely zero replies" (§ card 3012 scope).
        assert snapshot.unresolved_bot_threads[0].reply_count is None

        log_contents = open(log_path).read()
        assert "fetch_field_missing" in log_contents
        assert '"field": "reply_count"' in log_contents

    def test_missing_is_bot_field_becomes_unknown_never_silently_human(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        prc_missing_is_bot = json.dumps({
            "comments": [
                {
                    "id": 3, "author": "mystery",
                    "thread_id": "T_3", "url": "https://example/3",
                    "type": "inline", "is_resolved": False,
                },
            ],
            "rate_limit": {},
        })
        with patch("subprocess.run", side_effect=make_gh_side_effect(prc=prc_missing_is_bot)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert snapshot.unresolved_bot_threads == ()
        assert snapshot.unresolved_human_threads == ()
        assert len(snapshot.unresolved_unknown_author_threads) == 1
        assert snapshot.unresolved_unknown_author_threads[0].author == "mystery"

        log_contents = open(log_path).read()
        assert "fetch_field_missing" in log_contents
        assert "is_bot" in log_contents


# ---------------------------------------------------------------------------
# API-failure-versus-empty-result distinction (§ card scope, Error handling)
# ---------------------------------------------------------------------------

class TestFetchFailureVsEmptyResult:
    def test_gh_not_found_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")

        def side_effect(cmd, **kwargs):
            raise FileNotFoundError("gh: command not found")

        with patch("subprocess.run", side_effect=side_effect):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert snapshot is None
        assert isinstance(failure, FetchFailure)
        assert failure.source == "gh pr view"

    def test_checks_nonzero_exit_with_valid_json_is_not_a_failure(self, tmp_path):
        """gh pr checks legitimately exits non-zero (e.g. a failing check)
        while still emitting valid JSON — real PRSnapshot data, never an
        adapter failure on exit code alone."""
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect(checks_returncode=1)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert failure is None
        assert snapshot.checks_fail == ("test",)

    def test_checks_empty_stdout_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect(checks="", checks_returncode=1)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert snapshot is None
        assert isinstance(failure, FetchFailure)
        assert failure.source == "gh pr checks"

    def test_prc_list_unparseable_output_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_gh_side_effect(prc="not valid json")):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert snapshot is None
        assert isinstance(failure, FetchFailure)
        assert failure.source == "prc list"

    def test_missing_pr_number_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        view_without_number = json.dumps({
            "headRefOid": "abc123",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN",
            "reviewDecision": None,
            "latestReviews": [],
        })
        with patch("subprocess.run", side_effect=make_gh_side_effect(view=view_without_number)):
            snapshot, failure = fetch_pr_snapshot("123", log_path)

        assert snapshot is None
        assert isinstance(failure, FetchFailure)
        assert failure.source == "gh pr view"


# ---------------------------------------------------------------------------
# resolve_pr() — PR auto-detection from the current git worktree (§ card
# 3019). An explicit PR number/URL always short-circuits with zero
# git/gh calls; auto-detect shells out to `git rev-parse`, `gh auth status`,
# and `gh pr view --json number,url` — all faked below, no real gh calls,
# no network.
# ---------------------------------------------------------------------------

def make_resolve_side_effect(
    git_returncode: int = 0,
    gh_missing: bool = False,
    gh_auth_returncode: int = 0,
    gh_view_returncode: int = 0,
    gh_view_stdout: str = json.dumps(
        {"number": 123, "url": "https://github.com/karlhepler/nixpkgs/pull/123"}
    ),
    gh_view_stderr: str = "",
):
    """Build a subprocess.run side_effect covering every command resolve_pr
    can issue when auto-detecting: `git rev-parse --is-inside-work-tree`,
    `gh auth status`, and `gh pr view --json number,url`."""

    def side_effect(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return fake_run_result(returncode=git_returncode)
        if cmd[:2] == ["gh", "auth"]:
            if gh_missing:
                raise FileNotFoundError("gh: command not found")
            return fake_run_result(returncode=gh_auth_returncode)
        if cmd[:3] == ["gh", "pr", "view"]:
            if gh_missing:
                raise FileNotFoundError("gh: command not found")
            return fake_run_result(stdout=gh_view_stdout, stderr=gh_view_stderr, returncode=gh_view_returncode)
        raise AssertionError(f"unexpected command in test: {cmd}")

    return side_effect


class TestResolvePRExplicitOverride:
    """An explicit PR number or URL always wins — no git/gh calls at all."""

    def test_explicit_number_short_circuits_with_no_subprocess_calls(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")

        def side_effect(cmd, **kwargs):
            raise AssertionError(f"resolve_pr must not shell out for an explicit PR: {cmd}")

        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr("123", log_path)

        assert pr == "123"
        assert failure is None

    def test_explicit_url_short_circuits_with_no_subprocess_calls(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        url = "https://github.com/karlhepler/nixpkgs/pull/123"

        def side_effect(cmd, **kwargs):
            raise AssertionError(f"resolve_pr must not shell out for an explicit PR: {cmd}")

        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(url, log_path)

        assert pr == url
        assert failure is None


class TestResolvePRAutoDetectSuccess:
    def test_resolves_pr_number_from_current_branch(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect()):
            pr, failure = resolve_pr(None, log_path)

        assert failure is None
        assert pr == "123"


class TestResolvePRNotAGitRepo:
    def test_not_a_git_repo_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(git_returncode=128)):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert isinstance(failure, ResolutionFailure)
        assert failure.reason == "not_a_git_repo"
        assert "git repository" in failure.message

    def test_not_a_git_repo_never_calls_gh(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                return fake_run_result(returncode=128)
            raise AssertionError(f"gh must not be invoked when not in a git repo: {cmd}")

        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert failure.reason == "not_a_git_repo"


class TestResolvePRGhUnavailable:
    def test_gh_not_found_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(gh_missing=True)):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert isinstance(failure, ResolutionFailure)
        assert failure.reason == "gh_unavailable"


class TestResolvePRGhUnauthenticated:
    def test_gh_unauthenticated_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(gh_auth_returncode=1)):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert isinstance(failure, ResolutionFailure)
        assert failure.reason == "gh_unauthenticated"

    def test_gh_unauthenticated_never_calls_gh_pr_view(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"]:
                return fake_run_result(returncode=0)
            if cmd[:2] == ["gh", "auth"]:
                return fake_run_result(returncode=1)
            raise AssertionError(f"gh pr view must not run when unauthenticated: {cmd}")

        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert failure.reason == "gh_unauthenticated"


class TestResolvePRNoPRForBranch:
    def test_no_pr_for_branch_is_a_typed_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        side_effect = make_resolve_side_effect(
            gh_view_returncode=1,
            gh_view_stdout="",
            gh_view_stderr='no pull requests found for branch "main"',
        )
        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert isinstance(failure, ResolutionFailure)
        assert failure.reason == "no_pr_for_branch"
        assert "main" in failure.message


class TestResolvePRGenericGhError:
    def test_unrecognized_gh_pr_view_failure_is_a_generic_gh_error(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        side_effect = make_resolve_side_effect(
            gh_view_returncode=1,
            gh_view_stdout="",
            gh_view_stderr="some other gh failure unrelated to missing PRs",
        )
        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert failure.reason == "gh_error"

    def test_unparseable_gh_pr_view_json_is_a_gh_error(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        side_effect = make_resolve_side_effect(gh_view_stdout="not valid json")
        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert failure.reason == "gh_error"

    def test_missing_number_field_is_a_gh_error(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        side_effect = make_resolve_side_effect(
            gh_view_stdout=json.dumps({"url": "https://github.com/karlhepler/nixpkgs/pull/123"})
        )
        with patch("subprocess.run", side_effect=side_effect):
            pr, failure = resolve_pr(None, log_path)

        assert pr is None
        assert failure.reason == "gh_error"


class TestResolvePRLogsFailures:
    def test_failure_is_logged_with_reason_and_message(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(git_returncode=128)):
            resolve_pr(None, log_path)

        log_contents = open(log_path).read()
        record = json.loads(log_contents.strip().splitlines()[-1])
        assert record["event"] == "resolve_pr_failed"
        assert record["reason"] == "not_a_git_repo"
        assert "message" in record


# ---------------------------------------------------------------------------
# cmd_watch() and main() — directly exercised (review carry-forward #3006
# Finding 3), mirroring test_crew.py's convention of testing cmd_* handlers.
# ---------------------------------------------------------------------------

class TestCmdWatch:
    def test_dry_run_passes_preflight_and_returns_zero(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        parser = build_parser()
        args = parser.parse_args(["123", "--dry-run", "--log-file", log_path])

        result = cmd_watch(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "dry run" in out
        assert "123" in out

    def test_non_dry_run_wires_and_invokes_poll_loop(self, tmp_path):
        """A real (unbounded) poll_loop must never actually run inside a
        test — patch it and assert cmd_watch wires it with the resolved PR,
        a real send port, and the log file, per its own composition-root
        contract (§ Ports and adapters)."""
        log_path = str(tmp_path / "smithers.jsonl")
        parser = build_parser()
        args = parser.parse_args(["123", "--log-file", log_path])

        with patch.object(smithers_module, "poll_loop") as mock_poll_loop:
            result = cmd_watch(args)

        assert result == 0
        assert mock_poll_loop.call_count == 1
        call_pr, call_config, call_send, call_log_path = mock_poll_loop.call_args[0]
        assert call_pr == "123"
        assert isinstance(call_config, PollLoopConfig)
        assert callable(call_send)
        assert call_log_path == log_path

    def test_billing_refusal_raises_systemexit_before_any_action(self, tmp_path, monkeypatch):
        log_path = str(tmp_path / "smithers.jsonl")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
        parser = build_parser()
        args = parser.parse_args(["123", "--dry-run", "--log-file", log_path])

        with pytest.raises(SystemExit):
            cmd_watch(args)

    def test_accept_api_billing_flag_bypasses_refusal(self, tmp_path, monkeypatch, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
        parser = build_parser()
        args = parser.parse_args(
            ["123", "--dry-run", "--i-accept-api-billing", "--log-file", log_path]
        )

        result = cmd_watch(args)

        assert result == 0


class TestMain:
    def test_main_dispatches_to_cmd_watch(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        result = main(["watch", "123", "--dry-run", "--log-file", log_path])

        assert result == 0
        out = capsys.readouterr().out
        assert "dry run" in out

    def test_main_returns_an_int(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        result = main(["watch", "123", "--dry-run", "--log-file", log_path])
        assert isinstance(result, int)

    def test_main_with_no_args_uses_sys_argv_style_list(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        # Explicit argv (not reading real sys.argv) keeps this test hermetic.
        result = main(["watch", "456", "--dry-run", "--log-file", log_path])
        assert result == 0


# ---------------------------------------------------------------------------
# cmd_watch()/main() with NO explicit PR — exercises the auto-detect path
# end to end (§ card 3019). Every failure prints a clear message to stderr
# and returns non-zero; never a stack trace.
# ---------------------------------------------------------------------------

class TestBareInvocationAutoDetect:
    def test_bare_invocation_resolves_pr_and_proceeds(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect()):
            result = main(["--dry-run", "--log-file", log_path])

        assert result == 0
        out = capsys.readouterr().out
        assert "123" in out

    def test_not_a_git_repo_prints_clear_message_and_returns_nonzero(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(git_returncode=128)):
            result = main(["--dry-run", "--log-file", log_path])

        assert result == 1
        err = capsys.readouterr().err
        assert "git repository" in err
        assert "Traceback" not in err

    def test_gh_unavailable_prints_clear_message_and_returns_nonzero(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(gh_missing=True)):
            result = main(["--dry-run", "--log-file", log_path])

        assert result == 1
        err = capsys.readouterr().err
        assert "gh" in err.lower()
        assert "Traceback" not in err

    def test_gh_unauthenticated_prints_clear_message_and_returns_nonzero(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=make_resolve_side_effect(gh_auth_returncode=1)):
            result = main(["--dry-run", "--log-file", log_path])

        assert result == 1
        err = capsys.readouterr().err
        assert "authenticat" in err.lower()
        assert "Traceback" not in err

    def test_no_pr_for_branch_prints_clear_message_and_returns_nonzero(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        side_effect = make_resolve_side_effect(
            gh_view_returncode=1,
            gh_view_stdout="",
            gh_view_stderr='no pull requests found for branch "main"',
        )
        with patch("subprocess.run", side_effect=side_effect):
            result = main(["--dry-run", "--log-file", log_path])

        assert result == 1
        err = capsys.readouterr().err
        assert "no pull request" in err.lower()
        assert "Traceback" not in err

    def test_explicit_pr_argument_bypasses_auto_detect_entirely(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")

        def side_effect(cmd, **kwargs):
            raise AssertionError(f"explicit PR argument must skip auto-detect entirely: {cmd}")

        with patch("subprocess.run", side_effect=side_effect):
            result = main(["999", "--dry-run", "--log-file", log_path])

        assert result == 0
        out = capsys.readouterr().out
        assert "999" in out


# ---------------------------------------------------------------------------
# The gate's TRIGGERS (§ The gate) — the pure `tick` handler over a
# PRSnapshot. Suppressors are a sibling card's scope and are not exercised
# here: any trigger firing always results in an action message.
# ---------------------------------------------------------------------------

def _snapshot(**overrides):
    """A PRSnapshot with "nothing is happening" defaults, so each gate test
    only overrides the field(s) relevant to it. `checks_pending` is non-empty
    by default so the ready-to-land trigger never accidentally fires in a
    test that isn't about it."""
    defaults = dict(
        pr_number=123,
        head_sha="abc123",
        is_draft=False,
        mergeable="MERGEABLE",
        merge_state_status="BLOCKED",
        checks_pass=(),
        checks_fail=(),
        checks_pending=("still-running",),
        checks_other=(),
        checks_unknown=(),
        review_decision="REVIEW_REQUIRED",
        approvals=(),
        unresolved_bot_threads=(),
        unresolved_human_threads=(),
        unresolved_unknown_author_threads=(),
        merge_queue_state=None,
    )
    defaults.update(overrides)
    return PRSnapshot(**defaults)


def _bot_thread(**overrides):
    defaults = dict(
        thread_id="t1",
        author="coderabbitai",
        url="https://example/1#discussion_r1",
        type="inline",
        in_reply_to_id=None,
        reply_count=0,
    )
    defaults.update(overrides)
    return CommentThread(**defaults)


class TestTickNoTriggers:
    def test_clean_pending_snapshot_yields_no_work_needed(self):
        messages = []
        tick(TickRequest(pr_snapshot=_snapshot()), messages.append)
        assert messages == [NoWorkNeeded()]


class TestFailingCheckTrigger:
    def test_failing_check_starts_a_fix_session(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert len(messages) == 1
        assert isinstance(messages[0], StartFixSession)


class TestMergeConflictTrigger:
    def test_conflicting_mergeable_starts_a_fix_session(self):
        snapshot = _snapshot(mergeable="CONFLICTING", checks_pending=())
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert len(messages) == 1
        assert isinstance(messages[0], StartFixSession)


class TestActionableBotCommentTrigger:
    def test_zero_confirmed_replies_non_reply_bot_thread_is_actionable(self):
        snapshot = _snapshot(
            checks_pending=(),
            unresolved_bot_threads=(_bot_thread(reply_count=0, in_reply_to_id=None),),
        )
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert len(messages) == 1
        assert isinstance(messages[0], StartFixSession)

    def test_unknown_reply_count_is_not_actionable(self):
        """None means UNKNOWN, not zero — must not be treated as actionable,
        distinct from a confirmed reply_count == 0 above."""
        snapshot = _snapshot(
            checks_pending=(),
            unresolved_bot_threads=(_bot_thread(reply_count=None),),
        )
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert messages == [NoWorkNeeded()]

    def test_confirmed_nonzero_reply_count_is_not_actionable(self):
        snapshot = _snapshot(
            checks_pending=(),
            unresolved_bot_threads=(_bot_thread(reply_count=2),),
        )
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert messages == [NoWorkNeeded()]

    def test_a_reply_thread_is_never_actionable_even_with_zero_further_replies(self):
        snapshot = _snapshot(
            checks_pending=(),
            unresolved_bot_threads=(_bot_thread(reply_count=0, in_reply_to_id=999),),
        )
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert messages == [NoWorkNeeded()]

    def test_informational_bot_author_is_excluded_even_when_actionable_shaped(self):
        snapshot = _snapshot(
            checks_pending=(),
            unresolved_bot_threads=(_bot_thread(author="codecov[bot]", reply_count=0, in_reply_to_id=None),),
        )
        req = TickRequest(pr_snapshot=snapshot, informational_bot_authors=("codecov[bot]",))
        messages = []
        tick(req, messages.append)
        assert messages == [NoWorkNeeded()]


class TestReadyToLandTrigger:
    def test_all_clear_snapshot_emits_land(self):
        snapshot = _snapshot(
            checks_pass=("build",),
            checks_pending=(),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            review_decision="APPROVED",
        )
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert messages == [Land(method="squash")]

    def test_draft_pr_is_never_ready_to_land(self):
        snapshot = _snapshot(
            is_draft=True,
            checks_pass=("build",),
            checks_pending=(),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            review_decision="APPROVED",
        )
        messages = []
        tick(TickRequest(pr_snapshot=snapshot), messages.append)
        assert messages == [NoWorkNeeded()]


class TestMergeQueueEvictionTrigger:
    def test_fires_once_a_prior_confirmed_value_is_wired_in(self):
        """Proves the predicate's logic directly: once a later card wires a
        real confirmed prior merge-queue state into TickRequest, this
        trigger fires the moment the snapshot's own state bounces to null —
        no further code change required, only new data."""
        snapshot = _snapshot(checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, prior_merge_queue_state="QUEUED")
        messages = []
        tick(req, messages.append)
        assert len(messages) == 1
        assert isinstance(messages[0], StartFixSession)

    def test_structurally_unreachable_today_with_real_adapter_defaults(self, tmp_path):
        """`fetch_pr_snapshot` hard-codes merge_queue_state=None (no `gh`
        field exposes it) and `TickRequest.prior_merge_queue_state` defaults
        to None with nothing yet writing anything else into it (`poll_loop`
        is still a stub — see TestPhaseStubsExist). Both inputs this trigger
        depends on are always None in real usage today, so a real, fully
        fetched snapshot with nothing else actionable yields NoWorkNeeded,
        never a merge-queue-triggered fix session."""
        log_path = str(tmp_path / "smithers.jsonl")
        with patch(
            "subprocess.run",
            side_effect=make_gh_side_effect(
                checks=json.dumps([{"bucket": "pending", "name": "lint", "workflow": "CI"}]),
                prc=json.dumps({"comments": []}),
            ),
        ):
            snapshot, failure = fetch_pr_snapshot("123", log_path)
        assert failure is None
        assert snapshot.merge_queue_state is None

        req = TickRequest(pr_snapshot=snapshot)
        assert req.prior_merge_queue_state is None

        messages = []
        tick(req, messages.append)
        assert messages == [NoWorkNeeded()]


# ---------------------------------------------------------------------------
# The gate's SUPPRESSORS (§ The gate) — table-driven over every trigger and
# every suppressor. Phase 1's exit criterion for the gate: proves each of the
# six suppressors blocks every trigger it's relevant to, and that a fired
# trigger passes through to StartFixSession when every suppressor is clear.
# ---------------------------------------------------------------------------

# Each trigger case: (name, snapshot overrides, TickRequest kwargs) that make
# `tick` fire a StartFixSession when no suppressor is active. Deliberately
# excludes the ready-to-land trigger (§ The gate, trigger 5) — it routes to
# the deterministic Land action, never to a Claude invocation, so the
# suppressors (which only gate invocation) never apply to it; see
# TestSuppressorsDoNotBlockLand below.
TRIGGER_CASES = [
    ("failing_check", dict(checks_fail=("test",), checks_pending=()), {}),
    ("merge_conflict", dict(mergeable="CONFLICTING", checks_pending=()), {}),
    (
        "actionable_bot_comment",
        dict(checks_pending=(), unresolved_bot_threads=(_bot_thread(),)),
        {},
    ),
    ("merge_queue_eviction", dict(checks_pending=()), dict(prior_merge_queue_state="QUEUED")),
]

# Each suppressor case: (name, TickRequest kwargs, expected_reason) that make
# `_suppressed`/`_terminal_suppression_reason` true on its own, independent
# of which trigger fired. `expected_reason` is the Stop reason for a
# TERMINAL suppressor (fix/cycle budget exhausted, stagnated — card 3027),
# or None for a TRANSIENT one, which still yields a plain NoWorkNeeded
# (§ The gate classification, smithers.py `_terminal_suppression_reason`).
SUPPRESSOR_CASES = [
    ("fix_budget_exhausted", dict(fix_count=4, max_fix_invocations=4), "fix_budget_exhausted"),
    ("cycle_budget_exhausted", dict(cycle=10, max_cycles=10), "cycle_budget_exhausted"),
    ("stagnated", dict(stagnation_count=2), "stagnation_limit_reached"),
    ("coordinator_hold", dict(coordinator_hold=True), None),
    ("manual_merge_opt_out", dict(manual_merge_opt_out=True), None),
    ("fix_session_in_flight", dict(active_fix_session="smithers-fix-pr-123"), None),
]

TRIGGER_SUPPRESSOR_COMBOS = [
    pytest.param(
        trigger_name,
        snapshot_overrides,
        base_req_kwargs,
        suppressor_name,
        suppressor_kwargs,
        expected_reason,
        id=f"{trigger_name}-blocked-by-{suppressor_name}",
    )
    for trigger_name, snapshot_overrides, base_req_kwargs in TRIGGER_CASES
    for suppressor_name, suppressor_kwargs, expected_reason in SUPPRESSOR_CASES
]


class TestGateTriggersPassThroughWithNoSuppressors:
    """The no-suppressor case: every trigger, with all six suppressors at
    their clear defaults, still starts a fix session."""

    @pytest.mark.parametrize("trigger_name,snapshot_overrides,base_req_kwargs", TRIGGER_CASES)
    def test_trigger_fires_start_fix_session_when_all_suppressors_clear(
        self, trigger_name, snapshot_overrides, base_req_kwargs
    ):
        snapshot = _snapshot(**snapshot_overrides)
        req = TickRequest(pr_snapshot=snapshot, **base_req_kwargs)
        messages = []
        tick(req, messages.append)
        assert len(messages) == 1, trigger_name
        assert isinstance(messages[0], StartFixSession), trigger_name


class TestGateSuppressorsBlockEveryTrigger:
    """Every suppressor blocks every trigger it's relevant to: the full
    cross product of TRIGGER_CASES x SUPPRESSOR_CASES. A TERMINAL suppressor
    blocks with a distinguishable `Stop{reason}` (card 3027); a TRANSIENT
    one still blocks with a plain `NoWorkNeeded`, exactly as before."""

    @pytest.mark.parametrize(
        "trigger_name,snapshot_overrides,base_req_kwargs,suppressor_name,suppressor_kwargs,expected_reason",
        TRIGGER_SUPPRESSOR_COMBOS,
    )
    def test_suppressor_blocks_fired_trigger(
        self, trigger_name, snapshot_overrides, base_req_kwargs, suppressor_name, suppressor_kwargs, expected_reason
    ):
        snapshot = _snapshot(**snapshot_overrides)
        req_kwargs = dict(base_req_kwargs)
        req_kwargs.update(suppressor_kwargs)
        req = TickRequest(pr_snapshot=snapshot, **req_kwargs)

        messages = []
        tick(req, messages.append)

        if expected_reason is not None:
            assert messages == [Stop(reason=expected_reason)], f"{suppressor_name} failed to stop {trigger_name}"
        else:
            assert messages == [NoWorkNeeded()], f"{suppressor_name} failed to block {trigger_name}"


class TestFixBudgetSuppressor:
    """TERMINAL (card 3027): once tripped, emits Stop{reason} rather than a
    silent NoWorkNeeded — this budget only ever grows for the life of a
    watch, so every future tick would otherwise be suppressed forever."""

    def test_below_threshold_passes_through(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, fix_count=3, max_fix_invocations=4)
        messages = []
        tick(req, messages.append)
        assert isinstance(messages[0], StartFixSession)

    def test_at_threshold_stops_with_reason(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, fix_count=4, max_fix_invocations=4)
        messages = []
        tick(req, messages.append)
        assert messages == [Stop(reason="fix_budget_exhausted")]

    def test_above_threshold_stops_with_reason(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, fix_count=5, max_fix_invocations=4)
        messages = []
        tick(req, messages.append)
        assert messages == [Stop(reason="fix_budget_exhausted")]


class TestCycleBudgetSuppressor:
    """TERMINAL (card 3027): once tripped, emits Stop{reason} rather than a
    silent NoWorkNeeded — the concrete bug this card fixes (a poll loop with
    an unbounded outer cadence would otherwise keep polling forever past
    this threshold, structurally unable to ever start a fix session again)."""

    def test_below_threshold_passes_through(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, cycle=9, max_cycles=10)
        messages = []
        tick(req, messages.append)
        assert isinstance(messages[0], StartFixSession)

    def test_at_threshold_stops_with_reason(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, cycle=10, max_cycles=10)
        messages = []
        tick(req, messages.append)
        assert messages == [Stop(reason="cycle_budget_exhausted")]

    def test_stops_even_when_nothing_would_otherwise_be_actionable(self):
        """The terminal check runs ahead of, and independent of, trigger
        evaluation — a budget exhausted with a fully quiet snapshot must
        still Stop rather than silently fall through to NoWorkNeeded, since
        the watch is doomed regardless of what happens to fire later."""
        snapshot = _snapshot()  # default: only pending checks, nothing actionable
        req = TickRequest(pr_snapshot=snapshot, cycle=10, max_cycles=10)
        messages = []
        tick(req, messages.append)
        assert messages == [Stop(reason="cycle_budget_exhausted")]


class TestStagnationSuppressor:
    """TERMINAL (card 3027): once tripped, emits Stop{reason} rather than a
    silent NoWorkNeeded — HEAD not advancing across cycles means further
    fix attempts cannot help, so the watch is over."""

    def test_below_threshold_passes_through(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, stagnation_count=1)
        messages = []
        tick(req, messages.append)
        assert isinstance(messages[0], StartFixSession)

    def test_at_threshold_stops_with_reason(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, stagnation_count=2)
        messages = []
        tick(req, messages.append)
        assert messages == [Stop(reason="stagnation_limit_reached")]

    def test_above_threshold_stops_with_reason(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, stagnation_count=3)
        messages = []
        tick(req, messages.append)
        assert messages == [Stop(reason="stagnation_limit_reached")]


class TestOnlyPendingChecksSuppressor:
    """Suppressor 4: v1's early-exit branch — every check still pending and
    nothing else actionable."""

    def test_only_pending_checks_yields_no_work_needed(self):
        snapshot = _snapshot()  # default: checks_pending=("still-running",), nothing else actionable
        req = TickRequest(pr_snapshot=snapshot)
        messages = []
        tick(req, messages.append)
        assert messages == [NoWorkNeeded()]

    def test_predicate_true_when_only_pending_checks_exist(self):
        snapshot = _snapshot()
        req = TickRequest(pr_snapshot=snapshot)
        assert smithers_module._only_pending_checks_and_nothing_else_actionable(req) is True

    def test_predicate_false_once_a_failing_check_joins_pending_ones(self):
        snapshot = _snapshot(checks_fail=("test",))  # checks_pending stays non-empty (default)
        req = TickRequest(pr_snapshot=snapshot)
        assert smithers_module._only_pending_checks_and_nothing_else_actionable(req) is False

    def test_predicate_false_when_no_checks_are_pending_at_all(self):
        snapshot = _snapshot(checks_pending=())
        req = TickRequest(pr_snapshot=snapshot)
        assert smithers_module._only_pending_checks_and_nothing_else_actionable(req) is False


class TestHoldSuppressors:
    def test_coordinator_hold_suppresses(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, coordinator_hold=True)
        messages = []
        tick(req, messages.append)
        assert messages == [NoWorkNeeded()]

    def test_manual_merge_opt_out_suppresses(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, manual_merge_opt_out=True)
        messages = []
        tick(req, messages.append)
        assert messages == [NoWorkNeeded()]

    def test_neither_hold_flag_set_passes_through(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot)
        messages = []
        tick(req, messages.append)
        assert isinstance(messages[0], StartFixSession)


class TestFixSessionInFlightSuppressor:
    def test_active_fix_session_suppresses(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, active_fix_session="smithers-fix-pr-123")
        messages = []
        tick(req, messages.append)
        assert messages == [NoWorkNeeded()]

    def test_no_active_fix_session_passes_through(self):
        snapshot = _snapshot(checks_fail=("test",), checks_pending=())
        req = TickRequest(pr_snapshot=snapshot, active_fix_session=None)
        messages = []
        tick(req, messages.append)
        assert isinstance(messages[0], StartFixSession)


class TestSuppressorsDoNotBlockLand:
    """Trigger 5 (ready-to-land) routes to the deterministic Land action, not
    a Claude invocation — the suppressors gate invocation only, so a
    fully-clean, ready-to-land snapshot lands even with every suppressor
    maximally active."""

    def test_ready_to_land_ignores_every_suppressor(self):
        snapshot = _snapshot(
            checks_pass=("build",),
            checks_pending=(),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            review_decision="APPROVED",
        )
        req = TickRequest(
            pr_snapshot=snapshot,
            fix_count=100,
            max_fix_invocations=4,
            cycle=100,
            max_cycles=10,
            stagnation_count=100,
            coordinator_hold=True,
            manual_merge_opt_out=True,
            active_fix_session="smithers-fix-pr-123",
        )
        messages = []
        tick(req, messages.append)
        assert messages == [Land(method="squash")]


# ---------------------------------------------------------------------------
# Notification adapters (§ Ports and adapters) — macOS via osascript, Slack
# exclusively via the smithers-post CLI. Real subprocess calls are always
# faked at the boundary (`subprocess.run`), never a real osascript/Slack
# call, per card constraints.
# ---------------------------------------------------------------------------

class TestNotifyMacosAdapter:
    def test_dry_run_logs_and_makes_no_subprocess_call(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=AssertionError("dry-run must not call osascript")):
            smithers_module.notify_macos(Notify(title="t", body="b", sound=True), dry_run=True, log_path=log_path)

        log_contents = open(log_path).read()
        assert "notify_macos_dry_run" in log_contents

    def test_real_run_invokes_osascript(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return fake_run_result()

        with patch("subprocess.run", side_effect=fake_run):
            smithers_module.notify_macos(Notify(title="t", body="b", sound=True), dry_run=False, log_path=log_path)

        assert len(calls) == 1
        assert calls[0][0] == "osascript"

    def test_non_notify_message_is_a_no_op(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=AssertionError("must not be called for a non-Notify message")):
            smithers_module.notify_macos(NoWorkNeeded(), dry_run=False, log_path=log_path)
        assert not os.path.exists(log_path)


def fake_dedup_run(claude_result="NOT_DUPLICATE", calls=None):
    """Build a subprocess.run side_effect that answers a `claude -p` dedup
    invocation with a canned verdict token and passes any other command
    (e.g. `smithers-post`) through to a plain successful fake result.
    Records every command into `calls` (a caller-supplied list) when given,
    so a test can assert both which commands ran and in what order."""

    def side_effect(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        if cmd[0] == "claude":
            return fake_run_result(stdout=json.dumps({"result": claude_result}))
        return fake_run_result()

    return side_effect


class TestNotifySlackAdapter:
    def test_dry_run_logs_and_makes_no_subprocess_call(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=AssertionError("dry-run must not call smithers-post")):
            smithers_module.notify_slack(
                Notify(title="t", body="b", sound=False), "123", dry_run=True, log_path=log_path, already_posted={}
            )

        log_contents = open(log_path).read()
        assert "notify_slack_dry_run" in log_contents

    def test_no_pr_number_is_a_no_op(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=AssertionError("must not be called with no PR number")):
            smithers_module.notify_slack(
                Notify(title="t", body="b", sound=False), None, dry_run=False, log_path=log_path, already_posted={}
            )
        assert not os.path.exists(log_path)

    # -- Direction 1: dedup query FOUND an existing post -> never post again --

    def test_dedup_found_skips_the_post_entirely(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        with patch("subprocess.run", side_effect=fake_dedup_run("DUPLICATE", calls)):
            smithers_module.notify_slack(
                Notify(title="t", body="b", sound=False), "123", dry_run=False, log_path=log_path, already_posted={}
            )

        assert calls == [
            [
                "claude", "-p", "--model", "sonnet", "--output-format", "json",
                "--allowedTools", smithers_module.SLACK_SEARCH_TOOL, "--permission-mode", "dontAsk",
            ]
        ], "must query Slack and then stop — smithers-post must never run when a duplicate is found"
        log_contents = open(log_path).read()
        assert "notify_slack_dedup_skip" in log_contents

    # -- Direction 2: dedup query did NOT find an existing post -> post --

    def test_dedup_not_found_posts_to_slack(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        with patch("subprocess.run", side_effect=fake_dedup_run("NOT_DUPLICATE", calls)):
            smithers_module.notify_slack(
                Notify(title="t", body="b", sound=False), "123", dry_run=False, log_path=log_path, already_posted={}
            )

        assert calls[0][0] == "claude", "must query Slack first"
        assert calls[-1] == ["smithers-post", "123"], "must post once no duplicate is found"
        log_contents = open(log_path).read()
        assert "notify_slack" in log_contents

    # -- Direction 3: dedup query FAILS -> fail OPEN and post anyway --

    def test_dedup_query_failure_fails_open_and_still_posts(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "claude":
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=45)
            return fake_run_result()

        with patch("subprocess.run", side_effect=fake_run):
            smithers_module.notify_slack(
                Notify(title="t", body="b", sound=False), "123", dry_run=False, log_path=log_path, already_posted={}
            )

        assert calls[-1] == ["smithers-post", "123"], "a failed dedup query must fail OPEN, not swallow the post"
        log_contents = open(log_path).read()
        assert "slack_dedup_query_failed" in log_contents
        assert "notify_slack_dedup_query_failed_posting_anyway" in log_contents
        assert "notify_slack" in log_contents

    def test_dedup_invocation_uses_the_scoped_allowlist(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        with patch("subprocess.run", side_effect=fake_dedup_run("NOT_DUPLICATE", calls)):
            smithers_module.notify_slack(
                Notify(title="t", body="b", sound=False), "123", dry_run=False, log_path=log_path, already_posted={}
            )

        claude_cmd = calls[0]
        assert claude_cmd[claude_cmd.index("--allowedTools") + 1] == smithers_module.SLACK_SEARCH_TOOL
        assert claude_cmd[claude_cmd.index("--permission-mode") + 1] == "dontAsk"

    def test_in_memory_cache_skips_a_second_slack_query_for_the_same_pr(self, tmp_path):
        """`already_posted` is a same-run cache of the dedup query's own
        outcome, never a second, independently-disagreeing mechanism — once
        set, later ticks in the same run must not re-query Slack at all."""
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        already_posted = {}
        with patch("subprocess.run", side_effect=fake_dedup_run("NOT_DUPLICATE", calls)):
            smithers_module.notify_slack(
                Notify(title="t1", body="b1", sound=False), "123", dry_run=False, log_path=log_path,
                already_posted=already_posted,
            )
            smithers_module.notify_slack(
                Notify(title="t2", body="b2", sound=False), "123", dry_run=False, log_path=log_path,
                already_posted=already_posted,
            )

        claude_calls = [c for c in calls if c[0] == "claude"]
        post_calls = [c for c in calls if c[0] == "smithers-post"]
        assert len(claude_calls) == 1, "must not query Slack twice for the same PR in one run"
        assert len(post_calls) == 1, "must not post to Slack twice for the same PR"
        log_contents = open(log_path).read()
        assert "notify_slack_dedup_skip" in log_contents


# ---------------------------------------------------------------------------
# query_slack_dedup() — direct unit tests (§ card 3031, cross-restart Slack
# dedup). `subprocess.run` is always faked at this boundary: never a real
# `claude -p` invocation, never a real Slack call.
# ---------------------------------------------------------------------------

class TestSlackDedupQuery:
    def test_duplicate_response_returns_true(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch(
            "subprocess.run",
            side_effect=lambda cmd, **kw: fake_run_result(stdout=json.dumps({"result": "DUPLICATE"})),
        ):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is True

    def test_not_duplicate_response_returns_false(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch(
            "subprocess.run",
            side_effect=lambda cmd, **kw: fake_run_result(stdout=json.dumps({"result": "NOT_DUPLICATE"})),
        ):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is False

    def test_lowercase_and_whitespace_padded_token_still_parses(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch(
            "subprocess.run",
            side_effect=lambda cmd, **kw: fake_run_result(stdout=json.dumps({"result": "  duplicate  \n"})),
        ):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is True

    def test_nonzero_exit_code_returns_none_and_logs_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch(
            "subprocess.run",
            side_effect=lambda cmd, **kw: fake_run_result(stdout="", stderr="permission denied", returncode=1),
        ):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is None
        log_contents = open(log_path).read()
        assert "slack_dedup_query_failed" in log_contents

    def test_timeout_returns_none_and_logs_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")

        def raise_timeout(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=45)

        with patch("subprocess.run", side_effect=raise_timeout):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is None
        log_contents = open(log_path).read()
        assert "slack_dedup_query_failed" in log_contents

    def test_unparseable_json_returns_none_and_logs_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch("subprocess.run", side_effect=lambda cmd, **kw: fake_run_result(stdout="not valid json")):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is None
        log_contents = open(log_path).read()
        assert "slack_dedup_query_failed" in log_contents

    def test_unrecognized_token_returns_none_and_logs_failure(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        with patch(
            "subprocess.run",
            side_effect=lambda cmd, **kw: fake_run_result(
                stdout=json.dumps({"result": "maybe? let me look again"})
            ),
        ):
            verdict = smithers_module.query_slack_dedup("123", log_path)
        assert verdict is None
        log_contents = open(log_path).read()
        assert "slack_dedup_query_failed" in log_contents

    def test_invocation_is_scoped_to_the_slack_search_tool_and_dont_ask_mode(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        captured = []

        def fake_run(cmd, **kw):
            captured.append(cmd)
            return fake_run_result(stdout=json.dumps({"result": "NOT_DUPLICATE"}))

        with patch("subprocess.run", side_effect=fake_run):
            smithers_module.query_slack_dedup("123", log_path)

        cmd = captured[0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert cmd[cmd.index("--allowedTools") + 1] == smithers_module.SLACK_SEARCH_TOOL
        assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
        assert cmd[cmd.index("--model") + 1] == "sonnet"

    def test_prompt_searches_by_pr_reference_not_by_channel(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        captured_input = []

        def fake_run(cmd, **kw):
            captured_input.append(kw.get("input", ""))
            return fake_run_result(stdout=json.dumps({"result": "NOT_DUPLICATE"}))

        with patch("subprocess.run", side_effect=fake_run):
            smithers_module.query_slack_dedup("999", log_path)

        assert "999" in captured_input[0]


class TestLogAdapter:
    def test_every_message_type_is_logged(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        smithers_module.log_adapter(Land(method="squash"), log_path)

        record = json.loads(open(log_path).read().strip())
        assert record["event"] == "message"
        assert record["type"] == "Land"
        assert record["method"] == "squash"


# ---------------------------------------------------------------------------
# Composition-root smoke test (§ Ports and adapters, Composition-root
# corollary) — builds `tick` through the REAL entry point (`build_send`, the
# composition root) with REAL adapters wired, against a recorded fixture.
# Only the outermost I/O boundary (`subprocess.run`) is faked, never `send`
# itself — an adapter `build_send` forgot to bind would silently never fire,
# and this class of test catches that; a handler-with-injected-fake unit
# test cannot.
# ---------------------------------------------------------------------------

class TestCompositionRootSmoke:
    def test_real_entry_point_logs_tick_output_for_a_recorded_fixture(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")

        with patch(
            "subprocess.run",
            side_effect=make_gh_side_effect(
                checks=json.dumps([{"name": "build", "bucket": "pass", "workflow": "CI"}]),
                prc=json.dumps({"comments": []}),
            ),
        ):
            snapshot, failure = fetch_pr_snapshot("123", log_path)
        assert failure is None

        req = TickRequest(pr_snapshot=snapshot)
        send = build_send(pr_number="123", dry_run=True, log_path=log_path)

        # tick is pure and every adapter must respect dry_run: no subprocess
        # call is expected at all once tick() emits through the real send.
        with patch("subprocess.run", side_effect=AssertionError("no subprocess calls expected in dry-run")):
            tick(req, send)

        records = [json.loads(line) for line in open(log_path).read().strip().splitlines()]
        message_records = [r for r in records if r["event"] == "message"]
        assert any(r["type"] == "Land" for r in message_records), (
            "the structured-log adapter never saw the Land message — build_send "
            "did not actually wire the log adapter into the real fan-out"
        )

    def test_real_entry_point_fires_both_notification_adapters(self, tmp_path):
        """Sends a Notify message directly through the REAL `send` built by
        `build_send` and asserts BOTH the macOS osascript adapter and the
        Slack smithers-post adapter actually fire — proving build_send's
        fan-out list really includes both, not just one silently dropped."""
        log_path = str(tmp_path / "smithers.jsonl")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return fake_run_result()

        send = build_send(pr_number="123", dry_run=False, log_path=log_path)

        with patch("subprocess.run", side_effect=fake_run):
            send(Notify(title="PR ready", body="squash and merge", sound=True))

        assert any(cmd[0] == "osascript" for cmd in calls), "macOS notify adapter never fired"
        assert any(cmd[0] == "smithers-post" for cmd in calls), "Slack notify adapter never fired"

    def test_dry_run_end_to_end_performs_no_notification_and_no_mutation(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        send = build_send(pr_number="123", dry_run=True, log_path=log_path)

        with patch("subprocess.run", side_effect=AssertionError("dry-run must not call any subprocess")):
            send(Notify(title="t", body="b", sound=False))

        log_contents = open(log_path).read()
        assert "notify_macos_dry_run" in log_contents
        assert "notify_slack_dry_run" in log_contents


# ---------------------------------------------------------------------------
# The poll loop (§ card 3021) — foreground, bounded-for-tests cadence. The
# clock is always faked here (`time.sleep` patched) — never sleeps for real.
# ---------------------------------------------------------------------------

NOTHING_ACTIONABLE_VIEW = json.dumps({
    "number": 123,
    "headRefOid": "abc123def456",
    "isDraft": True,  # excludes the ready-to-land trigger unambiguously
    "mergeable": "MERGEABLE",
    "mergeStateStatus": "CLEAN",
    "reviewDecision": "REVIEW_REQUIRED",
    "latestReviews": [],
})
NOTHING_ACTIONABLE_CHECKS = json.dumps([{"name": "lint", "bucket": "pending", "workflow": "CI"}])
NOTHING_ACTIONABLE_PRC = json.dumps({"comments": []})


class TestPollLoopTerminatesOnBound:
    def test_loop_returns_after_max_cycles_and_sleeps_the_baseline_interval(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        sent = []

        with patch(
            "subprocess.run",
            side_effect=make_gh_side_effect(
                view=NOTHING_ACTIONABLE_VIEW,
                checks=NOTHING_ACTIONABLE_CHECKS,
                prc=NOTHING_ACTIONABLE_PRC,
            ),
        ):
            with patch("time.sleep") as mock_sleep:
                config = PollLoopConfig(max_cycles=3, env={}, accept_api_billing=True)
                poll_loop("123", config, sent.append, log_path)

        # Three ticks, nothing actionable each time -> three NoWorkNeeded
        # messages, and the loop returns instead of looping forever.
        assert len(sent) == 3
        assert all(isinstance(msg, NoWorkNeeded) for msg in sent)
        # A legitimately empty/pending-only result is not a fetch failure —
        # each tick sleeps the ordinary baseline interval, never a backoff.
        assert mock_sleep.call_args_list == [call(60), call(60), call(60)]


class TestPollLoopTerminatesOnStop:
    """Card 3027: reproduces the invisible-degradation bug this card fixes —
    the gate's own cycle-budget suppressor (default threshold 10, a fixed
    TickRequest default independent of this loop's own `max_cycles` bound)
    trips well before the loop's outer bound of 15. Before this card, that
    tripped suppressor emitted a silent NoWorkNeeded forever after; now it
    emits Stop, and the loop must exit immediately rather than continuing to
    poll all the way to its outer bound."""

    def test_loop_exits_early_when_the_gates_cycle_budget_is_exhausted(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        sent = []

        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            with patch("time.sleep") as mock_sleep:
                config = PollLoopConfig(max_cycles=15, env={}, accept_api_billing=True)
                poll_loop("123", config, sent.append, log_path)

        # Nine fix-triggering ticks (a failing check fires every cycle, no
        # suppressor active yet), then a tenth tick where the gate's own
        # cycle >= max_cycles(10) default trips -> Stop, and the loop
        # returns instead of continuing on to the outer bound of 15.
        assert len(sent) == 10
        assert all(isinstance(msg, StartFixSession) for msg in sent[:-1])
        assert isinstance(sent[-1], Stop)
        assert sent[-1].reason == "cycle_budget_exhausted"

        # No sleep follows the Stop-carrying tick — the loop returns
        # immediately rather than sleeping and polling again.
        assert mock_sleep.call_count == 9

        log_contents = open(log_path).read()
        assert "poll_loop_stopped" in log_contents


class TestPollLoopPreflightRunsAheadOfEveryTick:
    def test_preflight_invoked_once_per_tick_not_once_per_run(self, tmp_path):
        """The carried-forward finding this card exists to close: preflight
        must fire on EVERY tick, not just once at process start. Asserting
        `call_count == max_cycles` (not merely `>= 1`) is what would catch a
        regression back to a startup-only preflight call."""
        log_path = str(tmp_path / "smithers.jsonl")
        sent = []

        with patch(
            "subprocess.run",
            side_effect=make_gh_side_effect(
                view=NOTHING_ACTIONABLE_VIEW,
                checks=NOTHING_ACTIONABLE_CHECKS,
                prc=NOTHING_ACTIONABLE_PRC,
            ),
        ):
            with patch("time.sleep"):
                with patch.object(smithers_module, "billing_preflight") as mock_preflight:
                    config = PollLoopConfig(max_cycles=4, env={}, accept_api_billing=True)
                    poll_loop("123", config, sent.append, log_path)

        assert mock_preflight.call_count == 4


class TestPollLoopBackoffOnRepeatedFetchFailure:
    def test_backoff_grows_and_caps_across_consecutive_failures(self, tmp_path):
        log_path = str(tmp_path / "smithers.jsonl")
        sent = []

        def always_fail(cmd, **kwargs):
            return fake_run_result(stdout="", stderr="rate limited", returncode=1)

        with patch("subprocess.run", side_effect=always_fail):
            with patch("time.sleep") as mock_sleep:
                config = PollLoopConfig(max_cycles=4, env={}, accept_api_billing=True)
                poll_loop("123", config, sent.append, log_path)

        # Exponential 300 -> 900 -> 1800, then capped at 1800 — never a
        # spin, and `tick` never ran so no message was ever sent.
        assert mock_sleep.call_args_list == [call(300), call(900), call(1800), call(1800)]
        assert sent == []

    def test_fix_trigger_still_reaches_the_stub_when_present(self, tmp_path):
        """A failing check IS actionable (§ The gate, trigger 1) — confirms
        the loop reaches `tick` and hands a fired trigger to the phase-3 fix
        stub rather than invoking anything real (§ card scope, OUT OF
        SCOPE)."""
        log_path = str(tmp_path / "smithers.jsonl")
        sent = []

        with patch("subprocess.run", side_effect=make_gh_side_effect()):
            with patch("time.sleep"):
                config = PollLoopConfig(max_cycles=1, env={}, accept_api_billing=True)
                poll_loop("123", config, sent.append, log_path)

        assert any(isinstance(msg, StartFixSession) for msg in sent)
        log_contents = open(log_path).read()
        assert "fix_invocation_stub_todo" in log_contents
