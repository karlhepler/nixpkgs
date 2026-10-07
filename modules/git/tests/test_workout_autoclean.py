"""Tests for the merged-PR reap rule in workout-autoclean.bash.

Runs the real script with --dry-run only (nothing is ever trashed) against
throwaway git repos, with a fake `gh` first on PATH. Worktrees are brand new,
so the 30-day age rule never fires and only the merged-PR rule is exercised.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "workout-autoclean.bash")

FAKE_GH = """#!/usr/bin/env bash
[[ "${FAKE_GH_FAIL:-}" == 1 ]] && exit 1
if [[ "$1 $2" == "auth status" ]]; then exit 0; fi
if [[ "$1 $2" == "pr list" ]]; then
  [[ "${FAKE_GH_FAIL_LIST:-}" == 1 ]] && exit 1
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

        git("init", "-q", "-b", "main", self.repo, cwd=self.tmp)
        git("remote", "add", "origin", "git@github.com:acme/widgets.git", cwd=self.repo)
        git("commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo)
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

    def dry_run(self, **extra_env):
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


if __name__ == "__main__":
    unittest.main()
