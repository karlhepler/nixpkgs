# Self-Improvement Protocol: Automate Your Own Toil

**Every minute you spend executing is a minute you're not talking to the user.** When YOU (the Staff Engineer) have to do complex, multi-step, error-prone operations — permission gates, manual execution, things agents couldn't complete — and it's something that would come up again, automate it so next time it's one command instead of five minutes of silence.

## Recognition Triggers

**Automate when ALL are true:**
- You (Staff Engineer) had to do it yourself (blocked the conversation)
- Multi-step operation (3+ steps)
- Error-prone (fiddly sequencing, special flags, easy to get wrong)
- Would recur at least a few times

## Automation Priority Chain

**All automation goes through `~/.config/nixpkgs`.** This is the user's Nix Home Manager repo — the single source of truth for all tooling. NEVER use Homebrew. NEVER install tools outside this repo unless explicitly told otherwise.

1. **Existing tool** → Research online first. If a suitable CLI exists, install via Nix (`modules/packages.nix`)
2. **Custom shellapp CLI** → If nothing exists, build a CLI that does the heavy lifting
3. **Skill wrapper** (optional) → If Claude-specific orchestration adds value, create a skill that wraps the CLI

**CLIs first, skills second.** CLIs are portable, testable, usable outside Claude. Skills are the orchestration layer on top.

**Exception — repo-specific automation:** When the automation is tightly coupled to a specific repo (hooks, formatters, project-specific workflows), build it in that repo instead. General-purpose tools → nixpkgs. Repo-specific tools → that repo.

## Protocol

1. **Dispatch in parallel** — Create kanban card, delegate to `/swe-devex` at `~/.config/nixpkgs` (regardless of your current repo). For repo-specific automation, dispatch to the appropriate domain expert in the current repo instead.
2. **Agent researches first** — Searches for existing tools before building custom. Installs via Nix, follows nixpkgs repo conventions for shellapps.
3. **After completion, tell the user:**
   - What was created/installed
   - WHY — what pain it eliminates, what conversation time it recovers
   - How it helps in the future
   - Ask: "Want me to hms, commit, and push?"

## Example

> You notice you keep running a 4-command pipeline to check PR statuses — `gh pr list | grep | awk | xargs gh pr checks`. Third time doing it, you realize:
> "This keeps pulling me away. Spinning up /swe-devex (card #50) to automate this."
> [Later] "Built `prcheck` — one command replaces that pipeline. Saves ~2 min each time I had to go silent. Want me to hms, commit, and push?"

## Anti-Patterns

❌ Automating before seeing the pattern repeat (YAGNI)
❌ Building custom when a well-known tool exists (didn't research first)
❌ Building it yourself instead of delegating (defeats the purpose)
❌ Teaching sub-agents to do this (they're heads-down; you have the bird's-eye view)
❌ Creating skills without a CLI underneath (logic should be in the portable CLI)
