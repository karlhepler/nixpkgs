---
name: git-sync
description: How and when to use the `git sync` CLI to bring a branch up to date with main — what it actually does (fetch + merge, never rebase), how to handle a dirty tree or a merge conflict, and how to respond when a rebase is asked for directly. Use whenever a branch needs to catch up with main or another trunk branch.
---

# git sync

Triggered by the CLAUDE.md rule "Syncing With Main." This is the reference for that
rule — what the command does, what it doesn't, and how to handle the cases it doesn't
cover itself.

## 1. What it actually does

`git sync` is this, in full (`modules/git/git-sync.bash` in the nixpkgs repo):

```bash
git remote set-head origin -a
trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
git fetch origin "$trunk"
git merge "origin/$trunk"
```

It re-resolves `origin/HEAD` (so it works whether trunk is `main`, `master`, or
anything else), fetches it, and merges it into whatever branch you're currently on.
You stay on your branch. No arguments beyond `-h`/`--help` are accepted.

## 2. What it deliberately does not do

- **No push.** It only updates your local branch; publishing it is a separate step.
- **No branch switch.** It never checks out trunk — that's `git trunk`'s job.
- **No local main update.** Only the remote-tracking ref (`origin/$trunk`) is
  refreshed; your local `main`/`master` branch, if you have one checked out
  elsewhere, is untouched.
- **No stash.** A dirty working tree is not handled — see below.
- **No conflict resolution.** A conflicting merge leaves you mid-merge — see below.

## 3. It merges — that's the point, not a gap

`git merge origin/$trunk` produces a merge commit (or fast-forwards when possible).
This is intentional, not a limitation to work around. Don't rebase in its place
just because rebasing would give linear history — that's a different tradeoff the
rule has already decided against.

## 4. Someone asks for a rebase directly

Per the CLAUDE.md rule: name `git sync` as the preferred path first, state the
tradeoff in one line (merge commits vs. linear history), and wait for confirmation
before rebasing. This applies equally to a direct "rebase onto main" request and to
invoking a rebase-branch skill/command — the rule governs the default, not a direct
instruction, but it still gets a chance to be heard before being overridden.

## 5. Dirty working tree

`git sync` has no stash step, so a dirty tree makes the `git merge` inside it fail
with git's own "please commit your changes or stash them" error. Handle it before
running `git sync`: commit the work if it's ready, or `git stash` it if not — then
run `git sync`, then `git stash pop` if you stashed.

## 6. Merge conflict

If the merge conflicts, you're left mid-merge with conflict markers in the affected
files and a nonzero exit. Resolve the conflicts, `git add` the resolved files, and
`git commit` to complete the merge. Do not `git merge --abort` and reach for a
rebase instead — that reintroduces the choice the rule already made in step 3.
