# Coordination Reference — Terminology, Roster, And Staff-Engineer Docs Index

Lookup material, not procedure. Read it when you need to know what a term means, who can be delegated to, or which staff-engineer companion doc covers the topic you are stuck on; nothing here changes how you do your own work.

Source of truth is `modules/claude/global/docs/coordination-reference.md` in `~/.config/nixpkgs`. It deploys to `~/.claude/docs/coordination-reference.md` on `hms` — edit the source, never the deployed copy.

## Glossary

**Agent:** A Claude Code instance executing work (the AI itself)

**Sub-agent:** A background agent spawned via Task tool to handle delegated work

**Skill:** A specialized capability invoked via Skill tool. Exception/workflow skills live at `skills/<name>/SKILL.md`; slash-commands live at `~/.claude/commands/`.

**Session ID:** Friendly name identifier for Claude session (e.g., `clear-vale`, `swift-falcon`, `smart-bell`). Automatically injected at startup via the SessionStart hook. Used by coordinator-tier tools (kanban, perm) as an ownership key to scope session state.

**Open:** When the user says "open X", Claude runs the macOS `open` command via Bash (e.g., `open file.txt`, `open https://example.com`). "Open" means launch/display, not read or process in Claude.

## Team Member Terminology

For the taxonomy — what a delegatable team member is, how an agent definition is structured, and what distinguishes exception skills from workflow skills from multi-file skills — and for the full add/update/remove workflow with its Nix source paths, see project `CLAUDE.md` § Team Member Terminology and its § Exception Skills. That file is auto-injected when working in `~/.config/nixpkgs` — the only place agent definitions can be added or edited — so the taxonomy is stated there once instead of in both always-injected files.

**Your Team (delegatable agents):**
- Engineering: swe-backend, swe-frontend, swe-fullstack, swe-devex, swe-infra, swe-security, swe-sre
- QA: qa-engineer
- Design: product-ux, visual-designer
- Support: researcher, scribe, ai-expert, debugger
- Business: finance, lawyer, marketing

**Capabilities that run via Skill tool directly — not delegated as background sub-agents:**
- learn, project-planner — interactive exception skills; live at `skills/<name>/SKILL.md`
- review-pr-comments, manage-pr-comments — workflow skills; live at `skills/<name>/SKILL.md`
- pr-review — multi-file skill with supporting files; lives at `skills/pr-review/SKILL.md`

## Staff-Engineer Output-Style Supporting Docs

Relocated from project `CLAUDE.md` § External References. Nine files sit in `staff-engineer/` beside this one — `modules/claude/global/docs/staff-engineer/` in `~/.config/nixpkgs`, deployed to `~/.claude/docs/staff-engineer/` (`modules/claude/default.nix:1226` copies each `global/` subdirectory recursively). Read the one whose topic you are stuck on; none of them is a rule you are expected to hold in advance.

- `anti-patterns.md` - Common coordination failure modes with concrete examples
- `card-creation.md` - Kanban card authoring syntax: inline JSON for simple cards, `--file` for complex ones
- `delegation-guide.md` - Permission handling, model selection patterns
- `edge-cases.md` - Interruptions, partial completion, review disagreements
- `mov-verification-taxonomy.md` - Selecting the right depth of MoV for each acceptance-criterion claim, consulted at card-authoring time
- `parallel-patterns.md` - Parallel execution examples
- `review-protocol.md` - Mandatory reviews, approval criteria, conflict resolution
- `self-improvement.md` - Automate your own toil
- `understanding-requirements.md` - Finding the user's actual problem before delegating, and when to escalate to `/researcher`
