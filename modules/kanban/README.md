# Kanban CLI

File-based kanban board for agent coordination. Cards are JSON files stored in column directories. Designed for multi-agent Claude Code sessions coordinated by a staff engineer.

## Core Concepts

- **Cards** are JSON files (`NNN.json`) containing action, intent, acceptance criteria, and comments
- **Columns** are directories: `todo`, `doing`, `review`, `done`, `canceled`
- **Sessions** scope cards to specific Claude Code sessions (auto-detected, friendly names like `swift-falcon`)
- **Acceptance criteria** have dual columns: `agent_met` (self-checked by worker) and `reviewer_met` (verified by AC reviewer)
- **Comments** are timestamped messages on cards — the structured channel for agents to communicate findings back to the coordinator

## Quick Start

```bash
# Board auto-initializes in .kanban/ at git root

# Create a card in doing
kanban do '{"type":"work","action":"Fix the auth bug","intent":"Users cannot log in","criteria":["Auth endpoint returns 200","Existing tests pass"]}' --session wise-cedar

# Create a card in todo (queued)
kanban todo '{"type":"research","action":"Investigate performance regression","intent":"Dashboard loads slowly","criteria":["Root cause identified","Recommendations documented as comments"]}' --session wise-cedar

# Move todo card to doing
kanban start 2 --session wise-cedar

# View board
kanban list --output-style=xml --session wise-cedar

# View card details
kanban show 1 --output-style=xml --session wise-cedar
```

## Card Lifecycle

```
todo ──start──► doing ──review──► review ──(AC pass)──► done
                  ▲                  │
                  └────redo──────────┘
                  │
                  └──defer──► todo

Any column ──cancel──► canceled
```

## Commands

### Card Creation

```bash
# Create in doing (immediate work)
kanban do '<JSON>' --session <id>

# Create in todo (queued work)
kanban todo '<JSON>' --session <id>

# Bulk creation (pass JSON array)
kanban do '[{...}, {...}]' --session <id>
```

**Required JSON fields:**
- `type` — `"work"`, `"review"`, or `"research"`
- `action` — What to do (the task description, can be long)
- `criteria` — Array of acceptance criteria strings (minimum 1)

**Optional JSON fields:**
- `intent` — Why (the desired outcome)
- `editFiles` / `readFiles` — File path hints for conflict detection
- `persona` — Skill name (e.g., `"swe-backend"`)
- `model` — `"haiku"`, `"sonnet"`, or `"opus"`

### Card Transitions

```bash
kanban start <card> [card...]     # todo → doing
kanban review <card> [card...]    # doing → review
kanban redo <card>                # review → doing
kanban defer <card> [card...]     # doing/review → todo
kanban done <card> 'summary'     # review → done (requires all AC met)
kanban cancel <card> [card...]   # any → canceled
kanban cancel <card> --reason "why"
```

### Card Details

```bash
kanban show <card>                          # Terminal output
kanban show <card> --output-style=xml       # XML output (for agents)
```

### Comments

Timestamped messages on cards. The primary channel for agents to communicate detailed findings, recommendations, and deliverable details back to the coordinator.

```bash
kanban comment <card> "text" --session <id>
```

Comments appear in `kanban show` output (both terminal and XML formats).

### Acceptance Criteria

Also aliased as `kanban ac`.

```bash
kanban criteria add <card> "criterion text"       # Add criterion
kanban criteria remove <card> <n> "reason"        # Remove (with reason)
kanban criteria check <card> <n>                  # Set agent_met
kanban criteria uncheck <card> <n>                # Clear agent_met
kanban criteria verify <card> <n>                 # Set reviewer_met
kanban criteria unverify <card> <n>               # Clear reviewer_met
```

`kanban done` requires BOTH `agent_met` AND `reviewer_met` on all criteria.

### Board View

```bash
kanban list                                 # Simple terminal view
kanban list --output-style=xml              # XML (for staff engineer)
kanban list --output-style=detail           # Verbose terminal view
kanban list --show-done                     # Include done column
kanban list --show-canceled                 # Include canceled column
kanban list --show-all                      # Include both
kanban list --column doing,review           # Specific columns
kanban list --since today                   # Date filter
kanban list --session wise-cedar            # Session filter
```

### Watch Mode

Any command supports `--watch` for live auto-refresh on file changes:

```bash
kanban list --watch                         # Live board view
```

Interactive keys in watch mode: `?` toggle detail, `/` filter session, `#` filter card, `q` quit.

### Reporting

