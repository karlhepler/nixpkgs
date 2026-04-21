#!/usr/bin/env python3
"""
perm - Claude Code permission manager

Manages Claude Code permissions in .claude/settings.local.json.
Tracks temporary vs permanent patterns for lifecycle cleanup.
"""

import argparse
import fnmatch
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Pattern validation
# ---------------------------------------------------------------------------

# Valid pattern forms: bare tool name (e.g. "Bash") or Tool(content_glob).
# Rejects nested parens, unclosed parens, and other malformed inputs that
# would cause silent incorrect fnmatch behaviour in cmd_hook.
_PATTERN_RE = re.compile(r'^(\w+)(?:\(([^)]*)\))?$')


def validate_pattern(pattern: str) -> bool:
    """Return True if pattern has the expected Tool or Tool(content) shape."""
    return bool(_PATTERN_RE.match(pattern))


# ---------------------------------------------------------------------------
# Lazy repo root resolution
# ---------------------------------------------------------------------------

_repo_root: Optional[Path] = None
_settings_file: Optional[Path] = None
_tracking_file: Optional[Path] = None


def ensure_repo() -> None:
    """Resolve git repo root and set module-level path variables."""
    global _repo_root, _settings_file, _tracking_file
    if _repo_root is not None:
        return
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Not in a git repository")
    _repo_root = Path(result.stdout.strip())
    _settings_file = _repo_root / ".claude" / "settings.local.json"
    _tracking_file = _repo_root / ".claude" / ".perm-tracking.json"
    (_repo_root / ".claude").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Settings file helpers
# ---------------------------------------------------------------------------

def init_settings() -> None:
    """Initialize settings.local.json if absent or missing required keys."""
    ensure_repo()
    assert _settings_file is not None

    if not _settings_file.exists():
        _settings_file.write_text(json.dumps({"permissions": {"allow": []}}, indent=2) + "\n")
        return

    data = json.loads(_settings_file.read_text())

    if "permissions" not in data:
        data["permissions"] = {"allow": []}
        _write_json(_settings_file, data)
        return

    if "allow" not in data["permissions"]:
        data["permissions"]["allow"] = []
        _write_json(_settings_file, data)


def init_tracking() -> None:
    """Initialize .perm-tracking.json if absent, and run migrations."""
    ensure_repo()
    assert _tracking_file is not None

    if not _tracking_file.exists():
        _write_json(_tracking_file, {"temporary": {}, "permanent": []})
        return

    data = json.loads(_tracking_file.read_text())

    # Migration 1: temporary was a flat array → now an object keyed by pattern
    if isinstance(data.get("temporary"), list):
        data["temporary"] = {}
        _write_json(_tracking_file, data)

    # Migration 2: temporary values were session arrays → now session→timestamp objects
    temp = data.get("temporary", {})
    needs_migration = any(isinstance(v, list) for v in temp.values())
    if needs_migration:
        now = int(time.time())
        for pattern, value in temp.items():
            if isinstance(value, list):
                temp[pattern] = {session: now for session in value}
        data["temporary"] = temp
        _write_json(_tracking_file, data)


def _write_json(path: Path, data: object) -> None:
    """Atomically write JSON to path via a .tmp file."""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def _read_settings() -> dict:
    assert _settings_file is not None
    return json.loads(_settings_file.read_text())


def _read_tracking() -> dict:
    assert _tracking_file is not None
    return json.loads(_tracking_file.read_text())


def pattern_in_settings(pattern: str) -> bool:
    data = _read_settings()
    return pattern in data.get("permissions", {}).get("allow", [])


def pattern_in_permanent(pattern: str) -> bool:
    data = _read_tracking()
    return pattern in data.get("permanent", [])


def add_to_settings(pattern: str) -> None:
    """Add a pattern to settings.local.json permissions.allow (idempotent)."""
    if pattern_in_settings(pattern):
        return
    data = _read_settings()
    data["permissions"]["allow"].append(pattern)
    _write_json(_settings_file, data)


