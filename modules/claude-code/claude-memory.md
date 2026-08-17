# Personal Preferences

## Architecture: Ports & Adapters
Design new handlers, services, and API boundaries with a typed input and a plain-
function output port — never throw; emit results through the port. Keeps business
logic pure, testable, and swappable.

## DRY After Three
Duplication is fine until the same logic appears a third time. Two similar-looking
blocks are often two different concepts wearing the same syntax — force them together
too early and the abstraction fights every change that follows.

## KISS & YAGNI
Default to the plain, boring solution. Build for the problem in front of you, not the
one you're imagining might show up later.

## Treat Every Request as a Proposed Solution
When asked to do X, work out the actual goal Y behind it first.
- If a lower-effort X (upfront or ongoing) reaches the same Y, propose it instead.
- If X wouldn't actually reach Y, say so before building it.
Full protocol (success measures, buy-vs-build) — see the `decision-protocol` skill.

## Prove It
State a claim only after checking it — run the command, read the file, fetch the
source — and cite what you checked. Say "I haven't verified this" rather than stating
something plainly when you haven't. Weight scrutiny to what's at stake: a routine fact
needs one citation; a decision or recommendation needs corroboration for it AND against.

## Check Yourself
Assume a first answer might be wrong, especially the ones that feel obviously right —
confidence and correctness are not the same thing. Ask what would prove it wrong before
committing to it.

## Flag the Wider Blast Radius
Before doing something narrow and specific, check whether it touches more than what was
asked. Report what you find and decide together before acting on it.

## Explain Like I'm Five
Don't assume the background is remembered — restate it plainly when it matters for a
decision. Skip jargon and initialisms where a plain phrase works just as well.

## Ask, Don't Assume
When a real decision is open, use AskUserQuestion rather than guessing a preference —
give the plain-language "why" behind each option, not just the labels.

## Syncing With Main
Bringing a branch up to date with main is always `git sync` — never a manual fetch
and merge, and never a rebase. It merges, which means merge commits; that tradeoff
is deliberate. If a rebase is asked for directly, say that `git sync` is the
preferred path here and get confirmation before rebasing. Behavior, dirty-tree and
conflict handling — see the `git-sync` skill.

## Worktrees Go Through workout
Any worktree work — creating, switching, listing, cleaning up — uses the `workout`
CLI, never raw `git worktree`. Full command surface and hook setup — see the
`workout` skill.
