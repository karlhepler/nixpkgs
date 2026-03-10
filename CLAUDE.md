# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

Nix Home Manager configuration managing development environments with flakes. Creates reproducible system configurations (zsh, Neovim, terminal, git, dev tools).

**Required**: This repository must be installed at `~/.config/nixpkgs`.

## 🚨 NEVER HOMEBREW 🚨

**Read this before installing anything.**

This is a **Nix-managed system**. Homebrew is forbidden. No exceptions.

❌ Do NOT suggest `brew install` for ANYTHING
❌ Do NOT mention Homebrew as an option
❌ Do NOT say "you can also use Homebrew..."

✅ USE: Nix packages (`modules/packages.nix`)
✅ USE: Direct binary downloads (in `hms.bash`)
✅ USE: Language-specific managers (npm, pip in venvs)

**If you're about to type "brew" → STOP. Use Nix instead.**

## 🚨 SOURCE OF TRUTH PRINCIPLE 🚨

**CRITICAL: When working in this repository, NEVER edit files outside of this repository.**

This repository (`~/.config/nixpkgs`) is the **single source of truth** for system configuration. All work must be done here. The `hms` command deploys this configuration to your system.

### What This Means

**✅ CORRECT workflow:**
1. Edit files in `~/.config/nixpkgs/` (the source)
2. Add new files to git: `git add <file>`
3. Run `hms` to deploy changes
4. Nix automatically copies/symlinks files to correct locations

**❌ WRONG workflow:**
- ❌ Manually editing `~/.claude/commands/skill.md`
- ❌ Manually copying files to `~/.claude/`
- ❌ Directly modifying files in `~/.nix-profile/`
- ❌ Editing anything in user directories that hms manages

**Why:** Files outside this repo are **managed by Nix**. Manual edits will be:
- Overwritten on the next `hms` run
- Lost when switching generations
- Not version controlled
- Not reproducible

**Rule:** If you're working in `~/.config/nixpkgs`, assume **everything** outside this directory is read-only and managed by hms.

**Exception:** The only files you should edit outside this repo are:
- Active development code in OTHER repositories (not this one)
- Temporary scratch files in `/tmp/` or scratchpad

### Common Mistakes to Avoid