def add_to_temporary(pattern: str, session: str) -> None:
    """Add session claim with timestamp to the temporary pattern (idempotent, updates timestamp)."""
    data = _read_tracking()
    now = int(time.time())
    temp = data.setdefault("temporary", {})
    if pattern in temp:
        temp[pattern][session] = now
    else:
        temp[pattern] = {session: now}
    _write_json(_tracking_file, data)


def add_to_permanent(pattern: str) -> None:
    """Add a pattern to permanent tracking (idempotent)."""
    if pattern_in_permanent(pattern):
        return
    data = _read_tracking()
    data.setdefault("permanent", []).append(pattern)
    _write_json(_tracking_file, data)


def remove_from_settings(pattern: str) -> None:
    """Remove a pattern from settings.local.json permissions.allow."""
    data = _read_settings()
    data["permissions"]["allow"] = [p for p in data["permissions"].get("allow", []) if p != pattern]
    _write_json(_settings_file, data)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_allow(session: str, patterns: List[str], verbose: bool) -> None:
    if not session:
        print("Error: --session <id> is required for 'allow'", file=sys.stderr)
        print("Usage: perm --session <id> allow <pattern> [<pattern> ...]", file=sys.stderr)
        sys.exit(1)

    if not patterns:
        print("Error: at least one pattern required", file=sys.stderr)
        print("Usage: perm --session <id> allow <pattern> [<pattern> ...]", file=sys.stderr)
        sys.exit(1)

    for pattern in patterns:
        if not validate_pattern(pattern):
            print(f"Error: invalid pattern {pattern!r} — expected 'Tool' or 'Tool(glob)'", file=sys.stderr)
            sys.exit(1)

    init_settings()
    init_tracking()

    for pattern in patterns:
        add_to_settings(pattern)
        add_to_temporary(pattern, session)
        if verbose:
            print(f"Allowed (temporary): {pattern}")


def cmd_always(patterns: List[str], verbose: bool) -> None:
    if not patterns:
        print("Error: at least one pattern required", file=sys.stderr)
        print("Usage: perm always <pattern> [<pattern> ...]", file=sys.stderr)
        sys.exit(1)

    for pattern in patterns:
        if not validate_pattern(pattern):
            print(f"Error: invalid pattern {pattern!r} — expected 'Tool' or 'Tool(glob)'", file=sys.stderr)
            sys.exit(1)

    init_settings()
    init_tracking()

    for pattern in patterns:
        add_to_settings(pattern)
        add_to_permanent(pattern)
        if verbose:
            print(f"Allowed (permanent): {pattern}")


def cmd_cleanup(session: str, verbose: bool) -> None:
    if not session:
        print("Error: --session <id> is required for 'cleanup'", file=sys.stderr)
        print("Usage: perm --session <id> cleanup", file=sys.stderr)
        sys.exit(1)

    init_settings()
    init_tracking()

    data = _read_tracking()
    temp = data.get("temporary", {})

    if not temp:
        if verbose:
            print("No temporary permissions to clean up.")
        return

    # Find patterns that have a claim from this session
    owned_patterns = [p for p, claims in temp.items() if session in claims]

    if not owned_patterns:
        if verbose:
            print(f"No temporary permissions owned by session '{session}'.")
        return

    removed_count = 0

    for pattern in owned_patterns:
        # Remove this session's claim
        data = _read_tracking()
        temp = data.get("temporary", {})
        if pattern in temp and session in temp[pattern]:
            del temp[pattern][session]
            data["temporary"] = temp
            _write_json(_tracking_file, data)

        # If no claims remain, remove from both files
        data = _read_tracking()
        remaining = len(data.get("temporary", {}).get(pattern, {}))
        if remaining == 0:
            remove_from_settings(pattern)
            data = _read_tracking()
            if pattern in data.get("temporary", {}):
                del data["temporary"][pattern]
            _write_json(_tracking_file, data)
            removed_count += 1

    total_owned = len(owned_patterns)

    if verbose:
        if removed_count == total_owned:
            print(f"Cleaned up {removed_count} temporary permission(s) (session: {session}).")
        else:
            kept = total_owned - removed_count
            print(f"Released session '{session}' from {total_owned} permission(s).")
            print(f"  Removed: {removed_count} (no other sessions held them)")
            print(f"  Kept:    {kept} (still held by other sessions)")


