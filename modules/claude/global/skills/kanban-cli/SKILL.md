---
name: kanban-cli
description: kanban CLI full command reference. Auto-load BEFORE running any kanban subcommand other than `do`/`todo`/`list`/`show`/`start`/`done`/`criteria check/uncheck` — even when you believe you know the syntax. Cancel/defer/criteria add/remove flag conventions are commonly misremembered. Covers all lifecycle commands (do, todo, start, defer, done, cancel), AC criteria commands (criteria check, criteria uncheck, criteria add [--mov-cmd/--mov-timeout], criteria remove), MoV schema, __CARD_ID__ placeholder, output-style conventions, workflow examples, and exit codes. This skill is the canonical source for all kanban CLI syntax — `--help` should never be needed when this skill is loaded.
---

# kanban CLI — Full Command Reference

Exhaustive reference built from `kanban --help` and `kanban <sub> --help`. Use this to avoid syntax mistakes. No `--help` lookups needed in production use.

> **Skill loading:** This skill is a pure reference document — it loads in full on demand, no `$ARGUMENTS` parameterization. Consult the Commands at a Glance index below to jump to a specific command. This skill is auto-loaded at SessionStart.

## Commands at a Glance

**Lifecycle:** `kanban do` · `kanban todo` · `kanban start` · `kanban defer` · `kanban done` · `kanban cancel`
**Inspection:** `kanban show` · `kanban status` · `kanban list` · `kanban rejections`
**Criteria:** `kanban criteria add` · `kanban criteria remove` · `kanban criteria check` · `kanban criteria uncheck`
**Other:** `kanban agent` · `kanban rename` · `kanban report` · `kanban session-hook` · `kanban init`

### Card-Creation Quick Reference

| Verb | When to use | Result |
|------|-------------|--------------|
| `kanban do --file <path>` | Start work now (active card) | doing |
| `kanban todo --file <path>` | Queue for later (no agent yet) | todo |
| `kanban start <N>` | Move queued card to active | todo → doing |

**Both `kanban do` and `kanban todo` accept the same arguments**: inline JSON object/array, OR `--file <path>` to read from a JSON file. The `--file` flag deletes the input file after creating the card. Schema, JSON validation, and output behavior are identical between `do` and `todo` — the ONLY difference is the column the card lands in.

---

## 🚨 MoV Authoring Banned Patterns

Note: when authoring a MoV that searches for the literal text of any banned pattern below (e.g., to verify a review covers it), see § Self-reference trap.

These patterns recur in MoV authoring. Each one fails structurally — the kanban CLI lint hook will reject `kanban do --file` invocations containing them. Verify your `mov_commands[].cmd` fields against this list BEFORE invoking the CLI.

### `\|` is LITERAL in ripgrep — NEVER use for alternation

In ripgrep's default Rust regex engine, `\|` matches a literal pipe character `|`, NOT alternation. Use bare `|` for alternation, OR split into separate `mov_commands` entries (one per term) so failure attribution is per-term.

- ❌ `rg 'a\|b\|c' file` — matches files containing literal pipes between a, b, c
- ✅ `rg 'a|b|c' file` — alternation; matches files containing any of a, b, c
- ✅ Better: separate `mov_commands` entries — failure tells you WHICH term is missing

### `&&` AND-chains are HARD-PROHIBITED

The kanban CLI validator structurally rejects `&&` in `mov_commands[].cmd`. Split into separate array entries — one command per entry. Failures are per-command actionable.

- ❌ `rg X file && rg Y file` — rejected by validator
- ✅ Two `mov_commands` entries: `[{"cmd": "rg X file"}, {"cmd": "rg Y file"}]`

(See also: Quirks Catalog item 11 for full rationale on AND-chain failure-attribution issues.)

### `rg -E` is `--encoding`, NOT extended regex

In ripgrep, `-E` means `--encoding`. The default regex engine already handles PCRE-style patterns. Use `rg -q` or `rg -qi` for case-insensitive matching.

