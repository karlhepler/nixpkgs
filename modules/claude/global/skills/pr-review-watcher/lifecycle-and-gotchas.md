# PR Review Watcher — Lifecycle, Dedup Philosophy, and Gotchas

Background for reasoning about lifecycle edge cases in the pr-review-watcher skill: why the dedup check runs twice, why the watcher cron is exempt from zero-crew self-termination, the two independent `--tell` truncation failure modes and the length threshold that forces `--tell-file` delivery, why worktree add/remove operations on the same repo must be serialized (and the add-then-remove pattern that implements it), why background-everything keeps cron ticks short, why `active` entries are marked `spawning` before the spawn call, the `/pr-review --restricted-output` phase/sentinel mapping, and the worktree cleanup obligations `crew dismiss` leaves behind. Read this file from `SKILL.md` (source: `modules/claude/global/skills/pr-review-watcher/lifecycle-and-gotchas.md`) when debugging one of these edge cases or extending this behavior — it is not needed to execute a normal cycle.

### Dedup Philosophy

**"Skip if anybody (an independent human, not the author, not a bot) has reviewed."**

Teammates often approve faster than we can spin up. Re-check reviewers in BOTH:
1. **Dedup step (§ C)** — before spawning.
2. **Inside the findings-first review brief** — right before `/pr-review` runs (human approvals frequently land during the bootstrap window).

This is what prevents wasted/duplicate reviews. The two-layer check is intentional — not redundant.

### Never Review Own PRs

If `author.login == github_login`, skip unconditionally. Record in `done` with `reason: "skipped-own-pr"`.

### Cron Exemption

The watcher cron MUST persist even when there are zero active reviews — it has to catch new posts. If a `pulse-cron-lifecycle` style hook tries to self-terminate "when zero crew windows remain," this watcher cron must be **exempt**. It is not a crew-monitoring pulse cron.

### Single-Line `--tell` and Length-Based Truncation

Inline `--tell` has TWO independent truncation failure modes — guard against both:

- **Newline-triggered:** newlines in `--tell` cause the shell to submit the command early — the brief is truncated mid-line. Compose briefs as a single line. No literal `\n` or multi-line heredoc.
- **Length-based truncation:** even a newline-free, single-line brief above ~800-1000 characters can be silently truncated on delivery — no special character required, raw length alone triggers it (observed: a ~1900-char single-line brief was cut mid-word around ~1KB, leaving the spawned session blocked on a malformed brief and costing a full cron cycle).

**Rule:** long briefs (above ~800-1000 chars (truncation observed near 1KB)) MUST be delivered via `crew create --tell-file <path>` — write the composed brief to a `.scratchpad/` file first, then pass the path. Reserve inline `--tell` for short briefs and short pointers only. Both spawned-session briefs in this skill (Findings-First Review, Follow-Up — see § The Two Briefs) exceed this threshold and are delivered via `--tell-file`.

### Stagger Parallel Spawns

Stagger ~6 seconds between parallel `crew create` calls to avoid git-worktree lock collisions when multiple PRs are picked up in the same cycle.

### Serialize Worktree ADD/REMOVE (review→follow-up transition)

**Never run `git worktree remove` on a repo while a `crew create` (git worktree add) on the SAME repo is in-flight.** Concurrent add/remove operations contend on the repo's `.git/worktrees` administrative lock, which can stall the `crew create` for minutes. Symptom: the spawn task is still running, fetches have printed, but no `<created ...>` line appears and `crew status` shows no new window — this looks like a hang but is lock contention, not a crash.

This is distinct from § Stagger Parallel Spawns above, which covers ADD/ADD collisions between two parallel `crew create` calls. This rule covers ADD/REMOVE: one `crew create` (add) racing a `git worktree remove` on the same repo.

Serialize one of two ways:
- **(a) Add-then-remove (preferred for the review→follow-up transition):** spawn `fu-<pr>` via `crew create`, WAIT for its `<created ...>` line (spawn-task completion) — this keeps a Staff window alive for pulse-cron stability, per § A) Monitor Active Reviews — THEN dismiss the review session and run `git worktree remove` on its worktree (see § Worktree Cruft for cleanup mechanics).
- **(b) Remove-then-add (fully serial):** remove the old worktree first, then spawn the new session.

For the review→follow-up transition specifically: spawning `fu-<pr>` before dismissing the review session is correct and must be preserved — but the review-worktree removal MUST wait until the fu spawn's `<created ...>` line is observed, never fired concurrently with it.

### Background Everything

All `crew create` calls use `run_in_background=true`. A blocking spawn can take minutes (pnpm bootstrap, large repo setup). Blocking the cron tick causes queued firings to pile up. Background everything — keep cron ticks short.

### Mark `spawning` Before Spawning

Add the entry to `active` with `status: "spawning"` and persist the state file BEFORE calling `crew create`. This prevents the next tick from double-spawning the same PR before the crew window appears.

### `/pr-review` Integration

The watcher always invokes `/pr-review <pr> --restricted-output` (§ Findings-First Review Brief). In `--restricted-output` mode, `/pr-review` runs its full internal specialist review (Phases 1–5 unchanged) and restricts the GitHub write at Phase 6 to exactly one outcome: a clean empty APPROVE posted silently (`prr` — detectable via `gh pr view --json reviews`), or nothing posted plus an `ESCALATE-<pr>: ...` line emitted back to the caller. `/pr-review` short-circuits its worktree-setup phase when already inside a worktree (the review brief's `gh pr checkout` sets this up). Crucially, `/pr-review` still writes its aggregated structured findings to `.scratchpad/review-<pr>.json` (and `.scratchpad/review-<pr>.md`) during Phase 5 even in restricted-output mode — so the spawned session can read that file and relay an enumerated candidate-comments list after the `ESCALATE-<pr>` line without any change to `/pr-review`. The sentinel strings the watcher reads via `crew read` are `REVIEW-POSTED-<pr>` (silent clean approve), `ESCALATE-<pr>: ...` (non-clean → hold alive + per-finding walkthrough), `SKIPPED-<pr>-already-reviewed`, and `SUPERSEDED-<pr>`.

### Worktree Cruft

`crew dismiss` kills the tmux window but does NOT remove the git worktree. Dismissed review/follow-up sessions leave orphaned worktrees (each a full bootstrapped checkout — real disk usage). The skill should:
1. Track spawned worktree names in the state file alongside each `active`/`followup` entry.
2. When dismissing a session, offer or perform cleanup: `git worktree remove <path>` (with `--force` if needed for dirty worktrees). Warn the user if cleanup is skipped.

**Re-spawning the same PR:** If you dismiss a review session and immediately re-spawn the same PR, `gh pr checkout <pr>` in the new session may fail with "already checked out in another worktree" — `crew dismiss` killed the tmux window but the git worktree still exists on disk. Before re-spawning, prune the prior worktree (`git worktree remove <path> --force` or `git worktree prune`). If pruning is not possible, the re-spawned session can still review via `gh pr diff <pr>` (diff fetched by number) without requiring a worktree-on-exact-branch.
