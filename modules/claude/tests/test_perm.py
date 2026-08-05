"""
Tests for modules/claude/perm.py's non-git cwd fallback in `ensure_repo()`
and its downstream effects: cwd-drift detection in `cleanup`, the
`cleanup-stale` tidy-only guard, and `cmd_hook()`'s shared resolution.

Covered paths:
- In-repo: ensure_repo() resolves to the git root regardless of which
  subdirectory is cwd (regression guard — must stay bit-for-bit unchanged).
- Non-git: ensure_repo() falls back to Path.cwd().
- cwd drift outside a git repo: `allow` in directory A, `cleanup` (a
  SEPARATE process) in directory B — the grant is stranded in A, and
  `cleanup` warns loudly on stderr and exits non-zero instead of reporting
  a false success (the card's blocking fix).
- Same-cwd round trip outside a git repo: `allow` then `cleanup` from the
  identical directory (as two separate processes) still cleans up quietly.
- In-repo cleanup with nothing owned stays quiet and exits 0 — the
  narrowing must not make the ordinary in-repo case noisy.
- `cleanup-stale` does not create `.claude/` in a non-git cwd that has no
  tracking file (the janitor-shouldn't-create-what-it-tidies fix).
- `cmd_hook()` honors a grant written via the non-git cwd fallback,
  instead of silently no-op'ing via its own independent git resolution.

Isolation: every test redirects $HOME to a per-test tmp_path via
monkeypatch.setenv("HOME", ...) before touching perm.py, and only ever
operates inside tmp_path-rooted directories. Nothing here ever reads or
writes the real ~/.claude or this repo's own .claude/settings.local.json.
Each `perm` "process" is simulated by importing perm.py as a FRESH module
via load_perm() — this mirrors the real CLI, where `allow` and `cleanup`
are always separate process invocations and never share the
module-level `_repo_root` memoization within a single process.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PERM_PATH = Path(__file__).parent.parent / "perm.py"


def load_perm():
    """Import perm.py as a fresh module — isolated global state per call.

    Mirrors reality: `perm allow` and `perm cleanup` are always separate
    CLI invocations, i.e. separate Python processes, each starting with
    `_repo_root = None`. Loading a fresh module per simulated "process"
    reproduces that instead of accidentally sharing memoized state across
    what should be independent invocations.
    """
    spec = importlib.util.spec_from_file_location("perm_under_test", _PERM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init_git_repo(path: Path) -> None:
    """Create a minimal, fully-isolated git repo at `path` with one commit."""
    env_overrides = {"GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env={**_subprocess_env(), **env_overrides})
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)
    (path / "README.md").write_text("test\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _subprocess_env():
    return dict(os.environ)


# ---------------------------------------------------------------------------
# ensure_repo() resolution
# ---------------------------------------------------------------------------

class TestEnsureRepoResolution:
    def test_in_repo_resolves_to_git_root_from_subdirectory(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        subdir = repo / "sub"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        perm = load_perm()
        perm.ensure_repo()

        assert perm._repo_root == repo.resolve()
        assert perm._used_cwd_fallback is False

    def test_non_git_cwd_falls_back_to_cwd(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        nongit = tmp_path / "nongit"
        nongit.mkdir()
        monkeypatch.chdir(nongit)

        perm = load_perm()
        perm.ensure_repo()

        assert perm._repo_root == nongit.resolve()
        assert perm._used_cwd_fallback is True
        assert (nongit / ".claude").is_dir()


# ---------------------------------------------------------------------------
# cwd drift between allow and cleanup (the blocking fix)
# ---------------------------------------------------------------------------

class TestCwdDriftBlockingFix:
    def test_cwd_drift_strands_grant_and_cleanup_warns_loudly(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        dir_a = tmp_path / "dir_a"
        dir_a.mkdir()
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()

        session = "sess-drift"

        # "allow" runs as its own process, from dir_a (non-git).
        monkeypatch.chdir(dir_a)
        perm_a = load_perm()
        perm_a.cmd_allow(session, ["Bash(echo hi)"], False)

        assert perm_a._used_cwd_fallback is True
        settings_a = json.loads((dir_a / ".claude" / "settings.local.json").read_text())
        assert "Bash(echo hi)" in settings_a["permissions"]["allow"]

        # "cleanup" runs as a SEPARATE process, from dir_b — cwd drifted.
        monkeypatch.chdir(dir_b)
        perm_b = load_perm()
        with pytest.raises(SystemExit) as exc_info:
            perm_b.cmd_cleanup(session, False)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert session in captured.err
        assert "cwd" in captured.err.lower()
        assert "stranded" in captured.err.lower() or "different" in captured.err.lower()

        # The grant is still live in dir_a — stranded, exactly as predicted.
        settings_a_after = json.loads((dir_a / ".claude" / "settings.local.json").read_text())
        assert "Bash(echo hi)" in settings_a_after["permissions"]["allow"]

    def test_same_cwd_round_trip_outside_git_cleans_up_quietly(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        session = "sess-roundtrip"

        perm_a = load_perm()
        perm_a.cmd_allow(session, ["Bash(echo hi)"], False)

        perm_b = load_perm()  # separate process, IDENTICAL cwd
        perm_b.cmd_cleanup(session, False)  # must not raise / exit non-zero

        settings = json.loads((workdir / ".claude" / "settings.local.json").read_text())
        assert "Bash(echo hi)" not in settings["permissions"]["allow"]

        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# In-repo cleanup must stay quiet on "nothing owned" (the narrowing)
# ---------------------------------------------------------------------------

class TestInRepoCleanupStaysQuiet:
    def test_in_repo_cleanup_stays_quiet_when_nothing_owned(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)

        perm = load_perm()
        perm.cmd_cleanup("session-with-nothing-owned", False)  # must not raise

        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_in_repo_cleanup_verbose_still_prints_quiet_message(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        monkeypatch.chdir(repo)

        perm = load_perm()
        perm.cmd_cleanup("session-with-nothing-owned", True)  # must not raise

        captured = capsys.readouterr()
        assert captured.err == ""
        assert "No temporary permissions" in captured.out


# ---------------------------------------------------------------------------
# cleanup-stale: janitor must not create what it exists to tidy
# ---------------------------------------------------------------------------

class TestCleanupStaleDoesNotCreate:
    def test_no_claude_dir_created_in_non_git_cwd_with_no_tracking_file(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        nongit = tmp_path / "nongit"
        nongit.mkdir()
        monkeypatch.chdir(nongit)

        perm = load_perm()
        perm.cmd_cleanup_stale(4)

        assert not (nongit / ".claude").exists()

    def test_stale_entries_still_removed_when_tracking_file_exists(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        nongit = tmp_path / "nongit"
        nongit.mkdir()
        monkeypatch.chdir(nongit)

        perm = load_perm()
        perm.cmd_allow("sess-stale", ["Bash(echo hi)"], False)

        # Backdate the claim so it is stale relative to a 0-hour max-age.
        tracking_path = nongit / ".claude" / ".perm-tracking.json"
        data = json.loads(tracking_path.read_text())
        data["temporary"]["Bash(echo hi)"]["sess-stale"] = 0
        tracking_path.write_text(json.dumps(data))

        perm2 = load_perm()
        perm2.cmd_cleanup_stale(0)

        settings = json.loads((nongit / ".claude" / "settings.local.json").read_text())
        assert "Bash(echo hi)" not in settings["permissions"]["allow"]


# ---------------------------------------------------------------------------
# cmd_hook() honors grants written via the non-git cwd fallback
# ---------------------------------------------------------------------------

class TestHookHonorsFallbackGrant:
    def test_hook_emits_allow_decision_for_grant_in_non_git_cwd(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        nongit = tmp_path / "nongit"
        nongit.mkdir()
        monkeypatch.chdir(nongit)

        perm = load_perm()
        perm.cmd_allow("sess-hook", ["Bash(echo hi)"], False)

        payload = {
            "cwd": str(nongit),
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
        }
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with pytest.raises(SystemExit) as exc_info:
                perm.cmd_hook()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        decision = json.loads(captured.out)
        assert decision["hookSpecificOutput"]["decision"]["behavior"] == "allow"

    def test_hook_no_decision_when_no_settings_file_in_non_git_cwd(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))

        nongit = tmp_path / "nongit"
        nongit.mkdir()
        monkeypatch.chdir(nongit)

        perm = load_perm()

        payload = {
            "cwd": str(nongit),
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
        }
        with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
            with pytest.raises(SystemExit) as exc_info:
                perm.cmd_hook()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert captured.out == ""
