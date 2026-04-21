# Hook Tests

pytest-based regression guard for the two load-bearing Python hooks in
`modules/claude/`. Tests run locally against real hook source files using
monkeypatched subprocess calls — no real kanban cards are created or read.

## Files

| File | What it tests |
|------|--------------|
| `conftest.py` | Shared fixtures: payload builders, transcript helpers, `KanbanMockResponses` |
| `test_kanban_pretool_hook.py` | `kanban-pretool-hook.py` — PreToolUse enforcement |
| `test_kanban_subagent_stop_hook.py` | `kanban-subagent-stop-hook.py` — SubagentStop AC review |

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

## Adding a New Test

1. Identify which hook the test covers.
2. Open the corresponding test file (`test_kanban_pretool_hook.py` or
   `test_kanban_subagent_stop_hook.py`).
3. Add a class or method in the appropriate section. Follow the existing class
   naming convention (`TestWhatIsBeingTested`).
4. Use `conftest.py` fixtures (`tmp_transcript`, `kanban_responses`, etc.) and
   mock `subprocess.run` to avoid real kanban calls.
5. Run `pytest modules/claude/tests/ -x` to confirm the new test passes.

### Minimal test skeleton (pretool hook)

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
