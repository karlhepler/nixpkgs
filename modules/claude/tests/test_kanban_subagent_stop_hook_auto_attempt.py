"""
Regression tests for the auto-attempt behavior in kanban-subagent-stop-hook.py.

Feature: when the hook detects unchecked acceptance criteria, it now FIRST
attempts to run each unchecked criterion's mov_commands itself (by invoking
`kanban criteria check <card> <n> --session <s>` directly) before falling back
to the existing block/retry decision. `kanban criteria check` is the single
source of truth for running mov_commands (see cmd_criteria_check in
kanban.py) — the hook simply invokes the same command proactively instead of
waiting for the agent to remember to run it. This does not relax the quality
gate: a criterion with empty/missing mov_commands is still rejected by the
CLI itself ("invalid AC ... no programmatic verification provided") and is
never vacuously marked met.

This test invokes the hook as a subprocess feeding a realistic SubagentStop
JSON payload on stdin, per the Claude Code hook protocol — matching the
subprocess-invocation approach established in the sibling file
test_kanban_pretool_hook.py.

Because the new behavior calls the real `kanban` CLI multiple times (show,
criteria check, done, status, list), these tests substitute a small fake
`kanban` executable (written to a temp directory and prepended to PATH for
the hook subprocess) that returns pre-scripted responses per subcommand and
logs every invocation it receives — so assertions can confirm not just the
final decision, but that the hook actually attempted the auto-resolution
step rather than merely relying on the agent.

Cases:
    (a) Unmet criterion, mov_commands all pass  → hook auto-marks it met,
        allows the stop (kanban done then succeeds).
    (b) Unmet criterion, mov_commands fail      → hook blocks; the specific
        failing command and its exit code/stderr appear in the feedback.
    (c) Unmet criterion, empty/missing mov_commands → still auto-fails with
        the existing "invalid AC: no programmatic verification provided"
        message — NOT vacuously marked met. This is the case that most
        directly guards against silently gutting the quality gate.
    (d) Mixed: one criterion auto-passes, another fails → hook still blocks,
        and BOTH criteria were attempted (proven via the fake CLI's call log).
"""

import base64
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).parent.parent / "kanban-subagent-stop-hook.py"

# ---------------------------------------------------------------------------
# Fake `kanban` CLI — a stand-in binary that returns scripted responses per
# subcommand and appends every invocation (argv) to a call-log file, so tests
# can assert which commands the hook actually issued.
# ---------------------------------------------------------------------------

