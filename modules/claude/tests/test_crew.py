"""
Tests for crew.py — focused on the P6.1-P6.6 changes:
  - P6.1: crew list / status confined to current tmux session
  - P6.2: crew create accepts --tell
  - P6.3: default spawn command is 'staff', not 'claude'
  - P6.4: crew tell pane-0 default (already implemented; asserted here)
  - P6.5: --format xml is supported (no flag needed; already default)
  - P6.6: tests for all of the above
"""

import argparse
import json
import subprocess
import threading
import time
from io import StringIO
from typing import List, Optional, Tuple
from unittest.mock import MagicMock, call, patch

import pytest

# Import the module under test
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crew as crew_module
from crew import (
    _clean_stale_sentinel,
    _cleanup_sentinel,
    _CREW_SENTINEL_DIR,
    _ensure_hook_in_settings,
    _extract_org_repo_from_remote,
    _list_panes_in_window,
    _looks_like_message_not_target,
    _mangle_path_to_project_key,
    _pane_is_running_smithers,
    _pane_shows_prompt_ready,
    _resolve_targets_with_lookup,
    _sentinel_path,
    _SMITHERS_SPLIT_PERCENT,
    _tmux_fire_and_forget,
    _wait_for_sentinel,
    build_parser,
    cmd_create,
    cmd_dismiss,
    cmd_find,
    cmd_list,
    cmd_project_path,
    cmd_resume,
    cmd_sessions,
    cmd_smithers,
    cmd_status,
    cmd_tell,
    get_all_panes,
    get_current_session,
    get_window_lookup,
    is_claude_pane,
    resolve_worktree_path,
    run_post_switch_hook,
)


# ---------------------------------------------------------------------------
# Helper: build a fake subprocess.run result
# ---------------------------------------------------------------------------

