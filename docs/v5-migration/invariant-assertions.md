# Stage 1 invariant tripwire — what it is and how to use it

**Written:** 2026-07-27, session `stout-ember`, kanban card #2979. **Companion to** `invariant-assertions.sh` in this directory.

## What this covers

`invariant-assertions.sh` runs 28 independent `rg -q` assertions against the two always-injected Tier-1 prompt files:

- `modules/claude/global/CLAUDE.md` (530 lines at the time this script was written)
- `CLAUDE.md`, project root (387 lines at the time this script was written)

Each assertion checks for one distinctive, load-bearing phrase drawn from a workflow invariant named in `docs/v5-migration/D-implementation-plan.md` § Stage 1 validation gate, item 3. That item enumerates exactly which invariants need mechanical assertions before Stage 1's edit units (1.4 and 1.5) relocate or trim content out of these two files. This script is the artifact item 3 describes: *"This list becomes a committed script in the Stage 1 unit so Stages 2–4 can re-run it unchanged."*

The 28 assertions, in the order they appear in the script:

1. Never-skip-hooks clause (enforcement sentence)
2. Human-delegated-bypass sentence
3. `perm purge` as user-only
4–7. The four ask-first operations, by name: `hms --purge`, `git reset --hard`, `git push --force`, `rm -rf`
8–11. The four enumerated worktree-confinement prohibited-target categories
12. The `--draft` PR-creation requirement
13–17. The five entries in the PR-description banned-phrasing list
18. The `karlhepler/` branch-name prefix requirement
19. GitHub Actions SHA-pinning requirement
20. `rg`-not-`grep` and `fd`-not-`find` (kept as one combined assertion — the plan's own gate item 3 lists this pair as a single bullet)
21. The ripgrep `-E` encoding-flag footnote (kept separate from #20 — see rationale below)
22. One-command-per-Bash-call
23. The nested-shell (`sh -c`) prohibition
24. The Homebrew prohibition
25. One-task-one-deliverable
26. The LLM-specific abstraction trap
27. The rule of three
28. The macOS Trash mechanism sentence (the only assertion targeting the project-root file — all others target the global file)

## Why 28 assertions rather than 18 or 19

The card's acceptance criterion required at least 18. Several of the plan's named invariants are themselves multi-part (four ask-first operations, four worktree categories, five banned-phrasing entries), and each part got its own assertion rather than one combined pattern, per this card's explicit instruction: *"Prefer separate assertions — they identify which invariant failed."* A combined alternation-based pattern that fails cannot tell a reader which sub-item is missing; 28 single-purpose assertions can.

## How to run it

```bash
bash docs/v5-migration/invariant-assertions.sh
```

Run from the repository root — the script uses relative paths (`modules/claude/global/CLAUDE.md` and `CLAUDE.md`) and assumes the current working directory is the repo root. No arguments, no environment variables, only a dependency on `rg` being on `PATH` (guaranteed in this Nix-managed environment).

Exit code 0 means every assertion passed. Exit code 1 means at least one failed; the script prints a `FAIL:` line naming the invariant and the exact pattern it searched for, plus a "Failed invariants:" list at the end, so no failure requires re-reading the whole script to diagnose.

## What a failure means

A failure means one specific, named invariant's most distinctive phrase is no longer present in the file it used to live in. There are exactly two honest readings of a failure, and this script cannot distinguish between them on its own — a human (or the coordinator) has to:

1. **The edit deleted or reworded the invariant.** This is the regression the script exists to catch. Stop, do not proceed to the next Stage 1 gate check, and restore the invariant (or its equivalent, if it was deliberately relocated to a destination file per unit 1.0's constraint — see D-implementation-plan.md § Unit 1.0's destination finding).
2. **The invariant moved to a different file than this script checks.** This script only asserts presence in the two Tier-1 files named above. If a later stage relocates content into a supporting file, a skill, or an agent definition, this script will not know to look there — it was written against Stage 1's specific scope (the two always-injected files) and is not a general corpus-wide invariant checker. A relocation that is correct per the plan's sub-agent-need test (D-implementation-plan.md § Unit 1.0) will still fail an assertion here if the relocated content was one of the 28 anchors — that failure is expected and should be reconciled by checking the destination file manually, not by weakening the assertion.

**Do not weaken a failing assertion to make it pass.** If an assertion fails, either the anchor was wrong (investigate and report why) or the invariant is genuinely gone from where the plan's protected-set accounting expected it (report this as a finding — it means Stage 1's units 1.4/1.5 would be working from a false map). Both are real findings. Silently loosening a pattern to get a green run defeats the purpose of a tripwire.

## Which invariants are hook- or CLI-enforced versus prompt-only

This matters because it determines the actual behavioral stakes of a given assertion failing. Cross-referenced against `docs/v5-migration/B-current-configuration.md` § Workflow Invariants To Preserve, which verified enforcement classifications directly against `modules/claude/default.nix`, `modules/kanban/kanban.py`, and the hook scripts:

| Assertion(s) | Invariant | Enforcement |
|---|---|---|
| 1, 2 | Never-skip-hooks + human-delegated-bypass | **Prompt only** for the decision protocol; the hook-skip *flags themselves* (`--no-verify`, etc.) are hook-enforced via `git-no-verify-hook.py` (WI-9). A rewording cannot disable the hook, but it can remove the coordinator's own commitment to never suggest a bypass. |
| 3 | `perm purge` user-only | **Prompt only.** No hook prevents an agent from invoking `perm purge`; the prohibition exists solely as text. |
| 4–7 | Ask-first operations | **Prompt only** (WI-18), except the hook-skip-flag subset already covered under WI-9. These are irreversible operations guarded entirely by text. |
| 8–11 | Worktree confinement | **Prompt only** (WI-12). No hook or CLI check found. |
| 12 | Draft-PR requirement | **Prompt only** (WI-9). A search of the hook scripts and `default.nix` for `draft` returns nothing. |
| 13–17 | PR-description banned phrasing | **Prompt only** (WI-9). No mechanical check exists for these five phrases. |
| 18 | `karlhepler/` branch prefix | **Prompt only** (WI-9). |
| 19 | GitHub Actions SHA-pinning | **Prompt only.** Enforced in CI by `pinact run --check`, but that is a separate CI gate, not something this repository's hooks verify locally. |
| 20, 21 | `rg`/`fd` discipline, `-E` footnote | **Prompt only** (WI-16, the `rg`/`fd` preference half — the `cd`-compound half of WI-16 is separately hook-enforced by `bash-cd-compound-hook`, which is unrelated to these two assertions). |
| 22 | One-command-per-Bash-call | **Prompt only** (WI-16). |
| 23 | `sh -c` prohibition | **Prompt only** (WI-16). |
| 24 | Homebrew prohibition | **Prompt only** (WI-17). The repository's cleanest single-source rule — restated in neither coordinator output style. |
| 25–27 | One-task-one-deliverable, abstraction trap, rule of three | **Prompt only.** No hook or CLI enforces scope discipline or DRY judgment. |
| 28 | macOS Trash mechanism | **Prompt only.** Nothing prevents `pkgs.trash-cli` from being added to a shellapp's `runtimeInputs` other than a reviewer (human or Claude) reading this sentence. |

**The pattern across all 28: every single one is prompt-only.** This is exactly why the card commissioning this script frames it as "the only mechanical thing standing between that edit and a silent, corpus-wide behavioral regression" — none of these 28 invariants has a hook or CLI backstop that would catch their loss any other way. If this script's assertions pass, that is currently the *only* evidence that these 28 specific rules survived an edit to the two Tier-1 files.

## Anchor design principles, for a future maintainer extending this script

Each assertion in the script carries an inline comment explaining why its specific anchor phrase was chosen over a more generic alternative. The general test applied throughout: *would this anchor still pass against a file where the invariant had been deleted but similar prose remained nearby?* If yes, a more specific anchor was chosen. Four of the twenty-eight are spot-checked in detail in the script's header comment block, reasoning about a plausible rewording for each. When adding a new assertion to this script for a future stage:

- Anchor on the most distinctive multi-word phrase, a specific flag name, or a specific command — never a generic word that could appear in unrelated nearby prose.
- Prefer one assertion per invariant over combining several into one alternation pattern (`\|` is a *literal* pipe in ripgrep's default engine, not alternation — this has already caused confusion once in this effort and is worth remembering).
- Never use `rg -E` (it means `--encoding`, not extended regex).
- Guard every pattern with `rg -q -- 'pattern'` so a future anchor that happens to start with a dash does not get misparsed as a flag.
- For literal strings containing regex metacharacters (parentheses, `+`, etc.), use `rg -qF` — but never put a backslash inside an `-F` pattern, and never substitute a `.` wildcard for an apostrophe in `-F` mode. Build apostrophes into single-quoted bash strings via concatenation (`'...'"'"'...'`) instead.
- Re-run the whole script after adding an assertion and confirm the new one fails when you temporarily delete the target line, then passes again once restored — an assertion never observed failing is not known to work.
