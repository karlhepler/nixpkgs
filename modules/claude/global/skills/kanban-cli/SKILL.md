---
name: kanban-cli
description: kanban CLI full command reference. Auto-load BEFORE running any kanban subcommand other than `do`/`todo`/`list`/`show`/`start`/`done`/`criteria check/uncheck` — even when you believe you know the syntax. Cancel/redo/defer/criteria add/remove flag conventions are commonly misremembered. Covers all lifecycle commands (do, todo, start, defer, review, redo, done, cancel), AC criteria commands (criteria check, criteria uncheck, criteria add, criteria remove, criteria pass, criteria fail), MoV schema, __CARD_ID__ placeholder, output-style conventions, workflow examples, and exit codes. This skill is the canonical source for all kanban CLI syntax — `--help` should never be needed when this skill is loaded.
---

# kanban CLI — Full Command Reference

Exhaustive reference built from `kanban --help` and `kanban <sub> --help`. Use this to avoid syntax mistakes. No `--help` lookups needed in production use.

> **Skill loading:** This skill is a pure reference document — it loads in full on demand, no `$ARGUMENTS` parameterization. Consult the Commands at a Glance index below to jump to a specific command.

## Commands at a Glance

**Lifecycle:** `kanban do` · `kanban todo` · `kanban start` · `kanban defer` · `kanban review` · `kanban redo` · `kanban done` · `kanban cancel`
**Inspection:** `kanban show` · `kanban status` · `kanban list` · `kanban rejections`
**Criteria:** `kanban criteria add` · `kanban criteria remove` · `kanban criteria check` · `kanban criteria uncheck` · `kanban criteria pass` · `kanban criteria fail`
**Other:** `kanban agent` · `kanban rename` · `kanban report` · `kanban session-hook` · `kanban init`

### Card-Creation Quick Reference

| Verb | When to use | Result |
|------|-------------|--------------|
| `kanban do --file <path>` | Start work now (active card) | doing |
| `kanban todo --file <path>` | Queue for later (no agent yet) | todo |
| `kanban start <N>` | Move queued card to active | todo → doing |

**Both `kanban do` and `kanban todo` accept the same arguments**: inline JSON object/array, OR `--file <path>` to read from a JSON file. The `--file` flag deletes the input file after creating the card. Schema, JSON validation, and output behavior are identical between `do` and `todo` — the ONLY difference is the column the card lands in.

---

**Global flag available on every subcommand:**
- `--session SESSION` — Filter by session ID. **Mandatory on all lifecycle commands** (do, todo, start, cancel, redo, defer, review, done, show, list, criteria, agent, etc.). Always pass `--session <session-id>` unless explicitly scoping across all sessions (e.g., destructive git op board checks).
- `--output-style {simple,xml,detail}` — Available on `show` and `list`. Use `xml` for machine-readable output. Use `detail` for full card text in human-readable form.
- `--watch` — Auto-refresh on `.kanban/` changes. Useful for monitoring in a separate pane.
- `--only-mine` / `--show-mine` / `--hide-mine` — Filter visibility to current session's cards.

**Output-style convention:** `kanban list` and `kanban show <N>` produce XML by default. Use `--output-style=simple` when you want human-readable format. Machine-readable XML is the canonical AI-parsing target. Note: when specifying the flag explicitly, use the equals form: `--output-style=xml` (not `--output-style xml`).

---

## Card Creation

### `kanban do [json_data] [--file PATH] [--session SESSION]`

Create one or more cards in `doing` state immediately.

