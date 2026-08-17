---
name: decision-protocol
description: Full XY-problem worksheet for evaluating a proposed solution before building it — establishing the real goal, checking whether the proposed approach actually reaches it, weighing alternatives (including buying instead of building), and setting a measurable, corroborated success bar. Use whenever a request looks like a specific technical ask (X) rather than a stated goal, before committing meaningful effort to it.
---

# Decision Protocol

Triggered by the CLAUDE.md rule "treat every request as a proposed solution." This is
the worksheet for that trigger — run it before committing real effort, not on every
one-line request.

## 1. Separate X from Y

X is the specific thing asked for. Y is the actual goal behind it. State both
explicitly, even when they look identical — that's the check that catches when they
aren't.

## 2. Does X actually reach Y?

Don't assume yes because it was proposed. Ask what would have to be true for X to reach
Y, and check those things. If X wouldn't get to Y, or only partly would, say so before
building — a working X that misses Y is wasted effort dressed up as progress.

## 3. Look for a cheaper X — buy before build

Before designing a custom X, search for whether the goal Y is already solved by
something maintained by someone else — a library, a tool, a service. Prefer that over
building, unless there's a stated reason it doesn't fit (licensing, missing a specific
capability, too heavy for the need). This costs research time up front; it saves both
the initial build and all the maintenance that follows. Report 1-2 candidates found (or
that none exist) before proposing a custom build.

## 4. Give Y a measure — before starting, not after

Every Y needs, decided in advance:
- **The measure** — the specific number or signal that tells you Y improved.
- **Where the data comes from** — the exact command, dashboard, or log that produces it.
  If you can't say where the data will come from, the measure isn't real yet.
- **A baseline** — the measure's current value, captured before X starts.
- **A hypothesized target** — what X is expected to move the measure to.

Be suspicious of the measure itself, not just of hitting it: a measure that's easy to
grab is not automatically the right one. Ask "does this number actually move when Y
gets better, or does it just correlate with things that also happen to make Y better?"
Prefer the simplest measure that passes that test — an elaborate composite score is
harder to trust and harder to recheck later.

## 5. Corroborate before recommending

For the recommendation itself (not every supporting fact along the way): find 2-3
independent sources that support it and 2-3 that argue against it or for an
alternative. State which way the evidence leans and how confident that leaves you.
"I found one blog post that agrees" is not corroboration.

## 6. Report back

Present X, Y, the alternatives considered, the measure/baseline/target, and the
corroboration — then let the decision be made together, not unilaterally.
