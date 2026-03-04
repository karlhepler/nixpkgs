# Permission System Research Findings

> Written 2026-03-04 during investigation of background sub-agent kanban command failures.
> Session: noble-crane. Cards: #546 (cancelled), #547 (experiment tracker), #548 (perm CLI investigation).

---

## Why This Research Was Done

Background sub-agents launched via Task tool (`run_in_background: true`) were consistently
denied on kanban commands (`kanban comment`, `kanban criteria check`, `kanban review`) across
multiple cards and agent types. The kanban CLI was registering permissions via `perm --session
kanban-N allow "Bash(kanban comment N *)"` into `.claude/settings.local.json`, but agents
returned "Bash tool permission was denied."

Initial hypothesis: wrong scope (session-scoped vs. global). That hypothesis was wrong.

---

## Perm CLI Mechanics (from source: modules/claude/perm.bash)

### What `perm allow` does

Writes to **two files**:

1. **`.claude/settings.local.json`** — adds pattern to `permissions.allow` array.
   For Bash patterns containing spaces, BOTH the canonical form AND a colon-variant are added:
   ```json
   {
     "permissions": {
       "allow": [
         "Bash(npm run lint)",
         "Bash(npm:run:lint)"
       ]
     }
   }
   ```

2. **`.claude/.perm-tracking.json`** — records the session claim with a Unix timestamp:
   ```json
   {
     "temporary": {
       "Bash(npm run lint)": {
         "kanban-548": 1709000000
       }
     },
     "permanent": []
   }
   ```

The `--session` flag identifies WHICH session owns this claim (always `kanban-<N>` — a synthetic
ID tied to the card number, NOT the Claude Code session name). Multiple sessions can claim the
same pattern simultaneously. The pattern is only removed from `settings.local.json` when ALL
session claims are released.

### What `perm always` does

**Same as `perm allow` — writes to `.claude/settings.local.json`.** NOT `~/.claude/settings.json`.

The only difference: tracking uses the `permanent` array instead of `temporary`:
```json
{
  "temporary": {},
  "permanent": ["Bash(npm run test)"]
}
```

No session, no timestamp. Never touched by cleanup or cleanup-stale. The only removal path is
`perm reset` (which wipes all entries from `settings.local.json` — user-only command).

### Cleanup

`perm cleanup --session kanban-N`:
1. Finds all patterns claimed by `kanban-N` in `.perm-tracking.json`
2. Removes the session's claim from each pattern's claim object
3. If `remaining == 0` (no other sessions still claim it): removes pattern from `settings.local.json`
4. If `remaining > 0`: leaves pattern in `settings.local.json` (another card still needs it)

`perm cleanup-stale` (runs at session start): same logic but by age — removes claims with
timestamps older than 4 hours. Safety net for crashed sessions.

### What kanban.py registers (from source: modules/kanban/kanban.py)

When a card enters doing (`kanban do`, `kanban start`, `kanban redo`):
```python
session_id = f"kanban-{card_num}"
patterns = [
    f"Bash(kanban show {card_num} *)",
    f"Bash(kanban review {card_num} *)",
    f"Bash(kanban comment {card_num} *)",
    f"Bash(kanban done {card_num} *)",
]
for m in range(1, criteria_count + 1):
    patterns.append(f"Bash(kanban criteria check {card_num} {m} *)")
    patterns.append(f"Bash(kanban criteria uncheck {card_num} {m} *)")
    patterns.append(f"Bash(kanban criteria verify {card_num} {m} *)")
    patterns.append(f"Bash(kanban criteria unverify {card_num} {m} *)")

subprocess.run(["perm", "--session", session_id, "allow"] + patterns, ...)
```

Cleanup called by: `kanban done`, `kanban cancel`, `kanban defer`, `kanban redo` (before re-register).

---

## Experiment Results (2026-03-04)

All experiments run in `/Users/karlhepler/.config/nixpkgs` project directory.
Each test: pre-flight verified no test patterns in any settings file before adding.
Baseline: background agent denied with no permissions (confirmed).

### Group 1: Scope verification — all three files work

| Test | Pattern type | File | Result |
|------|-------------|------|--------|
| 1A | Exact | `.claude/settings.local.json` | ✅ SUCCESS |
| 1B | Partial wildcard (`path/*`) | `.claude/settings.local.json` | ✅ SUCCESS |
| 1C | Exact | `.claude/settings.json` | ✅ SUCCESS |
| 1D | Partial wildcard | `.claude/settings.json` | ✅ SUCCESS |
| 1E | Exact | `~/.claude/settings.json` | ✅ SUCCESS |
| 1F | Partial wildcard | `~/.claude/settings.json` | ✅ SUCCESS |

**Conclusion: All three settings files are read by background sub-agents.**

### Group 2: Additive vs. Override — fully additive

| Test | Setup | Result |
|------|-------|--------|
| 2A | Exact in `settings.local.json` + wildcard in `settings.json` | Both ✅ — additive |
| 2B | `settings.local.json` present (no perm), permission in `settings.json` | ✅ — not overridden |
| 2C | Both project files present (no perm), permission in global | ✅ — not overridden |

**Conclusion: Settings files fully merge. Higher-priority file presence does NOT shadow
lower-priority file permissions. All scopes contribute simultaneously.**

### Group 3: Deny list — global veto

| Test | Setup | Result |
|------|-------|--------|
| 3A | Allow + deny in same file | DENIED — deny wins |
| 3B | Allow in lower-priority, deny in higher-priority | DENIED — deny wins |
| 3C | Allow in higher-priority, deny in lower-priority | DENIED — deny wins |
| 3D | Allow in highest-priority, deny in lowest-priority | DENIED — deny wins |