- **`json_data`** — Inline JSON object or array of objects. Fields: `action` (string, required), `intent` (string, required), `type` (string: `"work"` | `"review"` | `"research"`), `model` (string), `criteria` (array of criterion objects), `editFiles` (array of strings), `readFiles` (array of strings), `agent` (string).
- **`--file PATH`** — Read card JSON from a file instead of inline. **Auto-deletes the input file after reading.** Never add `rm` after this command — the file is gone.
- **JSON input convention:** `kanban do` accepts a JSON object (single card) or a JSON array (batch). Do NOT pass a JSON blob as the `text` argument to `kanban criteria add` — that command takes plain text only (see criteria add below).
- **Criterion object schema (v5):**

  > **🚨 `&&` is hard-prohibited in `mov_commands[].cmd`.** The kanban CLI's `kanban do/todo --file` validator rejects any criterion whose `cmd` contains `&&`. Split into separate array entries — one command per entry. Example:
  >
  > ```json
  > // ❌ rejected by validator
  > "mov_commands": [{"cmd": "rg -q X file && rg -q Y file", "timeout": 10}]
  >
  > // ✅ accepted
  > "mov_commands": [
  >   {"cmd": "rg -q X file", "timeout": 10},
  >   {"cmd": "rg -q Y file", "timeout": 10}
  > ]
  > ```
  >
  > Pipes, redirects, command substitution, and other shell features within a single `cmd` are still permitted — only `&&` is rejected.

  ```json
  {
    "text": "AC statement (plain text only — no MoV annotation)",
    "mov_commands": [
      {"cmd": "rg -q 'pattern' file.md", "timeout": 10}
    ]
  }
  ```
  Every criterion is implicitly programmatic; presence of non-empty `mov_commands` is the canonical signal. The `mov_type` field has been removed from the schema.
- **No `&&` in `cmd`.** HARD RULE — split compound checks into separate array items. See Quirks Catalog item 12 (CLI-enforced).
- **`__CARD_ID__` placeholder:** Use the literal token `__CARD_ID__` in `mov_commands[].cmd` or criterion `text` fields when you need to reference the card's own number (e.g., `"cmd": "rg -q 'pattern' .scratchpad/__CARD_ID__-findings.md"`). The CLI substitutes the actual assigned card number at card-create time. Scope: only `mov_commands[].cmd` and criterion `text` — not `action`, `intent`, or other fields.
- **Returns:** Card number on stdout (e.g., `42`). The assigned number is what you use in all subsequent commands.

### `kanban todo [json_data] [--file PATH] [--session SESSION]`

**Symmetric to `kanban do`** — accepts the same JSON schema and `--file <path>` flag; the only difference is the resulting status (`todo` vs `doing`). See the Card-Creation Quick Reference in the Card-Creation Quick Reference subsection near the top of this skill.

Create one or more cards in `todo` (queued) state. Same JSON schema as `kanban do`. Use when the card has a file-conflict dependency on an in-flight card — schedule it now, `kanban start` when the blocking card reaches `done`.

---

## Card Lifecycle Transitions

### `kanban start <card> [--session SESSION]`

Move a card from `todo` → `doing`. Accepts one or more card numbers. Use after file-conflict blocking dependency clears.

### `kanban defer <card> [--session SESSION]`

Move a card from `doing` or `review` → `todo`. Use to de-prioritize active work without canceling it.

### `kanban review <card> [--session SESSION]`

Move a card from `doing` → `review`. **Staff engineer does NOT call this.** Called automatically by the SubagentStop hook when a sub-agent stops. If the hook failed to fire, you may call it manually to trigger the AC lifecycle.

### `kanban redo <card> [--session SESSION]`

Move a card from `review` → `doing`. Used when AC review fails (hook calls this automatically) or when staff engineer wants to re-delegate work with updated AC. After `kanban redo`, update criteria as needed via `kanban criteria add/remove`, then re-delegate via Agent tool.

### `kanban done <card> [message] [--session SESSION]`

Move a card from `review` → `done`. Requires BOTH `agent_met` AND `reviewer_met` columns to be set on all criteria — otherwise fails with a clear error. The `message` argument is the completion summary (optional positional arg, not a flag).

- **If `kanban done` fails:** Check which criteria are not fully verified via `kanban show <N>`. Diagnose using the Stuck Card Diagnostic Protocol.

### `kanban cancel <card> [--reason REASON] [--session SESSION]`

