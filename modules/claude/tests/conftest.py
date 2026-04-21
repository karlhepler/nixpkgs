"""
Shared pytest fixtures for kanban hook tests.

Provides minimal JSON payloads matching Claude Code's PreToolUse and
SubagentStop hook formats, plus mock helpers for subprocess calls.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# PreToolUse payload builders (kanban-pretool-hook.py)
# ---------------------------------------------------------------------------

def make_pretool_payload(
    tool_name: str = "Agent",
    prompt: str = "KANBAN CARD #42 | Session: test-session\nDo some work.",
    run_in_background: bool | None = True,
    description: str = "Test agent description",
    subagent_type: str = "swe-devex",
    extra_input: dict | None = None,
) -> dict:
    """Build a minimal PreToolUse hook JSON payload."""
    tool_input: dict[str, Any] = {
        "prompt": prompt,
    }
    if run_in_background is not None:
        tool_input["run_in_background"] = run_in_background
    if description is not None:
        tool_input["description"] = description
    if subagent_type is not None:
        tool_input["subagent_type"] = subagent_type
    if extra_input:
        tool_input.update(extra_input)

    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": "outer-session-abc",
    }


@pytest.fixture
def valid_pretool_payload():
    """A complete, valid PreToolUse Agent payload with a card reference."""
    return make_pretool_payload()


@pytest.fixture
def pretool_payload_no_background():
    """PreToolUse payload missing run_in_background (or set to False)."""
    return make_pretool_payload(run_in_background=False)


@pytest.fixture
def pretool_payload_no_description():
    """PreToolUse payload with an empty description."""
    return make_pretool_payload(description="")


@pytest.fixture
def pretool_payload_no_subagent_type():
    """PreToolUse payload with empty subagent_type."""
    return make_pretool_payload(subagent_type="")


@pytest.fixture
def pretool_payload_invalid_subagent_type():
    """PreToolUse payload with the forbidden 'general-purpose' subagent_type."""
    return make_pretool_payload(subagent_type="general-purpose")


@pytest.fixture
def pretool_payload_no_card():
    """PreToolUse payload with no kanban card reference in prompt."""
    return make_pretool_payload(prompt="Please do some work without any card reference.")


@pytest.fixture
def pretool_payload_with_foreground_authorized():
    """PreToolUse payload with FOREGROUND_AUTHORIZED marker but no run_in_background."""
    return make_pretool_payload(
        run_in_background=False,
        prompt="FOREGROUND_AUTHORIZED\nKANBAN CARD #42 | Session: test-session\nDo some work.",
    )


@pytest.fixture
def pretool_payload_with_skill_bypass():
    """PreToolUse payload with SKILL_AGENT_BYPASS marker."""
    return make_pretool_payload(
        run_in_background=None,
        description=None,
        subagent_type=None,
        prompt="SKILL_AGENT_BYPASS\nsome skill invocation",
    )


# ---------------------------------------------------------------------------
# SubagentStop payload builders (kanban-subagent-stop-hook.py)
# ---------------------------------------------------------------------------

def make_stop_payload(
    transcript_path: str = "",
    session_id: str = "outer-session-xyz",
    cwd: str = "/tmp",
) -> dict:
    """Build a minimal SubagentStop hook JSON payload."""
    return {
        "agent_transcript_path": transcript_path,
        "session_id": session_id,
        "cwd": cwd,
    }


def make_transcript_jsonl(entries: list[dict]) -> str:
    """Serialize a list of transcript entries to JSONL format."""
    return "\n".join(json.dumps(e) for e in entries) + "\n"


def make_card_header_entry(card_number: str = "42", session: str = "test-session") -> dict:
    """Create a transcript entry containing the KANBAN CARD header."""
    return {
        "role": "user",
        "content": f"KANBAN CARD #{card_number} | Session: {session}\nDo some work.",
    }


def make_kanban_criteria_bash_entry(card_number: str = "42", session: str = "test-session", n: int = 1) -> dict:
    """Create an assistant tool_use entry for a kanban criteria check command."""
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "name": "Bash",
                "input": {
                    "command": f"kanban criteria check {card_number} {n} --session {session}",
                },
            }
        ],
    }


def make_substantive_tool_entry(tool_name: str = "Read") -> dict:
    """Create an assistant tool_use entry for a substantive tool call."""
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "name": tool_name,
                "input": {"file_path": "/some/file.py"},
            }
        ],
    }


@pytest.fixture
def tmp_transcript(tmp_path):
    """Factory fixture: returns a function that writes JSONL and returns the path."""
    def _write(entries: list[dict]) -> str:
        p = tmp_path / "transcript.jsonl"
        p.write_text(make_transcript_jsonl(entries))
        return str(p)
    return _write


# ---------------------------------------------------------------------------
# Mock kanban subprocess responses
# ---------------------------------------------------------------------------

class KanbanMockResponses:
    """
    Container for pre-baked subprocess.CompletedProcess-like return values
    used to simulate kanban CLI calls.
    """

    @staticmethod
    def success(stdout: str = "", stderr: str = "") -> MagicMock:
        m = MagicMock()
        m.returncode = 0
        m.stdout = stdout
        m.stderr = stderr
        return m

    @staticmethod
    def failure(stdout: str = "", stderr: str = "error", returncode: int = 1) -> MagicMock:
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    @staticmethod
    def card_xml(
        card_number: str = "42",
        session: str = "test-session",
        status: str = "doing",
        review_cycles: int = 0,
        criteria: list[dict] | None = None,
    ) -> str:
        """Build a minimal card XML string matching what kanban show produces."""
        if criteria is None:
            criteria = [
                {"text": "File exists", "mov_type": "programmatic", "mov_command": "test -f /tmp/file", "mov_timeout": "5"},
                {"text": "Output is correct", "mov_type": "semantic"},
            ]

        ac_elements = []
        for i, c in enumerate(criteria, 1):
            mov_type = c.get("mov_type", "semantic")
            mov_command = c.get("mov_command", "")
            mov_timeout = c.get("mov_timeout", "30")
            agent_met = c.get("agent_met", "false")
            reviewer_met = c.get("reviewer_met", "unchecked")
            text = c.get("text", f"criterion {i}")
            ac_elements.append(
                f'    <ac agent-met="{agent_met}" reviewer-met="{reviewer_met}" '
                f'mov-type="{mov_type}" mov-command="{mov_command}" '
                f'mov-timeout="{mov_timeout}">{text}</ac>'
            )

        ac_block = "\n".join(ac_elements)
        return (
            f'<card num="{card_number}" session="{session}" status="{status}" '
            f'review-cycles="{review_cycles}">\n'
            f'  <intent>Test card intent</intent>\n'
            f'  <acceptance-criteria>\n{ac_block}\n  </acceptance-criteria>\n'
            f'</card>'
        )


@pytest.fixture
def kanban_responses():
    """Provide KanbanMockResponses helper as a fixture."""
    return KanbanMockResponses()