- ❌ `rg -qE 'pattern' file` — exits 2 with stderr 'unknown encoding' error (NOT silent)
- ✅ `rg -qi 'pattern' file` — case-insensitive, regex default

### Pattern-absence: use `! rg -q`, not `test $(rg -c) -le 0`

`rg -c` emits no stdout on zero matches, making `test $(empty) -le 0` syntactically broken (exit 2).

- ❌ `test $(rg -c 'pattern' file) -le 0` — exit 2 when no matches present
- ✅ `! rg -q 'pattern' file` — exit 0 if absent, 1 if present

### Dash-leading patterns need `--` or `-e` separator

`rg` parses leading `-` as a flag. For literal patterns starting with `-`, use the end-of-flags marker.

- ❌ `rg -qF '--watch' file` — exit 2 'unrecognized flag'
- ✅ `rg -qF -- '--watch' file` — `--` ends flag parsing
- ✅ `rg -qi -e '-pattern' file` — explicit pattern flag

### Unbalanced `{` in regex alternation

`{` is a PCRE2 quantifier opener. An unmatched `{` in alternation triggers a regex parse error. Escape (`\{`) or split into separate `mov_commands` entries.

- ❌ `rg -q 'A|try {|B' file` — PCRE2 parse error: unmatched `{`
- ✅ `rg -q 'A|try \{|B' file` — escaped
- ✅ Better: separate `mov_commands` entries (one per term)

### Self-reference trap (searching for literal banned-pattern text)