Move a card to `canceled`. See § Card Lifecycle for when cancel is appropriate (abandoned work only — never for cleanup). Accepts one or more card numbers. `--reason` is optional but recommended for audit trail.

---

## Card Inspection

### `kanban show <card> [--output-style {simple,xml,detail}] [--session SESSION]`

Display full card contents. XML is the default output style — machine-readable for programmatic use. Use `--output-style=simple` for human-readable output. Includes `agent_met` and `reviewer_met` columns per criterion.

### `kanban status <card> [--session SESSION]`

Print only the column name of a card (e.g., `doing`, `review`, `todo`, `done`, `canceled`). Fast check without full card output. **`--session` is mandatory** (consistent with all other lifecycle commands).

### `kanban list [--column COLUMN] [--output-style {simple,xml,detail}] [--session SESSION] [--show-done] [--show-canceled] [--show-all] [--since SINCE] [--until UNTIL]`

Show board overview. Primary board-check command.

- **`--output-style`** — XML is the default; omit for standard AI-parseable output. Pass `--output-style=simple` for human-readable output. Pass `--output-style=detail` for full card text.
- **`--session SESSION`** — Filter to a specific session. Omit to see ALL sessions (required for destructive git op board checks — must scan all sessions for file-ownership conflicts).
- **`--column COLUMN`** — Filter to a specific column (`todo`, `doing`, `review`, `done`, `canceled`).
- **`--show-done` / `--show-canceled` / `--show-all`** — Include completed/canceled cards (excluded by default).
- **`--since` / `--until`** — Date filters: `today`, `yesterday`, `week`, `month`, or ISO date (`2026-04-22`).
- **Alias:** `kanban ls` is identical to `kanban list`.

### `kanban rejections <card> [--session SESSION]`

Display the rejection history for a card — all AC review cycles, what failed, and why. Use when diagnosing repeated redo loops.

---

## Acceptance Criteria

### `kanban criteria add <card> <text> [--session SESSION]`

Add a new criterion to a card. **`text` is plain text — NOT JSON.** Do not pass a JSON object as the `text` argument. The text is stored verbatim as the criterion statement. Use `kanban criteria add 42 "Pattern present in output file"` — not `kanban criteria add 42 '{"text": "..."}'`.

- The criterion is added with `agent_met` and `reviewer_met` both unset.
- Added criteria are discovered by the SubagentStop hook on the next `kanban review` call — the agent is sent back to address them automatically.
- `__CARD_ID__` substitution applies to newly-added criteria too — the CLI substitutes the actual card number in both the `text` field and any `mov_commands[].cmd` entries at the time `kanban criteria add` runs.

### `kanban criteria remove <card> <n> <reason> [--session SESSION]`

Remove criterion number `n` (1-indexed) from a card. **`reason` is a required positional argument** — not a flag. Always provide a rationale: `kanban criteria remove 42 3 "scope changed — no longer relevant"`.

### `kanban criteria check <card> <n> [--session SESSION]`

Mark criterion `n` as agent-met (`agent_met = true`). When `mov_commands` is non-empty, this runs each command synchronously. All commands must exit 0 for the check to succeed. If any command fails, the check is rejected with an error showing the failed command and exit code — fix the underlying issue and retry.

- **`n`** — 1-indexed criterion number. Accepts multiple numbers: `kanban criteria check 42 1 2 3`.
- **Called by sub-agents only** (not staff engineer). Staff engineer MUST NEVER call criteria check.

### `kanban criteria uncheck <card> <n> [--session SESSION]`

Clear `agent_met` on criterion `n`. Used by the SubagentStop hook to reset failing criteria before a redo. Staff engineer MUST NEVER call this.

### `kanban criteria pass <card> <n> [--session SESSION]`

Set `reviewer_met = true` on criterion `n`. Called by the AC reviewer (hook). Staff engineer MUST NEVER call this.

### `kanban criteria fail <card> <n> [--reason REASON] [--session SESSION]`

