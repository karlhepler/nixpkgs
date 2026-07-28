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
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import smithers as smithers_module
from smithers import (
    REFUSAL_ENV_VARS,
    FetchFailure,
    PRSnapshot,
    billing_preflight,
    build_parser,
    cmd_watch,
    fetch_pr_snapshot,
    log_event,
    main,
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
    def test_watch_accepts_pr_argument(self):
        parser = build_parser()
        args = parser.parse_args(["watch", "123"])
        assert args.command == "watch"
        assert args.pr == "123"

    def test_watch_accepts_pr_url(self):
        parser = build_parser()
        args = parser.parse_args(["watch", "https://github.com/karlhepler/nixpkgs/pull/123"])
        assert args.pr == "https://github.com/karlhepler/nixpkgs/pull/123"

    def test_watch_accepts_dry_run_flag(self):
        parser = build_parser()
        args = parser.parse_args(["watch", "123", "--dry-run"])
        assert args.dry_run is True

    def test_watch_dry_run_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["watch", "123"])
        assert args.dry_run is False

    def test_watch_accept_api_billing_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["watch", "123"])
        assert args.accept_api_billing is False

    def test_watch_accept_api_billing_flag(self):
        parser = build_parser()
        args = parser.parse_args(["watch", "123", "--i-accept-api-billing"])
        assert args.accept_api_billing is True

    def test_missing_pr_argument_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["watch"])

    def test_missing_subcommand_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_top_level_help_exits_zero(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_watch_help_exits_zero(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["watch", "--help"])
        assert exc_info.value.code == 0


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
# TODO stubs — attachment points exist with the intended signatures
# ---------------------------------------------------------------------------

class TestPhaseStubsExist:
    def test_poll_loop_stub_raises_not_implemented(self):
        """poll_loop's signature now carries config + send (review carry-
        forward #3006 Finding 2) mirroring tick's own seam; the body is
        still a later-card TODO."""
        with pytest.raises(NotImplementedError):
            smithers_module.poll_loop("123", None, lambda msg: None, "/tmp/smithers.jsonl")

    def test_tick_stub_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            smithers_module.tick(None, lambda msg: None)


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
# cmd_watch() and main() — directly exercised (review carry-forward #3006
# Finding 3), mirroring test_crew.py's convention of testing cmd_* handlers.
# ---------------------------------------------------------------------------

class TestCmdWatch:
    def test_dry_run_passes_preflight_and_returns_zero(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        parser = build_parser()
        args = parser.parse_args(["watch", "123", "--dry-run", "--log-file", log_path])

        result = cmd_watch(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "dry run" in out
        assert "123" in out

    def test_non_dry_run_returns_zero_and_prints_skeleton_message(self, tmp_path, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        parser = build_parser()
        args = parser.parse_args(["watch", "123", "--log-file", log_path])

        result = cmd_watch(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "skeleton only" in out

    def test_billing_refusal_raises_systemexit_before_any_action(self, tmp_path, monkeypatch):
        log_path = str(tmp_path / "smithers.jsonl")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
        parser = build_parser()
        args = parser.parse_args(["watch", "123", "--dry-run", "--log-file", log_path])

        with pytest.raises(SystemExit):
            cmd_watch(args)

    def test_accept_api_billing_flag_bypasses_refusal(self, tmp_path, monkeypatch, capsys):
        log_path = str(tmp_path / "smithers.jsonl")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
        parser = build_parser()
        args = parser.parse_args(
            ["watch", "123", "--dry-run", "--i-accept-api-billing", "--log-file", log_path]
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
