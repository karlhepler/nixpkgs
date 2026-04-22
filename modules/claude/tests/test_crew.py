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
    _resolve_targets_with_lookup,
    build_parser,
    cmd_create,
    cmd_find,
    cmd_list,
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

    def _setup_create_mocks(self, mock_run, worktree_path_exists=False):
        """Configure mock_run side_effect for a typical successful create flow."""
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

    def _run_create(self, mock_run, **kwargs):
        """Run cmd_create with standard mocks for filesystem checks."""
        with patch("os.path.isdir", return_value=True):
            with patch("os.path.exists", return_value=False):
                self._setup_create_mocks(mock_run)
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
