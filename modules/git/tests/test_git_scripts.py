"""Regression tests for the small git scripts (git-trunk, workout, workout-delete,
commit, pull, git-tmp, git-branches, git-kill).

Every test runs the real script in a throwaway repo under a temp dir; nothing
touches your repositories. Scripts that call `git trunk` get a shim on PATH.

Run: python3 -m unittest modules.git.tests.test_git_scripts
"""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GIT_DIR = os.path.normpath(os.path.join(HERE, ".."))


def script(name):
    return os.path.join(GIT_DIR, name)


def git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=check, capture_output=True, text=True,
    ).stdout.strip()


class RepoCase(unittest.TestCase):
    """A temp dir with a bare origin, a clone of it on `main`, and a PATH shim dir."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="git-scripts-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        # `git trunk ...` resolves to the real script
        self.shim("git-trunk", f'exec bash "{script("git-trunk.bash")}" "$@"')
        # workout-delete sleeps after errors so the fzf screen stays readable
        self.shim("sleep", "exit 0")

        self.origin = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "repo")
        git("init", "-q", "--bare", "-b", "main", self.origin, cwd=self.tmp)
        git("init", "-q", "-b", "main", self.repo, cwd=self.tmp)
        git("commit", "--allow-empty", "-q", "-m", "init", cwd=self.repo)
        git("remote", "add", "origin", self.origin, cwd=self.repo)
        git("push", "-q", "-u", "origin", "main", cwd=self.repo)
        git("remote", "set-head", "origin", "main", cwd=self.repo)

    def shim(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/usr/bin/env bash\n" + body + "\n")
        os.chmod(path, 0o755)

    def run_script(self, name, *args, cwd=None, env=None, strict=True):
        full_env = {
            **os.environ,
            "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "BRANCH_PREFIX": "me",
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.com",
            **(env or {}),
        }
        # Nix's writeShellApplication adds these; plain scripts don't carry them
        shell = ["bash", "-euo", "pipefail"] if strict else ["bash"]
        return subprocess.run(
            [*shell, script(name), *args],
            cwd=cwd or self.repo, env=full_env, capture_output=True, text=True,
        )


class GitTrunkPrintTest(RepoCase):
    def test_uses_origin_head(self):
        git("branch", "-m", "main", "trunkish", cwd=self.repo)
        git("push", "-q", "origin", "trunkish", cwd=self.repo)
        git("remote", "set-head", "origin", "trunkish", cwd=self.repo)
        r = self.run_script("git-trunk.bash", "--print")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "trunkish"), r.stderr)

    def test_falls_back_to_local_master_without_origin_head(self):
        git("remote", "remove", "origin", cwd=self.repo)
        git("branch", "-m", "main", "master", cwd=self.repo)
        r = self.run_script("git-trunk.bash", "--print")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "master"), r.stderr)

    def test_falls_back_to_develop(self):
        git("remote", "remove", "origin", cwd=self.repo)
        git("branch", "-m", "main", "develop", cwd=self.repo)
        r = self.run_script("git-trunk.bash", "--print")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "develop"), r.stderr)

    def test_fails_when_nothing_looks_like_trunk(self):
        git("remote", "remove", "origin", cwd=self.repo)
        git("branch", "-m", "main", "something-else", cwd=self.repo)
        r = self.run_script("git-trunk.bash", "--print")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


class WorkoutDeleteTest(RepoCase):
    def test_refuses_the_primary_checkout(self):
        r = self.run_script("workout-delete.bash", self.repo, "main", cwd=self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("primary checkout", r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.repo, ".git")))


class WorkoutTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.tmp, "worktrees")
        os.makedirs(self.root)
        git("remote", "set-url", "origin", "https://example.com/org/repo", cwd=self.repo)

    def workout(self, *args):
        return self.run_script("workout.bash", *args, env={"WORKTREE_ROOT": self.root})

    def test_branch_name_must_match_exactly(self):
        """`workout foo` must not jump to the worktree of `foo-bar`."""
        git("branch", "foo-bar", cwd=self.repo)
        bar_path = os.path.join(self.root, "org", "repo", "foo-bar")
        git("worktree", "add", "-q", bar_path, "foo-bar", cwd=self.repo)

        r = self.workout("foo")
        self.assertEqual(r.returncode, 0, r.stderr)
        foo_path = os.path.join(self.root, "org", "repo", "foo")
        self.assertEqual(r.stdout.splitlines()[0], f"cd {foo_path}")
        self.assertTrue(os.path.isdir(foo_path))

    def test_finds_an_existing_worktree_of_the_exact_branch(self):
        git("branch", "foo-bar", cwd=self.repo)
        bar_path = os.path.join(self.root, "org", "repo", "foo-bar")
        git("worktree", "add", "-q", bar_path, "foo-bar", cwd=self.repo)

        r = self.workout("foo-bar")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], f"cd {bar_path}")

    def test_remote_url_without_dot_git_still_gives_org_repo(self):
        r = self.workout("topic")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout.splitlines()[0],
            f"cd {os.path.join(self.root, 'org', 'repo', 'topic')}",
        )

    def test_scp_style_remote_with_dot_git(self):
        git("remote", "set-url", "origin", "git@example.com:org/repo.git", cwd=self.repo)
        r = self.workout("topic")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            r.stdout.splitlines()[0],
            f"cd {os.path.join(self.root, 'org', 'repo', 'topic')}",
        )

    def test_cd_output_is_quoted_for_awkward_paths(self):
        root = os.path.join(self.tmp, "it's here")
        os.makedirs(root)
        r = self.run_script("workout.bash", "topic", env={"WORKTREE_ROOT": root})
        self.assertEqual(r.returncode, 0, r.stderr)
        # The line must be safe to eval: round-trip it through bash
        line = r.stdout.splitlines()[0]
        out = subprocess.run(
            ["bash", "-c", f"{line}; pwd"], capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), os.path.join(root, "org", "repo", "topic"))

    def test_migration_failure_is_reported_and_exits_nonzero(self):
        """A failed `git worktree add` must surface, not print a cd to nowhere."""
        git("checkout", "-q", "-b", "feature", cwd=self.repo)
        # Occupy the target path with a non-empty directory so worktree add fails
        target = os.path.join(self.root, "org", "repo", "feature")
        os.makedirs(target)
        with open(os.path.join(target, "blocker"), "w") as f:
            f.write("x")
        r = self.workout("feature")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("cd ", r.stdout)
        self.assertIn("migration failed", r.stderr)


class CommitTest(RepoCase):
    def test_no_message_stages_nothing(self):
        with open(os.path.join(self.repo, "new.txt"), "w") as f:
            f.write("hi")
        r = self.run_script("commit.bash")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(git("status", "--porcelain", cwd=self.repo), "?? new.txt")

    def test_message_stages_and_commits(self):
        with open(os.path.join(self.repo, "new.txt"), "w") as f:
            f.write("hi")
        r = self.run_script("commit.bash", "add new")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git("log", "-1", "--format=%s", cwd=self.repo), "add new")


class PullTest(RepoCase):
    def test_sets_upstream_when_remote_branch_exists(self):
        git("checkout", "-q", "-b", "topic", cwd=self.repo)
        git("push", "-q", "origin", "topic", cwd=self.repo)
        git("branch", "--unset-upstream", cwd=self.repo, check=False)
        r = self.run_script("pull.bash")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=self.repo), "origin/topic"
        )

    def test_clear_error_when_remote_branch_is_missing(self):
        git("checkout", "-q", "-b", "unpublished", cwd=self.repo)
        r = self.run_script("pull.bash")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("origin has no branch", r.stderr)


class GitTmpTest(RepoCase):
    def test_works_twice_in_a_row(self):
        self.assertEqual(self.run_script("git-tmp.bash").returncode, 0)
        r = self.run_script("git-tmp.bash")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git("branch", "--show-current", cwd=self.repo), "me/tmp")


class GitBranchesTest(RepoCase):
    def setUp(self):
        super().setUp()
        git("branch", "me/a", cwd=self.repo)
        git("branch", "other/b", cwd=self.repo)

    def names(self, *args):
        r = self.run_script("git-branches.bash", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return set(r.stdout.split())

    def test_default_filter_is_the_username_prefix(self):
        self.assertEqual(self.names(), {"me/a"})

    def test_explicit_empty_argument_lists_every_local_branch(self):
        self.assertEqual(self.names(""), {"main", "me/a", "other/b"})


class GitKillTest(RepoCase):
    def test_keeps_untracked_envrc_and_removes_other_untracked_files(self):
        with open(os.path.join(self.repo, ".envrc"), "w") as f:
            f.write("export A=1\n")
        with open(os.path.join(self.repo, "junk.txt"), "w") as f:
            f.write("junk")
        r = self.run_script("git-kill.bash", "--auto-confirm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".envrc")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "junk.txt")))


if __name__ == "__main__":
    unittest.main()
