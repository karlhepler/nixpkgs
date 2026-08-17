---
name: workout
description: How to use the `workout` CLI for all git worktree work — creating, switching, listing, and cleaning up worktrees — including its layout, deletion behavior, and the per-repo post-switch bootstrap hook (what it actually does, and how to propose one when a repo is missing it). Use whenever worktree work comes up, before reaching for raw `git worktree` commands.
---

# workout

Triggered by the CLAUDE.md rule "Worktrees Go Through workout." This is the
reference for that rule — the full command surface, where worktrees live, how
deletion works, and the hook mechanism.

## 1. Repo-local override comes first

Check the target repo's own `CLAUDE.md` before doing anything. `~/.config/nixpkgs`
forbids worktrees outright (all work happens directly on `main`) — that file wins
there, and `workout` is not used in that repo at all. This skill applies everywhere
else.

## 2. Command surface

- `workout` or `workout /` — interactive fzf browser: `Enter` to switch,
  `Ctrl-D` to delete, `Esc` to cancel.
- `workout <branch>` — switch to a worktree for `<branch>`, creating it (and the
  branch, if it doesn't exist yet) if it doesn't already exist.
- `workout .` — create/switch to a worktree for the branch currently checked out
  in the primary repo, migrating any uncommitted changes along with it.
- `workout -` — toggle back to the previous location (primary repo or worktree).
- `workout clean` — remove worktrees whose branch has been merged into trunk.
- `workout clean --expunge` — remove every worktree, merged or not.

There is no `rm`, `list`, or `prune` subcommand — deletion only happens through the
browser's `Ctrl-D` or through `clean`.

## 3. Layout

Worktrees live under `${WORKTREE_ROOT:-$HOME/worktrees}/<org>/<repo>/<branch>`,
where `<org>/<repo>` comes from the origin remote. A branch name containing `/`
nests further directories accordingly.

## 4. Deletion goes to Trash, not `git worktree remove`

Both `Ctrl-D` and `clean` trash the worktree directory via the macOS-native Trash
(`pkgs.darwin.trash`) — visible in Finder, recoverable with Put Back — and then run
`git worktree prune` to clean up git's bookkeeping. Never call
`git worktree remove` directly; it bypasses the Trash and is not reversible.

## 5. The post-switch hook

A repo can define a one-time bootstrap hook that runs the first time a worktree is
created for it (not on later navigation to the same worktree):

- **Location**: `<main-repo>/.git/workout-hooks/post-switch` — resolve the main
  `.git` with `git rev-parse --path-format=absolute --git-common-dir` (this works
  correctly from inside a worktree too; a bare `git rev-parse --git-dir` does not).
- **Must be executable** (`chmod +x`) or it is silently skipped — no error either
  way.
- **Runs with no positional arguments.** Don't write a hook that reads `$1`/`$2` —
  that isn't part of this contract.
- **Gets three environment variables**, in addition to the inherited shell
  environment: `WORKTREE_PATH` (absolute path of the new worktree), `BRANCH`
  (branch checked out in it), `SOURCE_REPO` (absolute path of the primary repo).
  They're scoped to the hook's own process, not exported into your shell.
- **CWD is the new worktree** when the hook runs.
- **Exit code is not checked** — a failing hook does not warn and does not block
  the switch.
- It is stored under the *main* repo's `.git`, so it is shared across all
  worktrees of that repo — but it lives under `.git/`, so it is not git-tracked
  and does not travel with a fresh clone. Anyone who wants the same behavior has
  to hand-create it.

### Proposing a hook

When creating a worktree for a repo that has no `post-switch` hook (or a
non-executable one), check what the repo actually contains and propose a hook
based on it — don't write one unprompted:

- `mise.toml` present → `mise trust --yes` so later commands in the new worktree
  don't prompt.
- `pnpm-lock.yaml` / `package.json` with a `bootstrap` script → `pnpm install` or
  `pnpm bootstrap`, whichever the repo actually defines.
- `.envrc` present → `direnv allow`.
- A gitignored `.env` in the primary checkout → note that it will be absent in the
  new worktree (it isn't copied by `git worktree add`); flag this rather than
  silently leaving the worktree half-configured.

Suggest the contents, write the file only on approval, and `chmod +x` it —
otherwise it's dead weight that never runs.