Set `reviewer_met = false` on criterion `n`, with optional reason. Called by the AC reviewer (hook). `--reason` is a flag (not positional) — unlike `criteria remove`. Staff engineer MUST NEVER call this.

### kanban criteria verify / unverify

Internal/suppressed commands — moved to § Internal / Suppressed Commands (Do Not Use) at the end of this skill. These are NOT usable by staff engineers or sub-agents.

---

## Other Commands

### `kanban agent <card> <agent_type> [--session SESSION]`

Set the agent type on a card after creation (e.g., `kanban agent 42 swe-backend`). Use when you need to update which specialist is assigned mid-flight.

### `kanban rename <new_name> --session SESSION`

Rename a session to a custom friendly name. `--session SESSION` is required and must be the current session UUID or existing name. `new_name` must be lowercase alphanumeric and hyphens only.

### `kanban report [--from FROM_DATE] [--to TO_DATE] [--output-style {human,xml}]`

Generate reporting from completed cards. Date format: `YYYY-MM-DD`. Output style: `human` (readable, default) or `xml` (structured for parsing). No `--session` filter (by design — reports aggregate across all sessions).

### `kanban session-hook [--session SESSION]`

Handle SessionStart hook (reads JSON from stdin). Called by the SessionStart hook infrastructure — not for direct coordinator use.

### `kanban init`

Create kanban board structure in the current directory. Run once per project.

---

## Quirks Catalog

1. **`criteria add` takes plain text, NOT JSON.** Passing a JSON blob stores it verbatim as the criterion statement text. Always pass plain English: `kanban criteria add 42 "Tests pass"`.

2. **`criteria remove` requires `reason` as a positional arg, not a flag.** Correct: `kanban criteria remove 42 3 "reason"`. Wrong: `kanban criteria remove 42 3 --reason "reason"` (this will error — `--reason` is not a flag on `criteria remove`).

3. **`criteria fail` uses `--reason` as a flag.** Correct: `kanban criteria fail 42 3 --reason "not found"`. Note: this is the opposite convention from `criteria remove`.

4. **`--file` deletes the input file after read.** `kanban do --file .scratchpad/card.json` removes `card.json` immediately after parsing. Never add `rm` afterward.

5. **`--session` is mandatory on all lifecycle commands.** Omitting `--session` on `kanban do`, `kanban criteria check`, `kanban done`, etc. means the card is created or operated on without session ownership. Always pass `--session <session-id>`.

6. **`--output-style` uses equals sign.** `--output-style=xml` (not `--output-style xml`). The `=` form is required.

7. **`kanban list` excludes done and canceled by default.** Pass `--show-done`, `--show-canceled`, or `--show-all` to include them.

8. **`kanban done` requires both `agent_met` AND `reviewer_met` set on all criteria.** If it fails, use `kanban show <N>` to inspect which criteria are not fully verified (XML output is the default).

9. **`criteria check` accepts text prefixes.** In addition to 1-indexed numbers, `n` can be a text prefix that uniquely matches a criterion. Prefer numeric indices for scripted use; text prefixes are for interactive convenience.

10. **`__CARD_ID__` placeholder.** The literal token `__CARD_ID__` in `mov_commands[].cmd` or criterion `text` is substituted with the actual card number at card-create time and on `kanban criteria add`. Use it when a MoV command references the card's own scratchpad file: `"cmd": "test -f .scratchpad/__CARD_ID__-findings.md"`.

11. **`kanban clean` is PROHIBITED.** Never run `kanban clean`, `kanban clean <column>`, or `kanban clean --expunge`. These delete cards permanently with no recovery. Use `kanban cancel` instead. (See § Hard Rules item 4.)