**Conclusion: Deny is a global veto. ANY deny entry in ANY file overrides ALL allow entries
in ALL files, regardless of file priority hierarchy.**

### Group 4: Pattern matching — all variants work with simple commands

| Test | Permission pattern | Command | Result |
|------|-------------------|---------|--------|
| 4A | `Bash(touch /exact/path.txt)` | exact match | ✅ SUCCESS |
| 4B | `Bash(touch /path/prefix-*)` | matches wildcard | ✅ SUCCESS |
| 4C | `Bash(touch *)` | full path argument | ✅ SUCCESS |
| 4D | `Bash(touch /path/prefix-*)` | non-matching path | ✅ DENIED (correct) |

**Conclusion: All three pattern styles work correctly with simple commands.**

---

## Open Question: Why Do Background Agents Fail on Kanban Commands?

The experiments prove `settings.local.json` works and wildcard patterns work. But the
original failures were real (the researcher in this very session was denied `kanban comment`
despite the card being in doing with permissions registered).

The key difference between the experiment commands and kanban commands:

- **Experiment:** `touch /path/simple-filename.txt` — simple path, no spaces in argument
- **Kanban comment:** `kanban comment 548 "Long comment body with\nnewlines, $special, 'quotes'" --session noble-crane`

### Hypothesis: Pattern matching fails on complex argument strings

Pattern `Bash(kanban comment 548 *)` needs to match:
```
kanban comment 548 "Long body with newlines and special chars" --session noble-crane
```

The `*` wildcard may not match across:
- Newlines in the comment body
- Shell-special characters (`$`, backticks, quotes)
- The `--session` suffix appended after the comment text

This is consistent with GitHub issue #18950 (found during initial research) which reported:
"redirects and operators break matching" and "wildcard syntax behaves unexpectedly in some contexts."

### Alternative hypothesis: Working directory mismatch

Background agents might launch in a different working directory than the parent session,
causing `.claude/settings.local.json` to not be found. This was NOT tested empirically.
In our experiments, test agents ran in the nixpkgs project directory (same as parent).

---

## Key Discovery: Bash(kanban *) Already Globally Allowed

Inspection of `~/.claude/settings.json` revealed `Bash(kanban *)` (and `Bash(kanban:*)`) are
already in the global `allow` list. A live test confirmed background agents can successfully
run complex kanban commands (including `kanban comment` with multi-line bodies, `$VARIABLES`,
and `--session` flags) via this global permission.

The `permissions.block` list in global settings contains `Bash(kanban clean)` and
`Bash(kanban clean *)` — these are hard blocks on the prohibited `kanban clean` command.
The `permissions.deny` list in global settings is empty.
`.claude/settings.local.json` has no `deny` or `block` entries.

**Distinction between `block` and `deny` keys:** Empirically tested in Group 3 experiments
using the `deny` key only. The `block` key behavior vs. `deny` key behavior is untested —
they may have different semantics (e.g., `block` = unoverridable managed-policy-level veto,
`deny` = overridable by higher-priority allow).

### Unresolved: Why Did the Researcher Fail Earlier This Session?

The researcher agent (card #546, run_in_background: true) was denied on `kanban comment 546`
despite `Bash(kanban *)` being globally allowed. Systematic follow-up experiments eliminated
all plausible hypotheses:

| Hypothesis | Test | Result |
|-----------|------|--------|
| Wrong scope | Group 1 experiments | ❌ All scopes work |
| Wildcard pattern fails on complex content | Card #549 researcher | ❌ Succeeded |
| Agent type (researcher) has restrictions | Card #549 researcher | ❌ Succeeded |
| Corrupt settings.local.json blocks global | Deliberate corruption test | ❌ Succeeded |

**Conclusion: The failure cannot be reproduced and has no identified root cause.** It was
likely a transient Claude Code platform bug, a session initialization issue (note: 20 stale
permissions were cleaned up at this session's start), or a bug in an older version that has
since been fixed. The same failure pattern was observed across prior sessions (#443, #446)
suggesting it was environmental, not random. Current behavior is correct.

### Per-Card Registration May Be Redundant

Since `Bash(kanban *)` globally covers all kanban commands, the per-card patterns registered
by kanban.py (e.g., `Bash(kanban comment 548 *)`) are functionally redundant for permission
purposes. They do provide a conceptual card-level isolation intent (agents should only operate
on their own card), but this is not enforced — any agent with global kanban access can run
any kanban command on any card number.

## Recommendations

1. **Investigate the unexplained researcher failure** — reproduce the conditions under which
   card #546's researcher was denied `kanban comment` despite global `Bash(kanban *)` being
   allowed. Specifically test whether working directory affects settings.local.json loading
   while leaving global settings intact.

2. **Clarify `block` vs `deny` semantics** — run a Group 3-style experiment using the `block`
   key instead of `deny` to verify whether they behave identically or differently.

3. **Consider removing per-card registration** — since `Bash(kanban *)` is globally allowed,
   kanban.py's `_register_card_permissions` is providing no additional access. If card-level
   isolation is desired, it would need to be enforced at the kanban CLI level (not permission
   level), or the global `Bash(kanban *)` would need to be removed in favor of relying solely
   on per-card registration.

4. **Deny list awareness:** If any file has a `deny` or `block` entry matching a kanban
   pattern, it will globally veto the allow. Check all settings files for accidental deny/block
   entries if permissions appear to be registered but still failing.
