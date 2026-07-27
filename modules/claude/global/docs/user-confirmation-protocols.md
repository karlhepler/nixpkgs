# User Confirmation Protocols

When to stop and get the user's agreement before acting. Read it before starting work that touches 3+ files, makes an architectural decision, changes a database or API, or arrives as an ambiguous multi-step request.

**These protocols require an interactive user.** A background sub-agent runs in `dontAsk` mode and cannot prompt anyone, and it receives a pre-scoped delegation prompt rather than a raw request — so neither protocol below applies to one. They are for the tier that is talking to the user.

Source of truth is `modules/claude/global/docs/user-confirmation-protocols.md` in `~/.config/nixpkgs`. It deploys to `~/.claude/docs/user-confirmation-protocols.md` on `hms` — edit the source, never the deployed copy.

## Check-In Before Executing

**Required for:** 3+ files, architectural decisions, database/API changes.

```
Task: [What you're about to do]
Why: [Problem being solved]
Approach: [Your solution]
Changes: [Files affected]
Scope: This will ONLY change [X]. NOT [Y, Z].

Ready to proceed?
```

Wait for confirmation.

## Complex Requests

For multi-step/ambiguous requests, paraphrase understanding first.
Skip for simple commands ("Read file", "Run tests").
