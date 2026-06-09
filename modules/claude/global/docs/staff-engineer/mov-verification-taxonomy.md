# MoV Verification Taxonomy

**Purpose:** Consulted at card-authoring time to select the right depth of MoV for each AC criterion.
**Referenced from:** staff-engineer.md § Pre-Card MoV Check.

---

## 1. The Layered Verification Model

Every AC criterion makes a claim. The MoV's job is to prove that claim — not just that a file was touched. Match the MoV depth to what the criterion actually asserts.

| Layer | What it proves | Canonical tools |
|-------|---------------|-----------------|
| **Existence layer** | The change is present in files | `rg`, `test -f`, `test -d`, `wc -l` |
| **Static layer** | The file/package is structurally sound | Lint, type-check, build, format-check, schema validation |
| **Functional layer** | The behavior is correct | Test runner, CLI invocation, curl/HTTP probe, exit-code script, throwaway verification script |

**Rule of thumb: match the deepest layer to what the criterion actually claims.**

- AC says "add a constant" → existence layer is sufficient.
- AC says "the file is valid JSON" → static layer (schema probe with `jq`).
- AC says "the command works" → functional layer (run the command, check exit code).
- AC says "the feature works end-to-end" → functional layer (test runner or runtime probe).

A single criterion can require multiple layers: a file-existence check (existence) AND a test run (functional) is two entries in `mov_commands` — both must exit 0.

**Why single-rg-and-done fails behavioral claims:** A ripgrep presence check proves text was written. It does not prove the text compiles, runs, or behaves as intended. An rg-only MoV on a "feature works" claim is a false-positive gate: the agent can satisfy it by adding any string matching the pattern — including incorrect or dead code.

---

## 2. AC-Type Sections

### New Feature

**What good AC looks like:** Encode the observable behavior, not just the code shape. "Feature exists" is insufficient. "Feature works as expected under these inputs/outputs" is correct. Side effects (new file, new endpoint, new config key) should appear as separate criteria.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Source file created | Existence | `test -f src/feature.ts` |
| Symbol exported | Existence | `rg -q 'export.*FeatureName' src/feature.ts` |
| Test file exists | Existence | `test -f src/feature.test.ts` |
| Tests pass | Functional | `pnpm test --filter feature` |
| CLI command runs without error | Functional | `my-cli feature --help` |
| HTTP endpoint responds | Functional | `curl -sf http://localhost:3000/api/feature` |
| New config key present and valid | Static | `jq -e '.featureKey' config.json` |
| TypeScript compiles | Static | `pnpm tsc --noEmit` |
| Lint passes | Static | `pnpm lint` |

**Notes:**
- Prefer one criterion per observable outcome. Do not bundle "tests pass AND lint passes" into one criterion — failures become individually actionable.
- For endpoints, `curl -sf` exits non-zero on HTTP 4xx/5xx AND on network errors; `curl -s -o /dev/null -w '%{http_code}'` extracts status explicitly.
- For CLIs in this Nix environment: invoke the Nix-installed binary directly (`my-command`) — not via language wrapper (`python3 -m my_module`).

---

### Bug Fix

**What good AC looks like:** Assert the absence of the failing behavior AND that surrounding behavior is undamaged. "Fixed the crash" isn't checkable; "command exits 0 with valid input" is.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Specific test that was failing now passes | Functional | `pytest tests/test_bug_123.py` |
| Command that was crashing exits 0 | Functional | `my-cmd --flag value` |
| Exit code on bad input is expected error code | Functional | `test $(my-cmd --invalid; echo $?) -eq 1` |
| Regression test added | Existence | see note below |
| No regressions in existing test suite | Functional | `pnpm test` |
| Error string no longer present in output | Functional | see note below |

```bash
# Regression test added — use bare | for alternation (ripgrep uses PCRE2 by default)
rg -q 'test.*bug.123|bug_123' tests/

# Error string no longer present in output — bare | is safe in shell pipe outside table cells
! my-cmd 2>&1 | rg -q 'NullPointerException'
```