def cmd_cleanup_stale(max_age_hours: int) -> None:
    """Remove temporary permissions older than max_age_hours. Background safety net — graceful on errors."""
    try:
        ensure_repo()
    except RuntimeError:
        return  # Gracefully exit if not in a git repo

    assert _tracking_file is not None
    if not _tracking_file.exists():
        return

    try:
        init_settings()
        init_tracking()
    except Exception as e:
        print(f"Warning: perm cleanup-stale failed to initialize: {e}", file=sys.stderr)
        return

    data = _read_tracking()
    temp = data.get("temporary", {})

    if not temp:
        return

    now = int(time.time())
    max_age_seconds = max_age_hours * 3600
    cutoff = now - max_age_seconds

    # Find patterns that have at least one stale claim
    stale_patterns = [
        p for p, claims in temp.items()
        if any(ts < cutoff for ts in claims.values())
    ]

    if not stale_patterns:
        return

    stale_count = 0

    for pattern in stale_patterns:
        # Remove stale claims from this pattern
        data = _read_tracking()
        temp_entry = data.get("temporary", {}).get(pattern, {})
        data["temporary"][pattern] = {s: ts for s, ts in temp_entry.items() if ts >= cutoff}
        _write_json(_tracking_file, data)

        # If no claims remain, remove from both files
        data = _read_tracking()
        remaining = len(data.get("temporary", {}).get(pattern, {}))
        if remaining == 0:
            remove_from_settings(pattern)
            data = _read_tracking()
            if pattern in data.get("temporary", {}):
                del data["temporary"][pattern]
            _write_json(_tracking_file, data)
            stale_count += 1

    if stale_count > 0:
        print(f"Cleaned up {stale_count} stale temporary permission(s) (older than {max_age_hours}h).")


def cmd_session_hook() -> None:
    """SessionStart hook: read JSON from stdin, print session UUID."""
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    session_id = data.get("session_id", "")
    if not session_id:
        return

    # Suppress for sub-agents (they have agent_type in the JSON)
    if data.get("agent_type", ""):
        return

    # Suppress for burns sessions
    if os.environ.get("BURNS_SESSION", ""):
        return

    print(f"\U0001f511 Your perm session is: {session_id}")


def cmd_hook() -> None:
    """PermissionRequest hook: read JSON from stdin, emit allow decision if pattern matches."""
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    cwd = payload.get("cwd", "")
    tool_name = payload.get("tool_name", "")

    if not cwd or not tool_name:
        sys.exit(0)

    # Extract content based on tool type
    tool_input = payload.get("tool_input", {}) or {}
    if tool_name == "Bash":
        content = tool_input.get("command", "")
    elif tool_name in ("Write", "Edit", "Read"):
        content = tool_input.get("file_path", "")
    elif tool_name == "WebFetch":
        content = tool_input.get("url", "")
    else:
        content = json.dumps(tool_input)

    # Resolve repo root — bail silently on failure
    result = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        sys.exit(0)

    repo_root = Path(result.stdout.strip())
    settings_file = repo_root / ".claude" / "settings.local.json"

    if not settings_file.exists():
        sys.exit(0)

    try:
        settings_data = json.loads(settings_file.read_text())
        allow_patterns = settings_data.get("permissions", {}).get("allow", [])
    except (json.JSONDecodeError, OSError) as e:
        # Log silently; don't block the permission request (fail open)
        try:
            log_path = Path.home() / ".claude" / "metrics" / "perm-hook-errors.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"[perm-hook parse error] {e}\n")
        except Exception:
            pass
        sys.exit(0)

    if not allow_patterns:
        sys.exit(0)

    for pattern in allow_patterns:
        if not pattern:
            continue

        if "(" in pattern:
            # Format: Tool(content_glob)
            pattern_tool = pattern[:pattern.index("(")]
            pattern_content = pattern[pattern.index("(") + 1:]
            if pattern_content.endswith(")"):
                pattern_content = pattern_content[:-1]
            has_content = True
        else:
            # Bare tool name — matches any input for that tool
            pattern_tool = pattern
            pattern_content = ""
            has_content = False

        if pattern_tool != tool_name:
            continue

        if not has_content:
            print('{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}', end="")
            sys.exit(0)

        # Glob match content against pattern
        if fnmatch.fnmatch(content, pattern_content):
            print('{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}', end="")
            sys.exit(0)

    # No pattern matched — fail open (empty stdout)
    sys.exit(0)


