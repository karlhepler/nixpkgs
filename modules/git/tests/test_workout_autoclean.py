"""Tests for the merged-PR reap rule in workout-autoclean.bash.

Runs the real script with --dry-run only (nothing is ever trashed) against
throwaway git repos, with a fake `gh` first on PATH. Worktrees are brand new,
so by default no age-based rule fires; tests make them look old by passing
WORKOUT_AUTOCLEAN_NOW (the script's "now" override).

Run: python3 -m unittest modules.git.tests.test_workout_autoclean
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "workout-autoclean.bash")

FAKE_GH = """#!/usr/bin/env bash
if [[ "${FAKE_GH_FAIL:-}" == 1 ]]; then echo "boom from gh" >&2; exit 1; fi
if [[ "$1 $2" == "auth status" ]]; then exit 0; fi
if [[ "$1 $2" == "pr list" ]]; then
  if [[ "${FAKE_GH_FAIL_LIST:-}" == 1 ]]; then echo "list blew up" >&2; exit 1; fi
  state=""
  prev=""
  for arg in "$@"; do
    [[ "$prev" == "--state" ]] && state="$arg"
    prev="$arg"
  done
  cat "$FAKE_GH_DIR/$state.txt"
  exit 0
fi
exit 1
"""


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


class WorkoutAutocleanMergedPrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="autoclean-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "worktrees")
        self.repo = os.path.join(self.tmp, "main-repo")
        self.gh_dir = os.path.join(self.tmp, "gh-data")
        bin_dir = os.path.join(self.tmp, "bin")
        for d in (self.root, self.repo, self.gh_dir, bin_dir):
            os.makedirs(d)
        gh = os.path.join(bin_dir, "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH)
        os.chmod(gh, 0o755)
        self.bin_dir = bin_dir

        bare = os.path.join(self.tmp, "origin.git")
        git("init", "-q", "--bare", "-b", "main", bare, cwd=self.tmp)
        git("init", "-q", "-b", "main", self.repo, cwd=self.tmp)
        git("commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo)
        # Real local origin so refs/remotes/origin/HEAD exists, then rewrite the
        # URL to a GitHub one (the script only parses `remote get-url origin`).
        git("remote", "add", "origin", bare, cwd=self.repo)
        git("push", "-q", "origin", "main", cwd=self.repo)
        git("remote", "set-head", "origin", "main", cwd=self.repo)
        git("remote", "set-url", "origin", "git@github.com:acme/widgets.git", cwd=self.repo)
        self.open_prs = []
        self.merged_prs = []  # (branch, oid, number)

    def worktree(self, branch):
        """Create a worktree on a new branch with two commits; return (path, c1, c2)."""
        path = os.path.join(self.root, "acme", "widgets", branch)
        git("worktree", "add", "-q", "-b", branch, path, "main", cwd=self.repo)
        git("commit", "--allow-empty", "-q", "-m", "c1", cwd=path)
        c1 = git("rev-parse", "HEAD", cwd=path)
        git("commit", "--allow-empty", "-q", "-m", "c2", cwd=path)
        c2 = git("rev-parse", "HEAD", cwd=path)
        return path, c1, c2

    def plain_worktree(self, branch):
        """A worktree at main with no commits of its own."""
        path = os.path.join(self.root, "acme", "widgets", branch)
        git("worktree", "add", "-q", "-b", branch, path, "main", cwd=self.repo)
        return path

    def hold_open(self, path):
        """Start a process whose cwd is `path`, like a live tmux pane."""
        proc = subprocess.Popen(["sleep", "60"], cwd=path)
        # Cleanups run last-registered first: kill, then wait.
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)

    def dry_run(self, days_old=0, **extra_env):
        with open(os.path.join(self.gh_dir, "open.txt"), "w") as f:
            f.write("".join(f"{b}\n" for b in self.open_prs))
        with open(os.path.join(self.gh_dir, "merged.txt"), "w") as f:
            f.write("".join(f"{b}\t{o}\t{n}\n" for b, o, n in self.merged_prs))
        env = {
            **os.environ,
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "WORKTREE_ROOT": self.root,
            "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
            "FAKE_GH_DIR": self.gh_dir,
            "WORKOUT_AUTOCLEAN_NOW": str(int(time.time()) + days_old * 86400),
            **extra_env,
        }
        result = subprocess.run(
            ["bash", SCRIPT, "--dry-run"], env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stderr

    def assertReaped(self, out, path, pr):
        self.assertIn(f"[dry-run] Would reap (reason: merged-pr, PR #{pr}", out)
        self.assertIn(path, out.split("[dry-run] Would reap", 1)[1])

    def assertReason(self, out, path, reason):
        lines = [ln for ln in out.splitlines() if ln.startswith("[dry-run]") and path in ln]
        self.assertEqual(len(lines), 1, out)
        self.assertIn(f"reason: {reason}", lines[0])

    def assertNotReaped(self, out, path):
        for line in out.splitlines():
            if line.startswith("[dry-run]"):
                self.assertNotIn(path, line)

    def test_merged_clean_head_equals_oid(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 7))
        self.assertReaped(self.dry_run(), path, 7)

    def test_head_ancestor_of_merged_oid(self):
        path, c1, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 8))
        git("reset", "-q", "--hard", c1, cwd=path)
        self.assertReaped(self.dry_run(), path, 8)

    def test_extra_commit_past_merged_oid_is_kept(self):
        path, c1, _ = self.worktree("feat-a")  # HEAD is c2, past c1
        self.merged_prs.append(("feat-a", c1, 9))
        out = self.dry_run()
        self.assertNotReaped(out, path)
        self.assertIn("commits not in the merged PR", out)

    def test_open_pr_on_same_branch_blocks_reap(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 10))
        self.open_prs.append("feat-a")
        out = self.dry_run()
        self.assertNotReaped(out, path)
        self.assertIn("open PR on branch feat-a", out)

    def test_dirty_worktree_is_kept(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 11))
        with open(os.path.join(path, "scratch.txt"), "w") as f:
            f.write("wip")
        self.assertNotReaped(self.dry_run(), path)

    def test_detached_head_is_kept(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 12))
        git("checkout", "-q", "--detach", cwd=path)
        self.assertNotReaped(self.dry_run(), path)

    def test_branch_without_merged_pr_is_kept(self):
        path, _, _ = self.worktree("feat-a")
        self.assertNotReaped(self.dry_run(), path)

    def test_gh_auth_failure_falls_back_to_age_only(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 13))
        out = self.dry_run(FAKE_GH_FAIL="1")
        self.assertIn("age-only", out)
        self.assertNotReaped(out, path)

    def test_gh_list_error_falls_back_to_age_only_for_that_repo(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 14))
        out = self.dry_run(FAKE_GH_FAIL_LIST="1")
        self.assertIn("age-only", out)
        self.assertNotReaped(out, path)

    def test_gh_stderr_text_is_in_fallback_line(self):
        self.worktree("feat-a")
        self.assertIn("gh: boom from gh", self.dry_run(FAKE_GH_FAIL="1"))
        self.assertIn("list blew up", self.dry_run(FAKE_GH_FAIL_LIST="1"))

    def test_merged_oid_missing_locally_is_kept_with_distinct_message(self):
        path, _, _ = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", "1" * 40, 15))
        out = self.dry_run()
        self.assertNotReaped(out, path)
        self.assertIn("merged PR commit not present locally", out)
        self.assertNotIn("commits not in the merged PR on branch", out)

    def test_non_github_origin_skips_merged_rule(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 16))
        git("remote", "set-url", "origin", os.path.join(self.tmp, "origin.git"), cwd=self.repo)
        out = self.dry_run()
        self.assertNotReaped(out, path)
        self.assertIn("not a GitHub remote", out)

    def test_in_use_worktree_is_kept_under_merged_rule(self):
        path, _, c2 = self.worktree("feat-a")
        self.merged_prs.append(("feat-a", c2, 17))
        self.hold_open(path)
        out = self.dry_run()
        self.assertNotReaped(out, path)
        self.assertIn(f"Skipping (in use by a running process): {path}", out)

    def test_in_use_worktree_is_kept_under_age_rule(self):
        path, _, _ = self.worktree("feat-a")
        os.makedirs(os.path.join(path, "sub"))
        self.hold_open(os.path.join(path, "sub"))  # cwd inside, not at, the root
        out = self.dry_run(days_old=31)
        self.assertNotReaped(out, path)
        self.assertIn("in use by a running process", out)

    def test_age_rule_reaps_old_worktree_without_pr(self):
        path, _, _ = self.worktree("feat-a")
        self.assertReason(self.dry_run(days_old=31), path, "age")
        self.assertNotReaped(self.dry_run(days_old=29), path)

    def test_no_commits_rule_after_seven_days(self):
        path = self.plain_worktree("empty-a")
        self.assertReason(self.dry_run(days_old=8), path, "no-commits")
        self.assertNotReaped(self.dry_run(days_old=6), path)

    def test_no_commits_rule_works_with_gh_down(self):
        path = self.plain_worktree("empty-a")
        out = self.dry_run(days_old=8, FAKE_GH_FAIL="1")
        self.assertReason(out, path, "no-commits")

    def test_no_commits_rule_keeps_worktree_with_local_commit(self):
        path, _, _ = self.worktree("feat-a")  # two commits beyond main
        self.assertNotReaped(self.dry_run(days_old=8), path)

    def test_no_commits_rule_needs_origin_head(self):
        path = self.plain_worktree("empty-a")
        git("remote", "set-head", "origin", "--delete", cwd=self.repo)
        self.assertNotReaped(self.dry_run(days_old=8), path)


if __name__ == "__main__":
    unittest.main()