**Notes:**
- A bug fix without a regression test is likely to regress. Bundle the regression test as a separate criterion.
- Bare `|` (shell pipe) in `mov_commands[].cmd` is fine. `&&` is prohibited (split into separate array entries). `\|` in rg/grep patterns is also banned — use bare `|` for alternation (ripgrep uses PCRE2 by default).
- For exit-code assertions, `test $(cmd; echo $?) -eq N` or `cmd; test $? -eq N` — never capture exit code in a subshell that might shadow the outer `$?`.

---

### Refactor

**What good AC looks like:** Refactors must not change observable behavior. The AC should assert: (1) the old shape is gone, (2) the new shape is present, (3) behavior is unchanged (tests still pass). All three layers are usually required.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Old identifier removed | Existence | `! rg -q 'OldFunctionName' src/` |
| New identifier present | Existence | `rg -q 'newFunctionName' src/` |
| All tests pass | Functional | `pnpm test` |
| No new lint violations | Static | `pnpm lint` |
| Type-check passes | Static | `pnpm tsc --noEmit` |
| File count unchanged (no accidental deletions) | Existence | see note below |

```bash
# File count unchanged — bare | is safe in shell pipe outside table cells
test $(fd -e ts src/ | wc -l) -ge N
```

**Notes:**
- Do NOT use `! rg -q 'oldName'` file-wide if the old name appears legitimately in comments, changelogs, or test descriptions. Scope to the source directory or use `rg --glob='*.ts'` to skip prose files.
- For rename-style refactors, verifying both absence-of-old AND presence-of-new prevents partial renames.
- Behavior parity is the most important claim: if tests don't cover the refactored surface, add a separate test-authoring card before or alongside the refactor.

---

### Copy / Config Change

**What good AC looks like:** For copy edits, assert the exact phrase or structural change. For config changes, assert the key/value and that the config is still valid. Prefer static layer (schema validation) over existence-layer-only for structured files.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Phrase present in doc | Existence | `rg -qF 'exact phrase' docs/file.md` |
| Phrase absent (removed copy) | Existence | `! rg -qF 'old phrase' docs/file.md` |
| Config key set to expected value | Static | `jq -e '.key == "value"' config.json` |
| YAML key present | Static | `yq -e '.key' config.yaml` |
| JSON file parses without error | Static | `jq . config.json` |
| YAML file parses without error | Static | `yq . config.yaml` |
| Nix file builds | Static | `hms` |
| Config value loads at runtime | Functional | see note below |

```bash
# Config value loads at runtime — bare | is safe in shell pipe outside table cells
my-cli config show | rg -q 'expected_value'
```

**Notes:**
- For config changes in Nix files, `hms` IS the static-layer MoV — it runs the full build including flake8 lint. Do not use standalone `flake8` (exits 127 in this environment). See staff-engineer.md § Card Management — Card Fields.
- For structured config files (JSON/YAML/TOML), always prefer `jq`/`yq` probes over `rg` for key-value assertions — `rg` cannot distinguish `"key": "wrong-value"` from `"key": "right-value"` without careful anchoring.
- Prefer `rg -qF` (fixed-strings) over regex when checking literal copy text — avoids regex metacharacter surprises.

---

### Test Authoring

**What good AC looks like:** Assert that the test file exists, covers the intended scenarios, and the tests pass. "Tests written" is not an AC — "tests pass and cover these cases" is.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Test file created | Existence | `test -f src/foo.test.ts` |
| Test describes the expected scenario | Existence | `rg -q 'should handle edge case' src/foo.test.ts` |
| All new tests pass | Functional | `pnpm test src/foo.test.ts` |
| Coverage includes target module | Functional | see note below |
| Test count meets floor | Functional | `test $(rg -c 'it\(' src/foo.test.ts) -ge 3` |
| No skipped tests introduced | Existence | see note below |

```bash
# Coverage includes target module — bare | is safe in shell pipe outside table cells
pnpm test --coverage | rg -q 'foo.*100'

# No skipped tests introduced — use bare | for alternation in rg patterns (PCRE2 default)
! rg -q 'it\.skip|xit|xdescribe' src/foo.test.ts
```

