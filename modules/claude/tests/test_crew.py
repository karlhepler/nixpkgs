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
import subprocess
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
    _looks_like_message_not_target,
    _mangle_path_to_project_key,
    _resolve_targets_with_lookup,
    build_parser,
    cmd_create,
    cmd_find,
    cmd_list,
    cmd_project_path,
    cmd_resume,
    cmd_sessions,
    cmd_status,
    cmd_tell,
    get_all_panes,
    get_current_session,
    get_window_lookup,
    is_claude_pane,
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
        """cmd_create must spawn 'staff --name <name>' by default (P6.3)."""
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
        assert "staff --name test-worker" in cmd_str
        # Must NOT spawn bare 'claude' as the first command
        assert "claude --name test-worker" not in cmd_str

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
        """--tell delivers initial message after prompt-ready (P6.2)."""
        with patch("subprocess.run") as mock_run:
            with patch.object(crew_module, "_wait_for_prompt_ready", return_value=True):
                self._run_create(
                    mock_run,
                    name="test-worker",
                    repo="/some/repo",
                    branch="test-worker",
                    base="main",
                    fmt="xml",
                    tell="Build the auth service",
                )

        # Look for the tell send-keys call
        send_keys_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][0] == "tmux" and "send-keys" in c[0][0]
        ]
        tell_call = next(
            (
                c for c in send_keys_calls
                if "Build the auth service" in " ".join(str(x) for x in c[0][0])
            ),
            None,
        )
        assert tell_call is not None, "Expected a send-keys call with the --tell message"

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
        """XML output includes told='true' when --tell is used (P6.2)."""
        with patch("subprocess.run") as mock_run:
            with patch.object(crew_module, "_wait_for_prompt_ready", return_value=True):
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

        assert len(send.resumed_calls) == 0
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

        assert len(send.resumed_calls) == 0
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

        assert len(send.resumed_calls) == 0
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

        assert len(send.resumed_calls) == 0
        assert len(send.failure_calls) == 1
        error_code, message = send.failure_calls[0]
        assert error_code == "TMUX_WINDOW_FAILED"


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
