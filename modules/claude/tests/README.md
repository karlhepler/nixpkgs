# Hook Tests

pytest-based regression guard for the load-bearing Python hooks in
`modules/claude/`. Tests run locally against real hook source files using
monkeypatched subprocess calls — no real kanban cards are created or read.

## Test Pyramid

### Tier 1 — Unit Tests (this directory)

Fast, isolated tests for hook and lint logic. Run on every local change.

```bash
pytest modules/claude/tests/
```

Pattern: hooks accept JSON on stdin; tests construct synthetic payloads and
pipe them via subprocess or monkeypatched stdin. Each test class targets one
behavioral path of one hook.

### Tier 2 — E2E Runbook (manual)

Full-stack validation against a live kanban session. Run on-demand, not in CI.

Location: `.scratchpad/kanban-staff-engineer-stress-test.md`

Covers: card lifecycle (todo → doing → done), multi-agent delegation, criteria
checking, hook enforcement with real kanban state.

**Tier 3 (deferred):** Sandboxed integration tests with a real kanban CLI in a
tmpdir. Not yet implemented; manual Tier 2 runbook covers cross-module behavior
for now.

## Files

| File | What it tests |
|------|--------------|
| `conftest.py` | Shared fixtures: payload builders, transcript helpers, `KanbanMockResponses` |
| `test_pretool_hook.py` | Starter/pattern file — cardless and general-purpose denial via subprocess |
| `test_kanban_pretool_hook.py` | `kanban-pretool-hook.py` — comprehensive PreToolUse enforcement |
| `test_kanban_subagent_stop_hook.py` | `kanban-subagent-stop-hook.py` — SubagentStop AC review |
| `test_kanban_mov_lint_hook.py` | `kanban-mov-lint-hook.py` — MoV lint detection logic |
| `test_kanban_permission_hook.py` | `kanban-permission-hook.py` — permission enforcement |
| `test_kanban_subagent_cmd_hook.py` | `kanban-subagent-cmd-hook.py` — subagent command hook |
| `test_kanban_v5.py` | kanban v5 criteria check protocol |
| `test_bash_cd_compound_hook.py` | bash cd compound command guard |
| `test_git_no_verify_hook.py` | git --no-verify guard |
| `test_kanban_done_reminder_hook.py` | kanban done reminder hook |
| `test_senior_staff_cron_hook.py` | senior staff cron hook |
| `test_taskstop_reminder_hook.py` | taskstop reminder hook |

### Other Module Tests

| File | What it tests |
|------|--------------|
| `test_crew.py` | crew lifecycle |

## Running the Tests

From the repository root:

```bash
pytest modules/claude/tests/ -x
```

Verbose output:

```bash
pytest modules/claude/tests/ -v
```

Run a specific test class or test:

```bash
pytest modules/claude/tests/test_kanban_pretool_hook.py::TestSkillAgentBypass -v
pytest modules/claude/tests/test_kanban_subagent_stop_hook.py::TestProgrammaticMovFailure::test_mov_pass_calls_criteria_pass -v
```

## Prerequisites

`pytest` is declared in `modules/packages.nix` and installed via `hms`. If it
is not available, run `hms` first.

## Hook Test Pattern

Hooks take JSON on stdin. Tests construct synthetic payloads and pipe them via
subprocess or monkeypatched stdin:

**Subprocess style** (exercises real hook I/O, slower):

```python
result = subprocess.run(
    [sys.executable, str(_HOOK_PATH)],
    input=json.dumps(payload),
    capture_output=True,
    text=True,
)
```

**Monkeypatch style** (unit-level, faster, used in test_kanban_pretool_hook.py):

```python
with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
    with patch("builtins.print", side_effect=captured_output.append):
        hook_mod.main()
```

## Adding a New Test

1. Identify which hook the test covers.
2. Open the corresponding test file or create a new one.
3. Add a class or method. Follow the `TestWhatIsBeingTested` naming convention.
4. Use `conftest.py` fixtures and mock `subprocess.run` to avoid real kanban calls.
5. Run `pytest modules/claude/tests/ -x` to confirm the new test passes.

### Minimal test skeleton (pretool hook — monkeypatch style)

```python
def test_my_new_case(self, hook):
    payload = make_pretool_payload(run_in_background=True, subagent_type="swe-devex")
    card_xml = KanbanMockResponses.card_xml()
    with patch("subprocess.run", return_value=KanbanMockResponses.success(stdout=card_xml)):
        result = run_hook_main(hook, payload)
    assert_allowed(result)
```

### Minimal test skeleton (stop hook)

```python
def test_my_new_case(self, hook, tmp_transcript):
    entries = [make_card_header_entry("42", "test-session")]
    transcript = tmp_transcript(entries)
    payload = make_stop_payload(transcript_path=transcript)
    # ... mock subprocess.run, then call run_process_stop(hook, payload)
```

## Follow-up Test Files (planned)

These test files will be added in follow-up improvement cards:

- `test_kanban_cli.py` — 18+ kanban CLI lifecycle test cases
- `test_subagentstop_hook.py` — hook protocol invariants (distinct from existing test_kanban_subagent_stop_hook.py which covers AC review)
- `test_prompt_coverage.py` — rg-based assertions on staff-engineer.md

## Coverage

### `kanban-pretool-hook.py`

| Path | Test class |
|------|-----------|
| Missing `run_in_background` | `TestMissingRunInBackground` |
| Missing `description` | `TestMissingDescription` |
| Missing `subagent_type` | `TestMissingSubagentType` |
| Invalid `subagent_type` (`general-purpose`) | `TestInvalidSubagentType` |
| Card XML injected into prompt | `TestCardInjection` |
| No card reference → denied | `TestNoCardReference` |
| `FOREGROUND_AUTHORIZED` marker | `TestForegroundAuthorized` |
| `SKILL_AGENT_BYPASS` marker | `TestSkillAgentBypass` |
| `BURNS_SESSION=1` skip | `TestBurnsSession` |
| Non-Agent tool passthrough | `TestNonAgentTool` |
| Response structure validation | `TestResponseStructure` |
| `extract_card_and_session` patterns | `TestCardPatternExtraction` |
| Destructive git safeguard | `TestDestructiveGitSafeguard` (planned) |
| `.kanban/` path guard | `TestKanbanPathGuard` (planned) |

### `kanban-subagent-stop-hook.py`

| Path | Test class |
|------|-----------|
| All programmatic criteria pass → kanban done, no Haiku | `TestAllProgrammaticCriteria` |
| Semantic criterion → Haiku reviewer invoked | `TestSemanticCriteriaInvokesHaiku` |
| Unchecked criteria → agent blocked | `TestUncheckedCriteriaBlocking` |
| Max retry cycles reached → stop allowed | `TestMaxRetryCyclesReached` |
| MoV exit 0 → `kanban criteria pass` | `TestProgrammaticMovFailure` |
| MoV exit nonzero → `kanban criteria fail` | `TestProgrammaticMovFailure` |
| MoV exit 126/127/124 → mov_error diagnostic | `TestMovErrorExitCodes` |
| Missing/nonexistent transcript → allow | `TestFailOpenBehavior` |
| `BURNS_SESSION=1` skip | `TestBurnsSession` |
| `extract_card_from_transcript` patterns | `TestTranscriptParsing` |
| Card already done → allow | `TestCardAlreadyDone` |