def fake_run_result(stdout: str = "", returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


# ---------------------------------------------------------------------------
# P6.1 — get_current_session
# ---------------------------------------------------------------------------

class TestGetCurrentSession:
    def test_returns_session_name_when_in_tmux(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout="my-session\n")
            result = get_current_session()
        assert result == "my-session"
        mock_run.assert_called_once_with(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True, text=True, check=False
        )

    def test_returns_none_when_not_in_tmux(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout="")
            result = get_current_session()
        assert result is None


# ---------------------------------------------------------------------------
# P6.1 — get_all_panes scoping
# ---------------------------------------------------------------------------

class TestGetAllPanesScoping:
    def test_all_sessions_when_no_session_given(self):
        """get_all_panes() with no argument uses -a (all sessions)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout="")
            get_all_panes()
        cmd = mock_run.call_args[0][0]
        assert "-a" in cmd
        assert "-t" not in cmd

    def test_single_session_when_session_given(self):
        """get_all_panes(session='foo') uses -t foo -s (current session only)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout="")
            get_all_panes(session="foo")
        cmd = mock_run.call_args[0][0]
        assert "-a" not in cmd
        assert "-t" in cmd
        assert "foo" in cmd
        assert "-s" in cmd

    def test_parses_pane_lines_correctly(self):
        raw = (
            "my-session|0|window-a|0|zsh\n"
            "my-session|0|window-a|1|claude\n"
            "my-session|1|window-b|0|2.1.100\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout=raw)
            panes = get_all_panes(session="my-session")
        assert len(panes) == 3
        assert panes[0] == ("my-session", "0", "window-a", "0", "zsh")
        assert panes[2] == ("my-session", "1", "window-b", "0", "2.1.100")


# ---------------------------------------------------------------------------
# P6.1 — cmd_list uses current session
# ---------------------------------------------------------------------------

class TestCmdListSessionScoping:
    def test_cmd_list_queries_current_session_only(self, capsys):
        """cmd_list must call get_all_panes with the current session name."""
        session_panes = [
            ("tidy-crown", "0", "staff-window", "0", "2.1.100"),
        ]
        with patch.object(crew_module, "get_current_session", return_value="tidy-crown"):
            with patch.object(crew_module, "get_all_panes", return_value=session_panes) as mock_panes:
                cmd_list(fmt="xml")
        mock_panes.assert_called_once_with(session="tidy-crown")

    def test_cmd_list_does_not_show_other_session_windows(self, capsys):
        """Windows from other sessions must NOT appear in cmd_list output."""
        # Only the current session pane is returned by the patched get_all_panes
        session_panes = [
            ("tidy-crown", "0", "my-worker", "0", "2.1.100"),
        ]
        with patch.object(crew_module, "get_current_session", return_value="tidy-crown"):
            with patch.object(crew_module, "get_all_panes", return_value=session_panes):
                cmd_list(fmt="xml")
        out = capsys.readouterr().out
        assert "my-worker" in out
        # Simulate that hms--expunge would appear if -a were used; it doesn't here.
        assert "hms" not in out


# ---------------------------------------------------------------------------
# P6.1 — cmd_status uses current session
# ---------------------------------------------------------------------------

class TestCmdStatusSessionScoping:
    def test_cmd_status_queries_current_session_only(self, capsys):
        """cmd_status must call get_all_panes with the current session name."""
        session_panes = [
            ("tidy-crown", "0", "staff-window", "0", "2.1.100"),
        ]
        with patch.object(crew_module, "get_current_session", return_value="tidy-crown"):
            with patch.object(crew_module, "get_all_panes", return_value=session_panes) as mock_panes:
                with patch.object(crew_module, "capture_pane", return_value="some content\n"):
                    cmd_status(lines=10, fmt="xml")
        mock_panes.assert_called_once_with(session="tidy-crown")


# ---------------------------------------------------------------------------
# P6.2 + P6.3 — cmd_create --tell and default staff command
# ---------------------------------------------------------------------------

class TestCmdCreate:
    """Test crew create behavior: default staff command, --tell support."""

    def _setup_create_mocks(self, mock_run, worktree_path_exists=False, fetch_should_fail=False):
        """Configure mock_run side_effect for a typical successful create flow.

        Args:
            mock_run: The patched subprocess.run mock to configure.
            worktree_path_exists: If True, simulate the worktree path already existing.
            fetch_should_fail: If True, simulate git fetch origin failing (returncode=1).
        """
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")  # no existing windows
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                # Default: branch tracks origin
                return fake_run_result(stdout="origin/main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                # Base existence check: base ref resolves
                return fake_run_result(stdout="abc1234\n")
            if "fetch" in joined and "origin" in joined:
                if fetch_should_fail:
                    return fake_run_result(returncode=1, stdout="")
                return fake_run_result()
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)  # branch doesn't exist
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            if "capture-pane" in joined:
                return fake_run_result(stdout="> \n")  # prompt-ready signal
            return fake_run_result()
        mock_run.side_effect = side_effect

    def _run_create(self, mock_run, fetch_should_fail=False, **kwargs):
        """Run cmd_create with standard mocks for filesystem checks."""
        with patch("os.path.isdir", return_value=True):
            with patch("os.path.exists", return_value=False):
                self._setup_create_mocks(mock_run, fetch_should_fail=fetch_should_fail)
                cmd_create(**kwargs)

    def test_default_command_is_staff(self, capsys, tmp_path):
        """cmd_create must spawn 'staff --model sonnet --name <name>' by default (P6.3)."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
            )

        # Find the send-keys call that spawns the command
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        spawn_call = next(
            (c for c in send_keys_calls if "staff" in " ".join(str(x) for x in c[0][0])),
            None,
        )
        assert spawn_call is not None, "Expected a send-keys call with 'staff'"
        cmd_str = " ".join(str(x) for x in spawn_call[0][0])
        assert "staff --model sonnet --name test-worker" in cmd_str
        # Must NOT spawn bare 'claude' as the first command
        assert "claude --name test-worker" not in cmd_str

    def test_cmd_override_does_not_include_model_sonnet(self, capsys, tmp_path):
        """--cmd override must NOT have --model sonnet injected (caller controls model)."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
                cmd_override="claude",
            )

        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        spawn_call = next(
            (c for c in send_keys_calls if "claude" in " ".join(str(x) for x in c[0][0])),
            None,
        )
        assert spawn_call is not None, "Expected a send-keys call with 'claude'"
        cmd_str = " ".join(str(x) for x in spawn_call[0][0])
        assert "--model sonnet" not in cmd_str, (
            f"--model sonnet must not be injected into --cmd override, got: {cmd_str!r}"
        )

    def test_cmd_override_replaces_staff(self, capsys, tmp_path):
        """--cmd claude overrides the default 'staff' spawn (P6.3 override path)."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
                cmd_override="claude",
            )

        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        spawn_call = next(
            (c for c in send_keys_calls if "claude" in " ".join(str(x) for x in c[0][0])),
            None,
        )
        assert spawn_call is not None, "Expected a send-keys call with 'claude'"
        cmd_str = " ".join(str(x) for x in spawn_call[0][0])
        assert "claude --name test-worker" in cmd_str

    def test_tell_sends_message_after_spawn(self, capsys, tmp_path):
        """--tell delivers initial message after sentinel is ready (P6.2)."""
        with patch("subprocess.run") as mock_run:
            with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                with patch.object(crew_module, "_deliver_tell", return_value=(True, "verified")) as mock_deliver:
                    self._run_create(
                        mock_run,
                        name="test-worker",
                        repo="/some/repo",
                        branch="test-worker",
                        base="main",
                        fmt="xml",
                        tell="Build the auth service",
                    )

        mock_deliver.assert_called_once_with("test-worker", "Build the auth service")

    def test_no_tell_skips_message_delivery(self, capsys, tmp_path):
        """Without --tell, no extra send-keys for a message is issued (P6.2)."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
                tell=None,
            )

        # There should only be ONE send-keys call (the spawn command)
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        assert len(send_keys_calls) == 1, (
            f"Expected exactly 1 send-keys call (spawn), got {len(send_keys_calls)}"
        )

    def test_xml_output_includes_command_field(self, capsys, tmp_path):
        """XML output from cmd_create includes the command attribute (P6.3)."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
            )
        out = capsys.readouterr().out
        assert 'command="staff"' in out

    def test_xml_output_includes_told_when_tell_given(self, capsys, tmp_path):
        """XML output includes told='true' when --tell delivery is verified (P6.2)."""
        with patch("subprocess.run") as mock_run:
            with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                with patch.object(crew_module, "_deliver_tell", return_value=(True, "verified")):
                    self._run_create(
                        mock_run,
                        name="test-worker",
                        repo="/some/repo",
                        branch="test-worker",
                        base="main",
                        fmt="xml",
                        tell="Hello crew",
                    )
        out = capsys.readouterr().out
        assert 'told="true"' in out

    def test_tell_text_verified_in_pane_after_delivery(self, capsys, tmp_path):
        """told='true' requires brief text to be observed in capture-pane (regression for race bug)."""
        tell_text = "Build the auth service"

        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "capture-pane" in joined:
                # Verification call: brief text visible in pane
                return fake_run_result(stdout=f"╭─ Claude Code ─╮\n{tell_text}\n")
            if "send-keys" in joined:
                return fake_run_result()
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            return fake_run_result()

        # Mock _wait_for_sentinel to return ready — this test is specifically about
        # _deliver_tell pane verification, not readiness detection.
        with patch("subprocess.run", side_effect=side_effect):
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch="test-worker",
                            base="main",
                            fmt="xml",
                            tell=tell_text,
                        )

        out = capsys.readouterr().out
        assert 'told="true"' in out
        assert "told_reason" not in out

    def test_tell_told_false_when_verification_times_out(self, capsys, tmp_path):
        """told='false' + told_reason when tell text never appears in pane."""
        with patch("subprocess.run") as mock_run:
            with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                with patch.object(
                    crew_module,
                    "_deliver_tell",
                    return_value=(False, "verification timeout: tell text not observed in pane"),
                ):
                    self._run_create(
                        mock_run,
                        name="test-worker",
                        repo="/some/repo",
                        branch="test-worker",
                        base="main",
                        fmt="xml",
                        tell="Build the auth service",
                    )

        out = capsys.readouterr().out
        assert 'told="false"' in out
        assert "told_reason" in out

    def test_tell_told_false_when_sentinel_never_ready(self, capsys, tmp_path):
        """told='false' when _wait_for_sentinel ceiling elapsed (Claude didn't start)."""
        with patch("subprocess.run") as mock_run:
            with patch.object(
                crew_module,
                "_wait_for_sentinel",
                return_value=(False, "session never reported ready — sentinel file not written (SessionStart hook may be missing) and prompt-box token not observed in pane"),
            ):
                self._run_create(
                    mock_run,
                    name="test-worker",
                    repo="/some/repo",
                    branch="test-worker",
                    base="main",
                    fmt="xml",
                    tell="Build the auth service",
                )

        out = capsys.readouterr().out
        assert "told_reason" in out
        assert 'told="false"' in out
        assert "sentinel file not written" in out

    def test_fetch_called_when_base_tracks_origin(self, capsys, tmp_path):
        """When base tracks origin, git fetch origin <base> is called before worktree add."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
            )

            all_cmds = [" ".join(str(x) for x in c[0][0]) for c in mock_run.call_args_list]
            fetch_cmds = [c for c in all_cmds if "fetch" in c and "origin" in c and "main" in c]
            assert len(fetch_cmds) == 1, f"Expected exactly 1 fetch call, got: {fetch_cmds}"

            # Fetch must occur BEFORE worktree add
            fetch_idx = next(i for i, c in enumerate(all_cmds) if "fetch" in c and "origin" in c)
            worktree_idx = next(i for i, c in enumerate(all_cmds) if "worktree" in c and "add" in c)
            assert fetch_idx < worktree_idx, "fetch must happen before worktree add"

    def test_fetch_failure_falls_back_to_local_ref(self, capsys, tmp_path):
        """When fetch fails, cmd_create continues with local ref (non-fatal)."""
        with patch("subprocess.run") as mock_run:
            self._run_create(
                mock_run,
                name="test-worker",
                repo="/some/repo",
                branch="test-worker",
                base="main",
                fmt="xml",
                fetch_should_fail=True,
            )

        err = capsys.readouterr().err
        assert "warning: fetch origin/main failed" in err
        # Worktree add must still have been called (fallback succeeded)
        all_cmds = [" ".join(str(x) for x in c[0][0]) for c in mock_run.call_args_list]
        worktree_cmds = [c for c in all_cmds if "worktree" in c and "add" in c]
        assert len(worktree_cmds) == 1, "worktree add must still be called after fetch failure"

    def test_local_only_base_skips_fetch(self, capsys, tmp_path):
        """When base has no upstream tracking ref, fetch is skipped entirely."""
        def side_effect_no_upstream(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "fetch" in joined:
                raise AssertionError("fetch must NOT be called for local-only base")
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="local-feature\n")
            if "rev-parse" in joined and "upstream" in joined:
                # No upstream tracking ref
                return fake_run_result(returncode=128)
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "local-feature" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            if "capture-pane" in joined:
                return fake_run_result(stdout="> \n")
            return fake_run_result()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effect_no_upstream
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    cmd_create(
                        name="test-worker",
                        repo="/some/repo",
                        branch="test-worker",
                        base="local-feature",
                        fmt="xml",
                    )

        err = capsys.readouterr().err
        assert "local-only" in err

    def test_nonexistent_base_errors_cleanly(self, capsys, tmp_path):
        """When base doesn't exist locally or remotely, emit BRANCH_NOT_FOUND."""
        def side_effect_no_base(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                # Base existence check fails — branch doesn't exist
                return fake_run_result(returncode=128)
            return fake_run_result()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effect_no_base
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with pytest.raises(SystemExit) as exc_info:
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch="test-worker",
                            base="does-not-exist",
                            fmt="xml",
                        )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "BRANCH_NOT_FOUND" in output or "does not exist" in output


# ---------------------------------------------------------------------------
# P6.4 — crew tell pane-0 default via _resolve_targets_with_lookup
# ---------------------------------------------------------------------------

class TestTellPaneZeroDefault:
    def test_bare_window_name_resolves_to_pane_zero(self):
        """A target without a dot suffix must resolve to pane 0 (P6.4)."""
        lookup = {"my-worker": ("some-session:0", "@42")}
        resolved = _resolve_targets_with_lookup("my-worker", lookup, fmt="xml")
        assert len(resolved) == 1
        tmux_target, label, window_id = resolved[0]
        assert tmux_target == "some-session:0.0"
        assert label == "my-worker.0"
        assert window_id == "@42"

    def test_explicit_dot_zero_also_resolves_to_pane_zero(self):
        """Explicit .0 suffix still works (P6.4 backward compat)."""
        lookup = {"my-worker": ("some-session:0", "@42")}
        resolved = _resolve_targets_with_lookup("my-worker.0", lookup, fmt="xml")
        tmux_target, label, _ = resolved[0]
        assert tmux_target == "some-session:0.0"
        assert label == "my-worker.0"

    def test_explicit_non_zero_pane_respected(self):
        """Explicit .N suffix is respected for non-zero panes (P6.4)."""
        lookup = {"my-worker": ("some-session:0", "@42")}
        resolved = _resolve_targets_with_lookup("my-worker.1", lookup, fmt="xml")
        tmux_target, label, _ = resolved[0]
        assert tmux_target == "some-session:0.1"
        assert label == "my-worker.1"


# ---------------------------------------------------------------------------
# P6.5 — --format xml is the default and explicitly accepted
# ---------------------------------------------------------------------------

class TestFormatFlag:
    def test_default_format_is_xml(self):
        """The default --format value must be 'xml' (P6.5)."""
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.format == "xml"

    def test_explicit_format_xml_accepted(self):
        """--format xml must be accepted without error (P6.5)."""
        parser = build_parser()
        args = parser.parse_args(["--format", "xml", "list"])
        assert args.format == "xml"

    def test_format_json_accepted(self):
        parser = build_parser()
        args = parser.parse_args(["--format", "json", "list"])
        assert args.format == "json"

    def test_format_human_accepted(self):
        parser = build_parser()
        args = parser.parse_args(["--format", "human", "list"])
        assert args.format == "human"


# ---------------------------------------------------------------------------
# P6.2 + P6.3 — parser wiring for --tell and --cmd
# ---------------------------------------------------------------------------

class TestCreateParserArgs:
    def test_tell_flag_accepted(self):
        """--tell is accepted by the create subcommand (P6.2)."""
        parser = build_parser()
        args = parser.parse_args(["create", "my-worker", "--tell", "Build the service"])
        assert args.tell == "Build the service"

    def test_tell_defaults_to_none(self):
        """--tell is None when not provided (P6.2)."""
        parser = build_parser()
        args = parser.parse_args(["create", "my-worker"])
        assert args.tell is None

    def test_cmd_override_accepted(self):
        """--cmd is accepted by the create subcommand (P6.3)."""
        parser = build_parser()
        args = parser.parse_args(["create", "my-worker", "--cmd", "claude"])
        assert args.cmd_override == "claude"

    def test_cmd_override_defaults_to_none(self):
        """--cmd is None when not provided; default 'staff' is applied at runtime (P6.3)."""
        parser = build_parser()
        args = parser.parse_args(["create", "my-worker"])
        assert args.cmd_override is None


# ---------------------------------------------------------------------------
# M-01 — cmd_find no-targets path scopes to current session
# ---------------------------------------------------------------------------

class TestCmdFindSessionScoping:
    def test_cmd_find_no_targets_queries_current_session_only(self, capsys):
        """cmd_find without targets must call get_all_panes with current session (M-01)."""
        session_panes = [
            ("tidy-crown", "0", "worker-window", "0", "2.1.100"),
        ]
        with patch.object(crew_module, "get_current_session", return_value="tidy-crown"):
            with patch.object(crew_module, "get_all_panes", return_value=session_panes) as mock_panes:
                with patch.object(crew_module, "capture_pane", return_value="no match here\n"):
                    cmd_find(pattern="nomatch", targets_str=None, lines=None, fmt="xml")
        mock_panes.assert_called_once_with(session="tidy-crown")

    def test_cmd_find_no_targets_outside_tmux_passes_none_session(self, capsys):
        """cmd_find without targets outside tmux passes None to get_all_panes (M-01 fallback)."""
        with patch.object(crew_module, "get_current_session", return_value=None):
            with patch.object(crew_module, "get_all_panes", return_value=[]) as mock_panes:
                cmd_find(pattern="anything", targets_str=None, lines=None, fmt="xml")
        mock_panes.assert_called_once_with(session=None)

    def test_cmd_find_with_targets_does_not_call_get_all_panes(self, capsys):
        """cmd_find with explicit targets resolves via resolve_targets, not get_all_panes."""
        with patch.object(crew_module, "get_all_panes") as mock_panes:
            with patch.object(crew_module, "resolve_targets", return_value=[]) as mock_resolve:
                cmd_find(pattern="anything", targets_str="my-worker", lines=None, fmt="xml")
        mock_panes.assert_not_called()
        mock_resolve.assert_called_once()


# ---------------------------------------------------------------------------
# is_claude_pane (regression guard — no changes, but must still work)
# ---------------------------------------------------------------------------

class TestIsClaudePaneRegression:
    @pytest.mark.parametrize("cmd,expected", [
        ("claude", True),
        ("node", True),
        ("2.1.116", True),
        ("3.0.0", True),
        ("zsh", False),
        ("bash", False),
        ("vim", False),
        ("smithers", False),
        ("staff", False),  # staff is NOT claude itself; crew filters on pane cmd
    ])
    def test_is_claude_pane(self, cmd, expected):
        assert is_claude_pane(cmd) == expected


# ---------------------------------------------------------------------------
# Legacy arg-order heuristic — _looks_like_message_not_target
# ---------------------------------------------------------------------------

class TestLegacyArgOrder:
    def test_multi_word_msg_triggers_legacy_error(self):
        """Multi-word phrase (space between words) is detected as a message."""
        assert _looks_like_message_not_target("Deploy the service") is True

    def test_single_space_msg_triggers_legacy_error(self):
        """Two-word phrase with a single space triggers detection (widened heuristic)."""
        assert _looks_like_message_not_target("fix it") is True

    def test_non_ascii_triggers_legacy_error(self):
        """Non-ASCII characters (e.g. emoji) trigger detection."""
        assert _looks_like_message_not_target("Fix 🚀") is True

    def test_sentence_punctuation_triggers_legacy_error(self):
        """Trailing sentence punctuation triggers detection."""
        assert _looks_like_message_not_target("Fix it.") is True

    def test_valid_window_name_does_not_trigger_heuristic(self):
        """A valid crew window name (no spaces, ASCII only) does not trigger detection."""
        assert _looks_like_message_not_target("my-worker") is False


# ---------------------------------------------------------------------------
# _mangle_path_to_project_key
# ---------------------------------------------------------------------------

class TestManglePathToProjectKey:
    def test_simple_path_mangled_correctly(self):
        """/foo/bar maps to -foo-bar (each / becomes -)."""
        assert _mangle_path_to_project_key("/foo/bar") == "-foo-bar"

    def test_deeply_nested_path(self):
        """Realistic worktree path is mangled to match ~/.claude/projects/ layout."""
        path = "/Users/karlhepler/worktrees/mazedesignhq/maze-monorepo"
        expected = "-Users-karlhepler-worktrees-mazedesignhq-maze-monorepo"
        assert _mangle_path_to_project_key(path) == expected

    def test_single_slash_becomes_leading_dash(self):
        """Root path '/' maps to a single '-'."""
        assert _mangle_path_to_project_key("/") == "-"

    def test_path_with_dot_preserved(self):
        """Dots in directory names are preserved unchanged."""
        path = "/Users/user/my.project/sub.dir"
        expected = "-Users-user-my.project-sub.dir"
        assert _mangle_path_to_project_key(path) == expected


# ---------------------------------------------------------------------------
# cmd_project_path
# ---------------------------------------------------------------------------

class _SpySend:
    """Test spy for the cmd_project_path send port."""

    def __init__(self) -> None:
        self.result_calls: List[tuple] = []
        self.failure_calls: List[tuple] = []

    def result(self, worktree_path, project_key, sessions_dir_exists, session_files):
        self.result_calls.append((worktree_path, project_key, sessions_dir_exists, session_files))

    def failure(self, error_code, message):
        self.failure_calls.append((error_code, message))


class TestCmdProjectPath:
    def test_emits_mangled_key_for_worktree(self, tmp_path):
        """Happy path: existing directory emits correct project key via send.result."""
        send = _SpySend()
        cmd_project_path(str(tmp_path), fmt="xml", send=send)

        assert len(send.result_calls) == 1
        assert len(send.failure_calls) == 0

        worktree_path, project_key, sessions_dir_exists, session_files = send.result_calls[0]
        assert worktree_path == str(tmp_path)
        assert project_key == _mangle_path_to_project_key(str(tmp_path))
        # The ~/.claude/projects/ dir for tmp_path won't exist in tests.
        assert sessions_dir_exists is False
        assert session_files == []

    def test_emits_failure_for_nonexistent_path(self, tmp_path):
        """Non-existent path emits send.failure with PATH_NOT_FOUND error code."""
        send = _SpySend()
        nonexistent = str(tmp_path / "does_not_exist")
        cmd_project_path(nonexistent, fmt="xml", send=send)

        assert len(send.result_calls) == 0
        assert len(send.failure_calls) == 1

        error_code, message = send.failure_calls[0]
        assert error_code == "PATH_NOT_FOUND"
        assert "does_not_exist" in message

    def test_handles_dot_as_cwd(self, monkeypatch, tmp_path):
        """'.' resolves to cwd and is mangled correctly via send.result."""
        monkeypatch.chdir(tmp_path)
        send = _SpySend()
        cmd_project_path(".", fmt="xml", send=send)

        assert len(send.result_calls) == 1
        assert len(send.failure_calls) == 0

        worktree_path, project_key, _, _ = send.result_calls[0]
        assert worktree_path == str(tmp_path)
        assert project_key == _mangle_path_to_project_key(str(tmp_path))


# ---------------------------------------------------------------------------
# cmd_sessions
# ---------------------------------------------------------------------------

class _SessionsSpySend:
    """Test spy for the cmd_sessions send port."""

    def __init__(self) -> None:
        self.session_calls: List[tuple] = []
        self.warning_calls: List[str] = []
        self.failure_calls: List[tuple] = []

    def session(self, window: str, worktree: str, session_id: str, last_modified: str) -> None:
        self.session_calls.append((window, worktree, session_id, last_modified))

    def warning(self, message: str) -> None:
        self.warning_calls.append(message)

    def failure(self, error_code: str, message: str) -> None:
        self.failure_calls.append((error_code, message))


class TestCmdSessions:
    def test_emits_sessions_for_active_window(self, tmp_path, monkeypatch):
        """Happy path: emits one session per .jsonl file found for the window's worktree."""
        # Set up a fake ~/.claude/projects/ directory with one .jsonl file.
        worktree_path = str(tmp_path / "my-worktree")
        project_key = _mangle_path_to_project_key(worktree_path)
        projects_dir = tmp_path / ".claude" / "projects" / project_key
        projects_dir.mkdir(parents=True)
        session_file = projects_dir / "abc123.jsonl"
        session_file.write_text("{}")

        # Patch Path.home() to point at tmp_path.
        monkeypatch.setattr(
            "crew.Path.home",
            lambda: tmp_path,
        )

        # Fake tmux: window lookup returns one window, display-message returns worktree_path.
        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="test-session\n")
            if "list-windows" in joined:
                return fake_run_result(
                    stdout=f"test-session:0|@1|my-worker\n"
                )
            if "display-message" in joined and "pane_current_path" in joined:
                return fake_run_result(stdout=worktree_path + "\n")
            return fake_run_result()

        send = _SessionsSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_sessions(fmt="xml", send=send)

        assert len(send.session_calls) == 1
        assert len(send.failure_calls) == 0
        window, worktree, session_id, last_modified = send.session_calls[0]
        assert window == "my-worker"
        assert worktree == worktree_path
        assert session_id == "abc123"

    def test_filters_by_window_name(self, tmp_path, monkeypatch):
        """--window filter restricts output to the named window only."""
        worktree_path = str(tmp_path / "my-worktree")
        project_key = _mangle_path_to_project_key(worktree_path)
        projects_dir = tmp_path / ".claude" / "projects" / project_key
        projects_dir.mkdir(parents=True)
        (projects_dir / "session-xyz.jsonl").write_text("{}")

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="test-session\n")
            if "list-windows" in joined:
                # Two windows: target-window and other-window
                return fake_run_result(
                    stdout=(
                        "test-session:0|@1|target-window\n"
                        "test-session:1|@2|other-window\n"
                    )
                )
            if "display-message" in joined and "pane_current_path" in joined:
                return fake_run_result(stdout=worktree_path + "\n")
            return fake_run_result()

        send = _SessionsSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_sessions(fmt="xml", send=send, window_filter="target-window")

        # Only the target-window sessions should be emitted.
        assert len(send.session_calls) == 1
        assert send.session_calls[0][0] == "target-window"
        assert len(send.failure_calls) == 0

    def test_emits_warning_when_no_sessions(self, tmp_path, monkeypatch):
        """Empty projects dir (no .jsonl files) emits a warning via send.warning."""
        worktree_path = str(tmp_path / "my-worktree")
        # Do NOT create any .jsonl files — projects dir is absent entirely.

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="test-session\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="test-session:0|@1|empty-window\n")
            if "display-message" in joined and "pane_current_path" in joined:
                return fake_run_result(stdout=worktree_path + "\n")
            return fake_run_result()

        send = _SessionsSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_sessions(fmt="xml", send=send, window_filter="empty-window")

        assert len(send.session_calls) == 0
        assert len(send.warning_calls) == 1
        assert "empty-window" in send.warning_calls[0]
        assert len(send.failure_calls) == 0

    def test_emits_failure_when_window_not_found(self, tmp_path, monkeypatch):
        """--window missing emits send.failure with WINDOW_NOT_FOUND error code."""
        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="test-session\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="test-session:0|@1|real-window\n")
            return fake_run_result()

        send = _SessionsSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_sessions(fmt="xml", send=send, window_filter="missing-window")

        assert len(send.session_calls) == 0
        assert len(send.warning_calls) == 0
        assert len(send.failure_calls) == 1
        error_code, message = send.failure_calls[0]
        assert error_code == "WINDOW_NOT_FOUND"
        assert "missing-window" in message


# ---------------------------------------------------------------------------
# cmd_resume
# ---------------------------------------------------------------------------

class _ResumeSpySend:
    """Test spy for the cmd_resume send port."""

    def __init__(self) -> None:
        self.resumed_calls: List[tuple] = []
        self.warning_calls: List[str] = []
        self.failure_calls: List[tuple] = []

    def resumed(self, window: str, session_id: str, worktree: str, command: str) -> None:
        self.resumed_calls.append((window, session_id, worktree, command))

    def warning(self, message: str) -> None:
        self.warning_calls.append(message)

    def failure(self, error_code: str, message: str) -> None:
        self.failure_calls.append((error_code, message))


