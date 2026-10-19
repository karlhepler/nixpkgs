# HMS — Home Manager Switch: Reference

`hms` is the single deployment command for this configuration. This document is the
semantic model of what it does, read from `modules/system/hms.bash` and
`modules/system/default.nix`. It deliberately cites steps by name, not line number, so
it does not drift when the script is edited.

## What it does, in one paragraph

`hms` refuses to run as root; validates that `user.nix` exists and has no placeholder
values; backs up `user.nix` and `overconfig.nix` with a timestamp; checks the source for
non-macOS trash tools (`check-darwin-trash.bash`); temporarily un-hides
those two files from git so Home Manager can read them; runs
`home-manager switch --flake ~/.config/nixpkgs`; installs Claude Code if it is enabled
and absent; and sets the repository's local git identity. On every exit, success or
failure, it re-hides `user.nix` and `overconfig.nix` from git. With `--purge` it then
also kills the tmux server.

## How the command is built

`hms` is a Nix `writeShellApplication` assembled in `modules/system/default.nix`, not a
loose script on `PATH`. The wrapper:

- exports `USER_NAME` and `USER_EMAIL` from `user.nix`, and `CLAUDE_CODE_ENABLED`
  (`1`/`0`) from `claudeCode.enable` in `flags.nix`, then runs the `hms.bash` body;
- puts `git`, `curl`, `ripgrep` and the flake's own `home-manager` package on `PATH` (`hmPackage`, passed
  from `flake.nix`), so the CLI always matches the home-manager modules the flake
  builds with.

## Flags

| Flag | Effect |
|---|---|
| *(none)* | Full deployment, as described above. |
| `--purge`, `--expunge` | Same, plus `tmux kill-server` on exit. See below. |
| `-h`, `--help` | Print usage and exit. No side effects. |

Unknown flags are silently ignored.

### `--purge` (alias `--expunge`)

The flag sets `PURGE=true`. The single `EXIT` trap (`cleanup`) then runs
`tmux kill-server` **unconditionally on exit** — whether the script finished, aborted on
validation, failed in `home-manager switch`, or was interrupted. It closes every tmux
session and window; there is no selective targeting.

It does **not** purge Home Manager generations, delete store paths, remove backups, or
touch any file in `~/.config/nixpkgs`. It is `hms` followed by `tmux kill-server`.

Use it when tmux config, plugins or keybindings change and you want a clean server
rather than one re-reading config. **Claude Code must never run it**: it would kill the
tmux session Claude Code is running in. Only the user may run it, typed themselves.

## Execution sequence

1. **Shell options** — `set -eou pipefail`: any failing step aborts the script (the
   exit trap still runs).
2. **Root check** — exits if run as root (`$EUID`/`$USER`). Runs first, before anything
   is changed.
3. **Argument parsing** — sets `PURGE`; handles `--help`.
4. **Exit trap** — registers `cleanup`, which re-hides `user.nix`/`overconfig.nix`
   (`git update-index --skip-worktree`) and, with `--purge`, kills tmux.
5. **Validate `user.nix`** — must exist and must not contain `= "CHANGE_ME"`. (The Nix
   assertion in `home.nix` additionally rejects empty fields and `CHANGE_ME` inside
   `homeDirectory`; both must pass.)
6. **Backup** — copies both files to `~/.backup/.config/nixpkgs/` as
   `user.YYYYMMDD-HHMMSS.nix` / `overconfig.YYYYMMDD-HHMMSS.nix` and updates the
   `user.latest.nix` / `overconfig.latest.nix` symlinks.
7. **Trash-tool check** — runs `modules/system/check-darwin-trash.bash`, which fails the
   run if config source references `trash-cli` or any freedesktop trash path (see
   `CLAUDE.md` § macOS Trash CLI). It is also a `nix flake check`.
8. **Un-hide from git** — `git update-index --no-skip-worktree user.nix overconfig.nix`.
   Flakes only see git-visible content, so without this the committed blank template
   would be deployed. (`--no-assume-unchanged` would *not* clear the bit; it must be
   `--no-skip-worktree`.)