**Notes:**
- Test-count floors (`-ge N`) set a minimum quality bar but are blunt instruments; prefer specific scenario coverage assertions.
- Coverage assertions are slow — use sparingly and scope to the specific module, not the whole test suite.
- For this environment's test runners: `pytest` (Python), `vitest` / `pnpm test` (TypeScript/JS), `go test ./...` (Go). Invoke direct binaries, not `python3 -m pytest`.

---

### Infra Change

**What good AC looks like:** Infrastructure changes often have no easily-runnable functional test in CI. Layer the MoV: existence (config present), static (config parses / validates), and a runtime probe when possible (service up, port open, resource reachable).

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Config file present | Existence | `test -f infra/service.tf` |
| Config parses | Static | `terraform validate` |
| Nix config builds | Static | `hms` |
| Service reachable after deploy | Functional | `curl -sf http://localhost:PORT/health` |
| Port open locally | Functional | `nc -z localhost PORT` |
| Process is running | Functional | `pgrep -x service-name` |
| Schema validates | Static | `jq -e '.required_field' schema.json` |
| Environment variable set | Functional | `test -n "$ENV_VAR"` |

**Notes:**
- Infra changes that require a running environment (deploy, provision) often cannot have a full functional MoV in isolation. In those cases, use `hms` (for Nix changes) or a schema-validation probe as the static layer, and note in the AC text that runtime verification requires the service to be running.
- For Nix Home Manager changes, `hms` is always the correct build + lint gate. Do not use `nix flake check` alone — it does not run flake8.

---

### Prompt/Doc Change

**What good AC looks like:** Assert the presence of the new content, absence of the old content (if removed), and that the file structure remains intact. For prompt files, rely on the Tier 1 AI Expert review rather than trying to encode behavioral correctness in an rg-based MoV.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| New section heading present | Existence | `rg -qF '## New Section Name' docs/file.md` |
| Old section removed | Existence | `! rg -qF '## Old Section Name' docs/file.md` |
| Required phrase present | Existence | `rg -qi 'required phrase' docs/file.md` |
| File word count within range | Existence | `test $(wc -w < docs/file.md) -le 5000` |
| Markdown parses (no broken syntax) | Static | `markdownlint docs/file.md` (if available) |
| File is non-empty | Existence | `test -s docs/file.md` |
| All referenced section names exist | Existence | `rg -qF 'target-section' docs/file.md` |