class TestCmdResume:
    """Tests for cmd_resume: recreate tmux window and resume a Claude session."""

    def _make_session_dir(self, tmp_path, worktree_path: str, session_ids: List[str]):
        """Create a fake ~/.claude/projects/<key>/ with the given .jsonl files.

        session_ids is treated as oldest-first, newest-last. The last entry in the
        list will have the highest mtime so _find_session_files picks it first.
        """
        project_key = _mangle_path_to_project_key(worktree_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)
        import time as _time
        base_mtime = _time.time()
        # Assign ascending mtimes: session_ids[0] = oldest, session_ids[-1] = newest.
        for i, sid in enumerate(session_ids):
            f = sessions_dir / f"{sid}.jsonl"
            f.write_text("{}")
            os.utime(f, (base_mtime + i, base_mtime + i))
        return sessions_dir

    def test_resumes_window_with_inferred_session(self, tmp_path, monkeypatch):
        """Happy path: no --session given; most recent .jsonl is picked; window + send-keys called."""
        worktree_path = str(tmp_path / "my-worktree")
        os.makedirs(worktree_path)
        self._make_session_dir(tmp_path, worktree_path, ["older-uuid", "newest-uuid"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        # Patch worktree resolution so the test-controlled path is returned.
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: worktree_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                # No existing window named my-worker (_tmux_window_exists check)
                return fake_run_result(stdout="")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("my-worker", None, "xml", send)

        assert len(send.failure_calls) == 0
        assert len(send.resumed_calls) == 1
        window, session_id, worktree, command = send.resumed_calls[0]
        assert window == "my-worker"
        assert worktree == worktree_path
        # The most-recent file (newest-uuid, highest mtime) must be selected.
        assert session_id == "newest-uuid"
        assert "--resume newest-uuid" in command

    def test_resumes_window_with_explicit_session_id(self, tmp_path, monkeypatch):
        """Explicit --session ID bypasses mtime inference and uses the given ID directly."""
        worktree_path = str(tmp_path / "explicit-worktree")
        os.makedirs(worktree_path)
        self._make_session_dir(tmp_path, worktree_path, ["old-session", "explicit-session"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: worktree_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("explicit-worktree", "explicit-session", "xml", send)

        assert len(send.failure_calls) == 0
        assert len(send.resumed_calls) == 1
        _, session_id, _, command = send.resumed_calls[0]
        assert session_id == "explicit-session"
        assert "--resume explicit-session" in command

    def test_emits_failure_when_window_exists(self, tmp_path, monkeypatch):
        """If the tmux window already exists, emit WINDOW_EXISTS failure and abort."""
        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                # Window 'existing-window' is already present
                return fake_run_result(stdout="existing-window\n")
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("existing-window", None, "xml", send)

        assert send.resumed_calls == []
        assert len(send.failure_calls) == 1
        error_code, message = send.failure_calls[0]
        assert error_code == "WINDOW_EXISTS"
        assert "existing-window" in message

    def test_emits_failure_when_no_session_found(self, tmp_path, monkeypatch):
        """When no .jsonl files exist for the worktree, emit NO_SESSION failure."""
        worktree_path = str(tmp_path / "empty-worktree")
        os.makedirs(worktree_path)
        # Do NOT create any .jsonl files — projects dir is absent

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        # Patch worktree resolution so the resolver returns the test path.
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: worktree_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("empty-worktree", None, "xml", send)

        assert send.resumed_calls == []
        assert len(send.failure_calls) == 1
        error_code, message = send.failure_calls[0]
        assert error_code == "NO_SESSION"
        assert "crew create" in message

    def test_warns_when_multiple_sessions_and_picks_most_recent(self, tmp_path, monkeypatch):
        """When multiple sessions exist and no --session given, pick most recent and emit warning."""
        worktree_path = str(tmp_path / "multi-session-worktree")
        os.makedirs(worktree_path)
        self._make_session_dir(tmp_path, worktree_path, ["alpha-uuid", "beta-uuid", "gamma-uuid"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: worktree_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("multi-session-worktree", None, "xml", send)

        # Must succeed
        assert len(send.failure_calls) == 0
        assert len(send.resumed_calls) == 1
        # Must emit exactly one warning about multiple sessions
        assert len(send.warning_calls) == 1
        assert "multiple sessions" in send.warning_calls[0]
        # The most recent session must be selected (gamma-uuid has the highest mtime)
        _, session_id, _, _ = send.resumed_calls[0]
        assert session_id == "gamma-uuid"

    def test_emits_failure_when_worktree_not_found(self, tmp_path, monkeypatch):
        """When _resolve_worktree_for_name returns None, emit WORKTREE_NOT_FOUND failure."""
        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        # Patch worktree resolution to return None — no tmux window and no ~/worktrees/<name>.
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: None)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("missing-worktree", None, "xml", send)

        assert send.resumed_calls == []
        assert len(send.failure_calls) == 1
        error_code, message = send.failure_calls[0]
        assert error_code == "WORKTREE_NOT_FOUND"
        assert "crew create" in message

    def test_emits_failure_when_tmux_new_window_fails(self, tmp_path, monkeypatch):
        """When tmux new-window returns non-zero, emit TMUX_WINDOW_FAILED failure."""
        worktree_path = str(tmp_path / "valid-worktree")
        os.makedirs(worktree_path)
        self._make_session_dir(tmp_path, worktree_path, ["some-session"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: worktree_path)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "new-window" in joined:
                # Simulate tmux new-window failure
                return fake_run_result(returncode=1)
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("valid-worktree", None, "xml", send)

        assert send.resumed_calls == []
        assert len(send.failure_calls) == 1
        error_code, message = send.failure_calls[0]
        assert error_code == "TMUX_WINDOW_FAILED"

    def test_resume_command_includes_model_sonnet(self, tmp_path, monkeypatch):
        """cmd_resume spawn command must include --model sonnet to pin the model on resume."""
        worktree_path = str(tmp_path / "resume-worktree")
        os.makedirs(worktree_path)
        self._make_session_dir(tmp_path, worktree_path, ["some-session-id"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)
        monkeypatch.setattr("crew._resolve_worktree_for_name", lambda name: worktree_path)

        send_keys_captured = []

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                send_keys_captured.append(cmd)
                return fake_run_result()
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("resume-worktree", None, "xml", send)

        assert len(send.failure_calls) == 0
        assert len(send.resumed_calls) == 1
        _, _, _, command = send.resumed_calls[0]
        assert "--model sonnet" in command, (
            f"Expected '--model sonnet' in resume spawn command, got: {command!r}"
        )
        assert "staff --model sonnet --name resume-worktree --resume some-session-id" in command

    def test_cmd_staff_override_does_not_include_model_sonnet(self, capsys, tmp_path):
        """Passing --cmd staff fires the else branch: --model sonnet is NOT injected.

        This is intentional: --cmd is an explicit override that gives the caller full
        control of the invocation. Sonnet pinning is only applied to the default path.
        """
        # Inline helper to mirror _run_create pattern from TestCmdCreate
        def setup_mocks(mock_run):
            def side_effect(cmd, **kwargs):
                cmd_list = cmd if isinstance(cmd, list) else [cmd]
                joined = " ".join(str(c) for c in cmd_list)
                if "list-windows" in joined:
                    return fake_run_result(stdout="")
                if "rev-parse" in joined and "show-toplevel" in joined:
                    return fake_run_result(stdout="/some/repo\n")
                if "symbolic-ref" in joined:
                    return fake_run_result(stdout="main\n")
                if "rev-parse" in joined and "upstream" in joined:
                    return fake_run_result(stdout="origin/main\n")
                if "fetch" in joined and "origin" in joined:
                    return fake_run_result()
                if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                    return fake_run_result(stdout="abc1234\n")
                if "rev-parse" in joined and "refs/heads" in joined:
                    return fake_run_result(returncode=1)
                if "branch" in joined and "main" in joined:
                    return fake_run_result()
                if "worktree" in joined and "add" in joined:
                    return fake_run_result()
                if "new-window" in joined:
                    return fake_run_result()
                if "send-keys" in joined:
                    return fake_run_result()
                return fake_run_result()
            mock_run.side_effect = side_effect

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    setup_mocks(mock_run)
                    cmd_create(
                        name="test-worker",
                        repo="/some/repo",
                        branch="test-worker",
                        base="main",
                        fmt="xml",
                        cmd_override="staff",
                    )

        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        spawn_call = next(
            (c for c in send_keys_calls if "staff" in " ".join(str(x) for x in c[0][0])),
            None,
        )
        assert spawn_call is not None, "Expected a send-keys call with 'staff'"
        cmd_str = " ".join(str(x) for x in spawn_call[0][0])
        assert "--model sonnet" not in cmd_str, (
            f"--model sonnet must NOT be injected when --cmd staff is passed explicitly, "
            f"got: {cmd_str!r}"
        )


# ---------------------------------------------------------------------------
# crew create --no-worktree
# ---------------------------------------------------------------------------

class TestCmdCreateNoWorktree:
    """Tests for the --no-worktree flag on crew create."""

    def _setup_no_worktree_mocks(self, mock_run, dirty=False):
        """Configure mock_run for a no-worktree create flow."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "list-windows" in joined:
                return fake_run_result(stdout="")  # no existing windows
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "status" in joined and "--porcelain" in joined:
                return fake_run_result(stdout="M file.txt\n" if dirty else "")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            if "capture-pane" in joined:
                return fake_run_result(stdout="> \n")
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_no_worktree_happy_path_succeeds(self, capsys):
        """--no-worktree with valid git repo: tmux window created at repo path."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch.object(crew_module, "_ensure_hook_in_settings", return_value=(True, None)):
                    self._setup_no_worktree_mocks(mock_run, dirty=False)
                    cmd_create(
                        name="test-nw",
                        repo="/some/repo",
                        branch=None,
                        base=None,
                        fmt="xml",
                        no_worktree=True,
                    )

        all_calls = mock_run.call_args_list
        # git worktree add must NOT be called
        worktree_add_calls = [
            c for c in all_calls
            if "worktree" in " ".join(str(x) for x in c[0][0])
            and "add" in " ".join(str(x) for x in c[0][0])
        ]
        assert worktree_add_calls == [], "git worktree add must not be called with --no-worktree"

        # tmux new-window must be called with -c /some/repo
        new_window_calls = [
            c for c in all_calls
            if "new-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(new_window_calls) == 1
        new_window_args = new_window_calls[0][0][0]
        assert "-c" in new_window_args
        c_idx = new_window_args.index("-c")
        assert new_window_args[c_idx + 1] == "/some/repo"

        # staff --name test-nw must be sent via send-keys
        send_keys_calls = [
            c for c in all_calls
            if "send-keys" in " ".join(str(x) for x in c[0][0])
        ]
        spawn_call = next(
            (c for c in send_keys_calls if "staff" in " ".join(str(x) for x in c[0][0])),
            None,
        )
        assert spawn_call is not None

        # No error/warning output
        captured = capsys.readouterr()
        assert "error" not in captured.err.lower()
        assert "warning" not in captured.err.lower()

    def test_no_worktree_branch_flag_errors_cleanly(self, capsys):
        """--no-worktree + --branch must error with INCOMPATIBLE_FLAGS."""
        with patch("subprocess.run") as mock_run:
            self._setup_no_worktree_mocks(mock_run)
            with pytest.raises(SystemExit) as exc_info:
                cmd_create(
                    name="test-nw",
                    repo="/some/repo",
                    branch="some-branch",
                    base=None,
                    fmt="xml",
                    no_worktree=True,
                )
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "INCOMPATIBLE_FLAGS" in captured.out

        # tmux new-window must NOT be called
        new_window_calls = [
            c for c in mock_run.call_args_list
            if "new-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert new_window_calls == []

    def test_no_worktree_base_flag_errors_cleanly(self, capsys):
        """--no-worktree + --base must error with INCOMPATIBLE_FLAGS."""
        with patch("subprocess.run") as mock_run:
            self._setup_no_worktree_mocks(mock_run)
            with pytest.raises(SystemExit) as exc_info:
                cmd_create(
                    name="test-nw",
                    repo="/some/repo",
                    branch=None,
                    base="main",
                    fmt="xml",
                    no_worktree=True,
                )
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "INCOMPATIBLE_FLAGS" in captured.out

        new_window_calls = [
            c for c in mock_run.call_args_list
            if "new-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert new_window_calls == []

    def test_no_worktree_uncommitted_changes_warning_fires(self, capsys):
        """--no-worktree with dirty repo: warning on stderr, window still created."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                self._setup_no_worktree_mocks(mock_run, dirty=True)
                cmd_create(
                    name="test-nw",
                    repo="/some/repo",
                    branch=None,
                    base=None,
                    fmt="xml",
                    no_worktree=True,
                )

        captured = capsys.readouterr()
        assert "uncommitted changes" in captured.err

        # Window is still created
        all_calls = mock_run.call_args_list
        new_window_calls = [
            c for c in all_calls
            if "new-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(new_window_calls) == 1

    def test_no_worktree_skips_git_worktree_add_even_with_dirty_tree(self, capsys):
        """--no-worktree with a dirty tree: git worktree add is still never called.

        Combines the skip assertion with a distinct setup (uncommitted changes)
        to verify that a dirty working tree does not cause --no-worktree to fall
        back to creating a worktree.
        """
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                self._setup_no_worktree_mocks(mock_run, dirty=True)
                cmd_create(
                    name="test-nw",
                    repo="/some/repo",
                    branch=None,
                    base=None,
                    fmt="xml",
                    no_worktree=True,
                )

        for c in mock_run.call_args_list:
            cmd_args = c[0][0]
            joined = " ".join(str(x) for x in cmd_args)
            assert not ("worktree" in joined and "add" in joined), (
                f"Expected no 'git worktree add' call even with dirty tree, but found: {joined}"
            )

    def test_no_worktree_non_git_dir_errors(self, capsys):
        """Passing a non-git --repo always errors with NOT_A_GIT_REPO (exit 1).

        This verifies step 3's NOT_A_GIT_REPO guard, which fires regardless of
        --no-worktree. The no-worktree block itself relies on step 3 having
        already enforced the git-repo invariant before it runs.
        """
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                # Fail: not a git repo
                return fake_run_result(returncode=128, stdout="")
            return fake_run_result()

        with patch("subprocess.run", side_effect=side_effect):
            with patch("os.path.isdir", return_value=True):
                with pytest.raises(SystemExit) as exc_info:
                    cmd_create(
                        name="test-nw",
                        repo="/not/a/git/repo",
                        branch=None,
                        base=None,
                        fmt="xml",
                        no_worktree=True,
                    )
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "NOT_A_GIT_REPO" in captured.out

    def test_no_worktree_tmux_window_cwd_is_repo_not_worktrees_subdir(self, capsys):
        """--no-worktree: tmux new-window -c is the repo path, not ~/worktrees/<name>."""
        repo_path = "/some/path"
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                self._setup_no_worktree_mocks(mock_run, dirty=False)
                # Pass repo directly — step 3 validates the provided path without
                # needing rev-parse to return the same value, so no side-effect
                # override is necessary.
                cmd_create(
                    name="test-nw",
                    repo=repo_path,
                    branch=None,
                    base=None,
                    fmt="xml",
                    no_worktree=True,
                )

        new_window_calls = [
            c for c in mock_run.call_args_list
            if "new-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(new_window_calls) == 1
        new_window_args = new_window_calls[0][0][0]
        c_idx = new_window_args.index("-c")
        cwd_used = new_window_args[c_idx + 1]
        assert cwd_used == repo_path
        assert "worktrees" not in cwd_used

    def test_parser_accepts_no_worktree_flag(self):
        """build_parser parses --no-worktree as True."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker", "--no-worktree"])
        assert args.no_worktree is True

    def test_parser_no_worktree_defaults_to_false(self):
        """build_parser defaults no_worktree to False when flag is absent."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker"])
        assert args.no_worktree is False


# ---------------------------------------------------------------------------
# --tell-file flag — crew create
# ---------------------------------------------------------------------------

class TestCreateTellFile:
    """Tests for crew create --tell-file PATH."""

    def _setup_create_mocks(self, mock_run):
        """Configure mock_run for a minimal successful create flow."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            if "capture-pane" in joined:
                return fake_run_result(stdout="╭─ Claude Code ─╮\n│ > │\n")
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_tell_file_content_used_as_tell_body_on_success(self, tmp_path, capsys):
        """--tell-file reads file contents and uses them as the tell body."""
        brief = "Build the auth service with JWT support."
        brief_file = tmp_path / "brief.txt"
        brief_file.write_text(brief + "\n")  # trailing newline should be stripped

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                        with patch.object(crew_module, "_deliver_tell", return_value=(True, "verified")) as mock_deliver:
                            self._setup_create_mocks(mock_run)
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell_file=str(brief_file),
                            )

        # File content (stripped) must be the tell body
        mock_deliver.assert_called_once_with("test-worker", brief)

    def test_tell_file_deleted_on_successful_delivery(self, tmp_path, capsys):
        """--tell-file auto-deletes the file when delivery succeeds (told=true)."""
        brief_file = tmp_path / "brief.txt"
        brief_file.write_text("Some brief.\n")

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                        with patch.object(crew_module, "_deliver_tell", return_value=(True, "verified")):
                            self._setup_create_mocks(mock_run)
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell_file=str(brief_file),
                            )

        assert not brief_file.exists(), "File must be deleted after successful delivery"

    def test_tell_file_preserved_on_delivery_failure(self, tmp_path, capsys):
        """--tell-file does NOT delete the file when delivery fails (told=false)."""
        brief_file = tmp_path / "brief.txt"
        brief_file.write_text("Some brief.\n")

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                        with patch.object(
                            crew_module, "_deliver_tell",
                            return_value=(False, "verification timeout: tell text not observed in pane"),
                        ):
                            self._setup_create_mocks(mock_run)
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell_file=str(brief_file),
                            )

        assert brief_file.exists(), "File must be preserved when delivery fails"

    def test_tell_file_nonexistent_errors_cleanly(self, tmp_path, capsys):
        """--tell-file with a nonexistent path fails immediately with TELL_FILE_ERROR."""
        nonexistent = str(tmp_path / "does_not_exist.txt")

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    self._setup_create_mocks(mock_run)
                    with pytest.raises(SystemExit) as exc_info:
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch="test-worker",
                            base="main",
                            fmt="xml",
                            tell_file=nonexistent,
                        )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "TELL_FILE_ERROR" in captured.out

    def test_tell_and_tell_file_mutex_at_parser_level(self):
        """--tell and --tell-file are mutually exclusive in crew create (argparse group)."""
        p = build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["create", "my-worker", "--tell", "msg", "--tell-file", "/tmp/f.txt"])

    def test_tell_file_flag_parsed_correctly(self, tmp_path):
        """build_parser parses --tell-file for crew create."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker", "--tell-file", "/tmp/brief.txt"])
        assert args.tell_file == "/tmp/brief.txt"
        assert args.tell is None

    def test_tell_file_preserved_when_claude_never_ready(self, tmp_path, capsys):
        """--tell-file preserved when Claude Code doesn't start (told=false, no delivery attempted)."""
        brief_file = tmp_path / "brief.txt"
        brief_file.write_text("Some brief.\n")

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module,
                        "_wait_for_sentinel",
                        return_value=(False, "session never reported ready — sentinel file not written (SessionStart hook may be missing) and prompt-box token not observed in pane"),
                    ):
                        self._setup_create_mocks(mock_run)
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch="test-worker",
                            base="main",
                            fmt="xml",
                            tell_file=str(brief_file),
                        )

        assert brief_file.exists(), "File must be preserved when sentinel never appears"


# ---------------------------------------------------------------------------
# --tell-file flag — crew tell
# ---------------------------------------------------------------------------

class TestTellTellFile:
    """Tests for crew tell --tell-file PATH."""

    def test_tell_file_content_used_as_message(self, tmp_path, capsys):
        """crew tell --tell-file reads file contents and sends them to the target."""
        message = "Hello from file."
        tell_file = tmp_path / "msg.txt"
        tell_file.write_text(message + "\n")  # trailing newline stripped

        lookup = {"my-worker": ("session:0", "@1")}
        with patch.object(crew_module, "resolve_targets", return_value=[("session:0.0", "my-worker.0", "@1")]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = fake_run_result()
                cmd_tell("my-worker", None, "xml", tell_file=str(tell_file))

        # The send-keys call for the message should use the file content
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        # Find the call that carries the message text
        msg_call = next(
            (c for c in send_keys_calls if message in " ".join(str(x) for x in c[0][0])),
            None,
        )
        assert msg_call is not None, f"Expected send-keys with '{message}'"

    def test_tell_file_deleted_after_delivery(self, tmp_path, capsys):
        """crew tell --tell-file auto-deletes the file after send completes."""
        tell_file = tmp_path / "msg.txt"
        tell_file.write_text("Some message.\n")

        with patch.object(crew_module, "resolve_targets", return_value=[("session:0.0", "my-worker.0", "@1")]):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = fake_run_result()
                cmd_tell("my-worker", None, "xml", tell_file=str(tell_file))

        assert not tell_file.exists(), "File must be deleted after crew tell delivery"

    def test_tell_file_preserved_on_delivery_failure(self, tmp_path, capsys):
        """crew tell --tell-file preserves the file when tmux send-keys returns non-zero exit."""
        tell_file = tmp_path / "msg.txt"
        tell_file.write_text("Some message.\n")

        with patch.object(crew_module, "resolve_targets", return_value=[("session:0.0", "my-worker.0", "@1")]):
            with patch("subprocess.run") as mock_run:
                # Simulate tmux send-keys failure (non-zero returncode)
                mock_run.return_value = fake_run_result(returncode=1)
                cmd_tell("my-worker", None, "xml", tell_file=str(tell_file))

        assert tell_file.exists(), "File must be preserved when tmux delivery fails"

    def test_tell_file_nonexistent_errors_cleanly(self, tmp_path, capsys):
        """crew tell --tell-file with nonexistent path fails with TELL_FILE_ERROR (exit 1)."""
        nonexistent = str(tmp_path / "does_not_exist.txt")
        with pytest.raises(SystemExit) as exc_info:
            cmd_tell("my-worker", None, "xml", tell_file=nonexistent)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "TELL_FILE_ERROR" in captured.out

    def test_tell_file_flag_parsed_for_tell_subcommand(self, tmp_path):
        """build_parser parses --tell-file for crew tell."""
        p = build_parser()
        args = p.parse_args(["tell", "my-worker", "--tell-file", "/tmp/msg.txt"])
        assert args.tell_file == "/tmp/msg.txt"
        assert args.message is None

    def test_tell_and_tell_file_both_given_errors_at_parser_level(self):
        """crew tell with both positional message and --tell-file errors at argparse level (exit 2)."""
        p = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            p.parse_args(["tell", "my-worker", "some message", "--tell-file", "/tmp/f.txt"])
        assert exc_info.value.code == 2

    def test_no_message_and_no_tell_file_errors(self, capsys):
        """crew tell with no message and no --tell-file errors with MISSING_MESSAGE."""
        import sys
        with patch.object(sys, "argv", ["crew", "tell", "my-worker"]):
            with pytest.raises(SystemExit) as exc_info:
                from crew import main
                main()
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "MISSING_MESSAGE" in captured.out


# ---------------------------------------------------------------------------
# post-switch hook — run_post_switch_hook unit tests
# ---------------------------------------------------------------------------

class TestRunPostSwitchHook:
    """Unit tests for run_post_switch_hook — isolated from cmd_create."""

    def test_absent_hook_returns_none(self, tmp_path):
        """No hook file → returns None (silent no-op)."""
        source_repo = str(tmp_path / "repo")
        os.makedirs(source_repo)
        result = run_post_switch_hook(source_repo, "/some/worktree", "my-branch")
        assert result is None

    def test_non_executable_hook_returns_none(self, tmp_path, capsys):
        """Hook file exists but is not executable → warning emitted to stderr, returns None."""
        hook_dir = tmp_path / "repo" / ".git" / "workout-hooks"
        hook_dir.mkdir(parents=True)
        hook_file = hook_dir / "post-switch"
        hook_file.write_text("#!/usr/bin/env bash\nexit 0\n")
        # Not chmod +x — leave non-executable
        result = run_post_switch_hook(str(tmp_path / "repo"), "/some/worktree", "my-branch")
        assert result is None
        captured = capsys.readouterr()
        assert "warning" in captured.err
        assert "not executable" in captured.err

    def test_hook_success_returns_zero_returncode(self, tmp_path):
        """Hook exits 0 → returns (0, tail_output)."""
        hook_dir = tmp_path / "repo" / ".git" / "workout-hooks"
        hook_dir.mkdir(parents=True)
        hook_file = hook_dir / "post-switch"
        hook_file.write_text("#!/usr/bin/env bash\necho 'bootstrap ok'\n")
        os.chmod(hook_file, 0o755)

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        rc, tail = run_post_switch_hook(str(tmp_path / "repo"), str(worktree), "my-branch")
        assert rc == 0
        assert "bootstrap ok" in tail

    def test_hook_failure_returns_nonzero_returncode(self, tmp_path):
        """Hook exits non-zero → returns (returncode, tail_output)."""
        hook_dir = tmp_path / "repo" / ".git" / "workout-hooks"
        hook_dir.mkdir(parents=True)
        hook_file = hook_dir / "post-switch"
        hook_file.write_text("#!/usr/bin/env bash\necho 'setup failed'\nexit 42\n")
        os.chmod(hook_file, 0o755)

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        rc, tail = run_post_switch_hook(str(tmp_path / "repo"), str(worktree), "my-branch")
        assert rc == 42
        assert "setup failed" in tail

    def test_hook_env_vars_passed_correctly(self, tmp_path):
        """WORKTREE_PATH, SOURCE_REPO, and BRANCH are passed to the hook."""
        hook_dir = tmp_path / "repo" / ".git" / "workout-hooks"
        hook_dir.mkdir(parents=True)
        hook_file = hook_dir / "post-switch"
        # Print the env vars so we can assert them in the tail output
        hook_file.write_text(
            "#!/usr/bin/env bash\n"
            'echo "WORKTREE_PATH=$WORKTREE_PATH"\n'
            'echo "SOURCE_REPO=$SOURCE_REPO"\n'
            'echo "BRANCH=$BRANCH"\n'
        )
        os.chmod(hook_file, 0o755)

        source_repo = str(tmp_path / "repo")
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        rc, tail = run_post_switch_hook(source_repo, str(worktree), "feature-x")
        assert rc == 0
        assert f"WORKTREE_PATH={worktree}" in tail
        assert f"SOURCE_REPO={source_repo}" in tail
        assert "BRANCH=feature-x" in tail

    def test_hook_runs_with_cwd_set_to_worktree(self, tmp_path):
        """Hook cwd is the new worktree path (not the source repo)."""
        hook_dir = tmp_path / "repo" / ".git" / "workout-hooks"
        hook_dir.mkdir(parents=True)
        hook_file = hook_dir / "post-switch"
        hook_file.write_text("#!/usr/bin/env bash\npwd\n")
        os.chmod(hook_file, 0o755)

        source_repo = str(tmp_path / "repo")
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        rc, tail = run_post_switch_hook(source_repo, str(worktree), "my-branch")
        assert rc == 0
        # Resolve symlinks so macOS /private/var/... paths compare correctly
        assert os.path.realpath(tail.strip()) == os.path.realpath(str(worktree))

    def test_tail_truncated_to_20_lines(self, tmp_path):
        """Only the last 20 lines of combined output are returned."""
        hook_dir = tmp_path / "repo" / ".git" / "workout-hooks"
        hook_dir.mkdir(parents=True)
        hook_file = hook_dir / "post-switch"
        lines = "\n".join(f'echo "line {i}"' for i in range(40))
        hook_file.write_text(f"#!/usr/bin/env bash\n{lines}\nexit 1\n")
        os.chmod(hook_file, 0o755)

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        rc, tail = run_post_switch_hook(str(tmp_path / "repo"), str(worktree), "my-branch")
        assert rc == 1
        tail_lines = tail.splitlines()
        assert len(tail_lines) <= 20
        # Last line should be line 39
        assert "line 39" in tail_lines[-1]


# ---------------------------------------------------------------------------
# post-switch hook — cmd_create integration tests
# ---------------------------------------------------------------------------

class TestCmdCreatePostSwitchHook:
    """Integration tests for post-switch hook behavior within cmd_create."""

    def _setup_create_mocks(self, mock_run):
        """Standard successful create flow mocks."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            if "capture-pane" in joined:
                return fake_run_result(stdout="> \n")
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_hook_present_exits_zero_staff_launched(self, capsys):
        """Hook present and exits 0 → staff is launched normally."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module,
                        "run_post_switch_hook",
                        return_value=(0, "bootstrap ok"),
                    ) as mock_hook:
                        self._setup_create_mocks(mock_run)
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch="test-worker",
                            base="main",
                            fmt="xml",
                        )

        call_args = mock_hook.call_args
        assert call_args[0][0] == "/some/repo"
        assert call_args[0][1].endswith("/worktrees/test-worker")
        assert call_args[0][2] == "test-worker"
        # Staff should have been launched (send-keys call present)
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        assert len(send_keys_calls) >= 1

    def test_hook_present_exits_nonzero_staff_not_launched(self, capsys):
        """Hook exits non-zero → POST_SWITCH_HOOK_FAILED error, staff NOT launched."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module,
                        "run_post_switch_hook",
                        return_value=(1, "pnpm: command not found"),
                    ):
                        self._setup_create_mocks(mock_run)
                        with pytest.raises(SystemExit) as exc_info:
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "POST_SWITCH_HOOK_FAILED" in captured.out
        assert "exited 1" in captured.out  # hook's exit code present in error message body

        # Staff must NOT have been launched
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        assert len(send_keys_calls) == 0

    def test_hook_absent_staff_launched_normally(self, capsys):
        """Hook absent (returns None) → no-op, staff launched as before."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module,
                        "run_post_switch_hook",
                        return_value=None,
                    ) as mock_hook:
                        self._setup_create_mocks(mock_run)
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch="test-worker",
                            base="main",
                            fmt="xml",
                        )

        mock_hook.assert_called_once()
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        assert len(send_keys_calls) >= 1

    def test_hook_not_called_with_no_worktree(self, capsys):
        """--no-worktree mode skips the post-switch hook entirely."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module,
                        "run_post_switch_hook",
                    ) as mock_hook:
                        self._setup_create_mocks(mock_run)
                        cmd_create(
                            name="test-worker",
                            repo="/some/repo",
                            branch=None,
                            base=None,
                            fmt="xml",
                            no_worktree=True,
                        )

        mock_hook.assert_not_called()


# ---------------------------------------------------------------------------
# resolve_worktree_path — parity with modules/git/workout.bash
# ---------------------------------------------------------------------------
# These tests assert that crew create and the workout.bash script produce the
# same filesystem path for equivalent repo + branch inputs.
#
# workout.bash formula (source of truth):
#   ${WORKTREE_ROOT:-$HOME/worktrees}/<org>/<repo>/<branch>
# where org/repo is extracted from `git remote get-url origin`.


class TestExtractOrgRepoFromRemote:
    """Unit tests for the org/repo extractor used by resolve_worktree_path."""

    @pytest.mark.parametrize("url,expected", [
        ("git@github.com:mctx-ai/mctx.git", "mctx-ai/mctx"),
        ("git@github.com:karlhepler/nixpkgs.git", "karlhepler/nixpkgs"),
        ("https://github.com/mctx-ai/mctx.git", "mctx-ai/mctx"),
        ("https://github.com/karlhepler/nixpkgs.git", "karlhepler/nixpkgs"),
        # Without .git suffix (some remotes omit it)
        ("git@github.com:mctx-ai/mctx", "mctx-ai/mctx"),
        ("https://github.com/org/repo", "org/repo"),
    ])
    def test_extracts_org_repo(self, url, expected):
        assert _extract_org_repo_from_remote(url) == expected

    def test_returns_none_for_unparseable_url(self):
        assert _extract_org_repo_from_remote("not-a-valid-url") is None


class TestResolveWorktreePath:
    """Parity tests: resolve_worktree_path must match workout.bash's path formula."""

    def test_ssh_remote_produces_nested_path(self, monkeypatch, tmp_path):
        """SSH remote URL → ~/worktrees/<org>/<repo>/<branch> (parity with workout.bash)."""
        # workout.bash formula for git@github.com:mctx-ai/mctx.git + branch "fix":
        #   ~/worktrees/mctx-ai/mctx/fix
        worktree_root = str(tmp_path / "worktrees")
        monkeypatch.setenv("WORKTREE_ROOT", worktree_root)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(
                stdout="git@github.com:mctx-ai/mctx.git\n"
            )
            path, used_fallback = resolve_worktree_path("/fake/repo", "fix")

        expected = str(tmp_path / "worktrees" / "mctx-ai" / "mctx" / "fix")
        assert path == expected
        assert used_fallback is False

    def test_https_remote_produces_nested_path(self, monkeypatch, tmp_path):
        """HTTPS remote URL → ~/worktrees/<org>/<repo>/<branch> (parity with workout.bash)."""
        worktree_root = str(tmp_path / "worktrees")
        monkeypatch.setenv("WORKTREE_ROOT", worktree_root)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(
                stdout="https://github.com/karlhepler/nixpkgs.git\n"
            )
            path, used_fallback = resolve_worktree_path("/fake/repo", "karlhepler/my-feature")

        expected = str(
            tmp_path / "worktrees" / "karlhepler" / "nixpkgs" / "karlhepler" / "my-feature"
        )
        assert path == expected
        assert used_fallback is False

    def test_falls_back_to_flat_layout_when_no_remote(self, monkeypatch, tmp_path):
        """No origin remote → flat ~/worktrees/<branch> fallback (graceful degradation)."""
        worktree_root = str(tmp_path / "worktrees")
        monkeypatch.setenv("WORKTREE_ROOT", worktree_root)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(returncode=2, stdout="")
            path, used_fallback = resolve_worktree_path("/fake/repo", "my-branch")

        expected = str(tmp_path / "worktrees" / "my-branch")
        assert path == expected
        assert used_fallback is True

    def test_worktree_root_defaults_to_home_worktrees(self, monkeypatch):
        """When WORKTREE_ROOT is unset, defaults to ~/worktrees/<org>/<repo>/<branch>."""
        monkeypatch.delenv("WORKTREE_ROOT", raising=False)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(
                stdout="git@github.com:myorg/myrepo.git\n"
            )
            path, used_fallback = resolve_worktree_path("/fake/repo", "feature-x")

        expected = os.path.join(
            os.path.expanduser("~/worktrees"), "myorg", "myrepo", "feature-x"
        )
        assert path == expected
        assert used_fallback is False

    def test_parity_with_workout_bash_formula(self, monkeypatch, tmp_path):
        """Python-internal consistency check for the workout.bash path formula.

        NOTE: This test is a Python-internal consistency check, NOT a live bash
        invocation. workout.bash (modules/git/workout.bash) has no dry-run or
        path-computation-only mode — it requires a live git repo with a configured
        remote and performs real filesystem operations. Invoking it via subprocess
        in a unit test would require significant test infrastructure (real git repos,
        real remotes, or mock git binaries). Option (c) per card #1354 F5 applies:
        annotate as Python-internal and add a secondary hardcoded-value assertion
        that was manually verified against workout.bash.

        Secondary hardcoded assertion (manually verified):
            Input:  remote URL = "git@github.com:mctx-ai/mctx.git", branch = "my-feature"
            workout.bash sed: sed -E 's#.*[:/]([^/]+/[^/]+)\\.git$#\\1#'
                            → extracts "mctx-ai/mctx"
            Expected path:  $WORKTREE_ROOT/mctx-ai/mctx/my-feature
        """
        worktree_root = str(tmp_path / "worktrees")
        monkeypatch.setenv("WORKTREE_ROOT", worktree_root)

        remote_url = "git@github.com:mctx-ai/mctx.git"
        branch = "my-feature"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout=remote_url + "\n")
            crew_path, used_fallback = resolve_worktree_path("/fake/repo", branch)

        # Hardcoded expected value manually verified against workout.bash formula:
        #   echo "git@github.com:mctx-ai/mctx.git" | sed -E 's#.*[:/]([^/]+/[^/]+)\.git$#\1#'
        #   → mctx-ai/mctx
        #   path = $WORKTREE_ROOT/mctx-ai/mctx/my-feature
        expected_path = os.path.join(worktree_root, "mctx-ai", "mctx", "my-feature")
        assert crew_path == expected_path, (
            f"crew path {crew_path!r} != workout.bash-verified path {expected_path!r}"
        )
        assert used_fallback is False

    def test_cmd_create_uses_nested_worktree_path(self, capsys, monkeypatch, tmp_path):
        """cmd_create must pass nested org/repo/branch path to git worktree add.

        Integration test: verifies the full cmd_create path from remote URL to
        the git worktree add invocation uses the nested layout, not the flat one.
        """
        worktree_root = str(tmp_path / "worktrees")
        monkeypatch.setenv("WORKTREE_ROOT", worktree_root)

        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "remote" in joined and "get-url" in joined:
                return fake_run_result(stdout="git@github.com:myorg/myrepo.git\n")
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            if "capture-pane" in joined:
                return fake_run_result(stdout="> \n")
            return fake_run_result()

        with patch("subprocess.run", side_effect=side_effect):
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    cmd_create(
                        name="my-feature",
                        repo="/some/repo",
                        branch="my-feature",
                        base="main",
                        fmt="xml",
                    )

        out = capsys.readouterr().out
        expected_nested_path = os.path.join(
            worktree_root, "myorg", "myrepo", "my-feature"
        )
        # The nested path must appear in the XML output (worktree= attribute)
        assert expected_nested_path in out, (
            f"Expected nested path {expected_nested_path!r} in output:\n{out}"
        )
        # The flat layout must NOT appear
        flat_path = os.path.join(worktree_root, "my-feature")
        assert flat_path not in out, (
            f"Flat path {flat_path!r} must not appear in output (nested layout required)"
        )