9. **`home-manager switch --flake ~/.config/nixpkgs`** — evaluates the flake, builds,
   activates a new generation, and runs the activation hooks (including the ones in
   `home.nix` that re-hide the two files). This is a real build, so errors that
   `nix flake check` never reaches (bad packages, failing shellapp builds, activation
   conflicts) surface here.
10. **Claude Code install** — if `CLAUDE_CODE_ENABLED=1` and `claude` is not on `PATH`,
   runs the official installer. No version pinning; Claude Code self-updates.
11. **Local git identity** — sets `user.name`/`user.email` for this repo from
    `user.nix` (silent, idempotent).
12. **Exit trap runs** — files re-hidden; tmux killed if `--purge`.

If step 8 fails, the previous generation stays active; nothing needs rolling back.

## Git-invisible `user.nix` and `overconfig.nix`

Both hold personal identity and machine-specific secrets, so they must exist for Nix
to evaluate the flake but must never be committed. They are marked
`--skip-worktree`, which makes git ignore local changes to them in `status`, `add .`
and friends. That mark is applied by the `home.nix` activation hooks and by `hms`'s
exit trap, and removed by `hms` just for the build.

**Never `git add user.nix` or `git add overconfig.nix`.**

## Backups

`~/.backup/.config/nixpkgs/` gets a timestamped copy of both files on every `hms` run,
plus `user.latest.nix` / `overconfig.latest.nix` symlinks. Nothing prunes them. To
restore:

```bash
cp ~/.backup/.config/nixpkgs/user.latest.nix ~/.config/nixpkgs/user.nix
ls -lt ~/.backup/.config/nixpkgs/        # pick a specific snapshot
```

Syncing `~/.backup` to cloud storage is the user's job.

## Sibling aliases: `hme`, `hmu`, `hmo`, `hm`

zsh aliases from `modules/zsh.nix` (`shellAliases`), not standalone commands — `which hme`
will not find them, and they exist only in interactive zsh.

| Alias | Does |
|---|---|
| `hme` | `vim ~/.config/nixpkgs/home.nix` |
| `hmu` | `vim ~/.config/nixpkgs/user.nix` |
| `hmo` | `vim ~/.config/nixpkgs/overconfig.nix` |
| `hm`  | `cd ~/.config/nixpkgs` |

Editing changes nothing until `hms` runs. A malformed `user.nix`/`overconfig.nix` fails
evaluation and aborts before anything is applied.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: hms should not be run as root` | Ran as root | Run as your normal user |
| `ERROR: user.nix not found!` | Fresh clone, or deleted | Create it from the template, or restore from backup |
| `ERROR: user.nix contains CHANGE_ME placeholder values` | Template not filled in | `hmu`, set every field |
| Assertion about placeholder values during switch | Empty field or `CHANGE_ME` in a value | Fix via `hmu` |
| Eval error / hash mismatch / network failure | Nix syntax, bad pin, transient network | Fix the file or retry; the old generation stays active |
| `Existing file '…' would be clobbered` | A hand-written file sits where Home Manager wants to link one | Move it aside (copy to `~/.backup` first), re-run `hms` |
| All tmux sessions gone | You ran `hms --purge` | Designed. Open a new terminal (zsh starts tmux); `tmux-restore` to pick a resurrect snapshot |

## Generations and the deployed environment

Each successful switch makes a generation (`home-manager generations`). Rolling back
re-activates an earlier generation's scripts; it does **not** restore `user.nix` or
`overconfig.nix` (restore those from `~/.backup`).

A running shell does not pick up a new `hms` automatically — open a new shell, or
re-source `~/.nix-profile/etc/profile.d/hm-session-vars.sh` after unsetting
`__HM_SESS_VARS_SOURCED`.

`home.nix` enables `nix.gc.automatic` (weekly, deleting generations older than 30 days),
which frees unreachable store paths.

## What Claude Code must never do

1. Never run `hms --purge` or `hms --expunge` — kills every tmux session, including its own.
2. Never run `hme`, `hmu`, `hmo` or `hm` — they open interactive vim; use Read/Edit/Write.
3. Never `git add user.nix` or `git add overconfig.nix` — they contain secrets.
4. Never edit files outside `~/.config/nixpkgs/` — Nix manages them and overwrites edits.
