#!/usr/bin/env python3
"""
skill-autoload-hook: SessionStart hook that injects the full CLI skill body
into the model's context based on the active agent identity.

PROBLEM SOLVED
==============
Staff and Senior Staff sessions each have a CLI reference skill (kanban-cli
and crew-cli respectively) that was previously loaded on demand. The on-demand
contract is unreliable: agents invoke subcommands with misremembered flag
conventions because the prompt's partial Quick Reference makes the syntax
feel known. Concrete failure: `crew list --format xml` errored because
`--format` is not accepted on `crew list` — the inline summary in
`senior-staff-engineer.md § Crew CLI Quick Reference` framed `--format xml`
as a global pattern.

DETECTION MECHANISM
===================
Agent identity is read from the `KANBAN_AGENT` environment variable, which
is exported by the `staff` and `sstaff` shell wrappers before invoking
Claude Code:
  staff.bash:  export KANBAN_AGENT=staff-engineer
  sstaff.bash: export KANBAN_AGENT=senior-staff-engineer

This is the same mechanism used by crew-lifecycle-hook.py (_is_senior_staff).
It is more reliable than reading settings.json (no file I/O race) or parsing
the session transcript path (fragile).

SKILL MAPPING
=============
  KANBAN_AGENT=staff-engineer         → injects kanban-cli/SKILL.md body
  KANBAN_AGENT=senior-staff-engineer  → injects crew-cli/SKILL.md body
  anything else                       → silent no-op (fail safe)

SKILL PATH RESOLUTION
=====================
Skills are deployed by hms to ~/.claude/skills/<name>/SKILL.md. The path is
derived from CLAUDE_CONFIG_DIR (if set) or defaults to ~/.claude.

IDEMPOTENCY
===========
Claude Code may fire SessionStart on /clear or /compact. The hook re-emits
additionalContext every time — cheap and correct. No sentinel tracking needed
(unlike crew-lifecycle-hook's readiness sentinel, which tracks external
process state).

On /compact: context is summarized but not reset — re-injection appends the
full skill body again. This is intentional: the skill body is a CLI syntax
reference, and refreshing it after compaction ensures the agent always has
current flag conventions even after context loss. Each fire is bounded by the
skill body size (~17-26 KB for current skills); the 10,000-char hook cap per
fire further limits blast radius. Across multiple compactions in one long
session the body accumulates, but the trade-off (correct syntax reference)
outweighs the context cost for these reference-style payloads.

OUTPUT FORMAT
=============
SessionStart hook output:
  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}

On silent no-op: no stdout (empty), exit 0.
On error: stderr only, exit 0 (fail open — never break SessionStart).

FAIL SAFE
=========
If the hook cannot determine the skill to load (unknown agent, file not
found, read error), it emits NO additionalContext and exits 0. Injecting a
wrong skill body is worse than injecting nothing.
"""

import argparse
import json
import os
import sys


# Map KANBAN_AGENT values to skill directory names under ~/.claude/skills/
_SKILL_MAP: dict[str, str] = {
    "staff-engineer": "kanban-cli",
    "senior-staff-engineer": "crew-cli",
}

# Maximum skill body size to read. Current deployed skills are ~17-26 KB.
# 200 KB is generous headroom; a file beyond this cap is anomalous (possibly
# replaced with malicious content) and should not be injected — partial context
# is worse than no context.
MAX_SKILL_BODY = 200_000  # bytes


def _resolve_skill_path(skill_name: str) -> str | None:
    """Return the absolute path to SKILL.md for the given skill name.

    Checks CLAUDE_CONFIG_DIR first (set by Claude Code), then falls back to
    ~/.claude. Returns None if the file does not exist.

    Path: <config_dir>/skills/<skill_name>/SKILL.md
    """
    # CLAUDE_CONFIG_DIR is unofficial (per upstream issue tracker,
    # github.com/anthropics/claude-code/issues/3833) — it is not guaranteed to
    # be exported into hook execution environments. Preferred when set because
    # it enables forward-compatibility with non-default config directories;
    # fallback to ~/.claude is correct for the current Nix-managed deployment
    # where hms always deploys skills to ~/.claude/skills/.
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not config_dir:
        config_dir = os.path.join(os.path.expanduser("~"), ".claude")

    skill_path = os.path.join(config_dir, "skills", skill_name, "SKILL.md")
    if os.path.isfile(skill_path):
        return skill_path
    return None


def _detect_skill_name() -> str | None:
    """Return the skill name to inject, or None for a silent no-op.

    Uses KANBAN_AGENT env var — the canonical agent-identity signal exported
    by staff.bash and sstaff.bash before launching Claude Code.
    """
    kanban_agent = os.environ.get("KANBAN_AGENT", "")
    return _SKILL_MAP.get(kanban_agent)


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter (---...---) from the start of a markdown string.

    Returns the body after the second '---' delimiter, trimmed of leading
    whitespace. If no frontmatter is present, returns the original text.
    """
    if not text.startswith("---"):
        return text
    # Find the closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return text
    # Skip past the closing --- and any trailing newline
    body_start = end + 4  # len("\n---") == 4
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    return text[body_start:]


def _emit_additional_context(content: str) -> None:
    """Write the SessionStart additionalContext envelope to stdout."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": content,
        }
    }
    print(json.dumps(payload))