# ---------------------------------------------------------------------------
# cmd_smithers — idempotency, split creation, error cases
# ---------------------------------------------------------------------------

class TestCmdSmithers:
    """Tests for the crew smithers subcommand."""

    def _make_window_lookup(self, name: str = "feature-xyz") -> dict:
        """Return a window lookup dict for a single window."""
        return {name: ("free-brook:0", "@1")}

    def test_smithers_creates_split_when_none_exists(self, capsys):
        """No split → split-window + send-keys smithers are called in sequence."""
        panes_before = [("0", "2.1.100", "/home/user/worktrees/feature-xyz")]

        with patch.object(crew_module, "get_window_lookup", return_value=self._make_window_lookup()):
            with patch.object(crew_module, "_list_panes_in_window", return_value=panes_before):
                with patch("subprocess.run") as mock_run:
                    # split-window succeeds and returns pane index "1"
                    # display-message for cwd fallback (if triggered): not needed since path in pane tuple
                    # send-keys succeeds
                    def side_effect(cmd, **kwargs):
                        joined = " ".join(str(c) for c in cmd)
                        if "split-window" in joined:
                            return fake_run_result(stdout="1\n")
                        if "send-keys" in joined:
                            return fake_run_result()
                        return fake_run_result()
                    mock_run.side_effect = side_effect

                    rc = cmd_smithers("feature-xyz", fmt="human")

        assert rc == 0
        out = capsys.readouterr().out
        assert "started smithers" in out
        assert "feature-xyz" in out

        # Verify split-window was called
        split_calls = [
            c for c in mock_run.call_args_list
            if "split-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(split_calls) == 1, f"Expected 1 split-window call, got {len(split_calls)}"

        # Verify send-keys was called with 'smithers'
        send_calls = [
            c for c in mock_run.call_args_list
            if "send-keys" in " ".join(str(x) for x in c[0][0])
        ]
        assert any("smithers" in " ".join(str(x) for x in c[0][0]) for c in send_calls), (
            "Expected send-keys call with 'smithers'"
        )

        # Verify split-window was called with the correct CWD (-c pane_current_path)
        assert len(split_calls) == 1
        split_cmd = " ".join(str(x) for x in split_calls[0][0][0])
        pane_0_cwd = panes_before[0][2]  # third element of pane tuple is pane_current_path
        assert pane_0_cwd in split_cmd, (
            f"Expected pane 0 CWD {pane_0_cwd!r} in split-window call, got: {split_cmd!r}"
        )

    def test_smithers_idempotent_when_already_running(self, capsys):
        """If a split exists and smithers is running in pane 1, report success without creating a new split."""
        panes_with_smithers = [
            ("0", "2.1.100", "/home/user/worktrees/feature-xyz"),
            ("1", "smithers", "/home/user/worktrees/feature-xyz"),
        ]

        with patch.object(crew_module, "get_window_lookup", return_value=self._make_window_lookup()):
            with patch.object(crew_module, "_list_panes_in_window", return_value=panes_with_smithers):
                with patch("subprocess.run") as mock_run:
                    rc = cmd_smithers("feature-xyz", fmt="human")

        assert rc == 0
        out = capsys.readouterr().out
        assert "already running" in out
        assert "feature-xyz.1" in out

        # split-window must NOT have been called (idempotent)
        split_calls = [
            c for c in mock_run.call_args_list
            if "split-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(split_calls) == 0, "split-window must not be called when smithers is already running"

    def test_smithers_errors_when_ambiguous_extra_pane(self, capsys):
        """Extra pane exists but is NOT running smithers → error returned, no overwrite."""
        panes_with_other = [
            ("0", "2.1.100", "/home/user/worktrees/feature-xyz"),
            ("1", "zsh", "/home/user/worktrees/feature-xyz"),
        ]

        with patch.object(crew_module, "get_window_lookup", return_value=self._make_window_lookup()):
            with patch.object(crew_module, "_list_panes_in_window", return_value=panes_with_other):
                with patch("subprocess.run") as mock_run:
                    rc = cmd_smithers("feature-xyz", fmt="human")

        assert rc == 1
        err = capsys.readouterr().err
        assert "ambiguous" in err.lower() or "refusing" in err.lower()

        # split-window must NOT have been called
        split_calls = [
            c for c in mock_run.call_args_list
            if "split-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(split_calls) == 0, "split-window must not be called in ambiguous state"

    def test_smithers_uses_correct_split_percentage(self, capsys):
        """The split is created with _SMITHERS_SPLIT_PERCENT (25%), matching prefix+s keybinding."""
        panes_before = [("0", "2.1.100", "/home/user/worktrees/feature-xyz")]

        with patch.object(crew_module, "get_window_lookup", return_value=self._make_window_lookup()):
            with patch.object(crew_module, "_list_panes_in_window", return_value=panes_before):
                with patch("subprocess.run") as mock_run:
                    def side_effect(cmd, **kwargs):
                        joined = " ".join(str(c) for c in cmd)
                        if "split-window" in joined:
                            return fake_run_result(stdout="1\n")
                        return fake_run_result()
                    mock_run.side_effect = side_effect

                    cmd_smithers("feature-xyz", fmt="human")

        # The split percentage constant must be 25 (matching prefix+s binding in modules/tmux/default.nix)
        assert _SMITHERS_SPLIT_PERCENT == 25, (
            f"Expected split percent 25 (matching tmux prefix+s), got {_SMITHERS_SPLIT_PERCENT}"
        )

        # Verify the split-window call used the correct percentage
        split_calls = [
            c for c in mock_run.call_args_list
            if "split-window" in " ".join(str(x) for x in c[0][0])
        ]
        assert len(split_calls) == 1
        split_cmd = " ".join(str(x) for x in split_calls[0][0][0])
        assert "25%" in split_cmd, f"Expected '25%' in split-window call, got: {split_cmd!r}"

    def test_smithers_no_such_window(self, capsys):
        """Window doesn't exist → clean error, rc=1."""
        with patch.object(crew_module, "get_window_lookup", return_value={}):
            rc = cmd_smithers("nonexistent-window", fmt="human")

        assert rc == 1
        err = capsys.readouterr().err
        assert "nonexistent-window" in err
        assert "not found" in err.lower()

    def test_smithers_registered_in_argparse(self):
        """crew smithers is registered as a subcommand in argparse."""
        parser = build_parser()
        # Should parse without error
        args = parser.parse_args(["smithers", "my-window"])
        assert args.command == "smithers"
        assert args.name == "my-window"

    def test_smithers_xml_output_started(self, capsys):
        """Started state emits valid XML with status=started."""
        panes_before = [("0", "2.1.100", "/home/user/worktrees/feature-xyz")]

        with patch.object(crew_module, "get_window_lookup", return_value=self._make_window_lookup()):
            with patch.object(crew_module, "_list_panes_in_window", return_value=panes_before):
                with patch("subprocess.run") as mock_run:
                    def side_effect(cmd, **kwargs):
                        if "split-window" in " ".join(str(c) for c in cmd):
                            return fake_run_result(stdout="1\n")
                        return fake_run_result()
                    mock_run.side_effect = side_effect

                    rc = cmd_smithers("feature-xyz", fmt="xml")

        assert rc == 0
        out = capsys.readouterr().out
        assert 'status="started"' in out
        assert 'window="feature-xyz"' in out

    def test_smithers_xml_output_already_running(self, capsys):
        """Already-running state emits valid XML with status=already-running."""
        panes = [
            ("0", "2.1.100", "/home/user/worktrees/feature-xyz"),
            ("1", "smithers", "/home/user/worktrees/feature-xyz"),
        ]

        with patch.object(crew_module, "get_window_lookup", return_value=self._make_window_lookup()):
            with patch.object(crew_module, "_list_panes_in_window", return_value=panes):
                with patch("subprocess.run"):
                    rc = cmd_smithers("feature-xyz", fmt="xml")

        assert rc == 0
        out = capsys.readouterr().out
        assert 'status="already-running"' in out
        assert 'pane="1"' in out


# ---------------------------------------------------------------------------
# _pane_is_running_smithers helper
# ---------------------------------------------------------------------------

class TestPaneIsRunningSmithers:
    """Unit tests for the smithers-detection helper."""

    def test_returns_true_for_smithers_command(self):
        pane = ("1", "smithers", "/some/path")
        assert _pane_is_running_smithers(pane) is True

    def test_returns_false_for_zsh(self):
        pane = ("1", "zsh", "/some/path")
        assert _pane_is_running_smithers(pane) is False

    def test_returns_false_for_claude_version(self):
        pane = ("1", "2.1.116", "/some/path")
        assert _pane_is_running_smithers(pane) is False

    def test_returns_false_for_empty_command(self):
        pane = ("1", "", "/some/path")
        assert _pane_is_running_smithers(pane) is False


# ---------------------------------------------------------------------------
# cmd_status multi-pane extension
# ---------------------------------------------------------------------------

class TestCmdStatusMultiPane:
    """Tests that crew status surfaces per-pane activity for multi-pane windows."""

    def test_status_shows_multiple_panes_xml(self, capsys):
        """Window with Claude in pane 0 and smithers in pane 1 → both appear in status XML."""
        all_panes = [
            ("free-brook", "0", "feature-xyz", "0", "2.1.100"),   # Claude pane
            ("free-brook", "0", "feature-xyz", "1", "smithers"),   # smithers pane
        ]

        with patch.object(crew_module, "get_current_session", return_value="free-brook"):
            with patch.object(crew_module, "get_all_panes", return_value=all_panes):
                with patch.object(crew_module, "capture_pane", return_value="pane content\n"):
                    cmd_status(lines=10, fmt="xml")

        out = capsys.readouterr().out
        # Both panes must appear
        assert 'index="0"' in out, "Pane 0 must appear in status output"
        assert 'index="1"' in out, "Pane 1 must appear in status output"
        # Window name must appear
        assert 'name="feature-xyz"' in out

    def test_status_shows_multiple_panes_human(self, capsys):
        """Human format includes both panes when a window has Claude + smithers."""
        all_panes = [
            ("free-brook", "0", "feature-xyz", "0", "2.1.100"),
            ("free-brook", "0", "feature-xyz", "1", "smithers"),
        ]

        with patch.object(crew_module, "get_current_session", return_value="free-brook"):
            with patch.object(crew_module, "get_all_panes", return_value=all_panes):
                with patch.object(crew_module, "capture_pane", return_value="content\n"):
                    cmd_status(lines=10, fmt="human")

        out = capsys.readouterr().out
        # Both panes appear in the listing
        assert "feature-xyz" in out
        assert "smithers" in out

    def test_status_excludes_windows_without_claude_pane(self, capsys):
        """Windows without any Claude pane must not appear in default (non --all) status."""
        all_panes = [
            ("free-brook", "0", "feature-xyz", "0", "2.1.100"),   # Claude
            ("free-brook", "0", "feature-xyz", "1", "smithers"),   # smithers
            ("free-brook", "1", "pure-zsh-win", "0", "zsh"),       # no Claude — excluded
        ]

        with patch.object(crew_module, "get_current_session", return_value="free-brook"):
            with patch.object(crew_module, "get_all_panes", return_value=all_panes):
                with patch.object(crew_module, "capture_pane", return_value="content\n"):
                    cmd_status(lines=10, fmt="xml")

        out = capsys.readouterr().out
        assert "feature-xyz" in out
        # pure-zsh-win has no Claude pane → must NOT appear in default mode
        assert "pure-zsh-win" not in out

    def test_status_show_all_includes_non_claude_windows(self, capsys):
        """--all includes ALL panes regardless of Claude presence."""
        all_panes = [
            ("free-brook", "0", "feature-xyz", "0", "2.1.100"),
            ("free-brook", "1", "pure-zsh-win", "0", "zsh"),
        ]

        with patch.object(crew_module, "get_current_session", return_value="free-brook"):
            with patch.object(crew_module, "get_all_panes", return_value=all_panes):
                with patch.object(crew_module, "capture_pane", return_value="content\n"):
                    cmd_status(lines=10, fmt="xml", show_all=True)

        out = capsys.readouterr().out
        assert "feature-xyz" in out
        assert "pure-zsh-win" in out


class TestCmdCreateToldReason:
    """Integration test: cmd_create told_reason reflects sentinel wait outcomes."""

    def test_cmd_create_told_reason_reflects_sentinel_hook_missing(self, capsys):
        """Integration: cmd_create told_reason reflects hook-missing when sentinel never appears."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module,
                        "_ensure_hook_in_settings",
                        return_value=(True, None),
                    ):
                        with patch.object(
                            crew_module,
                            "_wait_for_sentinel",
                            return_value=(False, "session never reported ready — sentinel file not written (SessionStart hook may be missing) and prompt-box token not observed in pane"),
                        ):
                            # Provide minimal subprocess mocks for the create path
                            def side_effect(cmd, **kwargs):
                                joined = " ".join(str(c) for c in cmd)
                                if "display-message" in joined and "session_name" in joined:
                                    return fake_run_result(stdout="tidy-crown\n")
                                if "display-message" in joined and "window_id" in joined:
                                    return fake_run_result(stdout="@1\n")
                                if "list-windows" in joined:
                                    return fake_run_result(stdout="")
                                if "rev-parse" in joined and "show-toplevel" in joined:
                                    return fake_run_result(stdout="/some/repo\n")
                                if "symbolic-ref" in joined:
                                    return fake_run_result(stdout="main\n")
                                if "rev-parse" in joined and "upstream" in joined:
                                    return fake_run_result(stdout="origin/main\n")
                                if "fetch" in joined and "origin" in joined:
                                    return fake_run_result()
                                if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                                    return fake_run_result(stdout="abc1234\n")
                                if "rev-parse" in joined and "refs/heads" in joined:
                                    return fake_run_result(returncode=1)
                                if "branch" in joined and "main" in joined:
                                    return fake_run_result()
                                if "worktree" in joined and "add" in joined:
                                    return fake_run_result()
                                if "new-window" in joined:
                                    return fake_run_result()
                                if "send-keys" in joined:
                                    return fake_run_result()
                                return fake_run_result()

                            mock_run.side_effect = side_effect
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell="Hello",
                            )

        out = capsys.readouterr().out
        assert 'told="false"' in out
        assert "sentinel file not written" in out, (
            f"Expected 'sentinel file not written' in told_reason, got output: {out!r}"
        )


# ---------------------------------------------------------------------------
# --mcp-trust parser tests
# ---------------------------------------------------------------------------

class TestMcpTrustParserFlag:
    """Tests for --mcp-trust flag on crew create."""

    def test_mcp_trust_defaults_to_all(self):
        """--mcp-trust defaults to 'all' when not provided."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker"])
        assert args.mcp_trust == "all"

    def test_mcp_trust_all_accepted(self):
        """--mcp-trust all is accepted."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker", "--mcp-trust", "all"])
        assert args.mcp_trust == "all"

    def test_mcp_trust_this_accepted(self):
        """--mcp-trust this is accepted."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker", "--mcp-trust", "this"])
        assert args.mcp_trust == "this"

    def test_mcp_trust_none_accepted(self):
        """--mcp-trust none is accepted."""
        p = build_parser()
        args = p.parse_args(["create", "my-worker", "--mcp-trust", "none"])
        assert args.mcp_trust == "none"

    def test_mcp_trust_invalid_rejected(self):
        """--mcp-trust with invalid value is rejected by argparse."""
        p = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            p.parse_args(["create", "my-worker", "--mcp-trust", "maybe"])
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# cmd_create mcp_trust integration — mcp_trust is still accepted by cmd_create
# (passed to the spawned staff command).
# ---------------------------------------------------------------------------

