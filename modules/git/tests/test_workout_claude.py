"""
Tests for workout-claude.py — focused on the existing-worktree caller-visibility enhancement:
  - Pre-existence check before calling workout
  - Stderr warning emitted when attaching to an existing worktree
  - No warning emitted on fresh worktree creation
  - Warning includes branch name and commit count
"""

import sys
import os
from io import StringIO
from typing import List
from unittest.mock import MagicMock, patch, call

import pytest

# workout-claude.py lives at modules/git/workout-claude.py (importable as workout_claude)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# workout-claude.py uses a hyphen in its filename; import via importlib
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "workout_claude",
    os.path.join(os.path.dirname(__file__), "..", "workout-claude.py"),
)
workout_claude = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(workout_claude)

create_worktree_with_prompt = workout_claude.create_worktree_with_prompt
_check_worktree_preexists = workout_claude._check_worktree_preexists
_get_worktree_info = workout_claude._get_worktree_info
normalize_branch_name = workout_claude.normalize_branch_name


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
# _check_worktree_preexists — unit tests
# ---------------------------------------------------------------------------

class TestCheckWorktreePreexists:
    def test_returns_true_when_branch_found_in_worktree_list(self):
        """Branch that appears in git worktree list --porcelain returns True."""
        porcelain_output = (
            "worktree /some/path\n"
            "HEAD abc123\n"
            "branch refs/heads/karlhepler/fix-auth\n\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout=porcelain_output)
            result = _check_worktree_preexists("karlhepler/fix-auth", None)
        assert result is True

    def test_returns_false_when_branch_not_in_worktree_list(self):
        """Branch not in any worktree returns False."""
        porcelain_output = (
            "worktree /some/path\n"
            "HEAD abc123\n"
            "branch refs/heads/karlhepler/other-branch\n\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout=porcelain_output)
            result = _check_worktree_preexists("karlhepler/fix-auth", None)
        assert result is False

    def test_returns_false_when_git_command_fails(self):
        """If git worktree list fails, returns False (safe default)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(returncode=1)
            result = _check_worktree_preexists("karlhepler/fix-auth", None)
        assert result is False

    def test_uses_cwd_when_provided(self):
        """When cwd is provided, it is passed to subprocess.run."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(stdout="")
            _check_worktree_preexists("karlhepler/fix-auth", "/some/repo")
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("cwd") == "/some/repo"


# ---------------------------------------------------------------------------
# TestWorkoutClaudeExistingWorktreeWarning
# ---------------------------------------------------------------------------

class TestWorkoutClaudeExistingWorktreeWarning:
    """Tests for the caller-visibility warning when attaching to an existing worktree."""

    def _make_worktree_def(self, branch: str = "fix-auth", prompt: str = "Do work") -> dict:
        return {"worktree": branch, "prompt": prompt}

    def _base_subprocess_side_effect(self, worktree_path: str):
        """Build a subprocess.run side_effect that simulates a successful workout call."""
        def side_effect(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "worktree" in joined and "list" in joined and "porcelain" in joined:
                # Simulate pre-existing worktree
                return fake_run_result(
                    stdout=(
                        f"worktree {worktree_path}\n"
                        "HEAD abc123\n"
                        "branch refs/heads/karlhepler/fix-auth\n\n"
                    )
                )
            if "workout" in " ".join(str(c) for c in cmd):
                return fake_run_result(stdout=f"cd '{worktree_path}'\n")
            if "branch" in joined and "--show-current" in joined:
                return fake_run_result(stdout="karlhepler/fix-auth\n")
            if "symbolic-ref" in joined and "origin/HEAD" in joined:
                return fake_run_result(stdout="refs/remotes/origin/main\n")
            if "rev-list" in joined and "--count" in joined:
                return fake_run_result(stdout="3\n")
            if "which" in joined:
                return fake_run_result(stdout="/usr/bin/staff\n")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()
        return side_effect

    def _fresh_subprocess_side_effect(self, worktree_path: str):
        """Build a subprocess.run side_effect that simulates a FRESH worktree creation."""
        def side_effect(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "worktree" in joined and "list" in joined and "porcelain" in joined:
                # No matching branch — fresh create
                return fake_run_result(
                    stdout=(
                        "worktree /some/other/path\n"
                        "HEAD abc123\n"
                        "branch refs/heads/karlhepler/other\n\n"
                    )
                )
            if "workout" in " ".join(str(c) for c in cmd):
                return fake_run_result(stdout=f"cd '{worktree_path}'\n")
            if "which" in joined:
                return fake_run_result(stdout="/usr/bin/staff\n")
            if "new-window" in joined:
                return fake_run_result()
            if "send-keys" in joined:
                return fake_run_result()
            return fake_run_result()
        return side_effect

    def test_emits_warning_when_attaching_to_existing_worktree(self, capsys, tmp_path):
        """When worktree pre-exists, a warning is printed to stderr."""
        worktree_path = str(tmp_path / "karlhepler" / "fix-auth")
        worktree_def = self._make_worktree_def("fix-auth")

        with patch("subprocess.run", side_effect=self._base_subprocess_side_effect(worktree_path)):
            result = create_worktree_with_prompt(worktree_def, "staff")

        assert result is True
        captured = capsys.readouterr()
        assert "Warning: attaching to EXISTING worktree" in captured.err
        assert worktree_path in captured.err
        assert "NOT a fresh worktree" in captured.err

    def test_no_warning_on_fresh_create(self, capsys, tmp_path):
        """When worktree is freshly created, no warning is emitted and success output IS present."""
        worktree_path = str(tmp_path / "karlhepler" / "new-feature")
        worktree_def = self._make_worktree_def("new-feature")

        with patch("subprocess.run", side_effect=self._fresh_subprocess_side_effect(worktree_path)):
            result = create_worktree_with_prompt(worktree_def, "staff")

        assert result is True
        captured = capsys.readouterr()
        assert "Warning" not in captured.err
        assert "EXISTING worktree" not in captured.err
        # Guard against regressions that silence all output: success path must emit its marker
        assert "✓ Created worktree" in captured.err

    def test_warning_includes_branch_and_commit_count(self, capsys, tmp_path):
        """The warning message includes the branch name and commit count ahead of trunk."""
        worktree_path = str(tmp_path / "karlhepler" / "fix-auth")
        worktree_def = self._make_worktree_def("fix-auth")

        with patch("subprocess.run", side_effect=self._base_subprocess_side_effect(worktree_path)):
            create_worktree_with_prompt(worktree_def, "staff")

        captured = capsys.readouterr()
        # Branch name must appear in the warning
        assert "karlhepler/fix-auth" in captured.err
        # Commit count (3) must appear
        assert "3 commit(s) ahead" in captured.err


# ---------------------------------------------------------------------------
# _get_worktree_info — unit tests
# ---------------------------------------------------------------------------

class TestGetWorktreeInfo:
    def test_returns_branch_and_commit_count(self):
        """Returns branch name and commits-ahead count from git commands."""
        def side_effect(cmd, **kwargs):
            joined = " ".join(str(c) for c in cmd)
            if "branch" in joined and "--show-current" in joined:
                return fake_run_result(stdout="karlhepler/fix-auth\n")
            if "symbolic-ref" in joined:
                return fake_run_result(stdout="refs/remotes/origin/main\n")
            if "rev-list" in joined and "--count" in joined:
                return fake_run_result(stdout="5\n")
            return fake_run_result()

        with patch("subprocess.run", side_effect=side_effect):
            branch, count = _get_worktree_info("/some/worktree")

        assert branch == "karlhepler/fix-auth"
        assert count == 5

    def test_falls_back_gracefully_on_git_errors(self):
        """Returns ('unknown', 0) when git commands fail."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = fake_run_result(returncode=1)
            branch, count = _get_worktree_info("/nonexistent/path")

        assert branch == "unknown"
        assert count == 0