def cmd_purge() -> None:
    """Purge ALL entries from permissions.allow (interactive, user-only)."""
    init_settings()

    data = _read_settings()
    current_count = len(data.get("permissions", {}).get("allow", []))

    if current_count == 0:
        print("permissions.allow is already empty. Nothing to purge.")
        return

    assert _settings_file is not None
    print(f"This will remove ALL {current_count} entries from permissions.allow in:")
    print(f"  {_settings_file}")
    print()

    try:
        response = input("Are you sure? [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted. No changes made.")
        return

    if response.strip().lower() != "y":
        print("Aborted. No changes made.")
        return

    data["permissions"]["allow"] = []
    _write_json(_settings_file, data)
    print(f"Purged: removed {current_count} permission(s) from permissions.allow.")


def cmd_list() -> None:
    """Show tracked permissions with labels and timestamps."""
    init_tracking()

    data = _read_tracking()
    temp = data.get("temporary", {})
    permanent = data.get("permanent", [])

    if not temp and not permanent:
        print("No tracked permissions.")
        return

    now = int(time.time())

    if temp:
        print("Temporary:")
        for pattern, claims in temp.items():
            for session, timestamp in claims.items():
                age_hours = (now - timestamp) // 3600
                print(f"  [temporary] {pattern} (session: {session}, age: {age_hours}h)")

    if permanent:
        print("Permanent:")
        for pattern in permanent:
            print(f"  [permanent] {pattern}")


def cmd_check(pattern: str, verbose: bool) -> None:
    """Check if pattern is approved across all settings files. Exits 0 if allowed, 1 if denied/not-allowed."""
    found_allow = False
    found_deny = False

    # Determine git repo root (gracefully handle non-repo context)
    repo_root_str = ""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        repo_root_str = result.stdout.strip()

    output_lines: List[str] = []
    output_lines.append(f"Checking: {pattern}")
    output_lines.append("")

    def check_file(settings_path: Path, label: str) -> None:
        nonlocal found_allow, found_deny
        if settings_path.exists():
            try:
                file_data = json.loads(settings_path.read_text())
                in_allow = pattern in file_data.get("permissions", {}).get("allow", [])
                in_deny = pattern in (
                    file_data.get("permissions", {}).get("deny", []) +
                    file_data.get("permissions", {}).get("block", [])
                )
                if in_allow:
                    output_lines.append(f"  ✓ {label}")
                    found_allow = True
                else:
                    output_lines.append(f"  ✗ {label}")
                if in_deny:
                    output_lines.append(f"  ⚠ deny/block  {label}")
                    found_deny = True
            except (json.JSONDecodeError, OSError):
                output_lines.append(f"  - {label} [error reading file]")
        else:
            output_lines.append(f"  - {label} [not found]")

    if repo_root_str:
        repo_root = Path(repo_root_str)
        check_file(repo_root / ".claude" / "settings.local.json", "local   .claude/settings.local.json")
        check_file(repo_root / ".claude" / "settings.json", "project .claude/settings.json")
    else:
        output_lines.append("  - local   .claude/settings.local.json [not in a git repo]")
        output_lines.append("  - project .claude/settings.json [not in a git repo]")

    home = Path.home()
    check_file(home / ".claude" / "settings.json", "global  ~/.claude/settings.json")

    output_lines.append("")
    if found_deny:
        output_lines.append("→ DENIED  (deny/block found — overrides all allows globally)")
    elif found_allow:
        output_lines.append("→ ALLOWED")
    else:
        output_lines.append("→ NOT ALLOWED")

    if verbose:
        for line in output_lines:
            print(line)

    if found_deny:
        sys.exit(1)
    elif found_allow:
        sys.exit(0)
    else:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