1. **Skill not deploying?** → Add to git, then run hms (don't copy manually)
2. **Command not available?** → Add shellapp to `default.nix`, run hms (don't create symlinks)
3. **Config not applying?** → Edit in source, run hms (don't edit deployed files)

**Remember:** This repository controls your computer. Work in the source, deploy with hms.

## Team Member Terminology

**Important:** When the user says "team member", "update a team member", "add a team member", or "remove a team member", they are referring to BOTH:

1. **The skill file:** `modules/claude/global/commands/<name>.md` - Contains the skill's system prompt, expertise, and workflows
2. **The agent definition:** `modules/claude/global/agents/<name>.md` - Custom sub-agent with the skill preloaded via `skills:` frontmatter

**Adding a team member** means:
- Create skill file in `commands/<name>.md` with skill prompt and expertise
- Create agent definition in `agents/<name>.md` with `skills: [<name>]` frontmatter
- Add to git: `git add modules/claude/global/{commands,agents}/<name>.md`
- Run `hms` to deploy both files to `~/.claude/`
- Update staff-engineer team table if needed

**Updating a team member** means:
- Edit both the skill file AND agent definition as needed
- Run `hms` to deploy changes

**Removing a team member** means:
- Delete both `commands/<name>.md` AND `agents/<name>.md`
- Run `hms` to remove from deployment
- Update staff-engineer team table

**Why both files:** Skills contain the detailed expertise and prompts. Agent definitions enable reliable skill injection (95%+ vs 70% reliability) by preloading the skill content into the sub-agent's context at startup.

### Exception Skills

Some skills intentionally lack agent definitions because they are exception or workflow skills that run differently:

- **Exception skills** (learn, workout-burns, workout-staff, project-planner) — Run via Skill tool directly, not delegated as background sub-agents. These are specialized capabilities invoked for specific use cases, not general-purpose team members.
- **Workflow skills** (manage-pr-comments, review-pr-comments) — Run via Skill tool with specific CLI tooling integration. These coordinate external processes and don't fit the standard team member pattern.
- **Multi-file skills** (review) — Live in `skills/<name>/SKILL.md` instead of `commands/<name>.md` because they have supporting files (e.g., `skills/review/review-citation-guide.md`, `skills/review/review-domains.md`). Deployed via `default.nix` skill copy rules, not the standard commands glob. No agent definition — invoked via Skill tool directly.

**Important:** The "Adding a team member" process (skill + agent) applies to standard delegatable team members only, not these exceptions. When updating or adding skills, distinguish between standard delegatable skills and exception/workflow skills.

## Quick Commands

### Configuration Management
- `hms`: Apply Home Manager changes (Claude Code must never use `--expunge` flag)
- `hme`: Edit the `home.nix` file (main configuration)
- `hmu`: Edit the `user.nix` file (user-specific identity)
- `hmo`: Edit the `overconfig.nix` file (machine-specific customizations)
- `hm`: Change directory to `~/.config/nixpkgs`

### Git Workflow
- `commit "message"`: Stage all changes and commit
- `push`: Push current branch to origin
- `pull`: Pull with automatic stash/unstash
- `save "message"`: Commit and push in one command
- `git trunk`: Switch to main/master branch (auto-detects)
- `git sync`: Merge trunk into current branch
- `git branches`: Interactive branch selector with fzf
- `git resume`: Switch to most recently used branch
- `git tmp`: Create temporary experimental branch
- `workout`: Interactive worktree browser and manager (default with no args)
- `workout <branch>`: Create/navigate to git worktree (organized in ~/worktrees/)
- `workout .`: Create worktree for current branch
- `workout -`: Toggle to previous worktree location
- `groot`: Navigate to git repository root

### Claude Code Helpers

> **These are shellapps defined in this repo.** To extend or modify them, edit their source in `modules/claude/` and run `hms`. Do NOT edit deployed copies directly.

- `q "question"`: Quick Claude question (haiku model - fastest)
- `qq "question"`: Claude question (sonnet model - balanced)
- `qqq "question"`: Complex Claude question (opus model - most capable)
- `burns "prompt"` or `burns file.md`: Run Ralph Orchestrator with Monty Burns coordinator hat (multi-hat YAML assembled at Nix build time) — source: `modules/claude/burns.py`
- `smithers` or `smithers <PR>`: Autonomous PR watcher (monitors checks, fixes issues, handles bot comments) — source: `modules/claude/smithers.py`
- `prc`: PR comment management tool (list, reply, resolve, collapse) — source: `modules/claude/prc.py`; see `/manage-pr-comments` skill for usage documentation

### Kanban CLI (Agent Coordination)

**Card Creation:**
- `kanban do '{"action":"...","intent":"..."}'`: Create card directly in doing (accepts single object or array)
- `kanban do --file .scratchpad/kanban-card-<session>.json`: Create card from file (for complex cards with quotes or multi-field JSON)
- `kanban todo '{"action":"...","intent":"..."}'`: Create card in todo (accepts single object or array)
- `kanban todo --file .scratchpad/kanban-card-<session>.json`: Create card in todo from file
- When full work queue is known, create ALL cards upfront (current batch in doing, rest in todo)

**Card Transitions:**
- `kanban start <card#> [card#...]`: Move card(s) from todo to doing
- `kanban review <card#>`: Move card to review column
- `kanban redo <card#>`: Move card from review back to doing
- `kanban defer <card#>`: Move card from doing/review to todo
- `kanban done <card#> 'summary'`: Complete card with summary
- `kanban cancel <card#>`: Cancel card

**Card Details:**
- `kanban show <card#> --output-style=xml`: Show full card details (XML format)
- `kanban status <card#>`: Print column name of card (lightweight check)
- `kanban comment <card#> "text"`: Add timestamped comment to card

**Acceptance Criteria (also aliased as `kanban ac`):**
- `kanban criteria add <card#> "text"`: Add acceptance criterion
- `kanban criteria remove <card#> <n> "reason"`: Remove criterion (with required reason)
- `kanban criteria check <card#> <n>`: Check off criterion
- `kanban criteria uncheck <card#> <n>`: Uncheck criterion

**Board View:**
- `kanban list --output-style=xml`: Board check (compact XML view for staff engineers)

**Session Management:**
- Session identity injected automatically via SessionStart hook (friendly names like `swift-falcon`)
- `--session <name>`: Pass session ID on commands (Claude does this automatically)
- `BURNS_SESSION=1`: Environment variable set by burns to suppress kanban session instructions (Burns uses Ralph's memory system instead of kanban)
- Session mappings stored in `.kanban/sessions.json`

### Kanban Command Reference

| Command | Purpose | Who Uses |
|---------|---------|----------|
| `kanban list --output-style=xml --session <id>` | Board check (compact XML) | Staff engineer |
| `kanban do '<json>' --session <id>` or `kanban do --file <path> --session <id>` | Create card(s) in doing | Staff engineer |
| `kanban todo '<json>' --session <id>` or `kanban todo --file <path> --session <id>` | Create card(s) in todo | Staff engineer |
| `kanban show <card>` | Read card details (action, intent, AC) | Sub-agents (own card), AC reviewer, staff engineer |
| `kanban status <card>` | Print column name of card (lightweight check) | Staff engineer, sub-agents |
| `kanban start <card> [cards...]` | Pick up from todo | Staff engineer |
| `kanban review <card> [cards...]` | Move to review column | Staff engineer |
| `kanban redo <card>` | Send back from review | Staff engineer |
| `kanban defer <card> [cards...]` | Park in todo | Staff engineer |
| `kanban criteria add <card> "text"` | Add AC (mid-flight OK) | Staff engineer |
| `kanban criteria remove <card> <n> "reason"` | Remove AC with reason | Staff engineer |
| `kanban criteria check <card> <n>` | Self-check AC (agent_met column) | Sub-agents (own card) |
| `kanban criteria uncheck <card> <n>` | Undo self-check | Sub-agents (own card) |
| `kanban criteria verify <card> <n>` | Verify AC (reviewer_met column) | AC reviewer |
| `kanban criteria unverify <card> <n>` | Undo verification | AC reviewer |
| `kanban comment <card> "text"` | Add timestamped comment | Sub-agents (own card), staff engineer |
| `kanban done <card> 'summary'` | Complete card (both columns enforced) | Staff engineer |
| `kanban cancel <card> [cards...]` | Cancel card(s) | Staff engineer |
| ~~`kanban clean`~~ | **PROHIBITED — never run** | Nobody |

**All commands accept `--session <id>` (required in multi-session contexts).**

## Critical Requirements

1. **🚨 NEVER HOMEBREW**: Do NOT suggest, recommend, or implement Homebrew. EVER. All packages MUST be managed through Nix (nixpkgs/nixpkgs-unstable) or direct binary downloads. See prohibition above.
2. **Repository Location**: MUST be installed at `~/.config/nixpkgs`
3. **Use hms Command**: Always use `hms` for syncing to ensure proper git handling
4. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety
5. **--expunge Flag**: Claude Code must NEVER use the `--expunge` flag with `hms`
6. **macOS ARM Only**: This configuration is locked to `aarch64-darwin` (Apple Silicon Macs)

## Configuration Structure

Domain-centric module architecture - related functionality co-located.

**Core files:** flake.nix (inputs/outputs), home.nix (entry point), user.nix (identity), overconfig.nix (machine-specific).

For detailed architecture, see README.md and source files in modules/.

## Development Workflows

**Add new package:**

🚨 **NEVER via Homebrew** - Use Nix or direct download ONLY

1. Add to `modules/packages.nix` under appropriate category
2. For LSP servers: Also update Neovim LSP config
3. Run `hms` to apply
4. Verify: `which <package-name>`

**Example (CORRECT):**
```nix
# modules/packages.nix
home.packages = with pkgs; [
  colima    # Docker runtime
  ripgrep   # Fast search
];
```

**Example (WRONG - NEVER DO THIS):**
```bash
brew install colima  # ❌ FORBIDDEN
```

**Add new shellapp:**
1. Create bash script in appropriate module directory (e.g., `modules/git/new-script.bash`)
2. Add shellapp definition to module's `_module.args.{domain}Shellapps` rec block
3. Add to git: `git add modules/git/new-script.bash`
4. Run `hms` to deploy
5. Command automatically available system-wide
6. Documentation auto-generated in `~/.claude/TOOLS.md`

**Add Claude Code skill:**
1. Create `modules/claude/global/commands/your-skill.md` with frontmatter
2. Add to git: `git add modules/claude/global/commands/your-skill.md`
3. Run `hms` to deploy
4. Skill automatically discovered in `~/.claude/commands/`

Note: If adding a team member skill (not a standalone workflow skill), also create an agent definition — see Team Member Terminology section above.

**Update Nix dependencies:**
1. `nix flake update` (updates flake.lock)
2. `hms` to apply
3. Test everything works
4. Commit flake.lock changes

## Scripting Principles

**Guaranteed Dependencies - No Fallbacks Needed:**

This is a Nix Home Manager environment. All dependencies are declaratively managed and guaranteed to be available at runtime. **NEVER write fallback logic in scripts.**

**❌ WRONG (defensive fallbacks):**
```bash
# Don't do this!
if command -v bat >/dev/null 2>&1; then
    bat file.txt
elif command -v less >/dev/null 2>&1; then
    less file.txt
else
    cat file.txt
fi
```

**✅ CORRECT (assume dependencies exist):**
```bash
# Just use it - Nix guarantees it's available
bat file.txt
```

**Why:**
- Dependencies are declared in `modules/packages.nix` or module-specific Nix files
- Nix ensures they're built and available before your script runs
- Fallback chains add complexity and can hide missing dependency declarations
- If a dependency is missing, the script SHOULD fail loudly (indicates Nix config needs updating)

**This applies to code review too.** Do not flag missing dependency handling (e.g., `FileNotFoundError` for a CLI, `command -v` checks) as a deficiency when the dependency is Nix-guaranteed via `runtimeInputs`, `wrapProgram`, or `modules/packages.nix`. Defensive checks for Nix-managed binaries are an anti-pattern, not a best practice.

**When adding external dependencies to scripts:**

**For shellapps (preferred):**
Declare dependencies directly in the script's Nix definition using `runtimeInputs`:

```nix
myScript = pkgs.writeShellApplication {
  name = "my-command";
  runtimeInputs = [ pkgs.bat pkgs.jq pkgs.fd ];  # Script-specific dependencies
  text = ''
    # These commands are guaranteed to exist - no fallbacks needed
    bat file.txt
    echo '{"key":"value"}' | jq .
    fd pattern
  '';
};
```

**For Python scripts:**
```nix
myPythonScript = pkgs.writers.writePython3Bin "my-script" {
  libraries = [ pkgs.python3Packages.requests pkgs.python3Packages.jinja2 ];
} ''
  import requests  # Guaranteed to exist
  import jinja2    # No try/except needed
'';
```

**For system-wide tools:**
Add to `modules/packages.nix` only when the tool should be available globally (not script-specific):
```nix
home.packages = with pkgs; [
  bat  # Available system-wide in all shells
  fd
  ripgrep
];
```

**The principle:**
- **Script-specific dependencies** → `runtimeInputs` in the script's Nix definition
- **System-wide tools** → `modules/packages.nix`
- **Never write fallbacks** → Nix guarantees availability

**Examples:**
- Shellapp needs bat → Add to `runtimeInputs`, use `bat` directly
- Python script needs requests → Add to `libraries`, `import requests` directly
- System needs global jq → Add to `modules/packages.nix`

**The only exception:** Checking for optional user configuration (e.g., checking if `~/.gitconfig` exists) is fine. But system commands should never have fallbacks.

## File Management

**user.nix:**
- Edit with `hmu`
- Contains: name, email, username, homeDirectory
- Auto-backed up to `~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix`
- Local git config for this repo uses these values

**overconfig.nix:**
- Edit with `hmo`
- Machine-specific customizations and secrets
- Auto-backed up to `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`
- Example: `programs.git.settings.user.email = lib.mkForce "work@email.com";`

Both files made git-invisible by `hms` after first run. Backups linked via `*.latest.nix` symlinks.

## Claude Code Integration

**Configuration deployment:**
- Global settings: `modules/claude/global/CLAUDE.md` → `~/.claude/CLAUDE.md`
- Skills: `modules/claude/global/commands/*.md` → `~/.claude/commands/`
- Hooks: notification-hook, complete-hook, csharp-format-hook (configured in `modules/claude/default.nix`)
- Commands: `~/.claude/TOOLS.md` auto-generated from shellapp metadata

**MCP integration:**
- Context7 MCP auto-configured if `CONTEXT7_API_KEY` set in overconfig.nix
- Config merged into `~/.claude.json` (preserves Claude's metadata)
- To disable: Remove `CONTEXT7_API_KEY`, run `hms`

**Analytics Dashboard (claudit):**
- Grafana-based dashboard for Claude Code usage analytics (user nickname: "claudit")
- Dashboard definition: `modules/grafana/dashboard.json`
- Metrics collection: `modules/claude/claude-metrics-hook.py` (captures metrics via Claude Code metrics hook)
- Displays: Total cost (today/all-time), token breakdown (input/output/cache), cost by kanban session, turn statistics by agent type, tool usage heat map (by tool and agent)
- Access via Grafana interface (configured in Home Manager)

## Burns and Ralph Architecture

**Build-time Assembly:**
Burns uses a multi-hat YAML configuration assembled at Nix build time. The Ralph orchestrator invokes a composite YAML formed from:
- `modules/claude/global/hats/wrapper.yml.tmpl` - Ralph event-loop wrapper
- `modules/claude/global/hats/monty-burns.yml.tmpl` - Monty Burns coordinator hat
- 8 specialist skill hats (swe-backend, swe-frontend, swe-fullstack, swe-infra, swe-devex, swe-sre, swe-security, researcher)

The assembled YAML path is substituted at build time in `modules/claude/default.nix`.

**Tiered Review Protocol:**
The mandatory review protocol that determines when work requires review is defined in `modules/claude/global/hats/monty-burns.yml.tmpl` (lines 86-114, "On work.done" section). Three tiers: Tier 1 (mandatory: auth/authz, financial, infra, PII DB, CI/CD), Tier 2 (high-risk: API endpoints, third-party, performance, migrations, deps, shell scripts), Tier 3 (recommended: UI, monitoring, large refactors). The protocol activates when a specialist emits 'work.done' event.

**Ralph vs. Kanban:**
Ralph is a self-contained event-loop orchestrator with its own memory system. Kanban is the human-facing coordination layer for staff engineers. These systems are separate. When burns runs, it sets `BURNS_SESSION=1` to suppress kanban session instructions — injecting kanban context would confuse the model. Ralph uses its internal memory system (`ralph tools memory`) instead of kanban cards.

**Available skills:**
- Engineering: swe-backend, swe-frontend, swe-fullstack, swe-devex, swe-infra, swe-security, swe-sre
- Design: ux-designer, visual-designer
- Support: researcher, scribe, ai-expert, ac-reviewer, debugger, learn
- Workflow: review-pr-comments, manage-pr-comments
- Business: finance, lawyer, marketing
- Special: workout-burns, workout-staff, project-planner

## Your Team

| Skill | What They Do | When to Use |
|-------|--------------|-------------|
| `/ac-reviewer` | AC verification (Haiku) | AUTOMATIC after every card review |
| `/researcher` | Multi-source investigation | Research, verify, fact-check |
| `/scribe` | Documentation | Docs, README, API docs, guides |
| `/ux-designer` | User experience | UI design, UX research, wireframes |
| `/project-planner` | Project planning | Multi-week efforts (exception skill) |
| `/visual-designer` | Visual design | Branding, graphics, design system |
| `/swe-frontend` | React/Next.js UI | Components, CSS, accessibility |
| `/swe-backend` | Server-side | APIs, databases, microservices |
| `/swe-fullstack` | End-to-end features | Full-stack, rapid prototyping |
| `/swe-sre` | Reliability | SLIs/SLOs, monitoring, incidents |
| `/swe-infra` | Cloud infrastructure | K8s, Terraform, IaC |
| `/swe-devex` | Developer productivity | CI/CD, build systems, testing |
| `/swe-security` | Security assessment | Vulnerabilities, threat models |
| `/ai-expert` | AI/ML and prompts | Prompt engineering, Claude optimization |
| `/debugger` | Systematic debugging | Complex bugs resisting 2-3 rounds of normal fixes (escalation only) |
| `/lawyer` | Legal documents | Contracts, privacy, ToS, GDPR |
| `/marketing` | Go-to-market | GTM, positioning, SEO |
| `/finance` | Financial analysis | Unit economics, pricing, burn rate |
| `/workout-staff` | Git worktree | Parallel branches (exception skill) |
| `/workout-burns` | Worktree with burns | Parallel dev with Ralph (exception skill) |
| `/review` | Full PR code review | Orchestrate specialist review of an **existing PR** — ONLY when user explicitly references a PR: "review PR #N", "code review PR #N", "review pull request". NOT triggered by user confirming Mandatory Review Protocol recommendations. |
| `/manage-pr-comments` | PR comment management via `prc` | List, filter, resolve, collapse comment threads |
| `smithers` (CLI) | Autonomous PR watcher (user-run, not invocable via Task/Skill) | See smithers note in staff-engineer output style |
| `/review-pr-comments` | Respond to reviewer feedback | Reply to reviewer comments on a PR you submitted — NOT for performing a code review |

## Reference Documentation

**User setup:** See README.md for installation and daily usage procedures.

**Command reference:** See `~/.claude/TOOLS.md` (auto-generated from shellapp metadata on `hms`).

**Nix development:**
- `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`: Get hash for GitHub packages
- `nix flake update`: Update dependencies
- `nix flake check`: Validate syntax
- `nix flake metadata`: Show flake info
- `nix search nixpkgs <package>`: Search packages

**Implementation details:** See source files in `modules/` directories for specific configurations (theme, LSP, activation hooks, etc).

**Permission system research:** See `modules/claude/perm-research.md` for empirical findings on how Claude Code permission settings files merge, how the `perm` CLI works, and why background sub-agent kanban permission gates fire (or don't).

**perm CLI mechanics (authoritative summary):**
- `perm allow <pattern> --session <id>` and `perm always <pattern> --session <id>` both write the permission pattern to `.claude/settings.local.json` — that file never contains a session ID.
- `--session` is an ownership key recorded only in `.claude/.perm-tracking.json`.
- The sole difference between `allow` and `always` is in `.perm-tracking.json`: `allow` creates a temporary, session-scoped claim (removable via cleanup); `always` creates a permanent entry that survives cleanup.
- Rule of thumb: `settings.local.json` = what is permitted; `.perm-tracking.json` = who owns it and for how long.

## External References

Supporting documentation for the staff engineer output style:

- [anti-patterns.md](modules/claude/global/docs/staff-engineer/anti-patterns.md) - Common coordination failure modes with concrete examples
- [delegation-guide.md](modules/claude/global/docs/staff-engineer/delegation-guide.md) - Permission handling, model selection patterns
- [parallel-patterns.md](modules/claude/global/docs/staff-engineer/parallel-patterns.md) - Parallel execution examples
- [edge-cases.md](modules/claude/global/docs/staff-engineer/edge-cases.md) - Interruptions, partial completion, review disagreements
- [review-protocol.md](modules/claude/global/docs/staff-engineer/review-protocol.md) - Mandatory reviews, approval criteria, conflict resolution
- [self-improvement.md](modules/claude/global/docs/staff-engineer/self-improvement.md) - Automate your own toil