When authoring a MoV that needs to search for the literal text of a banned pattern in a file (e.g., to verify a review's scratchpad covers the `rg -E` flag confusion), the lint hook cannot distinguish flag USAGE from text SEARCH. Authoring `rg -qi 'rg -E|encoding...' .scratchpad/...` triggers a false-positive rejection because the cmd literally contains `rg -E` as a substring. Or, similarly, `rg -qi 'AND-chain|backslash.pipe' .scratchpad/...` triggers rejection on the literal `&&` if you wrote that as part of the search keyword set.

**Workaround: MUST use a synonym or descriptive phrase instead of the banned pattern's literal name.**

| Banned pattern (don't search for) | Use this synonym instead |
|-----------------------------------|--------------------------|
| `rg -E` | `encoding flag`, `not extended regex` |
| `\|` (literal pipe) | `literal pipe`, `backslash.pipe`, `alternation trap` |
| `&&` (AND-chain) | `AND-chain`, `chained command`, `compound shell` |
| `test $(rg -c) -le 0` | `pattern-absence anti-pattern`, `absence-via-count`, `absence test idiom` |
| dash-leading patterns (`--watch`, `-pattern`) | `dash-leading pattern`, `flag-prefixed pattern`, `leading-dash literal` |
| backtick in `-c`/`-e` source | `backtick in inner source`, `shell-expansion trap`, `inner-source backtick` |
| `rg -o` on directory + sort -u | `directory filename prefix`, `unfiltered match prefix`, `sort -u uniqueness break` |
| `--no-verify` | `hook bypass`, `skip hooks` (also applies to hook-bypass keywords — banned by CLAUDE.md § Dangerous Operations) |
| `HUSKY=0` | `husky disable`, `husky skip` (also applies to hook-bypass keywords — banned by CLAUDE.md § Dangerous Operations) |

The permanent structural fix (token-based detection in the kanban CLI that distinguishes flag usage from quoted-pattern search) is tracked separately. Until it lands, ALWAYS use descriptive phrases over literal pattern names in MoV search expressions.

### `rg -o` on a directory prepends filename — breaks `sort -u` content-uniqueness checks

When extracting matches across multiple files for a uniqueness assertion, `rg -o <pattern> <directory>` outputs `<filename>:<match>` per line. Piping to `sort -u` deduplicates on the full line, not the match. Two files containing the same match produce two unique lines.

- ❌ `test "$(rg -o 'pattern' .github/ | sort -u | wc -l)" -eq 1` — counts unique `filename:match` pairs, not unique matches
- ✅ `test "$(rg --no-filename -o 'pattern' .github/ | sort -u | wc -l)" -eq 1` — counts unique matches across all files
- ✅ Shorthand: `rg -Io 'pattern' .github/` (`-I` = `--no-filename`; note `-N` is `--no-line-number`, NOT a valid shorthand here)

Trap is invisible at glance because `rg -o` works correctly on a single file (no filename prefix). Only when the input is a directory does the filename-prepending behavior kick in.

### Standalone Nix-managed lint/format tools in `~/.config/nixpkgs`

In this nixpkgs repo specifically (and any repo that deploys lint/format tools via Nix's build sandbox), **standalone `flake8 <file>`, `black <file>`, `shellcheck <file>`, `prettier <file>`, `mypy <file>`, `isort <file>` (and similar) MoV cmds exit 127 (`command not found`).** These tools are NOT in the agent's PATH from the Bash environment — they only exist inside the Nix build sandbox, invoked by `hms` during `home-manager switch`.

**Symptom:** card's MoV cmd exits 127. Agent correctly stops on structurally broken MoV (per the agent hard rule) instead of corrupting the artifact. Coordinator must remove the AC and re-launch — wasted agent run.

**Fixes (in priority order):**
- **Use `hms` as the lint MoV** — it runs flake8 internally with the project's actual ignore flags (E265, E501, W503, W504, etc.). Single MoV catches all Python lint, Nix syntax, and shell lint issues that the build cares about.
- If a standalone check is genuinely needed: `nix-shell -p flake8 --run 'flake8 <file>'` or invoke the nix-store path directly.
- Apply symmetrically to ANY standalone invocation of a Nix-managed build-time tool: `flake8`, `black`, `isort`, `mypy`, `shellcheck`, `prettier`, `pylint`, `ruff`, etc.

**Recurrence indicator:** any card with `editFiles` under `modules/claude/`, `modules/git/`, `modules/kanban/`, etc., that has a standalone lint tool name as the first token of a `mov_commands[].cmd`.

### `mise exec -- <tool>` in MoV commands and delegated Bash

**`mise exec -- <tool>` inside a MoV `cmd` (or any delegated Bash) resolves and installs the requested tool on demand before running it.** This can trigger an aqua-backend install (e.g., `aqua:pnpm/pnpm`) that FAILS BEFORE the tool ever runs, producing `mise ERROR Failed to install aqua:...: no asset found` and a non-zero exit whenever an aqua-managed tool lacks a release asset for the current platform — most commonly darwin-arm64, but any platform is affected if the tool's aqua package has no release asset for it. The MoV is then structurally broken regardless of whether the artifact under test is correct — the implementing agent correctly stops and reports it, costing a delegation cycle.

**Correct form:** `"$(mise which <tool>)" <args>` — `mise which <tool>` prints the tool's absolute install path WITHOUT activating the environment. Run the tool directly at that path to avoid the install dance.

- ❌ `mise exec -- actionlint -shellcheck= .github/workflows/foo.yml` — resolves and installs on demand; aqua-backend install can fail (no release asset for current platform) before actionlint runs
- ✅ `"$(mise which actionlint)" -shellcheck= .github/workflows/foo.yml` — resolves absolute path directly, no environment activation

**Applies to all mise-managed CLIs**, including but not limited to: `actionlint`, `terraform`, `argocd`, `shellcheck`, `helm`, `kubectl`, etc.

**Recurrence indicator:** any MoV `cmd` whose first two tokens are `mise exec`.

### `pnpm [run] <script> -- <flags>` separator forwarding in MoV commands

pnpm passes the `--` separator into the script's forwarded positional arguments (its `"$@"`), UNLIKE npm, which strips the first `--`. If the script forwards those positional arguments to a tool that treats a leading `--` as end-of-options (vitest and many CLIs), the flags silently become inert positionals and do nothing (e.g. an `--exclude`d spec still runs) — the check then fails as if it were a real test failure, not a flag-parsing bug.

- ❌ `pnpm --filter X test:run -- --exclude "<glob>"` — pnpm forwards the literal `--` into the script's forwarded positional arguments (its `"$@"`); vitest treats it as end-of-options and demotes `--exclude "<glob>"` to an inert positional, so the exclude never takes effect
- ✅ `pnpm --filter X test:run --exclude "<glob>"` — no `--`; flags reach vitest as real options

**Recurrence indicator:** any MoV of the form `pnpm [--filter X] [run] <script> -- <flag>`.

### BSD/macOS vs GNU coreutils flag divergence

The kanban criteria check shell runs under Nix with GNU coreutils on PATH — NOT the host shell's macOS/BSD userland. MoVs that use BSD-specific flag syntax will fail structurally even though the same command works in a macOS terminal.

Key divergences (BSD form → GNU coreutils alternative):

- ❌ `stat -f%z file` (BSD byte-count) → ✅ `wc -c < file` (POSIX) or `stat -c%s file` (GNU form)
- ❌ `sed -i '' 's/a/b/' file` (BSD in-place with empty extension) → ✅ `sed -i 's/a/b/' file` (GNU form; no empty string arg needed)
- ❌ `date -r file` (BSD: file mtime) — not portable; use `stat -c%Y file` (GNU: mtime in seconds since epoch) or `stat --format=%Y file`
- ❌ `date -v+1d` (BSD: date arithmetic) — not portable; use `date -d '+1 day'` (GNU)
- ❌ `find -E . -regex 'pattern'` (BSD: enable ERE) → ✅ `find . -regex 'pattern'` (GNU ERE default, or use `rg`)
- ❌ `du -h -d 1` (BSD: depth flag) → ✅ `du -h --max-depth=1` (GNU form)

**Framing:** MoVs must use POSIX-portable forms or assume GNU coreutils — never assume BSD flag syntax. `stat -f%z` is the canonical litmus example: it works on macOS but exits with an error under GNU coreutils. Prefer `wc -c < file` (POSIX, no coreutils assumption) for a byte count.

**Self-reference note:** When authoring a MoV that searches for this banned pattern's literal name in a scratchpad (e.g., to verify a review mentions it), use `bsd-stat`, `bsd.flag`, `stat dash-f`, or `byte-count portability` as synonyms — not `stat -f%z` literally (the lint hook sees the substring and triggers a false positive).

### Fixed-string (`-F`) anchor containing a code identifier

When a `-F` MoV pattern includes a code identifier (e.g., `updatedInput`, `run_in_background`, `editFiles`) that the agent will naturally render as inline code in Markdown (backtick-wrapped), the MoV forces the agent to strip backtick formatting to satisfy the literal match — forces the agent to strip backtick formatting, creating a formatting inconsistency in the artifact.

- ❌ `rg -qiF 'via updatedInput'` — agent writes `` via `updatedInput` ``; must strip backticks to match
- ✅ `rg -qiF 'injected via the hook'` — prose-only anchor; backtick formatting irrelevant
- ✅ `rg -qi 'via \`?updatedInput\`?'` — drop `-F`, regex tolerates optional surrounding backticks
- ✅ `rg -qiF 'via \`updatedInput\`'` — include backticks in the literal pattern

**Prefer prose-only anchors** (option 1) — they sidestep the formatting-vs-literal tension entirely.

**Worked example (card #2457):** the MoV used `rg -qiF 'via updatedInput'` (plain), while the agent correctly wrote the identifier backtick-wrapped; to pass, the agent stripped the backticks. This is a concrete sub-variant of the 'Agent satisfies broken MoV by corrupting artifact' anti-pattern.

### Line-ordering MoVs require UNIQUE anchors

`test $(rg -n PAT_A | head -1 | cut -d: -f1) -lt $(rg -n PAT_B | head -1 | cut -d: -f1)` requires PAT_A and PAT_B to be UNIQUE anchors. `head -1` silently returns the FIRST match; if the anchor phrase also appears in earlier prose (a table of contents, a 'When to Load' / mode-description section, or a cross-reference), `head -1` grabs that earlier occurrence and the comparison fails (or false-passes) despite correct content placement. Anchor each side on a line-start or bold-header-unique substring (for example, a regex anchored at line-start matching the bold header's literal asterisks, or a phrase that is unique to the header such as `media outlet only:`) — never a phrase that recurs in body prose. Before adding such an MoV, run `rg -n 'PAT' FILE` and confirm exactly one match per side.

- ❌ `test $(rg -n 'Cold outreach to unknown' file | head -1 | cut -d: -f1) -lt $(rg -n 'PAT_B' file | head -1 | cut -d: -f1)` — phrase `Cold outreach to unknown` also matches inline prose earlier in the file; `head -1` returns the wrong line even when placement is correct
- ✅ `test $(rg -n 'media outlet only:' file | head -1 | cut -d: -f1) -lt $(rg -n 'PAT_B' file | head -1 | cut -d: -f1)` — `media outlet only:` is unique to the header; `head -1` returns the correct line

This generalizes the existing 'Call-site vs import collision' entry (which already warns that `head -1` grabs the import line) to section/header ordering checks. Real incident: a relocation MoV used the anchor `Cold outreach to unknown` which also matched inline prose earlier in the file, so `head -1` returned the wrong line and the MoV failed even though placement was correct (fixed by re-anchoring on the header-unique `media outlet only:`).

### `sed`/`awk` range extraction on a mandated ONE-LINE function — range never closes, spills to EOF

When a card mandates a ONE-LINE shell function signature (e.g., `name() { echo "${1#@}"; }`) and an MoV extracts it for isolated testing with a range-extraction idiom like `sed -n '/^name()/,/^}/p'` (or the awk equivalent), the range NEVER CLOSES: a one-liner has no line that is just `}`, so `sed` spills to EOF, capturing the rest of the script (including any credential-loading logic). Sourcing that captured blob then fails for unrelated reasons, masking a correct implementation as broken across retry cycles.

- ❌ `sed -n '/^name()/,/^}/p' script.sh` — one-liner has no standalone `}` line; the range spills to EOF, capturing everything after the function
- ✅ `rg -m1 '^name' script.sh` — matches the single line directly, no range needed
- ✅ `awk '/^name\(\)/{print; exit}' script.sh` — prints the matching line and exits immediately, no closing-brace dependency

**Framing:** range extraction (`/start/,/end/p`) is only valid for genuinely MULTI-LINE function bodies. For a mandated one-liner, match the single line directly instead of range-extracting.

### `eval` in MoV commands trips the trust-scorer

Using `eval` in an MoV command to define a dynamically-extracted function or command before testing it is subject to a trust-scorer block (observed: `[trust-scorer] Score 0 — subshell-expansion, eval`), which will cause the sub-agent's `kanban criteria check` to be denied.

- ❌ `eval "$(rg -m1 '^name' script.sh)"; name arg` — trips the trust-scorer gate (subshell-expansion, eval); `kanban criteria check` is denied
- ✅ Write the extracted line to a temp file and `source` it, then invoke the function — a plain `source` of a temp file does not trip the same trust-scorer gate
- ✅ `rg -m1 '^name' script.sh > /tmp/fn.sh; source /tmp/fn.sh; name arg` — write-then-source: a plain redirect + `source` of a temp file does not trip the same trust-scorer gate

Real incident: a `kanban criteria check` MoV that used `eval` to invoke a dynamically-extracted function was blocked by the trust-scorer.

**Framing:** when an MoV must define and invoke a function extracted from a reviewed file, prefer write-then-`source` over `eval`.

### Pre-`kanban do --file` lint (mandatory before every CLI invocation)

Before invoking the kanban CLI, scan every `mov_commands[].cmd` field for these banned patterns:
- `&&` (AND-chain) — split into separate array entries
- `\|` (literal pipe in rg) — use bare `|` for alternation, OR split into separate entries
- `rg -E` (means --encoding, not extended regex) — use `rg -q` or `rg -qi`
- `test $(rg -c pattern) -le 0` for absence — use `! rg -q 'pattern' file`
- Dash-leading patterns without `--` or `-e` separator
- Backtick in double-quoted `-c`/`-e` source — backticks expand BEFORE inner language runs
- Standalone Nix-managed lint tool (`flake8`, `black`, `shellcheck`, `prettier`, `mypy`, `isort`, etc.) in `~/.config/nixpkgs` — exits 127 (NOT in agent's PATH); use `hms` as the lint MoV
- `mise exec -- <tool>` — use `"$(mise which <tool>)" <args>`; `mise exec` resolves and installs the requested tool on demand and can trigger an aqua-backend install that fails (no release asset for the current platform, most commonly darwin-arm64) before the tool runs
- `pnpm [run] <script> -- <flags>` — pnpm forwards `--` LITERALLY into the script's forwarded positional arguments (its `"$@"`) (unlike npm, which strips it); tools treating a leading `--` as end-of-options (vitest, etc.) demote the flags to inert positionals. Pass flags without the separator. See full entry above.
- BSD/macOS-specific flag syntax (`stat -f%z`, `sed -i ''`, `date -r`, `date -v`, `find -E`, `du -h -d`) — the check shell uses GNU coreutils; use POSIX-portable forms instead
- `-F` anchor containing a code identifier (e.g., `updatedInput`, `run_in_background`) — forces the agent to strip backtick formatting to satisfy the literal match; anchor on prose-only words instead
- Line-ordering MoVs (`head -1` line-number comparison) — run `rg -n 'PAT' FILE` and confirm exactly one match per side; anchor on a unique header substring, never a phrase that recurs in body prose. See § Line-ordering MoVs require UNIQUE anchors.
- `sed`/`awk` range extraction (`/^name()/,/^}/p`) on a mandated ONE-LINE function — the range never closes and spills to EOF; use `rg -m1 '^name' file` or `awk '/^pattern/{print; exit}' file` to match the single line directly.
- `eval` to define/invoke a dynamically-extracted function before testing — trips the trust-scorer gate (`Score 0 — subshell-expansion, eval`); write the extracted line to a temp file and `source` it instead.

The kanban CLI lint hook is the second-line defense. Every catch is an authoring failure.

For the comprehensive banned-patterns reference and rationale, see `~/.claude/output-styles/staff-engineer.md` § Card Management — Card Fields.

---

**Global flag available on every subcommand:**
- `--session SESSION` — Filter by session ID. **Mandatory on all lifecycle commands** (do, todo, start, cancel, defer, done, show, list, criteria, agent, etc.). Always pass `--session <session-id>` unless explicitly scoping across all sessions (e.g., destructive git op board checks).
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

Move a card from `doing` → `todo`. Use to de-prioritize active work without canceling it.

### `kanban done <card> [message] [--session SESSION]`

Move a card from `doing` → `done`. Gate: all criteria must have `met == true` — otherwise fails with a clear error. On failure, increments the card's `cycles` counter. The `message` argument is the completion summary (optional positional arg, not a flag).

Exit codes: 0 (success), 1 (retryable — criteria not all met or other recoverable error), 2 (max cycles reached).

- **If `kanban done` fails:** Check which criteria are not met via `kanban show <N>`. Diagnose using the Stuck Card Diagnostic Protocol.

### `kanban cancel <card> [--reason REASON] [--session SESSION]`

Move a card to `canceled`. See § Card Lifecycle for when cancel is appropriate (abandoned work only — never for cleanup). Accepts one or more card numbers. `--reason` is optional but recommended for audit trail.

---

## Card Inspection

### `kanban show <card> [--output-style {simple,xml,detail}] [--session SESSION]`

Display full card contents. XML is the default output style — machine-readable for programmatic use. Use `--output-style=simple` for human-readable output. Emits a single `met` field per criterion and a `cycles` field on the card.

### `kanban status <card> [--session SESSION]`

Print only the column name of a card (e.g., `doing`, `todo`, `done`, `canceled`). Fast check without full card output. **`--session` is mandatory** (consistent with all other lifecycle commands).

### `kanban list [--column COLUMN] [--output-style {simple,xml,detail}] [--session SESSION] [--show-done] [--show-canceled] [--show-all] [--since SINCE] [--until UNTIL]`

Show board overview. Primary board-check command.

- **`--output-style`** — XML is the default; omit for standard AI-parseable output. Pass `--output-style=simple` for human-readable output. Pass `--output-style=detail` for full card text.
- **`--session SESSION`** — Filter to a specific session. Omit to see ALL sessions (required for destructive git op board checks — must scan all sessions for file-ownership conflicts).
- **`--column COLUMN`** — Filter to a specific column (`todo`, `doing`, `done`, `canceled`).
- **`--show-done` / `--show-canceled` / `--show-all`** — Include completed/canceled cards (excluded by default).
- **`--since` / `--until`** — Date filters: `today`, `yesterday`, `week`, `month`, or ISO date (`2026-04-22`).
- **Alias:** `kanban ls` is identical to `kanban list`.

### `kanban rejections <card> [--session SESSION]`

Display the rejection history for a card — all AC review cycles, what failed, and why. Use when diagnosing repeated redo loops.

---

## Acceptance Criteria

### `kanban criteria add <card> <text> [--mov-cmd CMD] [--mov-timeout N] [--session SESSION]`

Add a new criterion to a card. **`text` is plain text — NOT JSON.** Do not pass a JSON object as the `text` argument. The text is stored verbatim as the criterion statement. Use `kanban criteria add 42 "Pattern present in output file"` — not `kanban criteria add 42 '{"text": "..."}'`.

- The criterion is added with `met` unset.
- **`--mov-cmd CMD`** (repeatable) — each occurrence appends an entry to `mov_commands`. Example: `--mov-cmd 'rg -q pattern file'`. Without `--mov-cmd`, the criterion has empty `mov_commands` and will be **rejected by `kanban criteria check`** (exit 1) — always provide at least one `--mov-cmd` for mid-flight injection.
- **`--mov-timeout N`** (repeatable, default 30) — sets the timeout in seconds for the most-recent `--mov-cmd`. Pair one `--mov-timeout` per `--mov-cmd` to set individual timeouts.
- Multiple commands, each with its own timeout:
  ```
  kanban criteria add 42 "Pattern present" \
    --mov-cmd 'rg -q pattern file' --mov-timeout 10 \
    --mov-cmd 'test -f file' --mov-timeout 5 \
    --session foo
  ```
- `__CARD_ID__` substitution applies to newly-added criteria too — the CLI substitutes the actual card number in both the `text` field and any `mov_commands[].cmd` entries at the time `kanban criteria add` runs.

### `kanban criteria remove <card> <n> <reason> [--session SESSION]`

Remove criterion number `n` (1-indexed) from a card. **`reason` is a required positional argument** — not a flag. Always provide a rationale: `kanban criteria remove 42 3 "scope changed — no longer relevant"`.

### `kanban criteria check <card> <n> [--session SESSION]`

Mark criterion `n` as met (`met = true`). When `mov_commands` is non-empty, this runs each command synchronously. All commands must exit 0 for the check to succeed. If any command fails, the check is rejected with an error showing the failed command and exit code — fix the underlying issue and retry.

- **`n`** — 1-indexed criterion number. Accepts multiple numbers: `kanban criteria check 42 1 2 3`.
- **Called by sub-agents only** (not staff engineer). Staff engineer MUST NEVER call criteria check.

### `kanban criteria uncheck <card> <n> [--session SESSION]`

Clear `met` on criterion `n` (`met = false`). Re-running `kanban criteria check` re-validates against `mov_commands`. Staff engineer MUST NEVER call this.

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

1. **`criteria add` takes plain text, NOT JSON.** Passing a JSON blob stores it verbatim as the criterion statement text. Always pass plain English: `kanban criteria add 42 "Tests pass" --mov-cmd 'pytest -x' --mov-timeout 60`. Without `--mov-cmd`, the criterion has empty `mov_commands` and `kanban criteria check` will reject it (exit 1).

2. **`criteria remove` requires `reason` as a positional arg, not a flag.** Correct: `kanban criteria remove 42 3 "reason"`. Wrong: `kanban criteria remove 42 3 --reason "reason"` (this will error — `--reason` is not a flag on `criteria remove`).

3. **`--file` deletes the input file after read.** `kanban do --file .scratchpad/card.json` removes `card.json` immediately after parsing. Never add `rm` afterward.

4. **`--session` is mandatory on all lifecycle commands.** Omitting `--session` on `kanban do`, `kanban criteria check`, `kanban done`, etc. means the card is created or operated on without session ownership. Always pass `--session <session-id>`.

5. **`--output-style` uses equals sign.** `--output-style=xml` (not `--output-style xml`). The `=` form is required.

6. **`kanban list` excludes done and canceled by default.** Pass `--show-done`, `--show-canceled`, or `--show-all` to include them.

7. **`kanban done` requires all criteria to have `met == true`.** If it fails, use `kanban show <N>` to inspect which criteria are not yet met (XML output is the default). On failure, the card's `cycles` counter is incremented.

8. **`criteria check` accepts text prefixes.** In addition to 1-indexed numbers, `n` can be a text prefix that uniquely matches a criterion. Prefer numeric indices for scripted use; text prefixes are for interactive convenience.

9. **`__CARD_ID__` placeholder.** The literal token `__CARD_ID__` in `mov_commands[].cmd` or criterion `text` is substituted with the actual card number at card-create time and on `kanban criteria add`. Use it when a MoV command references the card's own scratchpad file: `"cmd": "test -f .scratchpad/__CARD_ID__-findings.md"`.

10. **`kanban clean` is PROHIBITED.** Never run `kanban clean`, `kanban clean <column>`, or `kanban clean --expunge`. These delete cards permanently with no recovery. Use `kanban cancel` instead. (See § Hard Rules item 4.)

11. **`&&` is FORBIDDEN in `mov_commands[].cmd`.** HARD RULE. `mov_commands` is intentionally an array — multiple checks go in separate array items, never chained with `&&` in a single `cmd`. The kanban CLI rejects cards containing `&&` in any `mov_commands[].cmd` on creation.

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

12. **Regex backslash escapes (`\b`, `\d`, `\s`, `\w`) in `mov_commands[].cmd`.** The kanban CLI's XML storage pipeline historically corrupted regex backslash sequences via `html.unescape()`. Fixed in a subsequent release, but for portability and defense-in-depth, prefer character-class equivalents:
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

For `kanban done`:

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success — all criteria met, card moved to done |
| 1 | Retryable — one or more criteria not yet met |
| 2 | Max cycles reached |

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

> **Remember:** `mov_commands[].cmd` must NOT contain `&&`. Use separate array items for compound checks. See Quirks Catalog item 11.

**Add a mid-flight requirement with programmatic verification:**
```bash
kanban criteria add 42 "New requirement text" \
  --mov-cmd 'rg -q pattern file' --mov-timeout 10 \
  --session tidy-crown
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