```bash
kanban report                               # All completed cards
kanban report --from 2026-01-01             # Since date
kanban report --to 2026-02-28              # Until date
kanban report --output-style=xml            # XML format
```

### Board Management

```bash
kanban init [path]                          # Create board structure
kanban rename <new-name> --session <id>    # Rename a session to custom name
kanban clean                                # Trash cards (interactive confirmation)
kanban clean <column>                       # Trash cards from specific column
kanban clean --expunge                      # Trash cards + scratchpad
```

Clean moves files to macOS Trash (recoverable via Finder "Put Back").

Session names are auto-generated as friendly Docker-style names (e.g., `swift-quartz`). Use `kanban rename` to override this with a custom name if desired.

## Session Management

Sessions scope cards to specific Claude Code instances. Session names are automatically generated as Docker-style friendly names (e.g., `swift-quartz`) and mapped from session UUIDs via `.kanban/sessions.json`.

- **Auto-detection:** `KANBAN_SESSION` env var > `USER` env var > auto-generated name
- **Auto-generated names:** Deterministic adjective-noun pairs like `swift-quartz`, `wise-cedar` (from UUID)
- **Custom renaming:** `kanban rename <new-name> --session <uuid>` to override auto-generated name
- **All commands accept** `--session <name>` to filter
- **Session filtering flags:** `--only-mine`, `--show-mine`, `--hide-mine`
- **Env override:** `KANBAN_HIDE_MINE=true` hides own cards by default

## File Structure

```
.kanban/
├── todo/
│   └── 2.json
├── doing/
│   └── 1.json
├── review/
├── done/
│   └── 3.json
├── canceled/
├── archive/
│   └── 2026-01/
│       └── 4.json
├── scratchpad/
└── sessions.json
```

Cards older than 30 days in `done/` are auto-archived to `archive/YYYY-MM/`. Configure with `KANBAN_ARCHIVE_DAYS`.

## Card JSON Format

```json
{
  "action": "Fix the authentication bug in login endpoint",
  "intent": "Users cannot log in after password reset",
  "type": "work",
  "readFiles": [],
  "editFiles": ["src/auth/*.ts"],
  "persona": "swe-backend",
  "model": "sonnet",
  "session": "wise-cedar",
  "created": "2026-02-28T14:00:00Z",
  "updated": "2026-02-28T15:30:00Z",
  "criteria": [
    {"text": "Auth endpoint returns 200 for valid credentials", "agent_met": true, "reviewer_met": true},
    {"text": "Existing test suite passes", "agent_met": true, "reviewer_met": false}
  ],
  "comments": [
    {"timestamp": "2026-02-28T15:00:00Z", "text": "Root cause: password hash comparison was using timing-unsafe equality"},
    {"timestamp": "2026-02-28T15:25:00Z", "text": "Fixed with crypto.timingSafeEqual, added regression test"}
  ],
  "activity": [
    {"timestamp": "2026-02-28T14:00:00Z", "message": "Created"},
    {"timestamp": "2026-02-28T15:30:00Z", "message": "Completed"}
  ]
}
```

## Agent Coordination Workflow

The staff engineer coordinates; sub-agents execute. Sub-agents interact with cards via a limited set of commands:

**Sub-agents may use:**
- `kanban show` — Read their card's task and AC
- `kanban criteria check/uncheck` — Self-check AC as they complete work
- `kanban comment` — Write findings, recommendations, and deliverable details

**AC reviewer may use:**
- `kanban show` — Read card, AC, and comments
- `kanban criteria verify/unverify` — Independently verify each criterion

**Staff engineer uses everything else** — card creation, transitions, lifecycle management.

### Typical Flow

```
1. Staff engineer creates card (kanban do)
2. Staff engineer delegates to sub-agent via Task tool
3. Sub-agent reads card (kanban show), does work
4. Sub-agent checks AC (kanban criteria check) and writes findings (kanban comment)
5. Staff engineer moves to review (kanban review)
6. AC reviewer reads card + comments (kanban show), verifies AC (kanban criteria verify)
7. Staff engineer completes card (kanban done)
8. Staff engineer reads comments (kanban show) and briefs user
```

## Metrics

Card lifecycle events are written to `~/.claude/metrics/claude-metrics.db` (SQLite) for the claudit analytics dashboard. Events include: create, start, review, redo, defer, done, canceled.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `KANBAN_ROOT` | Override board location |
| `KANBAN_SESSION` | Override session detection |
| `KANBAN_HIDE_MINE` | Hide own cards by default (`true`/`1`/`yes`) |
| `KANBAN_ARCHIVE_DAYS` | Days before auto-archiving done cards (default: 30) |