class TestCmdCreateMcpTrust:
    """Tests that cmd_create still accepts the mcp_trust flag (parser-level)."""

    def _setup_create_mocks(self, mock_run):
        """Configure mock_run for a minimal successful create flow."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_mcp_trust_flag_accepted_with_this(self):
        """cmd_create(mcp_trust='this') succeeds — mcp_trust flag is still accepted."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module, "_wait_for_sentinel", return_value=(True, None)
                    ):
                        with patch.object(
                            crew_module, "_deliver_tell", return_value=(True, "verified")
                        ):
                            self._setup_create_mocks(mock_run)
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell="Hello",
                                mcp_trust="this",
                            )
        # No assertion needed beyond "did not raise" — mcp_trust is still accepted.

    def test_cmd_create_calls_wait_for_sentinel_not_claude_ready(self):
        """cmd_create uses _wait_for_sentinel (sentinel-file) for readiness, not _wait_for_claude_ready."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(
                        crew_module, "_wait_for_sentinel", return_value=(True, None)
                    ) as mock_sentinel:
                        with patch.object(
                            crew_module, "_deliver_tell", return_value=(True, "verified")
                        ):
                            self._setup_create_mocks(mock_run)
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell="Hello",
                            )

        mock_sentinel.assert_called_once_with("test-worker")


# ---------------------------------------------------------------------------
# Sentinel-file readiness system tests
# ---------------------------------------------------------------------------

class TestSentinelPath:
    """Tests for _sentinel_path helper."""

    def test_sentinel_path_uses_crew_subdir(self):
        """_sentinel_path returns a path inside the crew sentinel directory."""
        path = _sentinel_path("my-worker")
        assert path.endswith("crew/ready-my-worker")

    def test_sentinel_path_includes_session_name(self):
        """_sentinel_path encodes the session name in the filename."""
        path = _sentinel_path("platform-bootstrap")
        assert "platform-bootstrap" in path
        assert path.endswith("ready-platform-bootstrap")

    def test_sentinel_dir_constant_is_crew_subdir(self):
        """_CREW_SENTINEL_DIR is a 'crew' subdirectory of TMPDIR."""
        assert _CREW_SENTINEL_DIR.endswith("/crew") or _CREW_SENTINEL_DIR.endswith("\\crew")

    def test_sentinel_path_is_inside_sentinel_dir(self):
        """_sentinel_path returns a path inside _CREW_SENTINEL_DIR."""
        path = _sentinel_path("abc")
        assert path.startswith(_CREW_SENTINEL_DIR)


class TestCleanStaleSentinel:
    """Tests for _clean_stale_sentinel."""

    def test_removes_existing_file(self, tmp_path, monkeypatch):
        """_clean_stale_sentinel removes an existing sentinel file."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        sentinel = sentinel_dir / "ready-myworker"
        sentinel.touch()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        _clean_stale_sentinel("myworker")

        assert not sentinel.exists()

    def test_silent_when_file_absent(self, tmp_path, monkeypatch):
        """_clean_stale_sentinel does not raise when sentinel doesn't exist."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        # Should not raise
        _clean_stale_sentinel("myworker")


class TestCleanupSentinel:
    """Tests for _cleanup_sentinel (dismiss-side cleanup)."""

    def test_removes_existing_sentinel(self, tmp_path, monkeypatch):
        """_cleanup_sentinel removes the sentinel file on dismiss."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        sentinel = sentinel_dir / "ready-myworker"
        sentinel.touch()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        _cleanup_sentinel("myworker")

        assert not sentinel.exists()

    def test_silent_when_already_absent(self, tmp_path, monkeypatch):
        """_cleanup_sentinel does not raise when sentinel file is already gone."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        # Should not raise
        _cleanup_sentinel("myworker")


class TestWaitForSentinel:
    """Tests for _wait_for_sentinel — deterministic event-driven readiness detection via sentinel file."""

    def test_returns_true_immediately_if_sentinel_exists(self, tmp_path, monkeypatch):
        """If sentinel already exists, returns (True, None) before invoking fswatch."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        (sentinel_dir / "ready-myworker").touch()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        ready, reason = _wait_for_sentinel("myworker", ceiling=5.0, poll_interval=0.01)

        assert ready is True
        assert reason is None

    def test_returns_true_via_fswatch_event_driven(self, tmp_path, monkeypatch):
        """Returns (True, None) when fswatch is available and sentinel is written by background thread.

        This test proves event-driven detection: a background thread writes the sentinel
        after ~200ms; the main thread calls _wait_for_sentinel with a 5s ceiling and must
        return True quickly after the write — not by polling at 0.5s intervals.
        """
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        sentinel_file = sentinel_dir / "ready-myworker"

        # Background thread: write the sentinel after a brief delay.
        delay_s = 0.2

        def write_sentinel():
            time.sleep(delay_s)
            sentinel_file.touch()

        t = threading.Thread(target=write_sentinel, daemon=True)

        start = time.monotonic()
        t.start()
        ready, reason = _wait_for_sentinel("myworker", ceiling=5.0, poll_interval=0.5)
        elapsed = time.monotonic() - start

        t.join(timeout=2.0)

        assert ready is True, f"Expected ready=True, got reason={reason!r}"
        assert reason is None
        # Must have waited at least the delay (not returned from fast-path).
        assert elapsed >= delay_s * 0.5, (
            f"Elapsed {elapsed:.3f}s is suspiciously short — may have used fast-path unexpectedly"
        )
        # Must have returned well under the outer ceiling — proves event-driven wakeup.
        assert elapsed < 3.0, (
            f"Elapsed {elapsed:.3f}s is too close to ceiling — event-driven detection may be broken"
        )

    def test_returns_false_when_both_signals_timeout(self, tmp_path, monkeypatch):
        """When ceiling elapses with neither sentinel nor prompt-box signal, returns (False, reason)."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()  # Dir exists but sentinel file never appears
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        # Ensure prompt-box polling also returns no signal.
        with patch.object(crew_module, "_pane_shows_prompt_ready", return_value=False):
            ready, reason = _wait_for_sentinel("myworker", ceiling=0.1)

        assert ready is False
        assert reason is not None
        assert "session never reported ready" in reason, (
            f"Expected 'session never reported ready' in reason, got: {reason!r}"
        )

    def test_returns_false_combined_reason_when_hook_absent(self, tmp_path, monkeypatch):
        """When ceiling elapses and hook was not configured, reason mentions both signals checked."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        with patch.object(crew_module, "_pane_shows_prompt_ready", return_value=False):
            ready, reason = _wait_for_sentinel("myworker", ceiling=0.1)

        assert ready is False
        assert "prompt-box" in reason or "sentinel" in reason, (
            f"Expected reason to mention signal names, got: {reason!r}"
        )

    def test_returns_true_when_sentinel_dir_absent_at_wait_start(self, tmp_path, monkeypatch):
        """Returns (True, None) even when the sentinel directory doesn't exist when _wait_for_sentinel is called.

        This is the primary regression test for the sentinel-never-detected bug.

        Root cause: on macOS (kqueue backend), fswatch does NOT fire events for files
        created inside a directory that was itself created AFTER fswatch started watching
        the path. If _wait_for_sentinel starts before the SessionStart hook fires
        (which is always true — crew create calls _wait_for_sentinel immediately after
        spawning the staff session), and the hook creates the directory on first run,
        fswatch would never see the sentinel write.

        Fix: _wait_for_sentinel now calls os.makedirs(_CREW_SENTINEL_DIR, exist_ok=True)
        BEFORE starting the fswatch loop so that fswatch always watches a pre-existing
        directory. The hook still creates the directory idempotently (exist_ok=True), but
        the directory is guaranteed to exist before fswatch subscribes to events on it.
        """
        # Point at a subdirectory that does NOT exist yet — simulates a cold system
        # where no crew session has ever been created.
        sentinel_dir = tmp_path / "crew-absent"
        # Deliberately do NOT create sentinel_dir here.
        assert not sentinel_dir.exists(), "Pre-condition: dir must not exist at test start"
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        sentinel_file = sentinel_dir / "ready-myworker"

        # Background thread: write the sentinel after a brief delay (simulating
        # the SessionStart hook creating the directory and writing the file).
        delay_s = 0.3

        def write_sentinel():
            time.sleep(delay_s)
            sentinel_file.parent.mkdir(parents=True, exist_ok=True)
            sentinel_file.touch()

        t = threading.Thread(target=write_sentinel, daemon=True)

        start = time.monotonic()
        t.start()
        ready, reason = _wait_for_sentinel("myworker", ceiling=5.0, poll_interval=0.5)
        elapsed = time.monotonic() - start

        t.join(timeout=2.0)

        assert ready is True, (
            f"Expected ready=True but got ready=False, reason={reason!r}. "
            "This means fswatch did not detect the sentinel written into a "
            "directory created after fswatch started — the makedirs pre-creation "
            "fix is missing or not working."
        )
        assert reason is None
        assert elapsed < 3.0, (
            f"Elapsed {elapsed:.3f}s is too close to ceiling — event-driven detection may be broken"
        )

    def test_clean_stale_sentinel_before_wait_prevents_false_ready(self, tmp_path, monkeypatch):
        """_clean_stale_sentinel removes leftover file so fast-path cannot fire on stale data."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        stale = sentinel_dir / "ready-myworker"
        stale.touch()  # Leftover from prior session
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        _clean_stale_sentinel("myworker")

        # After cleanup, file is gone — fast-path will not fire.
        assert not stale.exists()


class TestHookPresentInSettings:
    """Tests for _hook_present_in_settings — settings.json parse for hook-missing heuristic."""

    def test_returns_true_when_hook_present_in_session_start(self, tmp_path):
        """Returns True when crew-lifecycle-hook appears in SessionStart hooks (Nix binary path)."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {"command": "/nix/store/93h3d25i13vmdq3claflp803g7qwf1df-crew-lifecycle-hook/bin/crew-lifecycle-hook"}
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings))

        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is True

    def test_returns_true_when_hook_present_as_nested_hooks_list(self, tmp_path):
        """Returns True for nested hooks list format (as deployed by default.nix)."""
        # default.nix deploys SessionStart as a list of hook-group dicts with
        # a 'hooks' key each containing a list of command objects.
        settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {"type": "command", "timeout": 5000, "command": "/nix/store/abc123-crew-lifecycle-hook/bin/crew-lifecycle-hook"}
                        ]
                    }
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings))

        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is True

    def test_returns_false_when_hook_absent_from_session_start(self, tmp_path):
        """Returns False when SessionStart hooks do not include crew-lifecycle-hook."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {"command": "/nix/store/xxx/some-other-hook"}
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings))

        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is False

    def test_returns_false_when_no_session_start_hooks(self, tmp_path):
        """Returns False when settings.json has no SessionStart key."""
        settings = {"hooks": {}}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings))

        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is False

    def test_returns_true_when_settings_json_missing(self, tmp_path):
        """Falls back to True (assume hook present) when settings.json is absent."""
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is True

    def test_returns_true_when_settings_json_malformed(self, tmp_path):
        """Falls back to True (assume hook present) when settings.json is malformed JSON."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not valid json {{")

        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is True

    def test_handles_string_hook_entries(self, tmp_path):
        """Handles plain string hook entries (not just dicts with 'command' key)."""
        settings = {
            "hooks": {
                "SessionStart": [
                    "/nix/store/xxx/crew-lifecycle-hook"
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(__import__("json").dumps(settings))

        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(tmp_path)}):
            result = crew_module._hook_present_in_settings()

        assert result is True


class TestCmdCreateSentinelCleanup:
    """Tests that cmd_create cleans stale sentinel before spawn."""

    def _setup_create_mocks(self, mock_run):
        """Configure mock_run for a minimal successful create flow."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_stale_sentinel_cleaned_before_spawn(self, tmp_path, monkeypatch):
        """cmd_create removes stale sentinel before spawning so _wait_for_sentinel waits for fresh signal."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        stale = sentinel_dir / "ready-test-worker"
        stale.touch()  # Stale file from prior session
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        clean_called = {"called": False, "name": None}
        original_clean = crew_module._clean_stale_sentinel

        def tracked_clean(name):
            clean_called["called"] = True
            clean_called["name"] = name
            original_clean(name)

        monkeypatch.setattr(crew_module, "_clean_stale_sentinel", tracked_clean)

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    with patch.object(crew_module, "_wait_for_sentinel", return_value=(True, None)):
                        with patch.object(crew_module, "_deliver_tell", return_value=(True, "ok")):
                            self._setup_create_mocks(mock_run)
                            cmd_create(
                                name="test-worker",
                                repo="/some/repo",
                                branch="test-worker",
                                base="main",
                                fmt="xml",
                                tell="hello",
                            )

        assert clean_called["called"], "_clean_stale_sentinel must be called before spawn"
        assert clean_called["name"] == "test-worker"

    def test_stale_sentinel_always_cleaned_even_without_tell(self, tmp_path, monkeypatch):
        """cmd_create cleans stale sentinel unconditionally, even without --tell.

        Defense-in-depth: future callers adding --tell later would see a stale
        sentinel if cleanup were conditional. Unconditional cleanup prevents this.
        """
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        clean_called = {"called": False, "name": None}
        monkeypatch.setattr(
            crew_module, "_clean_stale_sentinel",
            lambda name: clean_called.update({"called": True, "name": name}),
        )

        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    self._setup_create_mocks(mock_run)
                    cmd_create(
                        name="test-worker",
                        repo="/some/repo",
                        branch="test-worker",
                        base="main",
                        fmt="xml",
                        tell=None,  # no --tell — cleanup still fires
                    )

        assert clean_called["called"], "_clean_stale_sentinel must be called unconditionally"
        assert clean_called["name"] == "test-worker"


class TestCmdDismissSentinelCleanup:
    """Tests that cmd_dismiss cleans the sentinel for dismissed windows."""

    def _setup_dismiss_mocks(self, mock_run, session="my-session", window_id="@5"):
        """Configure mock_run for a successful dismiss of 'myworker' window."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout=f"{session}\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@99\n")  # invoking window
            if "list-windows" in joined:
                # Return the target window (NOT the invoking window)
                return fake_run_result(
                    stdout=f"myworker @{window_id[1:]} 0\n"
                    if "format" not in joined
                    else f"myworker {window_id} 0\n"
                )
            if "kill-window" in joined:
                return fake_run_result()
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_sentinel_cleaned_on_window_dismiss(self, tmp_path, monkeypatch):
        """cmd_dismiss calls _cleanup_sentinel with the dismissed window name."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        sentinel = sentinel_dir / "ready-myworker"
        sentinel.touch()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        cleanup_calls = []
        original_cleanup = crew_module._cleanup_sentinel
        monkeypatch.setattr(
            crew_module, "_cleanup_sentinel",
            lambda name: cleanup_calls.append(name),
        )

        with patch("subprocess.run") as mock_run:
            # Minimal mocks for dismiss flow.
            # list-windows output must match the -F format used by get_window_lookup:
            #   #{session_name}:#{window_index}|#{window_id}|#{window_name}
            # @99 is the invoking window; @5 is the target window to dismiss.
            def side_effect(cmd, **kwargs):
                joined = " ".join(str(c) for c in cmd)
                if "display-message" in joined and "session_name" in joined:
                    return fake_run_result(stdout="my-session\n")
                if "display-message" in joined and "window_id" in joined:
                    return fake_run_result(stdout="@99\n")
                if "list-windows" in joined:
                    return fake_run_result(stdout="my-session:0|@5|myworker\n")
                return fake_run_result()
            mock_run.side_effect = side_effect

            cmd_dismiss("myworker", fmt="xml")

        assert "myworker" in cleanup_calls, (
            f"Expected _cleanup_sentinel('myworker') to be called, got: {cleanup_calls}"
        )


# ---------------------------------------------------------------------------
# Emoji icon assignment (crew create calls random-emoji for new windows)
# ---------------------------------------------------------------------------

class TestCmdCreateEmojiIcon:
    """Tests that crew create invokes random-emoji for the new window after creation.

    Karl's manual flow assigns a random emoji icon to every new tmux window via an
    after-new-window hook. When `tmux new-window -d` creates a detached window, that
    hook targets the caller's current window (not the new one). crew create therefore
    explicitly calls `tmux run-shell -t <name>.0 random-emoji` after window creation
    so that the new window receives the correct icon.

    The emoji is stored as a window OPTION (@theme_plugin_inactive_window_icon and
    @theme_plugin_active_window_icon), not in the window NAME itself. The window name
    remains the bare name supplied to crew create. This means bare-name resolution in
    get_window_lookup (and all subcommands that use it) continues to work unchanged.
    """

    def _setup_create_mocks(self, mock_run):
        """Configure mock_run for a standard successful create flow."""
        def side_effect(cmd, **kwargs):
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            joined = " ".join(str(c) for c in cmd_list)
            if "display-message" in joined and "session_name" in joined:
                return fake_run_result(stdout="tidy-crown\n")
            if "display-message" in joined and "window_id" in joined:
                return fake_run_result(stdout="@1\n")
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "rev-parse" in joined and "show-toplevel" in joined:
                return fake_run_result(stdout="/some/repo\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="main\n")
            if "rev-parse" in joined and "upstream" in joined:
                return fake_run_result(stdout="origin/main\n")
            if "rev-parse" in joined and "--verify" in joined and "refs/heads" not in joined:
                return fake_run_result(stdout="abc1234\n")
            if "fetch" in joined and "origin" in joined:
                return fake_run_result()
            if "rev-parse" in joined and "refs/heads" in joined:
                return fake_run_result(returncode=1)
            if "branch" in joined and "main" in joined:
                return fake_run_result()
            if "worktree" in joined and "add" in joined:
                return fake_run_result()
            if "new-window" in joined:
                return fake_run_result()
            if "run-shell" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()
        mock_run.side_effect = side_effect

    def test_random_emoji_called_after_new_window(self, capsys):
        """crew create must invoke 'tmux run-shell -t <name>.0 random-emoji' after new-window."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    self._setup_create_mocks(mock_run)
                    cmd_create(
                        name="emoji-test",
                        repo="/some/repo",
                        branch="emoji-test",
                        base="main",
                        fmt="xml",
                    )

        all_cmds = [c[0][0] for c in mock_run.call_args_list if isinstance(c[0][0], list)]
        run_shell_calls = [c for c in all_cmds if "run-shell" in c]
        emoji_calls = [c for c in run_shell_calls if "random-emoji" in c]
        assert emoji_calls, (
            "Expected a 'tmux run-shell ... random-emoji' call; "
            f"run-shell calls found: {run_shell_calls}"
        )
        emoji_call = emoji_calls[0]
        # Must target the newly created window's first pane
        joined = " ".join(str(x) for x in emoji_call)
        assert "emoji-test.0" in joined, (
            f"random-emoji must be targeted at <name>.0, got: {joined!r}"
        )

    def test_random_emoji_called_after_new_window_not_before(self, capsys):
        """random-emoji invocation must come AFTER tmux new-window, not before."""
        with patch("subprocess.run") as mock_run:
            with patch("os.path.isdir", return_value=True):
                with patch("os.path.exists", return_value=False):
                    self._setup_create_mocks(mock_run)
                    cmd_create(
                        name="order-test",
                        repo="/some/repo",
                        branch="order-test",
                        base="main",
                        fmt="xml",
                    )

        all_cmds = [" ".join(str(x) for x in c[0][0]) for c in mock_run.call_args_list
                    if isinstance(c[0][0], list)]
        new_window_idx = next(
            (i for i, c in enumerate(all_cmds) if "new-window" in c), None
        )
        emoji_idx = next(
            (i for i, c in enumerate(all_cmds) if "run-shell" in c and "random-emoji" in c), None
        )
        assert new_window_idx is not None, "Expected tmux new-window call"
        assert emoji_idx is not None, "Expected random-emoji call"
        assert emoji_idx > new_window_idx, (
            f"random-emoji (idx={emoji_idx}) must come after new-window (idx={new_window_idx})"
        )

    def test_bare_name_resolution_unchanged_by_emoji(self):
        """get_window_lookup returns bare window names; bare-name resolution is unaffected.

        random-emoji sets window OPTIONS (@theme_plugin_inactive_window_icon), not the
        window NAME. The actual tmux window name remains the bare name supplied to
        crew create (e.g. 'audit', not '🦊 audit'). This test documents that contract:
        get_window_lookup parses #{window_name} which is unchanged, so all crew subcommands
        (tell/read/dismiss/list) continue to accept the bare name without modification.
        """
        raw_output = (
            "my-session:0|@1|audit\n"
            "my-session:1|@2|flag-preview\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout=raw_output)
            lookup = get_window_lookup()

        # Bare names must be resolvable directly
        assert "audit" in lookup, "Bare name 'audit' must be in lookup"
        assert "flag-preview" in lookup, "Bare name 'flag-preview' must be in lookup"
        # No emoji-prefixed key should appear (window names are bare)
        emoji_keys = [k for k in lookup if not k.isascii() or k != k.strip()]
        assert not emoji_keys, f"No emoji-prefixed keys expected in lookup, got: {emoji_keys}"


# ---------------------------------------------------------------------------
# _tmux_fire_and_forget helper
# ---------------------------------------------------------------------------

class TestTmuxFireAndForget:
    """Tests for _tmux_fire_and_forget — the fire-and-forget tmux subprocess helper."""

    def test_helper_does_not_log_on_success(self, capsys):
        """No output to stderr when subprocess.run returns returncode=0."""
        completed = MagicMock()
        completed.returncode = 0
        completed.stderr = b""
        with patch("subprocess.run", return_value=completed):
            _tmux_fire_and_forget(
                ["tmux", "run-shell", "-t", "test.0", "random-emoji"],
                context="random-emoji icon assignment",
            )
        captured = capsys.readouterr()
        assert captured.err == "", (
            f"Expected empty stderr on success, got: {captured.err!r}"
        )

    def test_helper_logs_on_nonzero_returncode(self, capsys):
        """Stderr log line must contain context, exit code, and stderr fragment on failure."""
        completed = MagicMock()
        completed.returncode = 2
        completed.stderr = b"tmux: no server running"
        with patch("subprocess.run", return_value=completed):
            _tmux_fire_and_forget(
                ["tmux", "run-shell", "-t", "test.0", "random-emoji"],
                context="random-emoji icon assignment",
            )
        captured = capsys.readouterr()
        assert "random-emoji icon assignment" in captured.err, (
            f"Expected context string in stderr, got: {captured.err!r}"
        )
        assert "exit 2" in captured.err, (
            f"Expected 'exit 2' in stderr, got: {captured.err!r}"
        )
        assert "tmux: no server running" in captured.err, (
            f"Expected stderr fragment in output, got: {captured.err!r}"
        )

    def test_helper_does_not_raise_on_subprocess_exception(self, capsys):
        """Helper must return None without raising even if subprocess.run raises."""
        with patch("subprocess.run", side_effect=FileNotFoundError("tmux")):
            result = _tmux_fire_and_forget(
                ["tmux", "run-shell", "-t", "test.0", "random-emoji"],
                context="random-emoji icon assignment",
            )
        assert result is None, (
            f"Expected None return, got: {result!r}"
        )
        captured = capsys.readouterr()
        assert "random-emoji icon assignment" in captured.err, (
            f"Expected context string in stderr on exception, got: {captured.err!r}"
        )
        assert "FileNotFoundError" in captured.err, (
            f"Expected 'FileNotFoundError' in stderr, got: {captured.err!r}"
        )

    def test_helper_does_not_return_truthy(self):
        """Helper must return None (fire-and-forget; no return value)."""
        completed = MagicMock()
        completed.returncode = 0
        completed.stderr = b""
        with patch("subprocess.run", return_value=completed):
            result = _tmux_fire_and_forget(
                ["tmux", "send-keys", "-t", "test", "staff --name test", "Enter"],
                context="staff session startup",
            )
        assert not result, (
            f"Expected falsy return (None), got: {result!r}"
        )
        assert result is None, (
            f"Expected exactly None, got: {result!r}"
        )


# ---------------------------------------------------------------------------
# crew resume --worktree flag
# ---------------------------------------------------------------------------

class TestCmdResumeWorktreeFlag:
    """Tests for the --worktree flag on crew resume."""

    def _make_session_dir(self, tmp_path, worktree_path: str, session_ids: List[str]):
        """Create a fake ~/.claude/projects/<key>/ with the given .jsonl files."""
        project_key = _mangle_path_to_project_key(worktree_path)
        sessions_dir = tmp_path / ".claude" / "projects" / project_key
        sessions_dir.mkdir(parents=True)
        import time as _time
        base_mtime = _time.time()
        for i, sid in enumerate(session_ids):
            f = sessions_dir / f"{sid}.jsonl"
            f.write_text("{}")
            os.utime(f, (base_mtime + i, base_mtime + i))
        return sessions_dir

    def test_resume_with_explicit_worktree(self, tmp_path, monkeypatch):
        """--worktree PATH is used verbatim and skips both default lookups."""
        explicit_worktree = str(tmp_path / "explicit-repo")
        os.makedirs(explicit_worktree)
        self._make_session_dir(tmp_path, explicit_worktree, ["session-abc"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        # Track whether _resolve_worktree_for_name was called.
        resolve_called = []
        original_resolve = crew_module._resolve_worktree_for_name

        def spy_resolve(name):
            resolve_called.append(name)
            return original_resolve(name)

        monkeypatch.setattr("crew._resolve_worktree_for_name", spy_resolve)

        new_window_calls = []

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "new-window" in joined:
                new_window_calls.append(cmd)
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("audit", None, "xml", send, worktree=explicit_worktree)

        # Must succeed with no failures.
        assert len(send.failure_calls) == 0, (
            f"Expected no failures, got: {send.failure_calls}"
        )
        assert len(send.resumed_calls) == 1, (
            f"Expected one resumed call, got: {send.resumed_calls}"
        )

        # The resolved worktree in the success event must be the explicit path.
        window, session_id, worktree, command = send.resumed_calls[0]
        assert worktree == explicit_worktree, (
            f"Expected explicit worktree path '{explicit_worktree}', got: '{worktree}'"
        )
        assert session_id == "session-abc", (
            f"Expected session 'session-abc', got: '{session_id}'"
        )

        # The tmux new-window must use the explicit path as -c argument.
        assert len(new_window_calls) == 1
        new_window_cmd = new_window_calls[0]
        assert explicit_worktree in new_window_cmd, (
            f"Expected explicit worktree in new-window call, got: {new_window_cmd}"
        )

        # The two-step lookup (_resolve_worktree_for_name) must NOT have been called.
        assert resolve_called == [], (
            f"_resolve_worktree_for_name must not be called when --worktree is provided, "
            f"but it was called with: {resolve_called}"
        )

    def test_resume_with_invalid_worktree_path(self, tmp_path, monkeypatch):
        """--worktree pointing to a non-existent path emits WORKTREE_NOT_FOUND."""
        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        bad_path = str(tmp_path / "does" / "not" / "exist")

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            cmd_resume("audit", None, "xml", send, worktree=bad_path)

        assert send.resumed_calls == [], (
            f"Expected no resumed calls, got: {send.resumed_calls}"
        )
        assert len(send.failure_calls) == 1, (
            f"Expected exactly one failure, got: {send.failure_calls}"
        )
        error_code, message = send.failure_calls[0]
        assert error_code == "WORKTREE_NOT_FOUND", (
            f"Expected WORKTREE_NOT_FOUND error code, got: '{error_code}'"
        )
        assert bad_path in message, (
            f"Expected bad path in failure message, got: '{message}'"
        )

    def test_resume_without_worktree_flag_unchanged(self, tmp_path, monkeypatch):
        """Without --worktree, the existing two-step lookup runs as before."""
        worktree_path = str(tmp_path / "standard-worktree")
        os.makedirs(worktree_path)
        self._make_session_dir(tmp_path, worktree_path, ["std-session"])

        monkeypatch.setattr("crew.Path.home", lambda: tmp_path)

        # Patch _resolve_worktree_for_name to return the test path and record the call.
        resolve_called = []

        def spy_resolve(name):
            resolve_called.append(name)
            return worktree_path

        monkeypatch.setattr("crew._resolve_worktree_for_name", spy_resolve)

        def fake_run(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "list-windows" in joined:
                return fake_run_result(stdout="")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()

        send = _ResumeSpySend()
        with patch("subprocess.run", side_effect=fake_run):
            # No worktree kwarg — exercises the original code path.
            cmd_resume("standard-worktree", None, "xml", send)

        assert len(send.failure_calls) == 0, (
            f"Expected no failures, got: {send.failure_calls}"
        )
        assert len(send.resumed_calls) == 1, (
            f"Expected one resumed call, got: {send.resumed_calls}"
        )

        # The two-step lookup must have been invoked for the name.
        assert resolve_called == ["standard-worktree"], (
            f"Expected _resolve_worktree_for_name called with 'standard-worktree', "
            f"got: {resolve_called}"
        )

        # The worktree returned must match what the resolver provided.
        _, _, worktree, _ = send.resumed_calls[0]
        assert worktree == worktree_path, (
            f"Expected worktree '{worktree_path}', got: '{worktree}'"
        )


# ---------------------------------------------------------------------------
# _ensure_hook_in_settings — hook auto-installation idempotency
# ---------------------------------------------------------------------------

class TestEnsureHookInSettings:
    """Tests for _ensure_hook_in_settings: idempotency, absent-hook installation, error handling."""

    def test_no_op_when_hook_already_present_hook_group_format(self, tmp_path):
        """Returns (True, None) without writing when crew-lifecycle-hook is already in SessionStart."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {"type": "command", "command": "crew-lifecycle-hook"}
                        ]
                    }
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))
        mtime_before = settings_file.stat().st_mtime

        ok, reason = _ensure_hook_in_settings(str(settings_file))

        assert ok is True
        assert reason is None
        # File must NOT have been rewritten (idempotent).
        assert settings_file.stat().st_mtime == mtime_before, (
            "settings.json was rewritten even though hook was already present"
        )

    def test_no_op_when_hook_present_as_flat_command(self, tmp_path):
        """Returns (True, None) when crew-lifecycle-hook appears as a flat command string."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {"command": "crew-lifecycle-hook", "type": "command"}
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))
        mtime_before = settings_file.stat().st_mtime

        ok, reason = _ensure_hook_in_settings(str(settings_file))

        assert ok is True
        assert reason is None
        assert settings_file.stat().st_mtime == mtime_before

    def test_installs_hook_when_session_start_is_empty(self, tmp_path):
        """Appends crew-lifecycle-hook to empty SessionStart list and writes the file."""
        settings = {"hooks": {"SessionStart": []}}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        ok, reason = _ensure_hook_in_settings(str(settings_file))

        assert ok is True
        assert reason is None

        # Re-read and verify hook is present.
        written = json.loads(settings_file.read_text())
        session_start = written.get("hooks", {}).get("SessionStart", [])
        assert len(session_start) >= 1
        found = False
        for entry in session_start:
            if isinstance(entry, dict):
                for hook in entry.get("hooks", []):
                    if isinstance(hook, dict) and "crew-lifecycle-hook" in hook.get("command", ""):
                        found = True
        assert found, f"crew-lifecycle-hook not found in written settings: {session_start}"

    def test_installs_hook_when_session_start_missing_entirely(self, tmp_path):
        """Creates SessionStart key and appends hook when SessionStart is absent from hooks."""
        settings = {"enabledMcpjsonServers": ["context7"]}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        ok, reason = _ensure_hook_in_settings(str(settings_file))

        assert ok is True
        written = json.loads(settings_file.read_text())
        session_start = written.get("hooks", {}).get("SessionStart", [])
        found = any(
            "crew-lifecycle-hook" in hook.get("command", "")
            for entry in session_start if isinstance(entry, dict)
            for hook in entry.get("hooks", []) if isinstance(hook, dict)
        )
        assert found, f"crew-lifecycle-hook not found after install: {session_start}"

    def test_creates_settings_json_when_file_missing(self, tmp_path):
        """Creates a minimal settings.json with SessionStart hook when the file doesn't exist."""
        settings_file = tmp_path / ".claude" / "settings.json"
        # Do NOT create the file — _ensure_hook_in_settings must create it.
        assert not settings_file.exists()

        ok, reason = _ensure_hook_in_settings(str(settings_file))

        assert ok is True
        assert settings_file.exists(), "settings.json was not created"

        written = json.loads(settings_file.read_text())
        session_start = written.get("hooks", {}).get("SessionStart", [])
        found = any(
            "crew-lifecycle-hook" in hook.get("command", "")
            for entry in session_start if isinstance(entry, dict)
            for hook in entry.get("hooks", []) if isinstance(hook, dict)
        )
        assert found, f"crew-lifecycle-hook not found in created settings.json: {session_start}"

    def test_preserves_existing_hooks_when_adding(self, tmp_path):
        """Existing SessionStart hooks are preserved when appending the lifecycle hook."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "other-hook"}]}
                ]
            }
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        ok, _ = _ensure_hook_in_settings(str(settings_file))

        assert ok is True
        written = json.loads(settings_file.read_text())
        session_start = written.get("hooks", {}).get("SessionStart", [])
        # Both original hook and new lifecycle hook must be present.
        all_commands = []
        for entry in session_start:
            if isinstance(entry, dict):
                for hook in entry.get("hooks", []):
                    if isinstance(hook, dict):
                        all_commands.append(hook.get("command", ""))
        assert "other-hook" in all_commands, f"Existing hook lost. Commands: {all_commands}"
        assert any("crew-lifecycle-hook" in cmd for cmd in all_commands), (
            f"crew-lifecycle-hook not added. Commands: {all_commands}"
        )

    def test_returns_false_on_malformed_json(self, tmp_path):
        """Returns (False, reason) without raising when settings.json is malformed JSON."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{this is not valid json")

        ok, reason = _ensure_hook_in_settings(str(settings_file))

        assert ok is False
        assert reason is not None
        assert "malformed" in reason.lower() or "json" in reason.lower(), (
            f"Expected malformed/json in reason, got: {reason!r}"
        )

    def test_idempotent_second_call_does_not_duplicate_hook(self, tmp_path):
        """Calling _ensure_hook_in_settings twice does not duplicate the hook entry."""
        settings = {"hooks": {"SessionStart": []}}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        _ensure_hook_in_settings(str(settings_file))
        _ensure_hook_in_settings(str(settings_file))  # Second call must be a no-op.

        written = json.loads(settings_file.read_text())
        session_start = written.get("hooks", {}).get("SessionStart", [])
        lifecycle_count = sum(
            1
            for entry in session_start if isinstance(entry, dict)
            for hook in entry.get("hooks", []) if isinstance(hook, dict)
            if "crew-lifecycle-hook" in hook.get("command", "")
        )
        assert lifecycle_count == 1, (
            f"Expected exactly 1 lifecycle hook entry, got {lifecycle_count}: {session_start}"
        )