EPILOG = """\
EXAMPLES:
  perm --session a1b2c3d4 allow "Bash(npm run lint)"
  perm --session a1b2c3d4 allow "Bash(npm run lint)" "Bash(npm run test *)" "Read(src/auth/**)"
  perm always "Bash(npm run test)"
  perm always "Bash(npm run test)" "Bash(npm run build)"
  perm --session a1b2c3d4 cleanup
  perm cleanup-stale
  perm cleanup-stale --max-age 2
  perm list
  perm check "Bash(kanban *)"
  perm check "Write(.scratchpad/**)"
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perm",
        description="perm - Claude Code permission manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument(
        "--session",
        metavar="<id>",
        default="",
        help=(
            "Session identifier (required for allow and cleanup). "
            "Controls ownership in .claude/.perm-tracking.json only — "
            "NOT written to settings.local.json."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help=(
            "Print human-readable confirmation on success. "
            "By default, allow/always/cleanup are silent on success (exit 0 is the signal). "
            "For check: show detailed output (file-by-file breakdown + verdict)."
        ),
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # allow
    allow_p = subparsers.add_parser(
        "allow",
        help="Add pattern(s) as temporary permission (session-scoped, timestamped)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    allow_p.add_argument("patterns", nargs="+", metavar="<pattern>", help="Permission pattern(s) to allow")

    # always
    always_p = subparsers.add_parser(
        "always",
        help="Add pattern(s) as permanent permission (never cleaned up)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    always_p.add_argument("patterns", nargs="+", metavar="<pattern>", help="Permission pattern(s) to allow permanently")

    # cleanup
    subparsers.add_parser(
        "cleanup",
        help="Remove temporary permissions owned by the given session",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # cleanup-stale
    cleanup_stale_p = subparsers.add_parser(
        "cleanup-stale",
        help="Remove temporary permissions older than max-age (default: 4h)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cleanup_stale_p.add_argument(
        "--max-age",
        type=int,
        metavar="<hours>",
        default=4,
        help="Maximum age in hours (default: 4)",
    )

    # list
    subparsers.add_parser(
        "list",
        help="Show tracked permissions with labels and timestamps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # check
    check_p = subparsers.add_parser(
        "check",
        help="Check if pattern is approved (exit 0 if allowed, 1 if denied/not-allowed)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    check_p.add_argument("pattern", metavar="<pattern>", help="Permission pattern to check")
    check_p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output (file-by-file breakdown + verdict)",
    )

    # purge
    subparsers.add_parser(
        "purge",
        help="Purge ALL entries from permissions.allow (interactive, user-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # session-hook
    subparsers.add_parser(
        "session-hook",
        help="SessionStart hook: read JSON from stdin, print session UUID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # hook
    subparsers.add_parser(
        "hook",
        help="PermissionRequest hook: read JSON from stdin, emit allow decision if pattern matches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Handle SIGINT → exit 130
    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(130))

    parser = build_parser()
    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(2)

    try:
        if args.subcommand == "allow":
            cmd_allow(args.session, args.patterns, args.verbose)

        elif args.subcommand == "always":
            cmd_always(args.patterns, args.verbose)

        elif args.subcommand == "cleanup":
            cmd_cleanup(args.session, args.verbose)

        elif args.subcommand == "cleanup-stale":
            cmd_cleanup_stale(args.max_age)

        elif args.subcommand == "list":
            cmd_list()

        elif args.subcommand == "check":
            # check manages its own exit codes
            # --verbose may be set globally or on the subcommand itself
            check_verbose = args.verbose
            cmd_check(args.pattern, check_verbose)

        elif args.subcommand == "purge":
            cmd_purge()

        elif args.subcommand == "session-hook":
            cmd_session_hook()

        elif args.subcommand == "hook":
            cmd_hook()

        else:
            print(f"Error: unknown subcommand '{args.subcommand}'", file=sys.stderr)
            sys.exit(2)

    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