12. **`&&` is FORBIDDEN in `mov_commands[].cmd`.** HARD RULE. `mov_commands` is intentionally an array — multiple checks go in separate array items, never chained with `&&` in a single `cmd`. The kanban CLI rejects cards containing `&&` in any `mov_commands[].cmd` on creation.

    ❌ WRONG:
    ```json
    "mov_commands": [{"cmd": "rg -q X && rg -q Y", "timeout": 10}]
    ```

    ✅ CORRECT:
    ```json
    "mov_commands": [
      {"cmd": "rg -q X", "timeout": 10},
      {"cmd": "rg -q Y", "timeout": 10}
    ]
    ```

    Why: A compound AND-chain returns a single exit code, masking which sub-check failed. Array items give individually-actionable pass/fail diagnostics. If a check genuinely requires shell composition (pipes, subshells for an atomic observation), reconsider whether the AC should be split into multiple criteria instead.

13. **Regex backslash escapes (`\b`, `\d`, `\s`, `\w`) in `mov_commands[].cmd`.** The kanban CLI's XML storage pipeline historically corrupted regex backslash sequences via `html.unescape()`. Fixed in a subsequent release, but for portability and defense-in-depth, prefer character-class equivalents:
    - `\b` (word boundary) → there is no character-class equivalent (`\b` is a zero-width assertion; `[^a-zA-Z0-9_]` consumes a char and is not equivalent). Best alternative: rewrite the AC to positive-match the new identifier instead of negative-matching the old with a boundary.
    - Digit `\d` → use `[0-9]`
    - Whitespace `\s` → use `[[:space:]]` (POSIX class) or a literal space + tab
    - Word char `\w` → use `[a-zA-Z0-9_]`
    - Literal dot/paren `\.`, `\(`, `\)` → safe (commonly tested round-trip)

---

## Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | General error (invalid args, card not found, state transition not allowed) |
| 2 | Command error / bad argument |

For `kanban criteria check` MoV execution:

| Exit Code | Meaning |
|-----------|---------|
| 0 | All `mov_commands` passed |
| 1 | One or more commands returned non-zero (work failure) |
| 2 | Structural command error (bad args) |
| 124 | Command timed out |
| 126/127 | Command not found or not executable |

---

## Common Workflow Examples

**Board check (all sessions, xml — default):**
```bash
kanban list
```

**Board check (current session only):**
```bash
kanban list --session tidy-crown
```

**Create a card with criteria (via Write tool + --file):**
```
# Write tool creates .scratchpad/kanban-card-tidy-crown.json
# Then:
kanban do --file .scratchpad/kanban-card-tidy-crown.json --session tidy-crown
```

> **Remember:** `mov_commands[].cmd` must NOT contain `&&`. Use separate array items for compound checks. See Quirks Catalog item 12.

**Add a mid-flight requirement:**
```bash
kanban criteria add 42 "New requirement text" --session tidy-crown
```

**Remove a broken criterion:**
```bash
kanban criteria remove 42 3 "MoV scope leaked into parallel card" --session tidy-crown
```

**Inspect a stuck card:**
```bash
kanban show 42 --session tidy-crown
```

**Complete a card manually (hook failed):**
```bash
kanban done 42 "Summary of completed work" --session tidy-crown
```

**Re-delegate after redo:**
```bash
kanban redo 42 --session tidy-crown
# (update criteria if needed, then re-delegate via Agent tool)
```

---

## Internal / Suppressed Commands (Do Not Use)

These commands are internal to the kanban CLI infrastructure. Staff engineers and sub-agents MUST NEVER invoke them. They are documented here only to prevent confusion when they appear in `--help` output.

### `kanban criteria verify <card> <n> [--session SESSION]`

Internal/suppressed command (shown as `==SUPPRESS==` in `kanban criteria --help`). Sets `reviewer_met = true`. Equivalent to `kanban criteria pass` — use `pass` instead. Staff engineer MUST NEVER call this.

### `kanban criteria unverify <card> <n> [--session SESSION]`

Internal/suppressed command (shown as `==SUPPRESS==` in `kanban criteria --help`). Clears `reviewer_met`. Use `kanban criteria fail` instead for explicit reviewer rejection. Staff engineer MUST NEVER call this.