# ---------------------------------------------------------------------------
# _pane_shows_prompt_ready — prompt-box polling detection
# ---------------------------------------------------------------------------

class TestPaneShowsPromptReady:
    """Tests for _pane_shows_prompt_ready: capture-pane polling fallback signal."""

    def test_returns_true_when_startup_banner_and_prompt_glyph_present(self):
        """Returns True when 'claude.ai/code' banner is present alongside ❯ prompt glyph."""
        pane_content = "╭─ Claude Code ─────────────────────────────────────────────────╮\nclaude.ai/code\n> ❯\n╰────────────────────────────────────────────────────────────────╯\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pane_content)
            result = _pane_shows_prompt_ready("test-worker.0")
        assert result is True

    def test_returns_true_when_startup_banner_present(self):
        """Returns True when 'claude.ai/code' appears in capture-pane output."""
        pane_content = "Welcome to Claude Code\nclaude.ai/code\nType your message...\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pane_content)
            result = _pane_shows_prompt_ready("test-worker.0")
        assert result is True

    def test_returns_false_when_no_prompt_tokens(self):
        """Returns False when pane output contains no Claude Code prompt tokens."""
        pane_content = "bash-3.2$ \n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=pane_content)
            result = _pane_shows_prompt_ready("test-worker.0")
        assert result is False

    def test_returns_false_when_capture_pane_fails(self):
        """Returns False (fail open) when tmux capture-pane returns non-zero exit code."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _pane_shows_prompt_ready("test-worker.0")
        assert result is False

    def test_uses_capture_pane_command(self):
        """Invokes tmux capture-pane -p -t <target> when called."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            _pane_shows_prompt_ready("my-window.0")
        called_cmd = mock_run.call_args[0][0]
        assert "capture-pane" in " ".join(str(x) for x in called_cmd)
        assert "my-window.0" in called_cmd

    def test_returns_false_for_shell_prompt_without_claude_banner(self):
        """Returns False for a shell prompt containing ❯ but NOT 'claude.ai/code'.

        Protects against H1 regression: the ❯ glyph appears in popular shell
        prompts (Starship, Oh My Zsh) and must NOT trigger a false-positive
        ready signal before Claude Code has started.
        """
        # Simulates a Starship/Oh My Zsh shell prompt visible in the pane
        # before Claude Code has taken over — contains ❯ but no Claude banner.
        shell_prompt_content = (
            "~/projects/myrepo on  main via  v20.11.0\n"
            "❯ staff --model sonnet\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=shell_prompt_content)
            result = _pane_shows_prompt_ready("test-worker.0")
        assert result is False, (
            "Shell prompt with ❯ but no 'claude.ai/code' must return False "
            "to avoid false-positive ready signal before Claude Code starts"
        )


# ---------------------------------------------------------------------------
# _wait_for_sentinel — polling fallback fires when sentinel is absent
# ---------------------------------------------------------------------------

class TestWaitForSentinelPollingFallback:
    """Tests that _wait_for_sentinel returns success when the polling fallback fires
    even when the sentinel file is never written."""

    def test_returns_true_via_prompt_box_polling_without_sentinel(self, tmp_path, monkeypatch):
        """Returns (True, None) when the prompt-box polling signal fires before the sentinel."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        # Sentinel file is NEVER written — only the poll signal fires.
        # _pane_shows_prompt_ready starts returning True after ~200ms.
        poll_fire_delay = 0.2
        call_count = {"n": 0}

        def fake_prompt_ready(target):
            call_count["n"] += 1
            # First few calls return False (Claude still booting),
            # then return True once the threshold is reached.
            if call_count["n"] >= 3:
                return True
            return False

        monkeypatch.setattr(crew_module, "_pane_shows_prompt_ready", fake_prompt_ready)

        start = time.monotonic()
        ready, reason = _wait_for_sentinel(
            "myworker",
            ceiling=5.0,
            prompt_poll_interval=poll_fire_delay / 3,
        )
        elapsed = time.monotonic() - start

        assert ready is True, f"Expected ready=True via polling fallback, got reason={reason!r}"
        assert reason is None
        # Must have returned well under the 5s ceiling.
        assert elapsed < 3.0, (
            f"Elapsed {elapsed:.3f}s is too close to ceiling — polling fallback may be broken"
        )

    def test_returns_true_via_sentinel_when_prompt_poll_never_fires(self, tmp_path, monkeypatch):
        """Returns (True, None) via sentinel even when prompt-box polling always returns False."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        sentinel_file = sentinel_dir / "ready-myworker"
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        # Polling fallback never fires — only the sentinel fires.
        monkeypatch.setattr(crew_module, "_pane_shows_prompt_ready", lambda target: False)

        delay_s = 0.2

        def write_sentinel():
            time.sleep(delay_s)
            sentinel_file.touch()

        t = threading.Thread(target=write_sentinel, daemon=True)

        start = time.monotonic()
        t.start()
        ready, reason = _wait_for_sentinel("myworker", ceiling=5.0)
        elapsed = time.monotonic() - start

        t.join(timeout=2.0)

        assert ready is True, f"Expected ready=True via sentinel, got reason={reason!r}"
        assert reason is None
        assert elapsed < 3.0, (
            f"Elapsed {elapsed:.3f}s is too close to ceiling — sentinel detection broken"
        )

    def test_returns_false_when_both_signals_timeout(self, tmp_path, monkeypatch):
        """Returns (False, reason) when neither sentinel nor prompt-box fires within ceiling."""
        sentinel_dir = tmp_path / "crew"
        sentinel_dir.mkdir()
        monkeypatch.setattr(crew_module, "_CREW_SENTINEL_DIR", str(sentinel_dir))

        monkeypatch.setattr(crew_module, "_pane_shows_prompt_ready", lambda target: False)

        ready, reason = _wait_for_sentinel("myworker", ceiling=0.1)

        assert ready is False
        assert reason is not None
        assert "session never reported ready" in reason