**Notes:**
- For prompt files (output-styles/*.md, agents/*.md, CLAUDE.md), MoVs verify structural presence only. Behavioral correctness requires Tier 1 AI Expert review — do not attempt to encode prompt-quality judgments in an rg check.
- Use `rg -qF` (fixed-strings) for heading text — markdown heading text often contains special regex characters (backticks, parentheses, colons).
- File-wide negation MoVs (`! rg -q 'phrase' file`) on large prompt files are high-collision-risk. Prefer a distinctive multi-word phrase or scope to a specific section range via heading anchors.

---

### Migration

**What good AC looks like:** Migrations are typically irreversible. Assert: the migration ran (artifact produced or version record updated), the target state is correct, and a rollback mechanism or down-migration exists if required.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Migration file created | Existence | `test -f migrations/YYYYMMDD_description.sql` |
| Up-migration file present | Existence | see note below |
| Down-migration file present | Existence | see note below |
| Schema change present in migration | Existence | `rg -qF 'ADD COLUMN new_col' migrations/latest.sql` |
| Migration dry-run exits 0 | Functional | `db-tool migrate --dry-run` |
| Target table/column accessible post-migration | Functional | `db-tool query 'SELECT new_col FROM table LIMIT 1'` |

```bash
# Up-migration file present — bare | is safe in shell pipe outside table cells
fd -g '*.up.sql' migrations/ | rg -q .

# Down-migration file present
fd -g '*.down.sql' migrations/ | rg -q .
```

**Notes:**
- Migration MoVs should never run destructive operations. Use `--dry-run` or read-only queries where available.
- For schema migrations in this Nix environment, verify the migration tool binary is available before authoring MoVs — use `which <tool>` in a one-off check, not in an MoV.

---

### Dependency Bump

**What good AC looks like:** Assert the version was updated in the manifest, the lock file was updated, and the existing tests still pass. The existence check on version is insufficient alone — a bump that breaks tests is worse than no bump.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Package version updated in manifest | Existence | see note below |
| Lock file updated | Existence | `rg -q 'package-name.*NEW_VER' pnpm-lock.yaml` |
| All tests pass | Functional | `pnpm test` |
| No new security advisories | Static | `pnpm audit --audit-level=high` |
| Build succeeds | Static | `pnpm build` |

```bash
# Package version updated in manifest — bare | is safe in shell pipe outside table cells
jq -e '.dependencies["package-name"]' package.json | rg -q 'NEW_VER'
```

**Notes:**
- For Nix flake updates (`nix flake update`), the MoV is `hms` — it builds and validates the entire system.
- `pnpm audit` exits 1 on any advisory at or above the specified level — ensure the project's baseline is clean before adding this as an MoV.

---

### Performance Work

**What good AC looks like:** Performance claims must be concrete: "p95 < 100ms" needs a benchmark, or Path A applies — scope down to "5 sample requests complete in < 200ms" using `time curl`. Do not accept "performance improved" as an AC.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Sample requests complete within threshold | Functional | `time curl -sf http://localhost:3000/api/endpoint` |
| Command completes within N seconds | Functional | `timeout N my-cmd` |
| Benchmark output shows improvement | Functional | see note below |
| No regression in existing benchmarks | Functional | `pnpm bench` |
| Build output size within budget | Existence | `test $(wc -c < dist/bundle.js) -le BYTES` |

```bash
# Benchmark output shows improvement — bare | is safe in shell pipe outside table cells
pnpm bench 2>&1 | rg -q 'ops/sec'
```

**Notes:**
- `timeout N cmd` exits 124 if the command exceeds N seconds, 0 if it completes in time. Clean exit-code semantics — no AND-chain suffix needed.
- Wall-clock time (`time cmd`) is flaky in CI environments. Prefer explicit `timeout` checks for hard SLA assertions.

---

### Security Fix

**What good AC looks like:** Assert the vulnerable code path is removed or guarded, the fix is in place, and the existing test suite passes. For CVE-related dependency fixes, assert the updated version. For code-level fixes, use a functional probe if the attack vector is testable.

**Candidate MoV patterns:**

| Claim | Layer | Example command |
|-------|-------|-----------------|
| Vulnerable code pattern removed | Existence | see note below |
| Auth guard present | Existence | see note below |
| Fixed dependency version in manifest | Existence | see note below |
| Security audit passes at high level | Static | `pnpm audit --audit-level=high` |
| Auth-required endpoint rejects unauthenticated | Functional | `test $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/protected) -eq 401` |

```bash
# Vulnerable code pattern removed — use bare | for alternation in rg patterns (PCRE2 default)
! rg -q 'eval(user_input|exec(user_input' src/

# Auth guard present — use bare | for alternation
rg -q 'requireAuth|authenticate' src/handler.ts

# Fixed dependency version in manifest — bare | is safe in shell pipe outside table cells
jq -e '.dependencies["pkg"]' package.json | rg -q 'FIXED_VER'
```

**Notes:**
- Security fixes always trigger Tier 1 Security review — do not rely on MoVs alone to gate security correctness.
- For authentication endpoint checks: assert on HTTP 401/403 status codes, not on response body text (which may vary by implementation).

---

## 3. Verification-Method Catalog

Methods beyond text-presence checks. Each with when to use and an example command shape.

### Test Runners (Project-Native)

**When to use:** Any AC that claims behavior — new features, bug fixes, refactors, test authoring.

| Ecosystem | Command shape |
|-----------|--------------|
| Node/pnpm | `pnpm test` |
| Node/npm | `npm test` |
| Vitest | `pnpm vitest run` |
| Jest | `pnpm jest --testPathPattern=<file>` |
| Python/pytest | `pytest path/to/tests/` |
| Python/pytest scoped | `pytest tests/test_specific.py::test_function` |
| Go | `go test ./...` |
| Go scoped | `go test ./pkg/...` |

Run the minimal scope that covers the AC — full suite for regression claims, scoped file for targeted claims.

---

### Lint / Static Analysis

**When to use:** "File is valid" claims, style enforcement, code quality. Required as a layer when the AC claims code is production-ready.

| Tool | Command shape |
|------|--------------|
| ESLint | `pnpm eslint src/changed.ts` |
| Biome | `pnpm biome check src/` |
| Flake8 (via hms) | `hms` |
| Shellcheck (via hms) | `hms` |
| Go vet | `go vet ./...` |
| Custom lint script | `pnpm run lint` |

**Note for this Nix environment:** Standalone `flake8`, `shellcheck`, `prettier`, `mypy`, `isort`, `pylint`, `ruff` are build-sandbox-only tools — they exit 127 when invoked directly. Use `hms` as the lint MoV for Nix-managed files. See staff-engineer.md § Card Management — Card Fields.

---

### Type-Check

**When to use:** TypeScript/Python/Go/Rust AC that claims types are correct.

| Language | Command shape |
|----------|--------------|
| TypeScript | `pnpm tsc --noEmit` |
| TypeScript scoped | `pnpm tsc --noEmit --project tsconfig.json` |
| Python/pyright | `pyright src/module.py` |
| Go | `go build ./...` (type-checks as a side effect) |

---

### Build / Compile Checks

**When to use:** AC that claims the artifact produces valid output (bundle, binary, Nix derivation, CSS).

| Artifact | Command shape |
|----------|--------------|
| pnpm build | `pnpm build` |
| Nix Home Manager | `hms` |
| Go binary | `go build -o /dev/null ./cmd/...` |
| Python syntax | `python3 -m py_compile src/module.py` |
| Astro build | `pnpm astro build` |

---

### Runtime Probes (CLI Invocation)

**When to use:** AC that claims a CLI command works, or that a process is running. The functional layer for command-line deliverables.

| Claim | Command shape |
|-------|--------------|
| Command exits 0 | `my-command --flag` |
| Command exits with expected code | `my-command --invalid-flag; test $? -eq 1` |
| Command produces expected output | see note below |
| Help text includes expected flag | see note below |
| Command completes within time budget | `timeout 5 my-command` |

```bash
# Command produces expected output — bare | is safe in shell pipe outside table cells
my-command query | rg -q 'expected_output'

# Help text includes expected flag
my-command --help | rg -qF '--expected-flag'
```

---

### Runtime Probes (HTTP / curl)

**When to use:** AC that claims a web service, API endpoint, or HTTP resource is reachable and returns expected responses.

| Claim | Command shape |
|-------|--------------|
| Endpoint is reachable | `curl -sf http://localhost:PORT/path` |
| Status code is 200 | `test $(curl -s -o /dev/null -w '%{http_code}' http://localhost:PORT/path) -eq 200` |
| Status code is 401 (auth required) | `test $(curl -s -o /dev/null -w '%{http_code}' http://localhost:PORT/protected) -eq 401` |
| Response body contains phrase | see note below |
| Response is valid JSON | see note below |

```bash
# Response body contains phrase — bare | is safe in shell pipe outside table cells
curl -sf http://localhost:PORT/path | rg -q 'expected phrase'

# Response is valid JSON
curl -sf http://localhost:PORT/api/data | jq .
```

**Notes:**
- `curl -sf` exits non-zero on HTTP 4xx/5xx (`-f` flag) and on network errors (`-s` suppresses progress but allows exit codes).
- For status code assertions: `-o /dev/null -w '%{http_code}'` extracts only the status code, which `test` or `rg` can match.
- HTTP probes require the service to be running — these are integration-layer MoVs. If the service is not running during MoV check, the MoV will fail. Note this as a precondition in the AC text when relevant.

---

### Exit-Code Scripts (Inline Verification Logic)

**When to use:** AC where the pass/fail condition requires a comparison, arithmetic, or multi-step check that no single tool provides directly.

| Claim | Command shape |
|-------|--------------|
| File size within budget | `test $(wc -c < dist/file.js) -le 100000` |
| Line count in expected range | `test $(wc -l < output.txt) -ge 5` |
| At least N matches of pattern | see note below |
| Process not running | `! pgrep -x process-name` |
| Environment variable set | `test -n "${VAR_NAME}"` |
| Environment variable has expected value | `test "${VAR_NAME}" = "expected"` |

```bash
# At least N matches of pattern — bare | is safe in shell pipe outside table cells
test $(rg -o 'pattern' file | wc -l) -ge 3
```

**Note:** `test` (POSIX `[...]`) is always available in this Nix environment. For complex arithmetic, `$(( ))` arithmetic expansion is available in bash.

---

### Coordinator-Authored Throwaway Verification Scripts

**When to use:** When no single existing command directly proves an AC, but a short script (5–15 lines) can. First-class verification method — not a hack or workaround.

A throwaway script lives in `.scratchpad/verify-<card>.sh` or `.scratchpad/verify-<card>.py`, is referenced directly in `mov_commands`, and is deleted after the card completes. The script's exit code is the MoV gate.

**Example (bash):**
```json
{
  "text": "All exported functions have JSDoc comments",
  "mov_commands": [
    {"cmd": "bash .scratchpad/verify-2364.sh", "timeout": 15}
  ]
}
```

Script content in `.scratchpad/verify-2364.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
# Check every exported function in src/api.ts has a JSDoc comment above it
rg -n 'export (function|const|async function)' src/api.ts | while IFS=: read -r file line _rest; do
  prev_line=$(( line - 1 ))
  if ! sed -n "${prev_line}p" "$file" | rg -q '^\s*\*/'; then
    echo "FAIL: $file:$line missing JSDoc"
    exit 1
  fi
done
echo "PASS"
```

**When throwaway scripts are appropriate:**
- The verification requires iteration over a collection (all exported functions, all config keys, all test files).
- The verification requires multi-step logic that would be unsafe as a single pipe.
- The single-command alternatives are too fragile (too prone to false-positive collisions).

**Constraints:**
- The script must be created BEFORE `kanban do --file` (so the MoV can reference it at check time).
- Use `set -euo pipefail` at the top of bash scripts.
- Prefer Python for scripts requiring structured data parsing; prefer bash for file-system and CLI composition.
- Delete the script after the card reaches `done` (or note it in the scratchpad for manual cleanup).

---

### Tool-Native Validators

**When to use:** When the tool under test has a built-in `validate` / `check` / `lint` subcommand that directly proves correctness. These are the most authoritative MoVs — the tool itself is the source of truth for what it accepts.

| Tool | Validator | Command shape |
|------|-----------|--------------|
| Terraform | `terraform validate` | `terraform validate` |
| Kubernetes | `kubectl --dry-run=client` | `kubectl apply --dry-run=client -f manifest.yaml` |
| jq | Schema probe | `jq -e '.required_key' file.json` |
| yq | Schema probe | `yq -e '.required_key' file.yaml` |
| JSON parse | Valid JSON | `jq . file.json` |
| YAML parse | Valid YAML | `yq . file.yaml` |
| Markdown lint | Valid markdown | `markdownlint file.md` |
| npm/pnpm package | Valid package.json | `jq -e '.name and .version' package.json` |

**See also:** global CLAUDE.md § Tool-First Integration — run `<tool> validate` before researching why something doesn't work.

---

### Contract Checks

**When to use:** AC that claims an interface boundary (API contract, function signature, schema) matches a specification. Lighter-weight than a full test run; heavier than an rg presence check.

| Boundary | Command shape |
|----------|--------------|
| Function signature matches expected | `rg -qF 'function foo(req: Request, send:' src/handler.ts` |
| API schema field present | `jq -e '.components.schemas.User.properties.email' openapi.json` |
| Export surface includes expected name | `rg -q 'export.*MyType' src/types.ts` |
| Package exports correct entrypoint | `jq -e '.exports["."].import' package.json` |

---

### Diff-Shape Assertions

**When to use:** AC that claims ONLY specific files were changed (scope isolation, "did not touch X"). Must be scoped to paths outside every parallel card's `editFiles`. See also staff-engineer.md § MoV Scope Isolation.

| Claim | Command shape |
|-------|--------------|
| File was not modified | see note below |
| Only expected files changed | `test -z "$(git diff HEAD -- path/to/unrelated/)"` |
| No changes outside scope | see note below |

```bash
# File was not modified — bare | is safe in shell pipe outside table cells
! git diff HEAD -- path/to/file.ts | rg -q '.'

# No changes outside scope
! git diff HEAD -- src/unrelated/ | rg -q '.'
```

**Caution:** Diff assertions are fragile in parallel-agent sessions. Use only when the claim is "this file was NOT touched" and the file is exclusively owned by this card's scope. Never use `git diff --stat` on shared directories. See staff-engineer.md § MoV Scope Isolation for full rules.

---

### Log / Artifact Evidence Checks

**When to use:** AC that claims a process ran, a build artifact was produced, or a log entry was written.

| Claim | Command shape |
|-------|--------------|
| Build artifact produced | `test -f dist/output.js` |
| Build artifact is non-empty | `test -s dist/output.js` |
| Log file contains expected entry | `rg -q 'expected log entry' logs/app.log` |
| Artifact count within expected range | see note below |
| Artifact size within budget | see note below |

```bash
# Artifact count within expected range — bare | is safe in shell pipe outside table cells
test $(fd -e js dist/ | wc -l) -ge 5

# Artifact size within budget
test $(du -k dist/ | tail -1 | cut -f1) -le 500
```

---

## 4. Anti-Patterns

### One-rg-and-done on Behavioral Claims

Using a single `rg` text-presence check as the only MoV for an AC that claims behavior is the most common MoV quality failure. Text presence proves the file was edited. It does not prove the code runs, compiles, or does what it says.

**Rule:** If the AC text says "works", "handles", "returns", "runs", "validates", "passes", or any behavioral verb — the functional layer is required.

```json
// WRONG — proves text was written, not that the feature works
{"text": "Feature handles edge case", "mov_commands": [
  {"cmd": "rg -q 'handleEdgeCase' src/feature.ts", "timeout": 10}
]}

// RIGHT — proves the test covering the edge case passes
{"text": "Feature handles edge case", "mov_commands": [
  {"cmd": "rg -q 'handleEdgeCase' src/feature.ts", "timeout": 10},
  {"cmd": "pnpm test src/feature.test.ts", "timeout": 60}
]}
```

### MoVs That Pass on Appearance

An MoV that checks a comment, a variable name, or a string literal embedded in a larger unit does not verify that unit works. Examples of appearance-only MoVs that should instead be functional:

- `rg -q 'TODO: fix edge case'` was replaced by actual implementation → verify the test passes, not that the comment is gone.
- `rg -q 'ErrorBoundary'` in a React file → verify the component renders without crashing (render test).
- `rg -q 'validateInput'` in a function → verify calling the function with invalid input returns an error (functional test or exit-code script).

### Backslash-pipe trap

In markdown tables, the pipe character (`|`) must be escaped as `\|` to prevent it from being interpreted as a table column separator. This means that when coordinators copy example commands from a markdown table cell, they copy `\|` (backslash-pipe) instead of bare `|`.

The problem: `\|` is not valid syntax in kanban `mov_commands`. The kanban validator explicitly bans `\|` in rg/grep context. In ripgrep's default PCRE2 engine, bare `|` is alternation — `\|` is a literal pipe character, not alternation. The validator rejects any card whose `mov_commands[].cmd` contains `\|`.

The fix: example commands that contain a pipe character — whether for shell pipes or rg alternation — must NOT live inside markdown table cells. This doc places them in fenced code blocks below their tables (bare `|` is safe there). When authoring MoVs, always use bare `|`:

```bash
# WRONG — \| is banned by the kanban validator
rg -q 'requireAuth\|authenticate' src/handler.ts

# RIGHT — bare | is the correct alternation syntax in PCRE2
rg -q 'requireAuth|authenticate' src/handler.ts
```

The `\|` escape is only valid inside markdown table cell rendering — never in shell commands or kanban card JSON.

### Banned Syntax

The full list of banned `mov_commands` patterns (AND-chains, `\|` alternation, `rg -E`, etc.) lives in staff-engineer.md § Card Management — Card Fields. That list is not duplicated here — consult it during the pre-`kanban do --file` lint check.

---

*End of taxonomy.*