_FAKE_KANBAN_SOURCE = '''#!/usr/bin/env python3
import json
import os
import sys


def _log_call(argv):
    log_path = os.environ.get("FAKE_KANBAN_CALL_LOG")
    if not log_path:
        return
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(argv) + "\\n")


def main():
    argv = sys.argv[1:]
    _log_call(argv)

    scenario_path = os.environ.get("FAKE_KANBAN_SCENARIO")
    scenario = {}
    if scenario_path and os.path.exists(scenario_path):
        with open(scenario_path, "r", encoding="utf-8") as fh:
            scenario = json.load(fh)

    if not argv:
        sys.exit(0)

    sub = argv[0]

    if sub == "status":
        sys.stdout.write(scenario.get("status", "doing"))
        sys.exit(0)

    if sub == "show":
        sys.stdout.write(scenario.get("show_xml", ""))
        sys.exit(0)

    if sub == "list":
        sys.stdout.write(scenario.get("list_xml", ""))
        sys.exit(0)

    if sub == "criteria":
        action = argv[1] if len(argv) > 1 else ""
        if action == "check":
            # argv layout: ["criteria", "check", <card>, <index>, "--session", <session>]
            index = argv[3] if len(argv) > 3 else ""
            entry = scenario.get("criteria_check", {}).get(
                index, {"returncode": 0, "stdout": "", "stderr": ""}
            )
            # Optional: write raw (possibly non-UTF-8) bytes to stdout, to
            # reproduce the empirically-confirmed UnicodeDecodeError trigger
            # (subprocess.run(..., text=True) raises when the child's stdout
            # contains bytes that aren't valid UTF-8).
            raw_b64 = entry.get("raw_stdout_b64")
            if raw_b64:
                import base64 as _base64
                sys.stdout.buffer.write(_base64.b64decode(raw_b64))
                sys.stdout.buffer.flush()
                sys.exit(entry.get("returncode", 0))
            sys.stdout.write(entry.get("stdout", ""))
            sys.stderr.write(entry.get("stderr", ""))
            sys.exit(entry.get("returncode", 0))
        # uncheck (or any other criteria subcommand) — always succeed.
        sys.exit(0)

    if sub == "done":
        entry = scenario.get("done", {"returncode": 0, "stdout": "", "stderr": ""})
        sys.stdout.write(entry.get("stdout", ""))
        sys.stderr.write(entry.get("stderr", ""))
        sys.exit(entry.get("returncode", 0))

    # Unknown subcommand — succeed with empty output (fail-open-friendly default).
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


def _write_fake_kanban(bin_dir: Path) -> None:
    """Write the fake kanban script into bin_dir and make it executable."""
    fake_kanban_path = bin_dir / "kanban"
    fake_kanban_path.write_text(_FAKE_KANBAN_SOURCE, encoding="utf-8")
    fake_kanban_path.chmod(fake_kanban_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _card_xml(card_number: str, session: str, ac_bodies: list[str]) -> str:
    """Build a minimal but realistic `kanban show --output-style=xml` document.

    ac_bodies: raw inner XML for each <ac> element (attrs + body), already
    formatted by the caller (see _unmet_ac / _met_ac helpers below).
    """
    ac_block = "\n".join(ac_bodies)
    return (
        f'<card num="{card_number}" session="{session}" status="doing" type="work">\n'
        f"  <intent>Test card intent</intent>\n"
        f"  <acceptance-criteria>\n{ac_block}\n  </acceptance-criteria>\n"
        f"</card>"
    )


def _unmet_ac(text: str, commands: list[tuple[str, int]] | None = None) -> str:
    """Build a single unmet (<ac met="false">) element, optionally with mov_commands."""
    if not commands:
        return f'    <ac met="false">{text}</ac>'
    cmd_entries = "".join(
        f'<command cmd="{cmd}" timeout="{timeout}"/>' for cmd, timeout in commands
    )
    return f'    <ac met="false">{text}<movCommands>{cmd_entries}</movCommands></ac>'


def _fake_home_env(home_dir: Path, env: dict) -> dict:
    """Redirect HOME to an isolated directory so the hook's log writes
    (ERROR_LOG_PATH / INFO_LOG_PATH, both resolved via Path.home()) land
    outside the real ~/.claude/metrics/ production log.

    The hook is launched as a real OS subprocess (see _run_hook), so an
    in-process monkeypatch of the hook module's ERROR_LOG_PATH/INFO_LOG_PATH
    constants (as used by the sibling in-process test file) cannot reach it —
    the child process never sees the parent's monkeypatched module attribute.
    Overriding the HOME env var the child inherits is the one lever that
    reaches across the subprocess boundary: Path.home() consults HOME on
    POSIX, so every log path the hook computes gets rebased under home_dir.
    """
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    return env


def _fake_kanban_env(bin_dir: Path, scenario_path: Path, call_log_path: Path, home_dir: Path) -> dict:
    """Build the subprocess env: fake kanban dir prepended to PATH, scenario/log wired up.

    home_dir: isolated HOME for this subprocess — see _fake_home_env.
    """
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_KANBAN_SCENARIO"] = str(scenario_path)
    env["FAKE_KANBAN_CALL_LOG"] = str(call_log_path)
    # Ensure the hook doesn't skip AC review as a non-coordinator session.
    env.pop("PERSONAL_TRAINER_SESSION", None)
    return _fake_home_env(home_dir, env)


def _run_hook(payload: dict, env: dict) -> dict:
    """Invoke the hook as a subprocess with the payload on stdin.

    Returns the parsed JSON from stdout. The hook always exits 0 (fail-open
    contract at the outer main() level), so we do not check the exit code —
    the decision lives in stdout.
    """
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.stdout.strip(), (
        f"Hook produced no stdout. stderr: {result.stderr!r}"
    )
    return json.loads(result.stdout.strip())


def _build_stop_payload(transcript_path: str) -> dict:
    return {
        "agent_transcript_path": transcript_path,
        "session_id": "outer-test-session",
        "cwd": "/tmp",
    }


def _write_transcript(tmp_path: Path, card_number: str, session: str) -> str:
    """Write a minimal transcript containing the hook-injected card XML header."""
    entry = {
        "role": "user",
        "content": (
            f'<card num="{card_number}" session="{session}" status="doing" type="work">'
        ),
    }
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return str(transcript)


def _read_call_log(call_log_path: Path) -> list[list[str]]:
    if not call_log_path.exists():
        return []
    calls = []
    for line in call_log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            calls.append(json.loads(line))
    return calls


def _criteria_check_calls(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if len(c) >= 2 and c[0] == "criteria" and c[1] == "check"]


# ---------------------------------------------------------------------------
# (a) All mov_commands pass → auto-marked met, hook allows
# ---------------------------------------------------------------------------

def test_criterion_with_passing_mov_commands_is_auto_marked_met_and_allows(tmp_path):
    """A single unmet criterion whose mov_commands all pass: the hook invokes
    `kanban criteria check` itself, and — since kanban done then reports
    success — the hook allows the stop without any further agent action.
    """
    card_number, session = "9001", "auto-pass-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number, session, [_unmet_ac("File exists", [("test -f /tmp/x", 5)])]
        ),
        "criteria_check": {
            "1": {"returncode": 0, "stdout": "Criterion 1 passed: File exists", "stderr": ""},
        },
        "done": {"returncode": 0, "stdout": f"Card #{card_number} done.", "stderr": ""},
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    assert result.get("decision") == "allow", f"Expected allow, got: {result}"

    calls = _read_call_log(call_log_path)
    check_calls = _criteria_check_calls(calls)
    assert any(c[2:4] == [card_number, "1"] for c in check_calls), (
        f"Expected the hook to call `kanban criteria check {card_number} 1 ...` "
        f"itself. Calls seen: {calls}"
    )


# ---------------------------------------------------------------------------
# (b) mov_commands fail → hook blocks, failing command appears in feedback
# ---------------------------------------------------------------------------

def test_criterion_with_failing_mov_commands_blocks_with_command_in_feedback(tmp_path):
    """A single unmet criterion whose mov_commands fail: the hook still calls
    `kanban criteria check` (which fails), and the resulting block reason must
    contain the specific failing command and its exit code — not just a
    generic "still unmet" message.
    """
    card_number, session = "9002", "auto-fail-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    failing_stderr = (
        "Criterion 1 check FAILED at command [1/1].\n"
        "  failed_index: 0\n"
        "  failed_cmd: false\n"
        "  exit_code: 1"
    )
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number, session, [_unmet_ac("Always false command", [("false", 5)])]
        ),
        "criteria_check": {
            "1": {"returncode": 1, "stdout": "", "stderr": failing_stderr},
        },
        "done": {
            "returncode": 1,
            "stdout": "",
            "stderr": "Cycle 1/3. Unchecked: 'Always false command'",
        },
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    assert result.get("decision") == "block", f"Expected block, got: {result}"
    reason = result.get("reason", "")
    assert "failed_cmd: false" in reason, (
        f"Expected the specific failing command in the block reason. Got:\n{reason}"
    )
    assert "exit_code: 1" in reason, (
        f"Expected the exit code in the block reason. Got:\n{reason}"
    )

    calls = _read_call_log(call_log_path)
    check_calls = _criteria_check_calls(calls)
    assert any(c[2:4] == [card_number, "1"] for c in check_calls), (
        f"Expected the hook to have attempted `kanban criteria check {card_number} 1`. "
        f"Calls seen: {calls}"
    )


# ---------------------------------------------------------------------------
# (c) empty/missing mov_commands → still auto-fails, NOT vacuously passed
# ---------------------------------------------------------------------------

def test_criterion_with_no_mov_commands_still_auto_fails_not_vacuously_passed(tmp_path):
    """The single most important regression case: a criterion with no
    mov_commands must NOT be treated as trivially "all commands passed". The
    fake kanban's `criteria check` response for this criterion mirrors the
    REAL kanban CLI's own rejection (see cmd_criteria_check in kanban.py):
    exit 1 with "invalid AC ... no programmatic verification provided". The
    hook must surface that rejection, not silently mark the criterion met.
    """
    card_number, session = "9003", "no-mov-commands-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    invalid_ac_stderr = (
        "invalid AC #1: no programmatic verification provided — criterion has no "
        "mov_commands. Use 'kanban criteria remove' to drop it, or recreate the "
        "card with programmatic mov_commands via 'kanban do --file'."
    )
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number, session, [_unmet_ac("Semantic criterion with no commands")]
        ),
        "criteria_check": {
            "1": {"returncode": 1, "stdout": "", "stderr": invalid_ac_stderr},
        },
        "done": {
            "returncode": 1,
            "stdout": "",
            "stderr": "Cycle 1/3. Unchecked: 'Semantic criterion with no commands'",
        },
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    assert result.get("decision") == "block", (
        f"Expected block — a criterion with no mov_commands must never be "
        f"vacuously passed. Got: {result}"
    )
    reason = result.get("reason", "")
    assert "invalid AC" in reason and "no programmatic verification provided" in reason, (
        f"Expected the existing 'invalid AC: no programmatic verification provided' "
        f"message to be surfaced verbatim. Got:\n{reason}"
    )

    calls = _read_call_log(call_log_path)
    check_calls = _criteria_check_calls(calls)
    assert any(c[2:4] == [card_number, "1"] for c in check_calls), (
        f"Expected the hook to have attempted `kanban criteria check {card_number} 1` "
        f"even though the criterion has no mov_commands (the CLI itself rejects it — "
        f"the hook must not skip the attempt or treat it as vacuously passing). "
        f"Calls seen: {calls}"
    )


# ---------------------------------------------------------------------------
# (d) Mixed: one auto-passes, one fails → hook still blocks; both attempted
# ---------------------------------------------------------------------------

def test_mixed_one_passes_one_fails_still_blocks_and_both_attempted(tmp_path):
    """Two unmet criteria: index 1's mov_commands pass, index 2's fail. The
    hook must attempt BOTH (auto-marking 1 as met) but still block overall
    because kanban done reports criterion 2 as unresolved.
    """
    card_number, session = "9004", "mixed-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    failing_stderr = (
        "Criterion 2 check FAILED at command [1/1].\n"
        "  failed_index: 0\n"
        "  failed_cmd: exit 1\n"
        "  exit_code: 1"
    )
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number,
            session,
            [
                _unmet_ac("First criterion, passes", [("true", 5)]),
                _unmet_ac("Second criterion, fails", [("exit 1", 5)]),
            ],
        ),
        "criteria_check": {
            "1": {"returncode": 0, "stdout": "Criterion 1 passed: First criterion, passes", "stderr": ""},
            "2": {"returncode": 1, "stdout": "", "stderr": failing_stderr},
        },
        "done": {
            "returncode": 1,
            "stdout": "",
            "stderr": "Cycle 1/3. Unchecked: 'Second criterion, fails'",
        },
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    assert result.get("decision") == "block", f"Expected block, got: {result}"
    reason = result.get("reason", "")
    assert "failed_cmd: exit 1" in reason, (
        f"Expected the failing criterion's command in the block reason. Got:\n{reason}"
    )

    calls = _read_call_log(call_log_path)
    check_calls = _criteria_check_calls(calls)
    attempted_indices = {c[2:4][1] for c in check_calls if c[2:4][0] == card_number}
    assert attempted_indices == {"1", "2"}, (
        f"Expected BOTH criteria 1 and 2 to be attempted (auto-attempt must not "
        f"stop after the first success or first failure). Calls seen: {calls}"
    )


# ---------------------------------------------------------------------------
# Sanity: a card with nothing unmet does not spuriously invoke criteria check
# ---------------------------------------------------------------------------

def test_no_unmet_criteria_does_not_call_criteria_check(tmp_path):
    """When every criterion is already met, the auto-attempt step has nothing
    to do and must not call `kanban criteria check` at all.
    """
    card_number, session = "9005", "already-met-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number, session, ['    <ac met="true">Already satisfied</ac>']
        ),
        "criteria_check": {},
        "done": {"returncode": 0, "stdout": f"Card #{card_number} done.", "stderr": ""},
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    assert result.get("decision") == "allow", f"Expected allow, got: {result}"
    calls = _read_call_log(call_log_path)
    check_calls = _criteria_check_calls(calls)
    assert check_calls == [], (
        f"Expected no `kanban criteria check` calls when nothing is unmet. "
        f"Calls seen: {calls}"
    )


# ---------------------------------------------------------------------------
# Hardening regression tests (card #3175): a single malformed-output, timed-
# out, or missing-binary criterion must not cascade into skipping Step 4
# (`kanban done`, the authoritative check) entirely for the whole card.
# ---------------------------------------------------------------------------

def test_non_utf8_criteria_check_output_is_contained_and_still_reaches_done(tmp_path):
    """Empirically-confirmed trigger (card #3175 security review, Finding A):
    `subprocess.run(..., text=True)` raises UnicodeDecodeError when a
    subprocess emits non-UTF-8 bytes on stdout/stderr — reproduced directly
    via `sys.stdout.buffer.write(b"\\xff\\xfe\\x00broken")`. Before the fix,
    this exception propagated uncaught out of the auto-attempt loop, through
    process_subagent_stop and main(), to the hook's top-level fail-open
    handler — which allows the stop AND skips `kanban done` (Step 4) entirely
    for that stop event, so the quality gate silently never runs.

    This test scripts the fake kanban's `criteria check` response for the
    single unmet criterion to write raw non-UTF-8 bytes to stdout, and asserts
    the hook still reaches `kanban done` (proven via the call log) and
    surfaces a contained diagnostic in the block reason, rather than silently
    allowing the stop with the quality gate never invoked.
    """
    card_number, session = "9006", "malformed-output-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    raw_stdout_b64 = base64.b64encode(b"\xff\xfe\x00broken").decode("ascii")
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number, session, [_unmet_ac("Criterion with malformed output", [("true", 5)])]
        ),
        "criteria_check": {
            "1": {"returncode": 0, "raw_stdout_b64": raw_stdout_b64},
        },
        "done": {
            "returncode": 1,
            "stdout": "",
            "stderr": "Cycle 1/3. Unchecked: 'Criterion with malformed output'",
        },
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    calls = _read_call_log(call_log_path)
    done_calls = [c for c in calls if c and c[0] == "done"]
    assert done_calls, (
        f"Expected `kanban done` (Step 4) to still run despite the malformed "
        f"criteria-check output for criterion 1 — a single malformed output "
        f"must not cascade into skipping the authoritative check. "
        f"Calls seen: {calls}"
    )

    check_calls = _criteria_check_calls(calls)
    assert any(c[2:4] == [card_number, "1"] for c in check_calls), (
        f"Expected the hook to have attempted `kanban criteria check {card_number} 1`. "
        f"Calls seen: {calls}"
    )

    assert result.get("decision") == "block", f"Expected block, got: {result}"
    reason = result.get("reason", "")
    assert "auto-attempt raised an unexpected error" in reason, (
        f"Expected the contained-exception diagnostic in the block reason. Got:\n{reason}"
    )


def test_negative_timeout_budget_still_reaches_done(tmp_path):
    """Regression test for the timeout-expiry path: a criterion whose
    declared mov_command timeout is deliberately very negative produces a
    negative computed timeout_budget, which subprocess.run's own timeout
    enforcement turns into an almost-instant subprocess.TimeoutExpired rather
    than a hang — a negative timeout is enforced immediately regardless of
    how long the child takes (confirmed empirically in the security review:
    `subprocess.run(['sleep', '2'], timeout=-1, ...)` raised TimeoutExpired in
    ~0.0014s, not after a wait). `run_kanban` already converts
    subprocess.TimeoutExpired into a synthetic failed result rather than
    re-raising it (pre-existing, unrelated to this diff's containment fix) —
    this test asserts that behavior degrades gracefully end-to-end through
    the auto-attempt loop: the still-unmet criterion does not crash the hook,
    and `kanban done` (Step 4) still runs afterward.
    """
    card_number, session = "9007", "timeout-session"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_kanban(bin_dir)

    scenario_path = tmp_path / "scenario.json"
    call_log_path = tmp_path / "calls.jsonl"
    scenario = {
        "status": "doing",
        "show_xml": _card_xml(
            card_number,
            session,
            # A deliberately huge negative declared timeout drives the
            # computed timeout_budget deeply negative, which subprocess.run
            # enforces as an immediate TimeoutExpired (no real waiting).
            [_unmet_ac("Criterion with negative timeout", [("true", -100000)])],
        ),
        "criteria_check": {
            "1": {"returncode": 0, "stdout": "should never be reached", "stderr": ""},
        },
        "done": {
            "returncode": 1,
            "stdout": "",
            "stderr": "Cycle 1/3. Unchecked: 'Criterion with negative timeout'",
        },
    }
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = _fake_kanban_env(bin_dir, scenario_path, call_log_path, tmp_path / "home")

    result = _run_hook(_build_stop_payload(transcript_path), env)

    calls = _read_call_log(call_log_path)
    done_calls = [c for c in calls if c and c[0] == "done"]
    assert done_calls, (
        f"Expected `kanban done` (Step 4) to still run after a criterion's "
        f"check timed out. Calls seen: {calls}"
    )
    assert result.get("decision") == "block", f"Expected block, got: {result}"


def test_missing_kanban_binary_degrades_gracefully(tmp_path):
    """A `kanban` binary absent from PATH entirely (e.g. a broken PATH, or an
    uninstalled binary) must not crash the hook. `run_kanban` already converts
    FileNotFoundError into a synthetic CompletedProcess(returncode=127,
    stderr="kanban: command not found") rather than re-raising it — this test
    exercises that behavior end-to-end through the whole hook, confirming it
    still produces a valid, deterministic decision instead of an unhandled
    crash.
    """
    card_number, session = "9008", "missing-binary-session"
    empty_bin_dir = tmp_path / "empty-bin"
    empty_bin_dir.mkdir()

    transcript_path = _write_transcript(tmp_path, card_number, session)
    env = os.environ.copy()
    env["PATH"] = str(empty_bin_dir)  # No `kanban` binary anywhere on PATH.
    env.pop("PERSONAL_TRAINER_SESSION", None)
    # This is the specific scenario that used to write "kanban CLI not found
    # in PATH" and "Card #9008 kanban done exit 127" lines into the real
    # ~/.claude/metrics/kanban-subagent-stop-hook-errors.log on every run —
    # redirect HOME so those log_error() calls land in an isolated directory.
    env = _fake_home_env(tmp_path / "home", env)

    result = _run_hook(_build_stop_payload(transcript_path), env)

    assert result.get("decision") == "block", (
        f"Expected the hook to degrade gracefully (not crash) when `kanban` "
        f"is missing from PATH. Got: {result}"
    )
    reason = result.get("reason", "")
    assert "command not found" in reason, (
        f"Expected the missing-binary diagnostic surfaced in the reason. Got:\n{reason}"
    )