def run() -> None:
    """Core hook logic.

    1. Detect which skill (if any) to inject based on KANBAN_AGENT.
    2. Resolve the skill file path.
    3. Read and strip frontmatter from the skill body.
    4. Emit the additionalContext envelope to stdout.

    Silent no-op on any detection/load failure — never break SessionStart.
    """
    skill_name = _detect_skill_name()
    if skill_name is None:
        print(
            f"[skill-autoload-hook] KANBAN_AGENT={os.environ.get('KANBAN_AGENT', '(unset)')!r} "
            "not in skill map; no injection",
            file=sys.stderr,
        )
        return

    skill_path = _resolve_skill_path(skill_name)
    if skill_path is None:
        print(
            f"[skill-autoload-hook] skill file not found for {skill_name!r}; no injection",
            file=sys.stderr,
        )
        return

    try:
        # O_NOFOLLOW rejects symlinks at the kernel level (raises OSError with
        # errno=ELOOP on macOS/Linux if the final path component is a symlink).
        # This prevents a symlink-substitution attack where a malicious actor
        # replaces SKILL.md with a symlink to an arbitrary file, causing the
        # hook to emit unintended content as additionalContext.
        fd = os.open(skill_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            # Read one byte beyond the cap so we can detect oversized files.
            # The cap is enforced below; we never load more than MAX_SKILL_BODY+1
            # bytes regardless of file size.
            raw = f.read(MAX_SKILL_BODY + 1)
    except OSError:
        # Do not emit the file path in the error — it would reveal the home
        # directory. Skill name is safe (hardcoded allowlist, not user input).
        print(
            f"[skill-autoload-hook] skill body unreadable for skill={skill_name!r}; check Nix activation",
            file=sys.stderr,
        )
        return

    if len(raw) > MAX_SKILL_BODY:
        print(
            f"[skill-autoload-hook] skill body for skill={skill_name!r} exceeds {MAX_SKILL_BODY} bytes; no injection",
            file=sys.stderr,
        )
        return

    body = _strip_frontmatter(raw)
    if not body.strip():
        print(
            f"[skill-autoload-hook] skill body is empty after frontmatter strip for {skill_name!r}; no injection",
            file=sys.stderr,
        )
        return

    _emit_additional_context(body)
    print(
        f"[skill-autoload-hook] injected {skill_name!r} skill body ({len(body)} chars) into SessionStart context",
        file=sys.stderr,
    )


def show_help() -> None:
    print("skill-autoload-hook - SessionStart hook that auto-injects CLI skill bodies")
    print()
    print("DESCRIPTION:")
    print("  Internal hook script called automatically by Claude Code at session start.")
    print("  Should not be invoked manually by users.")
    print()
    print("PURPOSE:")
    print("  Injects the full CLI skill body (kanban-cli or crew-cli) into model context")
    print("  at session start, eliminating the false-confidence failure mode where agents")
    print("  invoke CLI subcommands with misremembered syntax because the prompt's partial")
    print("  Quick Reference made the syntax feel known.")
    print()
    print("DETECTION:")
    print("  Reads KANBAN_AGENT env var (set by staff.bash / sstaff.bash wrappers).")
    print("  staff-engineer → injects kanban-cli/SKILL.md")
    print("  senior-staff-engineer → injects crew-cli/SKILL.md")
    print("  anything else → silent no-op")
    print()
    print("SKILL PATH:")
    print("  ${CLAUDE_CONFIG_DIR:-~/.claude}/skills/<skill-name>/SKILL.md")
    print()
    print("IDEMPOTENCY:")
    print("  Re-emits additionalContext on every SessionStart fire (e.g. /clear, /compact).")
    print("  No sentinel files — stateless by design.")
    print()
    print("OUTPUT (SessionStart):")
    print('  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}')
    print("  Silent (no stdout) for non-matching KANBAN_AGENT values or load failures.")
    print()
    print("FAIL SAFE:")
    print("  Any detection or load failure → silent exit 0. Never breaks SessionStart.")
    print()
    print("CONFIGURATION:")
    print("  Registered in modules/claude/default.nix as a SessionStart hook.")
    print("  Deployed by hms. Source: modules/claude/skill-autoload-hook.py")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    args, _ = parser.parse_known_args()
    if args.help:
        show_help()
        sys.exit(0)

    try:
        sys.stdin.read()  # consume stdin; payload unused — detection via env var
        run()
    except Exception as exc:
        print(
            f"[skill-autoload-hook] unhandled exception: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        # Fail open — never break SessionStart for all sessions


if __name__ == "__main__":
    main()
